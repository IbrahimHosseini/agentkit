#!/usr/bin/env python3
"""Render the README's illustrated terminal walkthrough; never execute commands.

Requires Python 3.9+ and Pillow (authoring only, not an agentkit dependency).
Run: python3 -I scripts/render-demo.py [--font /path/to/monospace.ttf]
The output and timings are illustrative, not a recording of a live agent session.
"""

import argparse
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent.parent
WIDTH, HEIGHT = 1120, 650
BG, PANEL = '#0b1118', '#111b25'
TEXT, MUTED, CYAN, GREEN = '#e5edf5', '#9bafc2', '#55cfdb', '#8bdfad'

# Installation and doctor lines are shortened from scratch-home CLI output.
# The researcher response is an explicitly labelled example, not a live result.
SCENES = [
    ('Get agentkit', 'Start with Bash, Git, Python 3.9+ and Claude Code installed.', [
        ('$ git clone https://github.com/IbrahimHosseini/agentkit.git', TEXT),
        ('$ cd agentkit', TEXT),
        ('', TEXT),
        ('# Keep this checkout: it is used by the CLI and hooks.', MUTED),
    ]),
    ('Install for Claude Code', 'Core setup; optional gstack and Karpathy installs are skipped.', [
        ('$ ./install.sh --target claude --yes \\', TEXT),
        ('    --skip gstack --skip karpathy', TEXT),
        ('', TEXT),
        ('[1/3] Claude: agents and skills', CYAN),
        ('  + 16 agents and 3 bundled skills', GREEN),
        ('[2/3] Claude: CLAUDE.md', CYAN),
        ('  + CLAUDE.md: added block', GREEN),
        ('[3/3] Claude: SubagentStop hook', CYAN),
        ('  + settings.json: agentkit-agent-log added', GREEN),
    ]),
    ('Check the setup', 'Doctor checks the managed files and required tools.', [
        ('$ ~/.local/bin/agentkit doctor --target claude', TEXT),
        ('', TEXT),
        ('  ok    agent researcher', GREEN),
        ('  ok    skill agent-report', GREEN),
        ('  ok    CLAUDE.md block', GREEN),
        ('  ok    SubagentStop hook in settings.json', GREEN),
        ('  warn  gstack not installed', MUTED),
        ('  warn  karpathy plugin not installed', MUTED),
        ('all required checks passed', GREEN),
    ]),
    ('Run your first agent', 'Open your project; Claude Code must already be signed in.', [
        ('$ cd /path/to/your-project', TEXT),
        ('$ claude --agent researcher \\', TEXT),
        ('    "Explain this project. Cite files. Do not edit."', TEXT),
        ('', TEXT),
        ('researcher / example response for the agentkit repo', CYAN),
        ('  agentkit shares agents and skills across Claude Code and Codex.', TEXT),
        ('  Source: README.md', MUTED),
        ('', TEXT),
        ('  The researcher reads the project and reports its findings.', GREEN),
    ]),
]


def load_font(size, override):
    candidates = [override] if override else [
        '/System/Library/Fonts/Menlo.ttc',
        '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
        str(Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/consola.ttf'),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return ImageFont.truetype(str(candidate), size)
    raise SystemExit('No monospace font found. Pass --font /path/to/font.ttf.')


def render(scene_index, visible, font, title_font):
    title, subtitle, lines = SCENES[scene_index]
    frame = Image.new('RGB', (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(frame)
    draw.text((40, 25), 'agentkit', font=title_font, fill=TEXT)
    draw.text((40, 70), 'INSTALL TO FIRST AGENT', font=font, fill=CYAN)
    draw.text((40, 108), '{:02d} / {}'.format(scene_index + 1, title),
              font=title_font, fill=TEXT)
    draw.text((40, 151), subtitle, font=font, fill=MUTED)
    draw.rounded_rectangle((30, 195, WIDTH - 30, 570), radius=16, fill=PANEL)
    for x, color in [(54, '#fa7773'), (76, '#edc46b'), (98, '#76ce96')]:
        draw.ellipse((x, 214, x + 10, 224), fill=color)
    draw.text((130, 206), 'terminal / Claude Code / macOS + Linux', font=font, fill=MUTED)
    draw.line((48, 242, WIDTH - 48, 242), fill='#263848', width=1)
    for index, (line, color) in enumerate(lines[:visible]):
        if draw.textbbox((0, 0), line, font=font)[2] > WIDTH - 100:
            raise ValueError('Line exceeds terminal width: ' + line)
        draw.text((50, 260 + index * 30), line, font=font, fill=color)
    if visible < len(lines):
        y = 266 + min(visible, len(lines) - 1) * 30
        draw.rectangle((50, y, 59, y + 18), fill=CYAN)
    draw.text((40, 593), 'Illustrated walkthrough / shortened example output', font=font, fill=MUTED)
    for step in range(len(SCENES)):
        x = 920 + step * 40
        draw.rounded_rectangle((x, 605, x + 28, 610), radius=2,
                               fill=CYAN if step == scene_index else '#344554')
    return frame


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--font', help='Path to a monospace TrueType font')
    args = parser.parse_args()
    font = load_font(19, args.font)
    title_font = load_font(28, args.font)
    frames, durations = [], []
    # One shared palette keeps colors stable between GIF frames.
    palette = render(1, len(SCENES[1][2]), font, title_font).quantize(colors=64)
    for index, (_, _, lines) in enumerate(SCENES):
        for visible in range(len(lines) + 1):
            frame = render(index, visible, font, title_font)
            frames.append(frame.quantize(palette=palette, dither=Image.Dither.NONE))
            durations.append(240 if visible < len(lines) else (4000 if index == 3 else 2000))
    output = ROOT / 'assets' / 'install-to-first-agent.gif'
    frames[0].save(output, save_all=True, append_images=frames[1:],
                   duration=durations, loop=0, optimize=True, disposal=1)
    print('{}: {:.1f}s, {} frames, {:,} bytes'.format(
        output.relative_to(ROOT), sum(durations) / 1000, len(frames), output.stat().st_size))


if __name__ == '__main__':
    main()
