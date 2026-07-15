"""Load and validate the practice configuration from YAML."""

from __future__ import annotations

from pathlib import Path

import yaml

from .models import PracticeConfig


def load_config(path: str | Path) -> PracticeConfig:
    """Parse a practice YAML file into a validated PracticeConfig.

    Raises pydantic.ValidationError on any malformed field, so a broken
    configuration fails at startup instead of mid-conversation.
    """
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return PracticeConfig.model_validate(raw)
