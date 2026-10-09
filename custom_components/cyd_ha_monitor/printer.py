"""Opt-in, selected-source printer monitor; one shared bounded media pipeline."""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime, timezone
import hashlib
import logging
import math
import re
from typing import Any

from .dashboard import _camera_snapshot_url, _local_thumbnail_url

ACTION_UPDATE_PRINTER = "update_printer"
FIELDS = ("status", "progress", "job", "start", "end", "elapsed", "remaining",
          "layer", "total_layers", "nozzle", "nozzle_target", "bed", "bed_target", "render", "camera")
BAMBU_ROLES = dict(zip(FIELDS, ("print_status", "print_progress", "subtask_name", "start_time",
    "end_time", None, "remaining_time", "current_layer", "total_layers", "nozzle_temp",
    "target_nozzle_temp", "bed_temp", "target_bed_temp", "cover_image", "camera"), strict=True))
_LOGGER = logging.getLogger(__name__)


def field_key(field: str) -> str:
    return f"printer_{field}_entity"


def text(value: Any, limit: int = 48) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.replace("\x00", "").split()).encode("utf-8")[:limit].decode("utf-8", errors="ignore")


def validate_printer(values: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    enabled = values.get("printer_enabled", False)
    mode = values.get("printer_mode", "custom")
    visibility = values.get("printer_visibility", "state")
    override = values.get("printer_visibility_override", "auto")
    media_default = values.get("printer_media_default", "render")
    if not isinstance(enabled, bool) or mode not in ("bambu", "custom"):
        raise ValueError("Invalid printer mode")
    if visibility not in ("always", "state") or override not in ("auto", "show", "hide") or media_default not in ("render", "camera"):
        raise ValueError("Invalid visibility")
    result.update(printer_enabled=enabled, printer_mode=mode, printer_visibility=visibility,
                  printer_visibility_override=override, printer_media_default=media_default,
                  printer_name=text(values.get("printer_name", "Printer"), 32))
    device = values.get("printer_device_id")
    if device is not None and (not isinstance(device, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", device)):
        raise ValueError("Invalid device")
    result["printer_device_id"] = device
    for field in (*FIELDS, "condition"):
        key = field_key(field)
        entity = values.get(key) or None
        domains = ("image", "camera") if field in ("render", "camera") else ("sensor", "input_number", "number")
        if field in ("status", "condition", "job"):
            domains = ("sensor", "binary_sensor", "input_select", "select", "input_text", "input_boolean")
        if entity is not None and (not isinstance(entity, str) or len(entity) > 255 or not re.fullmatch(
                rf"({'|'.join(domains)})\.[a-z0-9_]+", entity)):
            raise ValueError(f"Invalid {field} entity")
        result[key] = entity
    states = values.get("printer_condition_states", ["running", "pause"])
    if not isinstance(states, list) or len(states) > 12 or any(
            not isinstance(s, str) or not s.strip() or len(s.encode("utf-8")) > 48 for s in states):
        raise ValueError("Invalid condition states")
    result["printer_condition_states"] = [s.strip() for s in states]
    return result


def bambu_printers(devices: Any, entities: Any) -> list[Any]:
    """Only printer devices owned by Bambu, never AMS/spool child devices."""
    ids = {e.device_id for e in entities if e.platform == "bambu_lab" and not e.disabled_by
           and (getattr(e, "translation_key", None) == "print_status"
                or str(e.unique_id).endswith("_print_status"))}
    return [d for d in devices if d.id in ids and any(domain == "bambu_lab" for domain, _ in d.identifiers)]


def bambu_mapping(device: Any, entities: Any) -> dict[str, Any]:
    owned = [e for e in entities if e.device_id == device.id and e.platform == "bambu_lab" and not e.disabled_by]
    if not bambu_printers([device], owned):
        raise ValueError("Choose a Bambu printer, not a child device")
    result = {"printer_device_id": device.id, "printer_mode": "bambu",
              "printer_name": text(device.name_by_user or device.name or device.model or "Printer", 32)}
    for field, role in BAMBU_ROLES.items():
        if role is None:
            result[field_key(field)] = None
            continue
        domains = ("camera", "image") if field in ("render", "camera") else ("sensor",)
        candidates = [e for e in owned if e.entity_id.partition(".")[0] in domains
                      and getattr(e, "translation_key", None) == role]
        if not candidates:
            candidates = [e for e in owned if e.entity_id.partition(".")[0] in domains
                          and str(e.unique_id).endswith("_" + role)]
        # IMAGECAMERA uses the p1p_camera description but a _camera unique id.
        result[field_key(field)] = candidates[0].entity_id if len(candidates) == 1 else None
    result[field_key("condition")] = result[field_key("status")]
    return result


def printer_entities(options: Mapping[str, Any]) -> set[str]:
    if not options.get("printer_enabled"):
        return set()
    return {options[field_key(f)] for f in (*FIELDS, "condition") if options.get(field_key(f))}


def printer_visible(hass: Any, options: Mapping[str, Any]) -> bool:
    if not options.get("printer_enabled") or not options.get(field_key("status")):
        return False
    override = options.get("printer_visibility_override", "auto")
    if override == "hide":
        return False
    if override == "show" or options.get("printer_visibility") == "always":
        return True
    entity = options.get(field_key("condition"))
    state = hass.states.get(entity) if entity else None
    return state is not None and state.state not in ("unknown", "unavailable") and state.state in options["printer_condition_states"]


def media_url(hass: Any, entity: str | None) -> str:
    if not entity:
        return ""
    state = hass.states.get(entity)
    if state is None or state.state in ("unknown", "unavailable"):
        return ""
    if entity.startswith("camera."):
        return _camera_snapshot_url(hass, entity)
    if not entity.startswith("image."):
        return ""
    return _local_thumbnail_url(hass, entity, "printer_image", "image")


def _value(hass: Any, options: Mapping[str, Any], field: str) -> Any:
    entity = options.get(field_key(field))
    return hass.states.get(entity) if entity else None


def _number(state: Any) -> float | None:
    if state is None or state.state in ("unknown", "unavailable"):
        return None
    try:
        value = float(state.state)
        return value if math.isfinite(value) and abs(value) <= 1e9 else None
    except (TypeError, ValueError, OverflowError):
        return None


def _timestamp(state: Any) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(state.state.replace("Z", "+00:00"))
        return stamp if stamp.tzinfo is not None else None
    except (AttributeError, TypeError, ValueError):
        return None


def _duration(seconds: float | None) -> str:
    if seconds is None or not 0 <= seconds <= 365 * 86400:
        return "--"
    minutes = int(seconds // 60)
    return f"{minutes // 60}h {minutes % 60:02d}m" if minutes >= 60 else f"{minutes}m"


def _seconds(state: Any) -> float | None:
    number = _number(state)
    unit = state.attributes.get("unit_of_measurement") if state is not None else None
    multiplier = {"s": 1, "sec": 1, "min": 60, "h": 3600, "d": 86400}.get(unit)
    return number * multiplier if number is not None and multiplier else None


def printer_action_data(hass: Any, options: Mapping[str, Any], now: datetime | None = None) -> dict[str, Any]:
    visible = printer_visible(hass, options)
    data = {"visible": visible, "name": "", "job": "", "status": "", "progress": 0.0,
            "progress_available": False, "elapsed": "", "remaining": "", "layers": "",
            "nozzle": "", "bed": "", "render_url": "", "camera_url": "", "job_key": "",
            "prefer_camera": options.get("printer_media_default") == "camera"}
    if not visible:
        return data
    now = now or datetime.now(timezone.utc)
    state = _value(hass, options, "status")
    available = state is not None and state.state not in ("unknown", "unavailable", "offline")
    data.update(name=options.get("printer_name") or "Printer",
                status=text(state.state, 24) if available else "Unavailable")
    if not available:
        return data
    job = _value(hass, options, "job")
    data["job"] = text(job.state, 48) if job and job.state not in ("unknown", "unavailable") else ""
    progress = _number(_value(hass, options, "progress"))
    if progress is not None and 0 <= progress <= 100:
        data.update(progress=progress, progress_available=True)
    start, end = _timestamp(_value(hass, options, "start")), _timestamp(_value(hass, options, "end"))
    identity = (start.isoformat() if start else "") + "|" + (job.state if job and isinstance(job.state, str) else "")
    data["job_key"] = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    if options.get(field_key("elapsed")):
        data["elapsed"] = _duration(_seconds(_value(hass, options, "elapsed")))
    elif options.get(field_key("start")):
        # Wall-clock elapsed, including pauses. Completed jobs freeze at end.
        terminal = state.state in ("finish", "finished", "failed", "cancelled", "completed")
        stop = end if terminal else now
        data["elapsed"] = _duration((stop - start).total_seconds() if stop and start else None)
    if options.get(field_key("remaining")):
        data["remaining"] = _duration(_seconds(_value(hass, options, "remaining")))
    if options.get(field_key("layer")):
        current, total = _number(_value(hass, options, "layer")), _number(_value(hass, options, "total_layers"))
        layer = str(int(current)) if current is not None and 0 <= current <= 1000000 else "--"
        if options.get(field_key("total_layers")):
            layer += "/" + (str(int(total)) if total is not None and 0 <= total <= 1000000 else "--")
        data["layers"] = layer
    for field in ("nozzle", "bed"):
        if not options.get(field_key(field)):
            continue
        current = _value(hass, options, field)
        number = _number(current)
        temperature = f"{number:.0f}" if number is not None else "--"
        target = _number(_value(hass, options, field + "_target"))
        if options.get(field_key(field + "_target")):
            temperature += "/" + (f"{target:.0f}" if target is not None else "--")
        data[field] = text(temperature + text(current.attributes.get("unit_of_measurement"), 8) if current else temperature, 32)
    data["render_url"] = media_url(hass, options.get(field_key("render")))
    render_state = _value(hass, options, "render")
    if (options.get(field_key("render")) or "").startswith("image."):
        updated = _timestamp(render_state)
        if start and updated and updated < start:
            # A previous job's Bambu cover must not masquerade as this job.
            data["render_url"] = ""
    data["camera_url"] = media_url(hass, options.get(field_key("camera")))
    return data


class PrinterBridge:
    """Coalesce selected state updates and serialize with existing UI transport."""
    def __init__(self, hass: Any, runtime: Any, options: Mapping[str, Any]) -> None:
        self.hass, self.runtime, self.options = hass, runtime, options
        self.task: asyncio.Task | None = None
        self.dirty = False
        self.stopped = False
        self.last_job_key: str | None = None

    def schedule(self) -> None:
        if self.stopped or self.runtime.stopped:
            return
        if self.task:
            self.dirty = True
            return
        self.task = self.hass.async_create_task(self._send())

    async def _send(self) -> None:
        try:
            while not self.stopped and not self.runtime.stopped:
                await asyncio.sleep(0.2)
                self.dirty = False
                async with self.runtime.transition_lock:
                    if self.stopped or self.runtime.stopped:
                        return
                    data = printer_action_data(self.hass, self.options)
                    from .camera_thumbnail import STORE_KEY, selected_media
                    store = self.hass.data.get(STORE_KEY)
                    if store is not None:
                        await store.prune(selected_media(self.hass))
                    if data["job_key"] != self.last_job_key:
                        if store is not None:
                            await store.invalidate({self.options[field_key(f)] for f in ("render", "camera")
                                                    if self.options.get(field_key(f))})
                        self.last_job_key = data["job_key"]
                    async with asyncio.timeout(10):
                        await self.hass.services.async_call("esphome", self.runtime.service_names.update_printer, data, blocking=True)
                    await asyncio.sleep(0.1)
                if not self.dirty:
                    break
        except asyncio.CancelledError:
            raise
        except Exception as err:
            _LOGGER.warning("Printer display unavailable (%s)", type(err).__name__)
        finally:
            self.task = None

    async def close(self) -> None:
        self.stopped = True
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
