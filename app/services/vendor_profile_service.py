"""Vendor profile loading and selection."""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

import yaml

from app.db import repository

logger = logging.getLogger(__name__)

PROFILES_DIR = Path(__file__).parent.parent.parent / "config" / "vendor_profiles"


@lru_cache
def _load_yaml_profiles() -> dict[str, dict]:
    profiles = {}
    if not PROFILES_DIR.exists():
        return profiles
    for path in PROFILES_DIR.glob("*.yaml"):
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        vendor_id = data.get("vendor_id") or path.stem
        profiles[vendor_id] = data
    return profiles


def get_profile_for_vendor(vendor_name: str | None, vendor_id: str | None = None) -> dict | None:
    """Select vendor profile by ID or fuzzy name match."""
    db_profile = None
    if vendor_id:
        db_profile = repository.get_vendor_profile(vendor_id)
        if db_profile:
            return db_profile

    yaml_profiles = _load_yaml_profiles()
    if vendor_id and vendor_id in yaml_profiles:
        return yaml_profiles[vendor_id]

    if not vendor_name:
        return None

    normalized = vendor_name.lower().strip()
    for profile in yaml_profiles.values():
        aliases = [profile.get("vendor_id", "")] + profile.get("aliases", [])
        for alias in aliases:
            if alias and alias.lower() in normalized or normalized in alias.lower():
                return profile
    return None


def apply_profile_threshold_overrides(profile: dict | None, policy: dict) -> dict:
    """Merge vendor-specific threshold overrides into routing policy."""
    if not profile:
        return policy
    merged = dict(policy)
    overrides = profile.get("threshold_overrides", {})
    thresholds = dict(merged.get("thresholds", {}))
    thresholds.update(overrides)
    merged["thresholds"] = thresholds
    return merged
