"""Allow running as ``python -m uwmirror``."""

import sys

from uwmirror.cli import main

if __name__ == "__main__":
    sys.exit(main())
