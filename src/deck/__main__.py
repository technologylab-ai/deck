"""Entry point for `python -m deck`."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
