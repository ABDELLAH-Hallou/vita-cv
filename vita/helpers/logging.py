"""vita/helpers/logging.py — activity logging to .vita/logs/vita.log.

Responsible for:
- Appending timestamped entries to the VITA log file
"""

from datetime import datetime
from pathlib import Path
from vita.helpers.config import VITA_DIR

LOG_FILE = VITA_DIR / "logs" / "vita.log"


def log(msg: str) -> None:
    """Append a timestamped entry to the VITA log file."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {msg}\n")
