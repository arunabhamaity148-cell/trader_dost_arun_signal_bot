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


# Config sections that must exist with required keys; a missing/invalid config
# should crash loudly at startup ("fail fast") rather than run with silent
# defaults. This catches YAML edits that would otherwise cause 3AM failures.
_REQUIRED_CONFIG_KEYS: dict[str, list] = {
    "system": ["history_size", "min_snapshots_before_signals", "signal_evaluation_interval_seconds", "signal_evaluation_concurrency", "market_queue_maxsize"],
    "risk": ["daily_loss_limit_r", "kill_switch_after_consecutive_losses"],
    "adaptive": ["kelly_cap", "kelly_fraction", "max_gross_exposure", "max_same_direction_exposure", "meta_label_threshold"],
    "vetoes": ["exchange_instability", "freshness_quorum"],
    "strategy_priors": [],
}


def validate_config(config: dict[str, Any]) -> None:
    """Raise immediately on a config that would cause runtime failures later."""
    for section, keys in _REQUIRED_CONFIG_KEYS.items():
        if section not in config:
            raise ValueError(f"config missing required section '{section}'")
        value = config[section]
        if not isinstance(value, dict):
            raise ValueError(f"config section '{section}' must be a mapping, got {type(value).__name__}")
        for key in keys:
            if key not in value:
                raise ValueError(f"config['{section}'] missing required key '{key}'")
    # Type/smoke-check the risk-critical numeric fields so a misconfigured
    # YAML fails at boot instead of emitting a bad risk decision at 3AM.
    risk = config["risk"]
    for fld in ("daily_loss_limit_r", "kill_switch_after_consecutive_losses"):
        if not isinstance(risk.get(fld), (int, float)):
            raise ValueError(f"config['risk']['{fld}'] must be numeric")
    if float(risk["daily_loss_limit_r"]) <= 0:
        raise ValueError("config['risk']['daily_loss_limit_r'] must be > 0")
    if int(risk["kill_switch_after_consecutive_losses"]) < 1:
        raise ValueError("config['risk']['kill_switch_after_consecutive_losses'] must be >= 1")
    sys_cfg = config["system"]
    if int(sys_cfg["history_size"]) < 50:
        raise ValueError("config['system']['history_size'] must be >= 50")
    if int(sys_cfg["signal_evaluation_interval_seconds"]) <= 0:
        raise ValueError("config['system']['signal_evaluation_interval_seconds'] must be > 0")


def load_settings(project_root: Path) -> Settings:
    env_path = project_root / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    defaults = load_yaml(project_root / "config" / "defaults.yaml")
    override_path = project_root / "config" / "local.yaml"
    overrides = load_yaml(override_path) if override_path.exists() else {}
    config = deep_merge(defaults, overrides)
    validate_config(config)
    return Settings(
        brand_name=os.getenv("BRAND_NAME", "Trader Dost Arun"),
        environment=os.getenv("ENVIRONMENT", "development"),
        telegram_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
        config=config,
    )
