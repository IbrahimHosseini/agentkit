"""Inline terminal tables for human output, with stable redirected text."""
import atexit
import os
import sys
import unicodedata
from dataclasses import dataclass
from itertools import zip_longest

from . import platforms


TARGET_COLORS = {'claude': ('33', '38;5;173'), 'codex': ('36', '38;5;73')}
STATUS_COLORS = {'ok': '32', 'fail': '31', 'failed': '31', 'warn': '33',
                 'kept': '33', 'skipped': '33', 'unsupported': '33',
                 'added': '32', 'updated': '32', 'installed': '32', 'removed': '32',
                 'replaced': '32', 'unchanged': '2'}


@dataclass(frozen=True)
class ChoiceRow:
    label: str
    mark: str
    detail: str = ''
    target: str = ''


def _windows_vt(stream):
    try:
        import ctypes
        import msvcrt

        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        handle = ctypes.c_void_p(msvcrt.get_osfhandle(stream.fileno()))
        mode = ctypes.c_ulong()
        if not kernel.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        original = mode.value
        desired = original | 0x0001 | 0x0004  # PROCESSED_OUTPUT | VIRTUAL_TERMINAL_PROCESSING
        if original != desired:
            if not kernel.SetConsoleMode(handle, desired):
                return False
            atexit.register(kernel.SetConsoleMode, handle, original)
        return True
    except (ImportError, AttributeError, OSError, ValueError):
        return False


def _columns(stream):
    try:
        columns = int(os.environ.get('COLUMNS', '0')) or os.get_terminal_size(stream.fileno()).columns
    except (AttributeError, OSError, ValueError):
        columns = 0
    return columns if columns > 0 else 80


def _cell_width(char):
    if unicodedata.category(char) in ('Mn', 'Me', 'Cf'):
        return 0
    return 2 if unicodedata.east_asian_width(char) in ('F', 'W') else 1


def _width(text):
    return sum(_cell_width(char) for char in text)


def _wrap(text, width):
    lines = []
    start = 0
    while start < len(text):
        used = 0
        end = start
        while end < len(text):
            char = text[end]
            used += _cell_width(char)
            if used > width and end > start:
                break
            end += 1
        # Keep words together when possible and hard-wrap long IDs/paths.
        if end < len(text) and text[end] != ' ':
            space = text.rfind(' ', start, end)
            if space > start:
                end = space
        lines.append(text[start:end])
        start = end + int(text[end:end + 1] == ' ')
    return lines or ['']


class Terminal:
    def __init__(self, stream=None, *, quiet=False):
        stream = sys.stdout if stream is None else stream
        term = os.environ.get('TERM', '')
        self.rich = stream.isatty() and term != 'dumb'
        self.columns = _columns(stream) if self.rich else 80
        self.stream = stream
        self.encoding = getattr(stream, 'encoding', None) or 'utf-8'
        self.color = self.rich and not quiet and 'NO_COLOR' not in os.environ
        windows = platforms.is_windows()
        if self.color and windows:
            self.color = _windows_vt(stream)
        self.extended = (windows or '256color' in term
                         or os.environ.get('COLORTERM') in ('truecolor', '24bit'))
        self.box = self._encodable('─│┌┬┐├┼┤└┴┘') == '─│┌┬┐├┼┤└┴┘'

    def _encodable(self, value):
        return value.encode(self.encoding, errors='backslashreplace').decode(self.encoding)

    def _text(self, value):
        # An external display name or a filesystem path can contain controls.
        return self._encodable(''.join(repr(char)[1:-1] if unicodedata.category(char) in ('Cc', 'Cs')
                                       else char for char in value))

    def paint(self, value, code):
        return f'\x1b[{code}m{value}\x1b[0m' if self.color and code else value

    def target_label(self, label, target=None):
        colors = TARGET_COLORS.get((target or label).lower())
        return self.paint(label, colors[self.extended]) if colors else label

    def status(self, text, status):
        return self.paint(text, STATUS_COLORS.get(status))

    def checklist(self, title, read_key, rows, toggle, validate=lambda: ''):
        """Show a live view of choices. Return False when the user cancels."""
        active = 0
        height = 0
        try:
            height_available = os.get_terminal_size(self.stream.fileno()).lines or 21
            page_size = max(1, height_available - 5)
        except (OSError, AttributeError, ValueError):
            page_size = 16
        controls = '↑/↓ Move · Space Toggle · Enter Confirm · Esc Cancel'
        if self._encodable(controls) != controls:
            controls = 'Up/Down Move | Space Toggle | Enter Confirm | Esc Cancel'
        notice = ''
        while True:
            choices = rows()
            page = min(page_size, len(choices))
            start = max(0, min(active - page // 2, len(choices) - page))
            lines = [self.paint(_wrap(self._text(title), self.columns - 1)[0], '1'),
                     _wrap(controls, self.columns - 1)[0]]
            for index in range(start, start + page):
                choice = choices[index]
                pointer = '>' if index == active else ' '
                state = {'x': '32', '-': '33', ' ': '2'}[choice.mark]
                prefix = f'{pointer} [{choice.mark}] '
                text = self._text(choice.label + ('  ' + choice.detail if choice.detail else ''))
                text = _wrap(text, max(1, self.columns - len(prefix) - 1))[0]
                if index == active:
                    lines.append(self.paint(prefix + text, '1;7'))
                else:
                    lines.append(self.paint(prefix, state) + self.target_label(text, choice.target))
            if page < len(choices):
                lines.append(f'{start + 1}-{start + page} of {len(choices)}')
            if notice:
                lines.append(self.status(_wrap(self._text(notice), self.columns - 1)[0], 'warn'))
            if self.color and height:
                self.stream.write(f'\x1b[{height}F\x1b[J')
            for line in lines:
                self.stream.write(line + '\n')
            self.stream.flush()
            height = len(lines)
            while True:
                key = read_key()
                if key in ('cancel', 'eof'):
                    return False
                if key == 'enter':
                    notice = validate()
                    if not notice:
                        return True
                    break
                if key in ('up', 'down'):
                    active = (active + (-1 if key == 'up' else 1)) % len(choices)
                    notice = ''
                    break
                if key == 'toggle':
                    notice = toggle(active) or ''
                    break

    def table(self, headers, rows, say=print, *, target_column=None, status_column=None, group_by=None):
        if not self.rich:
            say('  '.join(headers))
            for row in rows:
                say('  '.join(row))
            return

        rows = [tuple(self._text(cell) for cell in row) for row in rows]
        widths = [max(map(_width, column)) for column in zip(headers, *rows)]
        minimum = [min(width, max(_width(header), 10)) for header, width in zip(headers, widths)]
        available = self.columns - (3 * len(headers) + 1)
        vertical, horizontal = ('│', '─') if self.box else ('|', '-')

        def style(index, value, text):
            if index == target_column:
                return self.target_label(text, value)
            if index == status_column:
                return self.paint(text, STATUS_COLORS.get(value.lower()))
            return text

        if available < sum(minimum):
            if not rows:
                for line in _wrap(' / '.join(headers), self.columns):
                    say(self.paint(line, '1'))
            for count, row in enumerate(rows):
                if count:
                    say(horizontal * self.columns)
                for index, (header, value) in enumerate(zip(headers, row)):
                    for line in _wrap(header + ': ' + value, self.columns):
                        say(style(index, value, line))
            return

        while sum(widths) > available:
            index = max(range(len(widths)), key=lambda i: widths[i] - minimum[i])
            widths[index] -= 1

        def border(chars):
            left, joint, right = chars if self.box else '+++'
            say(left + joint.join(horizontal * (width + 2) for width in widths) + right)

        def row_line(row, header=False):
            cells = [_wrap(value, width) for value, width in zip(row, widths)]
            for parts in zip_longest(*cells, fillvalue=''):
                padded = []
                for index, (value, width) in enumerate(zip(parts, widths)):
                    label = self.paint(value, '1') if header else style(index, row[index], value)
                    padded.append(label + ' ' * (width - _width(value)))
                say(vertical + ' ' + (' ' + vertical + ' ').join(padded) + ' ' + vertical)

        border('┌┬┐')
        row_line(headers, header=True)
        if rows:
            border('├┼┤')
        for index, row in enumerate(rows):
            if index and group_by is not None and rows[index - 1][group_by] != row[group_by]:
                border('├┼┤')
            row_line(row)
        border('└┴┘')
