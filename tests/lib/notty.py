"""Run a command in a new session, so it has no controlling terminal (/dev/tty cannot be opened)."""
import os
import sys

pid = os.fork()
if pid == 0:
    os.setsid()
    try:
        os.execvp(sys.argv[1], sys.argv[1:])
    except OSError as e:
        sys.stderr.write("notty: cannot run %s: %s\n" % (sys.argv[1], e))
        os._exit(127)
_, st = os.waitpid(pid, 0)
sys.exit(os.waitstatus_to_exitcode(st))
