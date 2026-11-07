"""jtrue.py FILE EXPR: load JSON FILE as d, print eval(EXPR); exit 0 if truthy, 1 if falsy, 2 on error."""
import json
import os
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as f:
        d = json.load(f)
    v = eval(sys.argv[2], {"d": d, "os": os, "json": json})
except Exception as e:  # noqa: BLE001
    sys.stderr.write("jtrue error: %s: %s\n" % (type(e).__name__, e))
    sys.exit(2)
print(v)
sys.exit(0 if v else 1)
