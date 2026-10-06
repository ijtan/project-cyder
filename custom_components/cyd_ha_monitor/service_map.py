"""Resolve device-prefixed ESPHome action service names for a selected device."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .const import (
    ACTION_CLEAR_ALERT,
    ACTION_DISMISS_ALERT,
    ACTION_DISPLAY_ALERT,
    ESPHOME_DOMAIN,
)

_ACTION_NAMES = (ACTION_DISPLAY_ALERT, ACTION_CLEAR_ALERT, ACTION_DISMISS_ALERT)
_DEVICE_NAME_KEYS = ("node_name", "device_name", "friendly_name", "name")


@dataclass(frozen=True, slots=True)
class ActionServices:
    """Service IDs (within the ``esphome`` domain) for the device actions."""

    display_alert: str
    clear_alert: str
    dismiss_alert: str


def service_names(device_prefix: str) -> ActionServices:
    """Build action IDs using ESPHome's current device-name prefix convention."""
    return ActionServices(
        display_alert=f"{device_prefix}_{ACTION_DISPLAY_ALERT}",
        clear_alert=f"{device_prefix}_{ACTION_CLEAR_ALERT}",
        dismiss_alert=f"{device_prefix}_{ACTION_DISMISS_ALERT}",
    )


def _device_name_candidates(device: Any, config_entries: Iterable[Any]) -> list[str]:
    """Collect native and registry names for this DeviceEntry/config entry pair."""
    candidates: list[str] = []

    def add(value: Any) -> None:
        if isinstance(value, str) and value.strip() and value not in candidates:
            candidates.append(value.strip())

    # ESPHome's device identifier is the most stable source; user-facing names
    # can be changed in the device registry and are considered as fallbacks.
    for identifier_domain, identifier in getattr(device, "identifiers", set()):
        if identifier_domain == ESPHOME_DOMAIN:
            add(identifier)
    for entry in config_entries:
        if getattr(entry, "domain", None) != ESPHOME_DOMAIN:
            continue
        add(getattr(entry, "title", None))
        data = getattr(entry, "data", {})
        if isinstance(data, Mapping):
            for key in _DEVICE_NAME_KEYS:
                add(data.get(key))
    add(getattr(device, "name", None))
    add(getattr(device, "name_by_user", None))
    return candidates


def _service_description(service: Any) -> str:
    """Read the service description exposed by HA's action service registry."""
    if isinstance(service, Mapping):
        description = service.get("description", "")
        schema = service.get("schema")
    else:
        description = getattr(service, "description", "")
        schema = getattr(service, "schema", None)
    schema_description = getattr(schema, "description", "")
    return " ".join(
        part for part in (str(description or ""), str(schema_description or "")) if part
    )


def _name_forms(value: str) -> set[str]:
    """Return literal and ESPHome-normalized forms for description matching."""
    value = value.strip().casefold()
    return {value, value.replace("-", "_")}


def _describes_device(description: str, candidates: Iterable[str]) -> bool:
    """Whether a registered action's description identifies this device."""
    folded = description.casefold()
    normalized = folded.replace("-", "_")
    return any(
        form in folded or form in normalized
        for candidate in candidates
        for form in _name_forms(candidate)
        if len(form) >= 3
    )


def resolve_action_services(
    device: Any,
    config_entries: Iterable[Any],
    registered_services: Mapping[str, Any],
) -> ActionServices | None:
    """Find all three actions associated with one selected ESPHome device.

    ESPHome action services are prefixed with the normalized device name.
    Prefer that exact prefix when it appears in the selected device's
    identifiers/config entry. The registered service description is also
    checked as a fallback because HA includes the originating device name
    there. This avoids guessing from a global device name or hard-coding one
    installation's service IDs.
    """
    entries = [
        entry
        for entry in config_entries
        if getattr(entry, "domain", None) == ESPHOME_DOMAIN
    ]
    if not entries:
        return None

    candidates = _device_name_candidates(device, entries)
    prefixes: set[str] | None = None
    for action_name in _ACTION_NAMES:
        suffix = f"_{action_name}"
        action_prefixes = {
            service_name[: -len(suffix)]
            for service_name in registered_services
            if service_name.endswith(suffix)
        }
        prefixes = action_prefixes if prefixes is None else prefixes & action_prefixes
    if not prefixes:
        return None

    # Match the core service-name convention against names carried by the
    # selected DeviceEntry/config entry (node identifier first).
    for candidate in candidates:
        prefix = candidate.replace("-", "_")
        if prefix in prefixes:
            return service_names(prefix)

    # Some core versions expose an edited display name in the DeviceEntry but
    # preserve the original node name in service metadata. Match only a prefix
    # whose three registered service descriptions identify this device.
    for prefix in sorted(prefixes):
        action_services = service_names(prefix)
        descriptions = [
            _service_description(registered_services[name])
            for name in (
                action_services.display_alert,
                action_services.clear_alert,
                action_services.dismiss_alert,
            )
        ]
        if all(
            _describes_device(description, candidates) for description in descriptions
        ):
            return action_services
    return None


def _linked_esphome_config_entry_ids(
    device_id: str, device: Any, entities: Iterable[Any]
) -> set[str]:
    """Get ESPHome config entries linked directly or through their entities."""
    entry_ids = set(getattr(device, "config_entries", None) or ())
    if entry_ids:
        return entry_ids
    return {
        entity.config_entry_id
        for entity in entities
        if getattr(entity, "device_id", None) == device_id
        and getattr(entity, "platform", None) == ESPHOME_DOMAIN
        and getattr(entity, "config_entry_id", None)
    }


def async_get_device_action_services(
    hass: Any, device_id: str
) -> tuple[str, ActionServices] | None:
    """Resolve actions using the selected device and its linked ESPHome entry."""
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        return None

    # Older and restored DeviceEntry records may have no config_entries value.
    # ESPHome entities still retain the authoritative link to their config
    # entry, so use them to recover it rather than guessing a service prefix.
    entity_registry = er.async_get(hass)
    config_entry_ids = _linked_esphome_config_entry_ids(
        device_id, device, entity_registry.entities.values()
    )

    entries = [
        entry
        for entry_id in config_entry_ids
        if (entry := hass.config_entries.async_get_entry(entry_id)) is not None
        and entry.domain == ESPHOME_DOMAIN
    ]
    services_by_domain = hass.services.async_services()
    registered = services_by_domain.get(ESPHOME_DOMAIN, {})
    services = resolve_action_services(device, entries, registered)
    if services is None:
        return None
    display_name = (
        getattr(device, "name_by_user", None)
        or getattr(device, "name", None)
        or (entries[0].title if entries else None)
        or device_id
    )
    return display_name, services
