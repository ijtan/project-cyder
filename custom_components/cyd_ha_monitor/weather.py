"""Selected-source weather: 17-argument current data and optional 20-field caches."""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime, timezone
import logging
import math
import re
import time
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

CONF_WEATHER_ENTITY = "weather_entity"
CONF_WEATHER_ENABLED = "weather_enabled"
CONF_WEATHER_FORECAST = "weather_forecast"
ACTION_UPDATE_WEATHER = "update_weather"
ACTION_UPDATE_WEATHER_FORECASTS = "update_weather_forecasts"
FORECAST_INTERVAL = 900
MAX_FORECAST_ROWS = 3
_LOGGER = logging.getLogger(__name__)


def validate_weather(values: Mapping[str, Any]) -> dict[str, Any]:
    entity = values.get(CONF_WEATHER_ENTITY)
    if entity == "":
        entity = None
    if entity is not None and (not isinstance(entity, str)
                              or not re.fullmatch(r"weather\.[a-z0-9_]+", entity)):
        raise ValueError("Choose a weather entity")
    enabled = values.get(CONF_WEATHER_ENABLED, False)
    mode = values.get(CONF_WEATHER_FORECAST, "auto")
    if not isinstance(enabled, bool) or mode not in ("auto", "hourly", "daily"):
        raise ValueError("Invalid weather options")
    return {CONF_WEATHER_ENTITY: entity, CONF_WEATHER_ENABLED: enabled,
            CONF_WEATHER_FORECAST: mode}


def _text(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.replace("\x00", "").split())[:limit]


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if abs(value) <= 10000 and math.isfinite(value) else None


def _temperature(value: Any, unit: Any, precision: int = 1) -> str:
    number = _number(value)
    if number is None:
        return "--"
    formatted = f"{number:.{precision}f}"
    if precision:
        formatted = formatted.rstrip("0").rstrip(".")
    return f"{formatted}{_text(unit, 4)}"[:16]


def _condition(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return {"partlycloudy": "Partly cloudy", "clear-night": "Clear night",
            "lightning-rainy": "Thunderstorms", "windy-variant": "Windy / cloudy",
            "snowy-rainy": "Sleet"}.get(value, _text(value, 24).replace("-", " ").capitalize())


def forecast_type(state: Any, mode: str) -> str | None:
    # HA WeatherEntityFeature: DAILY=1, HOURLY=2, TWICE_DAILY=4.
    features = state.attributes.get("supported_features", 0) if state is not None else 0
    if not isinstance(features, int) or isinstance(features, bool):
        return None
    candidates = (mode,) if mode != "auto" else ("hourly", "daily", "twice_daily")
    return next((kind for kind in candidates
                 if features & {"daily": 1, "hourly": 2, "twice_daily": 4}[kind]), None)


def forecast_rows(raw: Any, kind: str, unit: Any, now: datetime,
                  zone: ZoneInfo) -> list[tuple[str, str, str]]:
    rows = []
    if not isinstance(raw, list):
        return rows
    for item in raw[:48]:
        if not isinstance(item, Mapping) or not isinstance(item.get("datetime"), str):
            continue
        try:
            stamp = datetime.fromisoformat(item["datetime"].replace("Z", "+00:00"))
        except ValueError:
            continue
        if stamp.tzinfo is None:
            continue
        local = stamp.astimezone(zone)
        if kind == "hourly" and stamp < now:
            continue
        if kind != "hourly" and local.date() < now.astimezone(zone).date():
            continue
        label = local.strftime("%H:%M" if kind == "hourly" else "%a")
        if kind == "twice_daily":
            label += " AM" if item.get("is_daytime") else " PM"
        # Whole degrees keep forecast ranges legible on the 97 px cards.
        high = _temperature(item.get("temperature"), unit, precision=0)
        low = _number(item.get("templow"))
        temp = f"{low:.0f}/{high}"[:20] if low is not None and kind != "hourly" else high
        rows.append((label, _condition(item.get("condition")), temp))
        if len(rows) == MAX_FORECAST_ROWS:
            break
    return rows


def weather_action_data(state: Any, options: Mapping[str, Any],
                        rows: list[tuple[str, str, str]], kind: str | None,
                        forecast_status: str = "", updated: str = "") -> dict[str, Any]:
    enabled = bool(options.get(CONF_WEATHER_ENABLED) and options.get(CONF_WEATHER_ENTITY))
    available = enabled and state is not None and state.state not in ("unavailable", "unknown")
    attrs = state.attributes if available else {}
    parts = []
    apparent = _number(attrs.get("apparent_temperature"))
    wind = _number(attrs.get("wind_speed"))
    if apparent is not None:
        parts.append("Feels " + _temperature(apparent, attrs.get("temperature_unit")))
    if wind is not None:
        parts.append(f"Wind {wind:g} {_text(attrs.get('wind_speed_unit'), 8)}")
    payload = {
        "enabled": enabled, "available": bool(available),
        "location": _text(attrs.get("friendly_name"), 24) if available else "",
        "condition": _condition(state.state) if available else "",
        "temperature": _temperature(attrs.get("temperature"), attrs.get("temperature_unit")) if available else "",
        "details": " / ".join(parts)[:64],
        "forecast_heading": {"hourly": "NEXT HOURS", "daily": "NEXT DAYS",
                             "twice_daily": "DAY / NIGHT"}.get(kind, "FORECAST"),
        "status": _text(forecast_status or updated, 32) if available else "Weather unavailable" if enabled else "Select weather in Cydex",
    }
    for index in range(1, MAX_FORECAST_ROWS + 1):
        row = rows[index - 1] if available and index <= len(rows) else ("", "", "")
        for key, value, limit in zip(("label", "condition", "temperature"), row, (10, 24, 20), strict=True):
            payload[f"forecast_{index}_{key}"] = _text(value, limit)
    assert len(payload) == 17
    return payload


def weather_forecasts_data(state: Any, options: Mapping[str, Any],
                           modes: Mapping[str, list[tuple[str, str, str]]]) -> dict[str, Any]:
    """Two bounded three-card caches; no source fallback or on-tap requests."""
    available = bool(options.get(CONF_WEATHER_ENABLED) and options.get(CONF_WEATHER_ENTITY)
                     and state is not None and state.state not in ("unknown", "unavailable"))
    data: dict[str, Any] = {}
    for kind in ("hourly", "daily"):
        supported = available and forecast_type(state, kind) is not None
        data[f"{kind}_supported"] = supported
        rows = modes.get(kind, []) if supported else []
        for index in range(1, 4):
            row = rows[index - 1] if index <= len(rows) else ("", "", "")
            for key, value, limit in zip(("label", "condition", "temperature"), row, (10, 24, 20), strict=True):
                data[f"{kind}_{index}_{key}"] = _text(value, limit)
    assert len(data) == 20
    return data


class WeatherBridge:
    """Coalesce changes, fetch every 15 minutes, serialize with dashboards."""

    def __init__(self, hass: Any, runtime: Any, options: Mapping[str, Any],
                 clock=time.monotonic) -> None:
        self.hass = hass
        self.runtime = runtime
        self.options = options
        self.clock = clock
        self.task: asyncio.Task | None = None
        self.stopped = False
        self.dirty = False
        self.last_fetch = float("-inf")
        self.rows: list[tuple[str, str, str]] = []
        self.kind: str | None = None
        self.forecast_status = ""
        self.updated = ""
        self.mode_rows: dict[str, list[tuple[str, str, str]]] = {}
        self.mode_last_fetch: dict[str, float] = {}
        self.dual_service = getattr(runtime.service_names, "update_weather_forecasts", None)
        try:
            self.zone = ZoneInfo(getattr(hass.config, "time_zone", "UTC"))
        except (ZoneInfoNotFoundError, TypeError):
            self.zone = ZoneInfo("UTC")

    def schedule(self) -> None:
        if self.stopped or self.runtime.stopped:
            return
        if self.task is not None:
            self.dirty = True
            return
        self.task = self.hass.async_create_task(self._send())

    async def _send(self) -> None:
        try:
            while not self.stopped and not self.runtime.stopped:
                await asyncio.sleep(0.2)
                self.dirty = False
                entity = self.options[CONF_WEATHER_ENTITY]
                enabled = self.options[CONF_WEATHER_ENABLED] and entity is not None
                state = self.hass.states.get(entity) if enabled else None
                if enabled and state is not None and state.state not in ("unavailable", "unknown"):
                    kind = forecast_type(state, self.options[CONF_WEATHER_FORECAST])
                    if kind != self.kind:
                        self.rows = []
                        self.forecast_status = "Forecast unavailable"
                    self.kind = kind
                    if kind is None:
                        self.rows = []
                        self.forecast_status = "Forecast not supported"
                    elif self.clock() - (self.mode_last_fetch.get(kind, float("-inf"))
                                         if self.dual_service else self.last_fetch) >= FORECAST_INTERVAL:
                        self.last_fetch = self.clock()
                        if self.dual_service:
                            self.mode_last_fetch[kind] = self.last_fetch
                        self.rows = []
                        self.forecast_status = "Forecast unavailable"
                        try:
                            async with asyncio.timeout(10):
                                response = await self.hass.services.async_call(
                                    "weather", "get_forecasts", {"entity_id": entity, "type": kind},
                                    blocking=True, return_response=True)
                            now = datetime.now(timezone.utc)
                            raw = response.get(entity, {}).get("forecast") if isinstance(response, Mapping) else None
                            self.rows = forecast_rows(raw, kind, state.attributes.get("temperature_unit"), now, self.zone)
                            if self.rows:
                                self.forecast_status = ""
                                self.updated = "Forecast " + now.astimezone(self.zone).strftime("%H:%M")
                        except asyncio.CancelledError:
                            raise
                        except Exception as err:
                            _LOGGER.warning("Weather forecast unavailable (%s)", type(err).__name__)
                        if self.dual_service and kind in ("hourly", "daily"):
                            self.mode_rows[kind] = self.rows
                    if self.dual_service:
                        # Serial, capability-gated fetches. Switching on the CYD
                        # reads these caches and never bypasses the per-kind timer.
                        for mode in ("hourly", "daily"):
                            if forecast_type(state, mode) is None:
                                self.mode_rows.pop(mode, None)
                                continue
                            if self.clock() - self.mode_last_fetch.get(mode, float("-inf")) < FORECAST_INTERVAL:
                                continue
                            self.mode_last_fetch[mode] = self.clock()
                            self.mode_rows[mode] = []
                            try:
                                async with asyncio.timeout(10):
                                    response = await self.hass.services.async_call(
                                        "weather", "get_forecasts", {"entity_id": entity, "type": mode},
                                        blocking=True, return_response=True)
                                raw = response.get(entity, {}).get("forecast") if isinstance(response, Mapping) else None
                                self.mode_rows[mode] = forecast_rows(raw, mode, state.attributes.get("temperature_unit"),
                                                                     datetime.now(timezone.utc), self.zone)
                            except asyncio.CancelledError:
                                raise
                            except Exception as err:
                                _LOGGER.warning("Weather %s forecast unavailable (%s)", mode, type(err).__name__)
                        if kind in ("hourly", "daily"):
                            self.rows = self.mode_rows.get(kind, [])
                            self.forecast_status = "" if self.rows else "Forecast unavailable"
                else:
                    self.rows = []
                    self.kind = None
                    self.forecast_status = "Forecast unavailable"
                    self.mode_rows.clear()
                async with self.runtime.transition_lock:
                    if self.stopped or self.runtime.stopped:
                        return
                    state = self.hass.states.get(entity) if enabled else None
                    data = weather_action_data(state, self.options, self.rows, self.kind,
                                               self.forecast_status, self.updated)
                    async with asyncio.timeout(10):
                        await self.hass.services.async_call("esphome", self.runtime.service_names.update_weather,
                                                           data, blocking=True)
                    await asyncio.sleep(0.1)
                    if self.dual_service and not self.stopped and not self.runtime.stopped:
                        state = self.hass.states.get(entity) if enabled else None
                        dual_data = weather_forecasts_data(state, self.options, self.mode_rows)
                        async with asyncio.timeout(10):
                            await self.hass.services.async_call("esphome", self.dual_service, dual_data, blocking=True)
                        await asyncio.sleep(0.1)
                if not self.dirty:
                    break
        except asyncio.CancelledError:
            raise
        except Exception as err:
            _LOGGER.warning("Weather display update unavailable (%s)", type(err).__name__)
        finally:
            self.task = None

    async def close(self) -> None:
        self.stopped = True
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        self.rows = []
        self.mode_rows.clear()
