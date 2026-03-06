import json
import logging
import os

logger = logging.getLogger(__name__)


def load_state(path: str) -> set[str]:
    """Load seen URLs from the state file. Return empty set if file missing."""
    expanded = os.path.expanduser(path)
    if not os.path.exists(expanded):
        return set()
    try:
        with open(expanded) as f:
            data = json.load(f)
        return set(data.get("seen", []))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Could not load state file %s: %s. Starting fresh.", path, e)
        return set()


def save_state(path: str, seen: set[str]) -> None:
    """Write the updated seen set back to the state file."""
    expanded = os.path.expanduser(path)
    try:
        with open(expanded, "w") as f:
            json.dump({"seen": sorted(seen)}, f, indent=2)
    except OSError as e:
        logger.error("Could not save state file %s: %s", path, e)
