"""Frozen-executable entry point.

PyInstaller needs a script that actually *runs* on execution (unlike
``uwmirror.cli``, which only defines ``main``). Kept separate from the package
so the freeze entry and the console/gui entry points stay independent.

Under the ``--windowed`` build there is no console, so ``sys.stdout`` /
``sys.stderr`` are ``None``; ``uwmirror.cli`` already detects this and routes
logging (and fatal errors) to ``%APPDATA%\\uwmirror\\uwmirror.log``.
"""

import sys

from uwmirror.cli import main

if __name__ == "__main__":
    sys.exit(main())
