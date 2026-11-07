"""snap.py DIR: print 'relative-path TAB type TAB sha256' for everything under DIR (skips .git and __pycache__)."""
import hashlib
import os
import sys

root = sys.argv[1]
rows = []
for base, dirs, files in os.walk(root):
    dirs[:] = sorted(d for d in dirs if d not in (".git", "__pycache__"))
    for n in sorted(files + [d for d in dirs if os.path.islink(os.path.join(base, d))]):
        p = os.path.join(base, n)
        rel = os.path.relpath(p, root)
        if os.path.islink(p):
            rows.append("%s\tlink\t%s" % (rel, os.readlink(p)))
        else:
            with open(p, "rb") as f:
                rows.append("%s\tfile\t%s" % (rel, hashlib.sha256(f.read()).hexdigest()))
    if not dirs and not files and base != root:
        rows.append("%s\tdir\t-" % os.path.relpath(base, root))
print("\n".join(sorted(rows)))
