"""Validate dashboard options and format live HA states for the CYD."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import json
import math
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .alerts import numeric_state
from .const import (
    CONF_AI_PROVIDERS,
    CONF_AUTO_ROTATION,
    CONF_CAMERA_ENTITY,
    CONF_CAMERA_REFRESH_INTERVAL,
    CONF_CLAUDE_EXTRA_LIMIT_ENTITY,
    CONF_CLAUDE_EXTRA_MODE,
    CONF_CLAUDE_EXTRA_PERCENT_ENTITY,
    CONF_CLAUDE_EXTRA_USED_ENTITY,
    CONF_CLAUDE_SESSION_ENTITY,
    CONF_CLAUDE_SESSION_RESET_ENTITY,
    CONF_CLAUDE_WEEK_ENTITY,
    CONF_CLAUDE_WEEK_RESET_ENTITY,
    CONF_CLIMATE_ENTITY,
    CONF_ROOM_ENTITIES,
    CONF_CODEX_NAME,
    CONF_CODEX_SESSION_ENTITY,
    CONF_CODEX_WEEK_ENTITY,
    CONF_DAILY_ENERGY_ENTITY,
    CONF_MAIN_POWER_ENTITY,
    CONF_METRIC_ENTITY_ID,
    CONF_METRIC_NAME,
    CONF_POWER_METRICS,
    CONF_PROVIDER_NAME,
    CONF_PROVIDER_SESSION_ENTITY,
    CONF_PROVIDER_SESSION_RESET_ENTITY,
    CONF_PROVIDER_WEEK_ENTITY,
    CONF_PROVIDER_WEEK_RESET_ENTITY,
    CONF_ROTATION_INTERVAL,
    CONF_ROTATION_PAGE_1,
    CONF_ROTATION_PAGE_2,
    CONF_ROTATION_PAGE_3,
    CONF_ROTATION_PAGE_4,
    CONF_ROTATION_PAGE_5,
    CONF_ROTATION_PAGE_6,
    CONF_SENSOR_METRICS,
    CONF_SHOW_AI_PAGE,
    CONF_SHOW_CAMERA_PAGE,
    CONF_SHOW_CLIMATE_PAGE,
    CONF_SHOW_ENERGY_PAGE,
    CONF_SHOW_SENSORS_PAGE,
)

MAX_POWER_METRICS = 4
MAX_SENSOR_METRICS = 5
MAX_AI_PROVIDERS = 3
MAX_ROOMS = 4
MAX_ROOM_DEVICES = 5
ROOM_DEVICE_DOMAINS = frozenset({"climate", "light", "switch"})
EXTRA_MODES = frozenset({"used", "remaining"})
ROTATION_INTERVAL_MIN = 10
ROTATION_INTERVAL_MAX = 120
ROTATION_INTERVAL_STEP = 5
PAGE_ORDER_FIELDS = (
    CONF_ROTATION_PAGE_1,
    CONF_ROTATION_PAGE_2,
    CONF_ROTATION_PAGE_3,
    CONF_ROTATION_PAGE_4,
    CONF_ROTATION_PAGE_5,
    CONF_ROTATION_PAGE_6,
)
PAGE_ORDER_VALUES = ("home", "ai", "climate", "sensors", "energy", "camera")
PAGE_VISIBLE_FIELDS = (
    (CONF_SHOW_AI_PAGE, "page_ai_enabled"),
    (CONF_SHOW_CLIMATE_PAGE, "page_climate_enabled"),
    (CONF_SHOW_SENSORS_PAGE, "page_sensors_enabled"),
    (CONF_SHOW_ENERGY_PAGE, "page_energy_enabled"),
    (CONF_SHOW_CAMERA_PAGE, "page_camera_enabled"),
)

_POWER_TO_KW = {"W": 0.001, "kW": 1.0, "MW": 1000.0, "mW": 0.000001}
_ENERGY_TO_KWH = {
    "Wh": 0.001,
    "kWh": 1.0,
    "MWh": 1000.0,
    "mWh": 0.000001,
}

_ENTITY_FIELDS = (
    CONF_CLIMATE_ENTITY,
    CONF_CAMERA_ENTITY,
    CONF_MAIN_POWER_ENTITY,
    CONF_DAILY_ENERGY_ENTITY,
    CONF_CLAUDE_SESSION_ENTITY,
    CONF_CLAUDE_WEEK_ENTITY,
    CONF_CLAUDE_SESSION_RESET_ENTITY,
    CONF_CLAUDE_WEEK_RESET_ENTITY,
    CONF_CLAUDE_EXTRA_USED_ENTITY,
    CONF_CLAUDE_EXTRA_LIMIT_ENTITY,
    CONF_CLAUDE_EXTRA_PERCENT_ENTITY,
)


def validate_dashboard(
    values: Any,
    hass: Any | None = None,
    *,
    enforce_room_capacity: bool = False,
) -> dict[str, Any]:
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

    auto_rotation = values.get(CONF_AUTO_ROTATION, False)
    if not isinstance(auto_rotation, bool):
        raise ValueError("Automatic rotation setting must be boolean")
    validated[CONF_AUTO_ROTATION] = auto_rotation

    interval_value = values.get(CONF_ROTATION_INTERVAL, 30)
    if isinstance(interval_value, bool) or not isinstance(interval_value, (int, float)):
        raise ValueError("Page rotation interval must be a number")
    if not math.isfinite(interval_value):
        raise ValueError("Page rotation interval must be finite")
    interval = int(round(interval_value))
    if (
        abs(interval - interval_value) > 1e-6
        or not ROTATION_INTERVAL_MIN <= interval <= ROTATION_INTERVAL_MAX
        or (interval - ROTATION_INTERVAL_MIN) % ROTATION_INTERVAL_STEP
    ):
        raise ValueError("Page rotation interval must be 10–120 seconds in 5-second steps")
    validated[CONF_ROTATION_INTERVAL] = interval

    camera_refresh_value = values.get(CONF_CAMERA_REFRESH_INTERVAL, 30)
    if isinstance(camera_refresh_value, bool) or not isinstance(
        camera_refresh_value, (int, float)
    ):
        raise ValueError("Camera refresh interval must be a number")
    if not math.isfinite(camera_refresh_value):
        raise ValueError("Camera refresh interval must be finite")
    camera_refresh_interval = int(round(camera_refresh_value))
    if (
        abs(camera_refresh_interval - camera_refresh_value) > 1e-6
        or not ROTATION_INTERVAL_MIN <= camera_refresh_interval <= ROTATION_INTERVAL_MAX
        or (camera_refresh_interval - ROTATION_INTERVAL_MIN) % ROTATION_INTERVAL_STEP
    ):
        raise ValueError(
            "Camera refresh interval must be 10–120 seconds in 5-second steps"
        )
    validated[CONF_CAMERA_REFRESH_INTERVAL] = camera_refresh_interval

    for field, _action_field in PAGE_VISIBLE_FIELDS:
        value = values.get(field, True)
        if not isinstance(value, bool):
            raise ValueError(f"{field} must be boolean")
        validated[field] = value

    page_order = [
        values.get(field, PAGE_ORDER_VALUES[index])
        for index, field in enumerate(PAGE_ORDER_FIELDS)
    ]
    if (
        any(
            not isinstance(page, str) or page not in PAGE_ORDER_VALUES
            for page in page_order
        )
        or set(page_order) != set(PAGE_ORDER_VALUES)
    ):
        raise ValueError("Page rotation order must include each dashboard page exactly once")
    for field, page in zip(PAGE_ORDER_FIELDS, page_order, strict=True):
        validated[field] = page

    climate_entity = validated[CONF_CLIMATE_ENTITY]
    if climate_entity is not None and not climate_entity.startswith("climate."):
        raise ValueError("Thermostat entity must be in the climate domain")
    validated[CONF_ROOM_ENTITIES] = _validate_room_entities(
        values, hass, enforce_capacity=enforce_room_capacity
    )
    camera_entity = validated[CONF_CAMERA_ENTITY]
    if camera_entity is not None and not camera_entity.startswith("camera."):
        raise ValueError("Snapshot entity must be in the camera domain")
    for field in (CONF_CLAUDE_SESSION_RESET_ENTITY, CONF_CLAUDE_WEEK_RESET_ENTITY):
        entity_id = validated[field]
        if entity_id is not None and not entity_id.startswith("sensor."):
            raise ValueError(f"{field} must be a sensor entity")

    validated[CONF_AI_PROVIDERS] = _validate_ai_providers(values)

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

    sensor_metrics = values.get(CONF_SENSOR_METRICS, [])
    if not isinstance(sensor_metrics, list):
        raise TypeError("Sensor metrics must be a list")
    if len(sensor_metrics) > MAX_SENSOR_METRICS:
        raise ValueError(f"At most {MAX_SENSOR_METRICS} sensor metrics are supported")
    validated_sensors: list[dict[str, str]] = []
    for index, metric in enumerate(sensor_metrics, start=1):
        if not isinstance(metric, Mapping):
            raise TypeError(f"Sensor metric {index} must be an object")
        entity_id = metric.get(CONF_METRIC_ENTITY_ID)
        name = metric.get(CONF_METRIC_NAME)
        if (
            not isinstance(entity_id, str)
            or not _looks_like_entity_id(entity_id.strip())
            or not entity_id.strip().startswith("sensor.")
        ):
            raise ValueError(f"Sensor metric {index} needs a sensor entity")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Sensor metric {index} needs a display name")
        name = " ".join(name.split())
        if len(name) > 18:
            raise ValueError(f"Sensor metric {index} name must be 18 characters or less")
        if any(not character.isprintable() for character in name):
            raise ValueError(f"Sensor metric {index} name must be printable")
        validated_sensors.append(
            {CONF_METRIC_ENTITY_ID: entity_id.strip(), CONF_METRIC_NAME: name}
        )
    validated[CONF_SENSOR_METRICS] = validated_sensors
    return validated


def _validate_room_entities(
    values: Mapping[str, Any],
    hass: Any | None,
    *,
    enforce_capacity: bool,
) -> list[str]:
    """Validate selected controls and, when available, their HA Area capacities."""
    entities = values.get(CONF_ROOM_ENTITIES, [])
    if not isinstance(entities, list):
        raise TypeError("Room devices must be a list")
    if len(entities) > MAX_ROOMS * MAX_ROOM_DEVICES:
        raise ValueError(
            f"At most {MAX_ROOMS * MAX_ROOM_DEVICES} room devices are supported"
        )

    normalized: list[str] = []
    for entity_id in entities:
        if (
            not isinstance(entity_id, str)
            or not _looks_like_entity_id(entity_id.strip())
            or entity_id.strip().partition(".")[0] not in ROOM_DEVICE_DOMAINS
        ):
            raise ValueError("Room devices must be climate, light, or switch entities")
        entity_id = entity_id.strip()
        if entity_id in normalized:
            raise ValueError("A room device can only be selected once")
        normalized.append(entity_id)

    if hass is not None and enforce_capacity:
        groups = _group_room_entities(hass, normalized)
        if len(groups) > MAX_ROOMS:
            raise ValueError(f"At most {MAX_ROOMS} Home Assistant Areas are supported")
        if any(len(group["devices"]) > MAX_ROOM_DEVICES for group in groups):
            raise ValueError(
                f"Each Area can have at most {MAX_ROOM_DEVICES} selected devices"
            )
    return normalized


def _group_room_entities(hass: Any, entities: list[str]) -> list[dict[str, Any]]:
    """Group explicitly selected controls by their entity/device Home Assistant Area."""
    from homeassistant.helpers import area_registry as ar
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    area_registry = ar.async_get(hass)
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    groups: dict[str, dict[str, Any]] = {}
    for entity_id in entities:
        entity_entry = entity_registry.async_get(entity_id)
        area_id = getattr(entity_entry, "area_id", None)
        if not area_id and entity_entry is not None:
            device = device_registry.async_get(entity_entry.device_id)
            area_id = getattr(device, "area_id", None)
        area_id = area_id or "unassigned"
        area = (
            area_registry.async_get_area(area_id)
            if area_id != "unassigned"
            else None
        )
        room = groups.setdefault(
            area_id,
            {
                "area_id": area_id,
                "name": " ".join(area.name.split())[:20]
                if area is not None
                else "Unassigned",
                "devices": [],
            },
        )
        room["devices"].append(entity_id)
    return list(groups.values())


def _validate_ai_providers(values: Mapping[str, Any]) -> list[dict[str, str | None]]:
    """Normalize configurable providers, migrating the former Codex slot."""
    providers = values.get(CONF_AI_PROVIDERS)
    if providers is None:
        legacy_session = values.get(CONF_CODEX_SESSION_ENTITY)
        legacy_week = values.get(CONF_CODEX_WEEK_ENTITY)
        providers = (
            [
                {
                    CONF_PROVIDER_NAME: values.get(CONF_CODEX_NAME, "Codex"),
                    CONF_PROVIDER_SESSION_ENTITY: legacy_session,
                    CONF_PROVIDER_WEEK_ENTITY: legacy_week,
                }
            ]
            if legacy_session or legacy_week
            else []
        )
    if not isinstance(providers, list):
        raise TypeError("AI providers must be a list")
    if len(providers) > MAX_AI_PROVIDERS:
        raise ValueError(f"At most {MAX_AI_PROVIDERS} additional AI providers are supported")

    normalized: list[dict[str, str | None]] = []
    names: set[str] = set()
    for index, provider in enumerate(providers, start=1):
        if not isinstance(provider, Mapping):
            raise TypeError(f"AI provider {index} must be an object")
        name = provider.get(CONF_PROVIDER_NAME)
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"AI provider {index} needs a display name")
        name = name.strip()
        if len(name) > 8:
            raise ValueError(f"AI provider {index} name must be 8 characters or less")
        if name.casefold() in names:
            raise ValueError("AI provider names must be unique")
        names.add(name.casefold())

        entities: dict[str, str | None] = {}
        for field in (
            CONF_PROVIDER_SESSION_ENTITY,
            CONF_PROVIDER_WEEK_ENTITY,
            CONF_PROVIDER_SESSION_RESET_ENTITY,
            CONF_PROVIDER_WEEK_RESET_ENTITY,
        ):
            entity_id = provider.get(field)
            if entity_id in (None, ""):
                entities[field] = None
                continue
            if (
                not isinstance(entity_id, str)
                or not _looks_like_entity_id(entity_id.strip())
                or not entity_id.strip().startswith("sensor.")
            ):
                raise ValueError(f"AI provider {index} {field} must be a sensor entity")
            entities[field] = entity_id.strip()
        if not any(
            entities[field]
            for field in (CONF_PROVIDER_SESSION_ENTITY, CONF_PROVIDER_WEEK_ENTITY)
        ):
            raise ValueError(f"AI provider {index} needs a session or weekly quota sensor")
        normalized.append({CONF_PROVIDER_NAME: name, **entities})
    return normalized


def dashboard_entities(options: Mapping[str, Any]) -> set[str]:
    """Return configured entities whose state changes should refresh the UI."""
    entities = {
        entity_id
        for field in _ENTITY_FIELDS
        if field != CONF_CAMERA_ENTITY or options.get(CONF_SHOW_CAMERA_PAGE, True)
        if isinstance((entity_id := options.get(field)), str) and entity_id
    }
    for provider in options.get(CONF_AI_PROVIDERS, []):
        if isinstance(provider, Mapping):
            for field in (
                CONF_PROVIDER_SESSION_ENTITY,
                CONF_PROVIDER_WEEK_ENTITY,
                CONF_PROVIDER_SESSION_RESET_ENTITY,
                CONF_PROVIDER_WEEK_RESET_ENTITY,
            ):
                entity_id = provider.get(field)
                if isinstance(entity_id, str) and entity_id:
                    entities.add(entity_id)
    for metric in options.get(CONF_POWER_METRICS, []):
        if isinstance(metric, Mapping):
            entity_id = metric.get(CONF_METRIC_ENTITY_ID)
            if isinstance(entity_id, str) and entity_id:
                entities.add(entity_id)
    for metric in options.get(CONF_SENSOR_METRICS, []):
        if isinstance(metric, Mapping):
            entity_id = metric.get(CONF_METRIC_ENTITY_ID)
            if isinstance(entity_id, str) and entity_id:
                entities.add(entity_id)
    entities.update(
        entity_id
        for entity_id in options.get(CONF_ROOM_ENTITIES, [])
        if isinstance(entity_id, str) and entity_id
    )
    return entities


def dashboard_action_data(
    hass: Any,
    options: Mapping[str, Any],
    alert_engine: Any | None = None,
) -> dict[str, Any]:
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
    camera_page_enabled = bool(
        options.get(CONF_CAMERA_ENTITY)
        and options.get(CONF_SHOW_CAMERA_PAGE, True)
    )
    payload: dict[str, Any] = {
        **_climate_payload(hass, options.get(CONF_CLIMATE_ENTITY)),
        "room_devices_json": _room_devices_json(hass, options),
        "auto_rotation_enabled": options.get(CONF_AUTO_ROTATION, False),
        "rotation_interval_seconds": options.get(CONF_ROTATION_INTERVAL, 30),
        "camera_refresh_interval_seconds": options.get(
            CONF_CAMERA_REFRESH_INTERVAL, 30
        ),
        "camera_snapshot_url": _camera_snapshot_url(
            hass, options.get(CONF_CAMERA_ENTITY) if camera_page_enabled else None
        ),
        "camera_name": _camera_display_name(
            hass, options.get(CONF_CAMERA_ENTITY) if camera_page_enabled else None
        ),
        # Compatibility flags select API ownership in existing firmware. Every
        # snapshot is authoritative, including empty/not-yet-saved selections.
        # Availability/enabled flags below still describe the actual sources.
        "power_configured": True,
        "claude_configured": True,
        "ai_provider_count": len(options.get(CONF_AI_PROVIDERS, [])),
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

    for option_field, action_field in PAGE_VISIBLE_FIELDS:
        payload[action_field] = options.get(option_field, True)
    payload["page_camera_enabled"] = camera_page_enabled
    for index, option_field in enumerate(PAGE_ORDER_FIELDS):
        default_page = PAGE_ORDER_VALUES[index]
        page = options.get(option_field, default_page)
        payload[option_field] = PAGE_ORDER_VALUES.index(page)

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

    sensor_metrics = options.get(CONF_SENSOR_METRICS, [])
    payload["sensor_monitor_configured"] = True
    for index in range(MAX_SENSOR_METRICS):
        metric = sensor_metrics[index] if index < len(sensor_metrics) else {}
        entity_id = (
            metric.get(CONF_METRIC_ENTITY_ID) if isinstance(metric, Mapping) else None
        )
        name = metric.get(CONF_METRIC_NAME, "") if isinstance(metric, Mapping) else ""
        payload[f"sensor_{index + 1}_enabled"] = bool(entity_id)
        payload[f"sensor_{index + 1}_name"] = name
        payload[f"sensor_{index + 1}_text"] = _monitor_sensor_text(hass, entity_id)
        payload[f"sensor_{index + 1}_status"] = (
            alert_engine.sensor_status(entity_id)
            if entity_id and alert_engine is not None
            else 0
        )

    _add_percentage(payload, hass, "session", options.get(CONF_CLAUDE_SESSION_ENTITY))
    _add_percentage(payload, hass, "week", options.get(CONF_CLAUDE_WEEK_ENTITY))
    payload["session_reset_epoch_minute"] = _reset_epoch_minute(
        hass,
        options.get(CONF_CLAUDE_SESSION_RESET_ENTITY),
        options.get(CONF_CLAUDE_SESSION_ENTITY),
    )
    payload["week_reset_epoch_minute"] = _reset_epoch_minute(
        hass,
        options.get(CONF_CLAUDE_WEEK_RESET_ENTITY),
        options.get(CONF_CLAUDE_WEEK_ENTITY),
    )
    _add_percentage(
        payload,
        hass,
        "extra",
        options.get(CONF_CLAUDE_EXTRA_PERCENT_ENTITY),
    )
    providers = options.get(CONF_AI_PROVIDERS, [])
    for index in range(MAX_AI_PROVIDERS):
        provider = providers[index] if index < len(providers) else {}
        prefix = f"provider_{index + 1}"
        payload[f"{prefix}_name"] = provider.get(CONF_PROVIDER_NAME, "")
        _add_percentage(
            payload,
            hass,
            f"{prefix}_session",
            provider.get(CONF_PROVIDER_SESSION_ENTITY),
        )
        _add_percentage(
            payload,
            hass,
            f"{prefix}_week",
            provider.get(CONF_PROVIDER_WEEK_ENTITY),
        )
        payload[f"{prefix}_session_reset_epoch_minute"] = _reset_epoch_minute(
            hass,
            provider.get(CONF_PROVIDER_SESSION_RESET_ENTITY),
            provider.get(CONF_PROVIDER_SESSION_ENTITY),
        )
        payload[f"{prefix}_week_reset_epoch_minute"] = _reset_epoch_minute(
            hass,
            provider.get(CONF_PROVIDER_WEEK_RESET_ENTITY),
            provider.get(CONF_PROVIDER_WEEK_ENTITY),
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
    if used is not None and limit is not None and used_unit == limit_unit:
        display_value = extra_value if mode == "remaining" else used
        compact_unit = "cr" if extra_unit.casefold() == "credits" else extra_unit
        payload["extra_summary_text"] = (
            f"{display_value:.1f}/{limit:.1f} {compact_unit}".strip()
        )
    else:
        payload["extra_summary_text"] = payload["extra_text"]
    payload["extra_limit_enabled"] = bool(
        options.get(CONF_CLAUDE_EXTRA_LIMIT_ENTITY)
    )
    payload["extra_limit_text"] = (
        f"{limit:.1f} {limit_unit or 'credits'}"
        if limit is not None
        else "-- credits"
    )
    return payload


def _room_devices_json(hass: Any, options: Mapping[str, Any]) -> str:
    """Serialize the selected, area-grouped device controls for the CYD UI."""
    selected_entities = options.get(CONF_ROOM_ENTITIES, [])
    if not isinstance(selected_entities, list):
        selected_entities = []
    # Preserve existing installs: the former single thermostat remains in the
    # Unassigned room until its owner selects devices in the new room setting.
    if not selected_entities and options.get(CONF_CLIMATE_ENTITY):
        selected_entities = [options[CONF_CLIMATE_ENTITY]]

    try:
        groups = _group_room_entities(hass, selected_entities)
    except (ImportError, AttributeError):
        # Isolated formatting tests and unusual HA registries treat devices as
        # unassigned rather than suppressing otherwise valid selected controls.
        groups = [
            {
                "area_id": "unassigned",
                "name": "Unassigned",
                "devices": selected_entities,
            }
        ] if selected_entities else []

    rooms: list[dict[str, Any]] = []
    for room in groups[:MAX_ROOMS]:
        devices: list[dict[str, Any]] = []
        entities = room["devices"]
        for entity_id in entities[:MAX_ROOM_DEVICES]:
            if not isinstance(entity_id, str) or "." not in entity_id:
                continue
            domain = entity_id.partition(".")[0]
            state = hass.states.get(entity_id)
            attributes = state.attributes if state is not None else {}
            name = attributes.get("friendly_name")
            if not isinstance(name, str) or not name.strip():
                name = entity_id.partition(".")[2].replace("_", " ").title()
            name = " ".join(name.split())[:22]
            state_text = (
                "Unavailable"
                if state is None or state.state in {"unknown", "unavailable"}
                else state.state
            )
            device: dict[str, Any] = {
                "entity_id": entity_id,
                "domain": domain,
                "name": name,
                "state": state_text,
            }
            if domain == "climate":
                climate = _climate_payload(hass, entity_id)
                device["climate"] = {
                    "current": climate["climate_current_text"],
                    "target": climate["climate_target_text"],
                    "value": climate["climate_target"],
                    "low": climate["climate_target_low"],
                    "high": climate["climate_target_high"],
                    "step": climate["climate_temperature_step"],
                    "min": climate["climate_min_temp"],
                    "max": climate["climate_max_temp"],
                    "range": climate["climate_range_control"],
                    "available": climate["climate_target_available"],
                    "mode": climate["climate_mode_text"],
                    "prev": climate["climate_mode_previous"][:14],
                    "next": climate["climate_mode_next"][:14],
                    "mode_control": climate["climate_mode_control"],
                }
                device["value"] = f"{device['climate']['current']} / {device['climate']['target']}"
            elif state_text in {"on", "off"}:
                device["value"] = state_text.upper()
            else:
                device["value"] = "UNAVAILABLE"
            devices.append(device)
        rooms.append({"name": room["name"], "devices": devices})
    return json.dumps({"rooms": rooms}, ensure_ascii=True, separators=(",", ":"))


def _camera_snapshot_url(hass: Any, entity_id: Any) -> str:
    """Build a short-lived local camera-proxy URL; never persist this value."""
    if not isinstance(entity_id, str) or not entity_id.startswith("camera."):
        return ""
    state = hass.states.get(entity_id)
    token = state.attributes.get("access_token") if state is not None else None
    if not isinstance(token, str) or not token:
        return ""
    internal_url = getattr(getattr(hass, "config", None), "internal_url", None)
    if not isinstance(internal_url, str) or not internal_url:
        # Explicit internal_url is optional in HA. Resolve the automatically
        # detected LAN URL, never an external/cloud fallback carrying the token.
        # Keep the import lazy: the pure payload module is also used offline.
        try:
            from homeassistant.helpers.network import NoURLAvailableError, get_url
        except ImportError:
            return ""
        try:
            internal_url = get_url(
                hass,
                allow_internal=True,
                allow_external=False,
                allow_cloud=False,
                allow_ip=True,
                prefer_external=False,
            )
        except NoURLAvailableError:
            return ""
    if not isinstance(internal_url, str):
        return ""
    try:
        parsed = urlsplit(internal_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            return ""
    except ValueError:
        return ""

    base_path = parsed.path.rstrip("/")
    proxy_path = f"{base_path}/api/cyd_ha_monitor/camera_thumbnail/{entity_id}"
    query = urlencode({"token": token})
    return urlunsplit((parsed.scheme, parsed.netloc, proxy_path, query, ""))


def _camera_display_name(hass: Any, entity_id: Any) -> str:
    """Return a short camera label without exposing its access token."""
    if not isinstance(entity_id, str) or not entity_id:
        return "CAMERA"
    state = hass.states.get(entity_id)
    attributes = state.attributes if state is not None else {}
    name = attributes.get("friendly_name")
    if not isinstance(name, str) or not name.strip():
        name = entity_id.partition(".")[2].replace("_", " ").title()
    return " ".join(name.split())[:20]


def _climate_payload(hass: Any, entity_id: Any) -> dict[str, Any]:
    """Format one selected climate entity for the thermostat card and controls."""
    state = hass.states.get(entity_id) if isinstance(entity_id, str) else None
    attributes = state.attributes if state is not None else {}
    unit = attributes.get("temperature_unit", "°C")
    if not isinstance(unit, str) or not unit:
        unit = "°C"

    current = _numeric_attribute(attributes.get("current_temperature"))
    target = _numeric_attribute(attributes.get("temperature"))
    target_low = _numeric_attribute(attributes.get("target_temp_low"))
    target_high = _numeric_attribute(attributes.get("target_temp_high"))
    mode = state.state if state is not None else ""
    modes_value = attributes.get("hvac_modes", [])
    modes = (
        [item for item in modes_value if isinstance(item, str) and item]
        if isinstance(modes_value, (list, tuple))
        else []
    )
    try:
        mode_index = modes.index(mode)
    except ValueError:
        mode_index = 0
    mode_previous = modes[(mode_index - 1) % len(modes)] if modes else ""
    mode_next = modes[(mode_index + 1) % len(modes)] if modes else ""

    step = _numeric_attribute(attributes.get("target_temp_step"))
    minimum = _numeric_attribute(attributes.get("min_temp"))
    maximum = _numeric_attribute(attributes.get("max_temp"))
    if step is None or step <= 0:
        step = 0.5
    if minimum is None:
        minimum = -100.0
    if maximum is None:
        maximum = 100.0

    unavailable = state is None or state.state in {"unknown", "unavailable"}
    range_control = target_low is not None and target_high is not None
    target_value = (
        (target_low + target_high) / 2
        if range_control
        else target
    )
    target_text = (
        f"{_compact_temperature(target_low)}-{_compact_temperature(target_high)}{unit}"
        if range_control
        else f"{target:.1f}{unit}" if target is not None else f"--.-{unit}"
    )
    return {
        "climate_configured": isinstance(entity_id, str) and bool(entity_id),
        "climate_entity": entity_id if isinstance(entity_id, str) else "",
        "climate_current_text": f"{current:.1f}{unit}" if current is not None else f"--.-{unit}",
        "climate_target_text": target_text,
        "climate_target": target_value if target_value is not None else 0.0,
        "climate_target_low": target_low if target_low is not None else 0.0,
        "climate_target_high": target_high if target_high is not None else 0.0,
        "climate_target_available": target_value is not None and not unavailable,
        "climate_range_control": range_control and not unavailable,
        "climate_mode_text": _climate_mode_label(mode) if not unavailable else "Unavailable",
        "climate_mode_previous": mode_previous,
        "climate_mode_next": mode_next,
        "climate_mode_previous_label": (
            f"< {_climate_mode_label(mode_previous).upper()}" if mode_previous else ""
        ),
        "climate_mode_next_label": (
            f"{_climate_mode_label(mode_next).upper()} >" if mode_next else ""
        ),
        "climate_mode_control": len(modes) > 1 and not unavailable,
        "climate_temperature_step": step,
        "climate_min_temp": minimum,
        "climate_max_temp": maximum,
    }


def _numeric_attribute(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _compact_temperature(value: float) -> str:
    """Keep target ranges on one line without showing redundant decimal zeros."""
    return f"{value:.1f}".removesuffix(".0")


def _climate_mode_label(mode: str) -> str:
    """Make HA's snake-case hvac mode legible on the compact display."""
    if not mode:
        return "Unavailable"
    return mode.replace("_", " ").title()[:16]


def _add_percentage(
    payload: dict[str, Any], hass: Any, name: str, entity_id: Any
    ) -> None:
    value, _unit = _read_sensor(hass, entity_id)
    payload[f"{name}_enabled"] = bool(entity_id)
    payload[f"{name}_bar_enabled"] = bool(entity_id) and value is not None
    payload[f"{name}_percent"] = value if value is not None else 0.0
    payload[f"{name}_text"] = f"{value:.0f}%" if value is not None else "--%"


def _reset_epoch_minute(
    hass: Any,
    reset_entity_id: Any,
    quota_entity_id: Any,
) -> int:
    """Return a reset timestamp in Unix epoch minutes, or -1 if unavailable.

    Quota integrations such as hass-claude-usage expose a ``resets_at``
    attribute directly on the percentage sensor, so that remains the no-setup
    fallback when no dedicated reset entity has been selected.
    """
    candidates: list[Any] = []
    for entity_id in (reset_entity_id, quota_entity_id):
        if not isinstance(entity_id, str) or not entity_id:
            continue
        state = hass.states.get(entity_id)
        if state is None:
            continue
        if entity_id == reset_entity_id:
            candidates.append(getattr(state, "state", None))
        attributes = getattr(state, "attributes", {})
        if isinstance(attributes, Mapping):
            candidates.extend(
                attributes.get(key)
                for key in ("resets_at", "reset_at", "timestamp")
            )

    reset_at = next(
        (
            parsed
            for value in candidates
            if (parsed := _parse_reset_datetime(value, hass)) is not None
        ),
        None,
    )
    if reset_at is None:
        return -1
    return math.floor(reset_at.timestamp() / 60)


def _parse_reset_datetime(value: Any, hass: Any) -> datetime | None:
    """Parse HA datetime states, ISO strings, and Unix timestamp attributes."""
    parsed: datetime | None = None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, bool) or value is None:
        return None
    elif isinstance(value, (int, float)):
        if not math.isfinite(value):
            return None
        timestamp = float(value)
        if abs(timestamp) >= 10_000_000_000:
            timestamp /= 1000
        if abs(timestamp) < 100_000_000:
            return None
        try:
            parsed = datetime.fromtimestamp(timestamp, timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    elif isinstance(value, str):
        value = value.strip()
        if not value or value.casefold() in {"unknown", "unavailable", "none"}:
            return None
        try:
            timestamp = float(value)
        except ValueError:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
        else:
            return _parse_reset_datetime(timestamp, hass)
    else:
        return None

    if parsed.tzinfo is None:
        timezone_name = getattr(getattr(hass, "config", None), "time_zone", None)
        try:
            local_timezone = ZoneInfo(timezone_name) if timezone_name else timezone.utc
        except (ZoneInfoNotFoundError, TypeError):
            local_timezone = timezone.utc
        parsed = parsed.replace(tzinfo=local_timezone)
    try:
        return parsed.astimezone(timezone.utc)
    except (OverflowError, ValueError):
        return None


def _read_sensor(hass: Any, entity_id: Any) -> tuple[float | None, str]:
    if not isinstance(entity_id, str) or not entity_id:
        return None, ""
    state = hass.states.get(entity_id)
    if state is None:
        return None, ""
    value = numeric_state(state.state)
    unit = state.attributes.get("unit_of_measurement", "")
    return value, unit if isinstance(unit, str) else ""


def _monitor_sensor_text(hass: Any, entity_id: Any) -> str:
    """Format a numeric or textual HA sensor value for one compact row."""
    if not isinstance(entity_id, str) or not entity_id:
        return "Unavailable"
    state = hass.states.get(entity_id)
    if state is None or state.state.strip().casefold() in {
        "", "unknown", "unavailable", "none"
    }:
        return "Unavailable"
    value = numeric_state(state.state)
    unit = state.attributes.get("unit_of_measurement", "")
    unit = " ".join(unit.split()) if isinstance(unit, str) else ""
    if value is None:
        text = " ".join(state.state.split())
    elif value.is_integer():
        text = f"{value:.0f}"
    elif abs(value) >= 100:
        text = f"{value:.1f}"
    elif abs(value) >= 1:
        text = f"{value:.2f}".rstrip("0").rstrip(".")
    elif abs(value) >= 0.01:
        text = f"{value:.3f}".rstrip("0").rstrip(".")
    else:
        text = f"{value:.2g}"
    if unit:
        text = f"{text} {unit}"
    return text[:16]


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
