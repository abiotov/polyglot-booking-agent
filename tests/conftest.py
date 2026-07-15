"""Shared fixtures: a reference practice configuration.

Monday opening hours 08:00-14:00 with 15-minute slots, matching the
worked example documented in the README.
"""

from __future__ import annotations

import pytest

from scheduling_engine.models import PracticeConfig

REFERENCE_CONFIG: dict = {
    "practice": {"name": "Test Practice", "timezone": "UTC", "languages": ["fr", "en"]},
    "slots": {"duration_minutes": 15},
    "opening_hours": {
        "monday": ["08:00-14:00"],
        "friday": ["08:00-10:00", "11:00-13:00"],
    },
    "client_types": {
        "premium": {"priority": 1, "windows": ["08:00-14:00"]},
        "standard": {"priority": 2, "windows": ["10:00-14:00"]},
    },
    "visit_types": {
        "first_visit": {"labels": {"fr": "Première visite", "en": "First visit"}},
    },
    "scoring": {"adjacent_before": 10, "adjacent_after": 8},
}


@pytest.fixture
def config() -> PracticeConfig:
    return PracticeConfig.model_validate(REFERENCE_CONFIG)
