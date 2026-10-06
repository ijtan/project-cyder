"""Validate dashboard options and format live HA states for the CYD."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .alerts import numeric_state
from .const import (
    CONF_CLAUDE_EXTRA_LIMIT_ENTITY,
    CONF_CLAUDE_EXTRA_MODE,
    CONF_CLAUDE_EXTRA_PERCENT_ENTITY,
    CONF_CLAUDE_EXTRA_USED_ENTITY,
    CONF_CLAUDE_SESSION_ENTITY,
    CONF_CLAUDE_WEEK_ENTITY,
    CONF_DAILY_ENERGY_ENTITY,
    CONF_MAIN_POWER_ENTITY,
    CONF_METRIC_ENTITY_ID,
    CONF_METRIC_NAME,
    CONF_POWER_METRICS,
)

MAX_POWER_METRICS = 4
EXTRA_MODES = frozenset({"used", "remaining"})

_POWER_TO_KW = {"W": 0.001, "kW": 1.0, "MW": 1000.0, "mW": 0.000001}
_ENERGY_TO_KWH = {
    "Wh": 0.001,
    "kWh": 1.0,
    "MWh": 1000.0,
    "mWh": 0.000001,
}

_ENTITY_FIELDS = (
    CONF_MAIN_POWER_ENTITY,
    CONF_DAILY_ENERGY_ENTITY,
    CONF_CLAUDE_SESSION_ENTITY,
    CONF_CLAUDE_WEEK_ENTITY,
    CONF_CLAUDE_EXTRA_USED_ENTITY,
    CONF_CLAUDE_EXTRA_LIMIT_ENTITY,
    CONF_CLAUDE_EXTRA_PERCENT_ENTITY,
)


def validate_dashboard(values: Any) -> dict[str, Any]:
    """Validate and normalize the optional dashboard entity selections."""
    if not isinstance(values, Mapping):
        raise TypeError("Dashboard settings must be an object")

    validated: dict[str, Any] = {}
    for field in _ENTITY_FIELDS:
        value = values.get(field)
        if value in (None, ""):
            validated[field] = None
            continue
        if not isinstance(value, str) or not _looks_like_entity_id(value.strip()):
            raise ValueError(f"{field} must be a Home Assistant entity ID")
        validated[field] = value.strip()

    mode = values.get(CONF_CLAUDE_EXTRA_MODE, "used")
    if mode not in EXTRA_MODES:
        raise ValueError("Extra usage mode must be used or remaining")
    validated[CONF_CLAUDE_EXTRA_MODE] = mode

    metrics = values.get(CONF_POWER_METRICS, [])
    if not isinstance(metrics, list):
        raise TypeError("Power metrics must be a list")
    if len(metrics) > MAX_POWER_METRICS:
        raise ValueError(f"At most {MAX_POWER_METRICS} power metrics are supported")

    validated_metrics: list[dict[str, str]] = []
    for index, metric in enumerate(metrics, start=1):
        if not isinstance(metric, Mapping):
            raise TypeError(f"Power metric {index} must be an object")
        entity_id = metric.get(CONF_METRIC_ENTITY_ID)
        name = metric.get(CONF_METRIC_NAME)
        if not isinstance(entity_id, str) or not _looks_like_entity_id(
            entity_id.strip()
        ):
            raise ValueError(f"Power metric {index} needs a sensor entity")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Power metric {index} needs a display name")
        name = name.strip()
        if len(name) > 16:
            raise ValueError(f"Power metric {index} name must be 16 characters or less")
        validated_metrics.append(
            {CONF_METRIC_ENTITY_ID: entity_id.strip(), CONF_METRIC_NAME: name}
        )
    validated[CONF_POWER_METRICS] = validated_metrics
    return validated


def dashboard_entities(options: Mapping[str, Any]) -> set[str]:
    """Return configured entities whose state changes should refresh the UI."""
    entities = {
        entity_id
        for field in _ENTITY_FIELDS
        if isinstance((entity_id := options.get(field)), str) and entity_id
    }
    for metric in options.get(CONF_POWER_METRICS, []):
        if isinstance(metric, Mapping):
            entity_id = metric.get(CONF_METRIC_ENTITY_ID)
            if isinstance(entity_id, str) and entity_id:
                entities.add(entity_id)
    return entities


def dashboard_action_data(hass: Any, options: Mapping[str, Any]) -> dict[str, Any]:
    """Format selected HA states using the units expected by the display."""
    power_value, power_unit = _read_sensor(
        hass, options.get(CONF_MAIN_POWER_ENTITY)
    )
    power_factor = _POWER_TO_KW.get(power_unit)
    power_available = power_value is not None and power_factor is not None
    power_kw = power_value * power_factor if power_available else 0.0
    if power_available:
        power_text = f"{power_kw:.2f} kW"
    else:
        power_text = _raw_display(power_value, power_unit, "--.-- kW")

    energy_value, energy_unit = _read_sensor(
        hass, options.get(CONF_DAILY_ENERGY_ENTITY)
    )
    energy_factor = _ENERGY_TO_KWH.get(energy_unit)
    if energy_value is None:
        energy_text = "--.-- kWh"
    elif energy_factor is not None:
        energy_text = f"{energy_value * energy_factor:.2f} kWh"
    else:
        energy_text = _raw_display(energy_value, energy_unit, "--.-- kWh")

    metrics = options.get(CONF_POWER_METRICS, [])
    payload: dict[str, Any] = {
        "power_configured": bool(
            options.get(CONF_MAIN_POWER_ENTITY)
            or options.get(CONF_DAILY_ENERGY_ENTITY)
            or metrics
        ),
        "claude_configured": any(
            options.get(field)
            for field in (
                CONF_CLAUDE_SESSION_ENTITY,
                CONF_CLAUDE_WEEK_ENTITY,
                CONF_CLAUDE_EXTRA_USED_ENTITY,
                CONF_CLAUDE_EXTRA_LIMIT_ENTITY,
                CONF_CLAUDE_EXTRA_PERCENT_ENTITY,
            )
        ),
        "power_available": power_available,
        "power_kw": power_kw,
        "power_text": power_text,
        "energy_text": energy_text,
        "extra_label": (
            "Extra remaining"
            if options.get(CONF_CLAUDE_EXTRA_MODE, "used") == "remaining"
            else "Extra used"
        ),
    }

    for index in range(MAX_POWER_METRICS):
        metric = metrics[index] if index < len(metrics) else {}
        entity_id = (
            metric.get(CONF_METRIC_ENTITY_ID) if isinstance(metric, Mapping) else None
        )
        name = metric.get(CONF_METRIC_NAME, "") if isinstance(metric, Mapping) else ""
        value, unit = _read_sensor(hass, entity_id)
        factor = _POWER_TO_KW.get(unit)
        payload[f"metric_{index + 1}_enabled"] = bool(entity_id)
        payload[f"metric_{index + 1}_name"] = name
        payload[f"metric_{index + 1}_text"] = (
            f"{value * factor * 1000:.0f} W"
            if value is not None and factor is not None
            else _raw_display(value, unit, "-- W")
        )

    _add_percentage(payload, hass, "session", options.get(CONF_CLAUDE_SESSION_ENTITY))
    _add_percentage(payload, hass, "week", options.get(CONF_CLAUDE_WEEK_ENTITY))
    _add_percentage(
        payload,
        hass,
        "extra",
        options.get(CONF_CLAUDE_EXTRA_PERCENT_ENTITY),
    )

    used, used_unit = _read_sensor(hass, options.get(CONF_CLAUDE_EXTRA_USED_ENTITY))
    limit, limit_unit = _read_sensor(hass, options.get(CONF_CLAUDE_EXTRA_LIMIT_ENTITY))
    mode = options.get(CONF_CLAUDE_EXTRA_MODE, "used")
    if mode == "remaining":
        compatible_units = used_unit == limit_unit
        extra_value = (
            limit - used
            if used is not None and limit is not None and compatible_units
            else None
        )
        extra_unit = used_unit or limit_unit or "credits"
    else:
        extra_value = used
        extra_unit = used_unit or "credits"
    payload["extra_enabled"] = bool(
        options.get(CONF_CLAUDE_EXTRA_USED_ENTITY)
        or (mode == "remaining" and options.get(CONF_CLAUDE_EXTRA_LIMIT_ENTITY))
    )
    payload["extra_text"] = (
        f"{extra_value:.1f} {extra_unit}"
        if extra_value is not None
        else "-- credits"
    )
    payload["extra_limit_enabled"] = bool(
        options.get(CONF_CLAUDE_EXTRA_LIMIT_ENTITY)
    )
    payload["extra_limit_text"] = (
        f"{limit:.1f} {limit_unit or 'credits'}"
        if limit is not None
        else "-- credits"
    )
    return payload


def _add_percentage(
    payload: dict[str, Any], hass: Any, name: str, entity_id: Any
) -> None:
    value, _unit = _read_sensor(hass, entity_id)
    payload[f"{name}_enabled"] = bool(entity_id)
    payload[f"{name}_bar_enabled"] = bool(entity_id) and value is not None
    payload[f"{name}_percent"] = value if value is not None else 0.0
    payload[f"{name}_text"] = f"{value:.0f}%" if value is not None else "--%"


def _read_sensor(hass: Any, entity_id: Any) -> tuple[float | None, str]:
    if not isinstance(entity_id, str) or not entity_id:
        return None, ""
    state = hass.states.get(entity_id)
    if state is None:
        return None, ""
    value = numeric_state(state.state)
    unit = state.attributes.get("unit_of_measurement", "")
    return value, unit if isinstance(unit, str) else ""


def _raw_display(value: float | None, unit: str, fallback: str) -> str:
    if value is None:
        return fallback
    text = f"{value:.2f} {unit}".strip()
    return text[:24]


def _looks_like_entity_id(value: str) -> bool:
    domain, separator, object_id = value.partition(".")
    return bool(
        separator
        and domain
        and object_id
        and " " not in value
        and value.count(".") == 1
    )
