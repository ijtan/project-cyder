"""Bounded typed dashboard actions; never send the legacy giant request."""

from collections.abc import Mapping
from typing import Any

DASHBOARD_SECTION_FIELDS = {
    "layout": (
        "auto_rotation_enabled", "rotation_interval_seconds", "page_ai_enabled",
        "page_climate_enabled", "page_sensors_enabled", "page_energy_enabled",
        *(f"rotation_page_{index}" for index in range(1, 7)),
        "page_camera_enabled", "camera_refresh_interval_seconds",
        "camera_snapshot_url", "camera_name",
    ),
    "controls": (
        "room_devices_json", "climate_configured", "climate_entity",
        "climate_current_text", "climate_target_text", "climate_target",
        "climate_target_low", "climate_target_high", "climate_target_available",
        "climate_range_control", "climate_mode_text", "climate_mode_previous",
        "climate_mode_next", "climate_mode_previous_label", "climate_mode_next_label",
        "climate_mode_control", "climate_temperature_step", "climate_min_temp",
        "climate_max_temp",
    ),
    "sensors": (
        "sensor_monitor_configured",
        *(f"sensor_{index}_{field}" for index in range(1, 6)
          for field in ("enabled", "name", "text", "status")),
    ),
    "energy": (
        "power_configured", "power_available", "power_kw", "power_text", "energy_text",
        *(f"metric_{index}_{field}" for index in range(1, 5)
          for field in ("enabled", "name", "text")),
    ),
    "claude": (
        "claude_configured",
        *(f"{period}_{field}" for period in ("session", "week")
          for field in ("enabled", "bar_enabled", "percent", "text", "reset_epoch_minute")),
        "extra_enabled", "extra_bar_enabled", "extra_percent", "extra_label",
        "extra_text", "extra_summary_text", "extra_limit_enabled", "extra_limit_text",
    ),
    **{
        f"provider_{index}": (
            "ai_provider_count", f"provider_{index}_name",
            *(f"provider_{index}_{period}_{field}" for period in ("session", "week")
              for field in ("enabled", "bar_enabled", "percent", "text", "reset_epoch_minute")),
        )
        for index in range(1, 4)
    },
}
DASHBOARD_ACTIONS = tuple(f"update_dashboard_{section}" for section in DASHBOARD_SECTION_FIELDS)
MAX_DASHBOARD_ARGUMENTS = 21
DASHBOARD_SECTION_DELAY = 0.1
DASHBOARD_COALESCE_DELAY = 0.2


def dashboard_action_batches(payload: Mapping[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Split one consistent snapshot, including explicit empty/disabled fields."""
    expected = {field for fields in DASHBOARD_SECTION_FIELDS.values() for field in fields}
    if set(payload) != expected:
        raise ValueError("Dashboard payload does not match the bounded transport schema")
    return [
        (f"update_dashboard_{section}", {field: payload[field] for field in fields})
        for section, fields in DASHBOARD_SECTION_FIELDS.items()
    ]
