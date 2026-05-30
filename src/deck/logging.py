"""File logging for deck.

Logs to ~/.local/state/deck/deck.log (XDG-ish state dir). Stdlib only.
Kept deliberately small so startup stays fast.
"""

import logging
import os
from pathlib import Path

_LOGGER_NAME = "deck"
_configured = False


def log_path() -> Path:
    """Resolve the log file path, honoring XDG_STATE_HOME."""
    base = os.environ.get("XDG_STATE_HOME")
    if base:
        root = Path(base)
    else:
        root = Path.home() / ".local" / "state"
    return root / "deck" / "deck.log"


def get_logger() -> logging.Logger:
    """Return the shared deck logger, configuring the file handler once."""
    global _configured
    logger = logging.getLogger(_LOGGER_NAME)
    if _configured:
        return logger

    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    path = log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(message)s")
        )
        logger.addHandler(handler)
    except OSError:
        # If the log can't be opened, fall back to silence rather than crash;
        # the CLI still prints user-facing errors to stderr.
        logger.addHandler(logging.NullHandler())

    _configured = True
    return logger
