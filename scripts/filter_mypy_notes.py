"""Drop mypy messages at note level while preserving every error diagnostic."""

import sys

for line in sys.stdin:
    if ": note: " not in line:
        sys.stdout.write(line)
