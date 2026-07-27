from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

try:
    from dotenv import load_dotenv
except Exception:  # noqa: BLE001
    def load_dotenv(*_args: Any, **_kwargs: Any) -> bool:
        return False


@dataclass(slots=True)
class Settings:
    brand_name: str
    environment: str
    telegram_token: str
    telegram_chat_id: str
    config: dict[str, Any]


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    output = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(output.get(key), dict):
            output[key] = deep_merge(output[key], value)
        else:
            output[key] = value
    return output


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load_settings(project_root: Path) -> Settings:
    env_path = project_root / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    defaults = load_yaml(project_root / "config" / "defaults.yaml")
    override_path = project_root / "config" / "local.yaml"
    overrides = load_yaml(override_path) if override_path.exists() else {}
    config = deep_merge(defaults, overrides)
    return Settings(
        brand_name=os.getenv("BRAND_NAME", "Trader Dost Arun"),
        environment=os.getenv("ENVIRONMENT", "development"),
        telegram_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
        config=config,
    )
