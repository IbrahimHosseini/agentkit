"""pty_run.py CMD...: run CMD with a pseudo terminal as stdin/stdout/stderr, print what it wrote (raw bytes), keep its exit code."""
import os
import pty
import sys

pid, fd = pty.fork()
if pid == 0:
    try:
        os.execvp(sys.argv[1], sys.argv[1:])
    except OSError as e:
        sys.stderr.write("pty_run: cannot run %s: %s\n" % (sys.argv[1], e))
        os._exit(127)
chunks = []
while True:
    try:
        b = os.read(fd, 65536)
    except OSError:  # EIO on Linux when the child side closes
        break
    if not b:
        break
    chunks.append(b)
_, st = os.waitpid(pid, 0)
sys.stdout.buffer.write(b"".join(chunks))
sys.stdout.buffer.flush()
sys.exit(os.waitstatus_to_exitcode(st))
