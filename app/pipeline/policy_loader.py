"""Load YAML config files from project config directory."""

from functools import lru_cache
from pathlib import Path

import yaml

CONFIG_DIR = Path(__file__).parent.parent.parent / "config"


@lru_cache
def load_field_aliases() -> dict:
    path = CONFIG_DIR / "field_aliases.yaml"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache
def load_routing_policy() -> dict:
    path = CONFIG_DIR / "routing_policy.yaml"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache
def load_validation_policy() -> dict:
    path = CONFIG_DIR / "validation_policy.yaml"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache
def load_decision_policy() -> dict:
    path = CONFIG_DIR / "decision_policy.yaml"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache
def load_matching_policy() -> dict:
    path = CONFIG_DIR / "matching_policy.yaml"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache
def load_import_mapping() -> dict:
    path = CONFIG_DIR / "import_mapping.yaml"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
