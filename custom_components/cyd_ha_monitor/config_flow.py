"""Configuration and options flows for Project Cyder."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers import selector

from .alerts import validate_rules
from .const import (
    CONF_DEVICE_ID,
    CONF_DIRECTION,
    CONF_ENTITY_ID,
    CONF_HYSTERESIS,
    CONF_MESSAGE,
    CONF_PRIORITY,
    CONF_RULES,
    CONF_THRESHOLD,
    CONF_TITLE,
    DOMAIN,
    ISSUE_ACTIONS_UNAVAILABLE,
)


def _device_selector() -> selector.DeviceSelector:
    """Select one device provided by the native ESPHome integration."""
    return selector.DeviceSelector({"integration": "esphome"})


def _rules_selector() -> selector.ObjectSelector:
    """Build a repeatable native object selector for threshold rules."""
    return selector.ObjectSelector(
        {
            "multiple": True,
            "fields": {
                CONF_ENTITY_ID: {
                    "required": True,
                    "label": "Numeric entity",
                    "selector": selector.EntitySelector(
                        {"domain": ["sensor", "input_number", "number"]}
                    ),
                },
                CONF_DIRECTION: {
                    "required": True,
                    "label": "Direction",
                    "selector": selector.SelectSelector(
                        {
                            "options": [
                                {"value": "above", "label": "Above"},
                                {"value": "below", "label": "Below"},
                            ]
                        }
                    ),
                },
                CONF_THRESHOLD: {
                    "required": True,
                    "label": "Threshold",
                    "selector": selector.NumberSelector({"mode": "box", "step": "any"}),
                },
                CONF_HYSTERESIS: {
                    "required": False,
                    "label": "Hysteresis",
                    "selector": selector.NumberSelector(
                        {"min": 0, "mode": "box", "step": "any"}
                    ),
                },
                CONF_PRIORITY: {
                    "required": False,
                    "label": "Priority",
                    "selector": selector.SelectSelector(
                        {
                            "options": [
                                {"value": "1", "label": "1: Notice"},
                                {"value": "2", "label": "2: Warning"},
                                {"value": "3", "label": "3: Critical"},
                            ]
                        }
                    ),
                },
                CONF_TITLE: {
                    "required": True,
                    "label": "Title",
                    "selector": selector.TextSelector(),
                },
                CONF_MESSAGE: {
                    "required": True,
                    "label": "Message",
                    "selector": selector.TextSelector({"multiline": True}),
                },
            },
        }
    )


class CydHAMonitorConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up one ESPHome CYD and configure its alert rules."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            device_id = user_input[CONF_DEVICE_ID]
            await self.async_set_unique_id(device_id)
            self._abort_if_unique_id_configured()
            title = _device_title(self.hass, device_id)
            return self.async_create_entry(
                title=f"Project Cyder - {title}",
                data={CONF_DEVICE_ID: device_id},
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE_ID): _device_selector(),
                }
            ),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Reload the selected ESPHome device after its firmware is updated."""
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            device_id = user_input[CONF_DEVICE_ID]
            await self.async_set_unique_id(device_id)
            self._abort_if_unique_id_mismatch(reason="wrong_device")
            ir.async_delete_issue(
                self.hass,
                DOMAIN,
                f"{ISSUE_ACTIONS_UNAVAILABLE}_{entry.entry_id}",
            )
            return self.async_update_reload_and_abort(
                entry,
                reason="reconfigure_successful",
            )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_DEVICE_ID, default=entry.data[CONF_DEVICE_ID]
                    ): _device_selector(),
                }
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return CydHAMonitorOptionsFlow()


class CydHAMonitorOptionsFlow(OptionsFlow):
    """Configure one or more entity threshold alerts."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            try:
                rules = validate_rules(user_input.get(CONF_RULES, []))
            except (TypeError, ValueError):
                return self.async_show_form(
                    step_id="init",
                    data_schema=self._schema(user_input.get(CONF_RULES, [])),
                    errors={"base": "invalid_rules"},
                )
            return self.async_create_entry(title="", data={CONF_RULES: rules})

        return self.async_show_form(
            step_id="init",
            data_schema=self._schema(self.config_entry.options.get(CONF_RULES, [])),
        )

    @staticmethod
    def _schema(rules: list[dict[str, Any]] | None = None) -> vol.Schema:
        rules = rules or []
        return vol.Schema(
            {
                vol.Required(CONF_RULES, default=rules): _rules_selector(),
            }
        )


def _device_title(hass: Any, device_id: str) -> str:
    """Return the selected device's registry name for the config entry title."""
    from homeassistant.helpers import device_registry as dr

    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        return device_id
    return (
        getattr(device, "name_by_user", None)
        or getattr(device, "name", None)
        or device_id
    )
