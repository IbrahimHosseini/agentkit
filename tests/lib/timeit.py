"""timeit.py OUTFILE CMD...: run CMD (no tty, stdin is inherited), write elapsed seconds to OUTFILE, keep its exit code."""
import os
import subprocess
import sys
import time

here = os.path.dirname(os.path.abspath(__file__))
t = time.time()
r = subprocess.run([sys.executable, "-I", os.path.join(here, "notty.py")] + sys.argv[2:])
with open(sys.argv[1], "w") as f:
    f.write("%.3f\n" % (time.time() - t))
sys.exit(r.returncode)
