from pathlib import Path
from typing import Any, Dict
import yaml

CONFIG_DIR = Path(__file__).resolve().parent
SETTINGS_FILE = CONFIG_DIR / "settings.yaml"


def load_settings(custom_path: Path | str | None = None) -> Dict[str, Any]:
    target = Path(custom_path) if custom_path else SETTINGS_FILE
    if not target.exists():
        # Fallback to local default if file is missing
        return {}

    with open(target, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
