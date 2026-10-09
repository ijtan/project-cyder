"""Explicit per-entry automation override, persisted in HA options only."""
from __future__ import annotations

from typing import Any

from .const import DOMAIN


def async_setup_printer_services(hass: Any) -> None:
    import voluptuous as vol
    from homeassistant.exceptions import ServiceValidationError

    async def visibility(call: Any) -> None:
        entry = hass.config_entries.async_get_entry(call.data["entry_id"])
        if entry is None or entry.domain != DOMAIN:
            raise ServiceValidationError("Choose a Project Cydex config entry")
        mode = call.data["mode"]
        if entry.options.get("printer_visibility_override", "auto") != mode:
            hass.config_entries.async_update_entry(entry, options={**entry.options, "printer_visibility_override": mode})
        # Options listener reloads selected subscriptions and sends latest state.

    hass.services.async_register(DOMAIN, "set_printer_visibility", visibility,
        schema=vol.Schema({vol.Required("entry_id"): str,
                           vol.Required("mode"): vol.In(("auto", "show", "hide"))}))
