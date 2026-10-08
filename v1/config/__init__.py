from pathlib import Path
from typing import Any, Dict
import yaml

CONFIG_DIR = Path(__file__).parent.resolve()


def load_yaml(file_path: Path) -> Dict[str, Any]:
    with open(file_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_settings(path: Path | None = None) -> Dict[str, Any]:
    settings_file = path or (CONFIG_DIR / "settings.yaml")
    return load_yaml(settings_file)


def load_customer_config(name_or_path: str) -> Dict[str, Any]:
    candidate = Path(name_or_path)
    if candidate.exists() and candidate.is_file():
        return load_yaml(candidate)
    
    # Try as customer name in CONFIG_DIR
    fname = name_or_path if name_or_path.endswith(".yaml") else f"{name_or_path}.yaml"
    cfg_path = CONFIG_DIR / fname
    if cfg_path.exists():
        return load_yaml(cfg_path)
    
    raise FileNotFoundError(f"Customer config '{name_or_path}' not found at {cfg_path}")
