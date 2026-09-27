#!/usr/bin/env python3
"""usage: check_vault_copies.py [<repo root>]

Check that every plugin holds the same shared files, byte for byte:
plugins/*/scripts/vault.py and plugins/*/tests/test_vault.py.
Quiet when all copies of a file are identical, or when there are none.

arguments:
  <repo root>  repo to check, default: the repo this script lives in

output (only on a difference):
  differs: <file>
    <hash prefix>  <path>      one line per copy, grouped by content

exit codes:
  0  all copies identical
  1  copies differ
  2  bad usage (too many arguments, root folder not found)

example: python3 tests/check_vault_copies.py
"""

import hashlib
import sys
from pathlib import Path

SHARED = ("scripts/vault.py", "tests/test_vault.py")


def copies(root, shared):
    """Map content hash to the copies of one shared file that have that content."""
    groups = {}
    for path in sorted(root.glob(f"plugins/*/{shared}")):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        groups.setdefault(digest, []).append(path.relative_to(root).as_posix())
    return groups


def main(argv):
    if argv[:1] in (["-h"], ["--help"]):
        print(__doc__.strip())
        return 0
    if len(argv) > 1:
        print("usage: check_vault_copies.py [<repo root>]", file=sys.stderr)
        return 2
    root = Path(argv[0]) if argv else Path(__file__).resolve().parents[1]
    if not root.is_dir():
        print(f"check_vault_copies.py: folder not found: {root}", file=sys.stderr)
        return 2
    differs = False
    for shared in SHARED:
        groups = copies(root, shared)
        if len(groups) <= 1:
            continue
        differs = True
        print(f"differs: {shared}")
        for digest, paths in groups.items():
            for path in paths:
                print(f"  {digest[:12]}  {path}")
    return 1 if differs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
