"""Configuration and options flows for Project Cydex."""

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
    ATTENTION_PAGE_VALUES,
    CONF_ATTENTION_PAGE,
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
    CONF_DASHBOARD_SETTINGS_SAVED,
    CONF_DEVICE_ID,
    CONF_DIRECTION,
    CONF_ENTITY_ID,
    CONF_HYSTERESIS,
    CONF_MAIN_POWER_ENTITY,
    CONF_MESSAGE,
    CONF_METRIC_ENTITY_ID,
    CONF_METRIC_NAME,
    CONF_POWER_METRICS,
    CONF_PRIORITY,
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
    CONF_RULES,
    CONF_THRESHOLD,
    CONF_TITLE,
    CONF_WARNING_THRESHOLD,
    DOMAIN,
    ENTRY_TITLE_PREFIX,
    ISSUE_ACTIONS_UNAVAILABLE,
    ISSUE_DASHBOARD_ACTION_UNAVAILABLE,
)
from .dashboard import _looks_like_entity_id, validate_dashboard


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
                    "label": "Limit (entity units)",
                    "selector": selector.NumberSelector({"mode": "box", "step": "any"}),
                },
                CONF_WARNING_THRESHOLD: {
                    "required": False,
                    "label": "Warning starts at (optional, same units)",
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
                CONF_ATTENTION_PAGE: {
                    "required": False,
                    "label": "Show dashboard page",
                    "selector": selector.SelectSelector(
                        {
                            "options": [
                                {
                                    "value": page,
                                    "label": {
                                        "none": "Keep current page",
                                        "home": "Home",
                                        "ai": "AI usage",
                                        "climate": "Climate",
                                        "sensors": "Sensors",
                                        "energy": "Energy",
                                        "camera": "Camera snapshots",
                                    }[page],
                                }
                                for page in ATTENTION_PAGE_VALUES
                            ]
                        }
                    ),
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
                title=f"{ENTRY_TITLE_PREFIX}{title}",
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
            ir.async_delete_issue(
                self.hass,
                DOMAIN,
                f"{ISSUE_DASHBOARD_ACTION_UNAVAILABLE}_{entry.entry_id}",
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
    """Configure dashboard sources and entity threshold alerts."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=["dashboard", "alerts"],
        )

    async def async_step_dashboard(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            try:
                dashboard = validate_dashboard(
                    user_input, self.hass, enforce_room_capacity=True
                )
            except (TypeError, ValueError):
                return self.async_show_form(
                    step_id="dashboard",
                    data_schema=self._dashboard_schema(user_input),
                    errors={"base": "invalid_dashboard"},
                )
            return self.async_create_entry(
                title="",
                data={
                    **self.config_entry.options,
                    **dashboard,
                    CONF_DASHBOARD_SETTINGS_SAVED: True,
                },
            )

        return self.async_show_form(
            step_id="dashboard",
            data_schema=self._dashboard_schema(self.config_entry.options),
        )

    async def async_step_alerts(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            try:
                rules = validate_rules(user_input.get(CONF_RULES, []))
            except (TypeError, ValueError):
                return self.async_show_form(
                    step_id="alerts",
                    data_schema=self._rules_schema(user_input.get(CONF_RULES, [])),
                    errors={"base": "invalid_rules"},
                )
            return self.async_create_entry(
                title="",
                data={**self.config_entry.options, CONF_RULES: rules},
            )

        return self.async_show_form(
            step_id="alerts",
            data_schema=self._rules_schema(self.config_entry.options.get(CONF_RULES, [])),
        )

    @staticmethod
    def _rules_schema(rules: list[dict[str, Any]] | None = None) -> vol.Schema:
        rules = [
            {
                **rule,
                # The rule engine stores integers; HA select options are strings.
                # Convert only the form copy so reopening an unchanged rule saves.
                CONF_PRIORITY: str(rule.get(CONF_PRIORITY, 2)),
                CONF_ATTENTION_PAGE: rule.get(CONF_ATTENTION_PAGE, "none"),
            }
            for rule in (rules or [])
            if isinstance(rule, dict)
        ]
        return vol.Schema(
            {
                vol.Required(CONF_RULES, default=rules): _rules_selector(),
            }
        )

    def _dashboard_schema(self, values: dict[str, Any]) -> vol.Schema:
        schema: dict[Any, Any] = {}
        schema[
            vol.Optional(
                CONF_ROOM_ENTITIES,
                default=[],
                description={"suggested_value": values.get(CONF_ROOM_ENTITIES, [])},
            )
        ] = _room_entities_selector()
        for field in (
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
        ):
            entity_default = _entity_selector_default(values.get(field))
            # HA omits cleared optional selectors from the submitted mapping.
            # A schema default would silently reinsert the old selection.
            field_key = (
                vol.Optional(field, description={"suggested_value": entity_default})
                if entity_default is not None
                else vol.Optional(field)
            )
            schema[field_key] = selector.EntitySelector(
                {
                    "domain": (
                        "climate"
                        if field == CONF_CLIMATE_ENTITY
                        else "camera"
                        if field == CONF_CAMERA_ENTITY
                        else "sensor"
                    )
                }
            )
        schema[
            vol.Optional(
                CONF_AUTO_ROTATION,
                default=values.get(CONF_AUTO_ROTATION, False),
            )
        ] = selector.BooleanSelector()
        schema[
            vol.Optional(
                CONF_ROTATION_INTERVAL,
                default=values.get(CONF_ROTATION_INTERVAL, 30),
            )
        ] = selector.NumberSelector(
            {"min": 10, "max": 120, "step": 5, "mode": "slider"}
        )
        schema[
            vol.Optional(
                CONF_CAMERA_REFRESH_INTERVAL,
                default=values.get(CONF_CAMERA_REFRESH_INTERVAL, 30),
            )
        ] = selector.NumberSelector(
            {"min": 10, "max": 120, "step": 5, "mode": "slider"}
        )
        for field in (
            CONF_SHOW_AI_PAGE,
            CONF_SHOW_CLIMATE_PAGE,
            CONF_SHOW_SENSORS_PAGE,
            CONF_SHOW_ENERGY_PAGE,
            CONF_SHOW_CAMERA_PAGE,
        ):
            schema[vol.Optional(field, default=values.get(field, True))] = (
                selector.BooleanSelector()
            )
        page_options = (
            ("home", "Home"),
            ("ai", "AI usage"),
            ("climate", "Climate"),
            ("sensors", "Sensors"),
            ("energy", "Energy"),
            ("camera", "Camera snapshots"),
        )
        page_choices = [
            {"value": value, "label": label} for value, label in page_options
        ]
        page_fields = (
            CONF_ROTATION_PAGE_1,
            CONF_ROTATION_PAGE_2,
            CONF_ROTATION_PAGE_3,
            CONF_ROTATION_PAGE_4,
            CONF_ROTATION_PAGE_5,
            CONF_ROTATION_PAGE_6,
        )
        for index, field in enumerate(page_fields):
            schema[
                vol.Optional(
                    field,
                    default=values.get(field, page_options[index][0]),
                )
            ] = selector.SelectSelector({"options": page_choices})
        schema[
            vol.Optional(
                CONF_AI_PROVIDERS,
                default=[],
                description={"suggested_value": _ai_providers_default(values)},
            )
        ] = _ai_providers_selector()
        schema[
            vol.Required(
                CONF_CLAUDE_EXTRA_MODE,
                default=values.get(CONF_CLAUDE_EXTRA_MODE, "used"),
            )
        ] = selector.SelectSelector(
            {
                "options": [
                    {"value": "used", "label": "Used"},
                    {"value": "remaining", "label": "Remaining"},
                ]
            }
        )
        schema[
            vol.Optional(
                CONF_POWER_METRICS,
                default=[],
                description={"suggested_value": values.get(CONF_POWER_METRICS, [])},
            )
        ] = _power_metrics_selector()
        schema[
            vol.Optional(
                CONF_SENSOR_METRICS,
                default=[],
                description={"suggested_value": values.get(CONF_SENSOR_METRICS, [])},
            )
        ] = _sensor_metrics_selector()
        return vol.Schema(schema)


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


def _power_metrics_selector() -> selector.ObjectSelector:
    """Select up to four named numeric power entities for the energy page."""
    return selector.ObjectSelector(
        {
            "multiple": True,
            "fields": {
                CONF_METRIC_ENTITY_ID: {
                    "required": True,
                    "label": "Power sensor",
                    "selector": selector.EntitySelector({"domain": "sensor"}),
                },
                CONF_METRIC_NAME: {
                    "required": True,
                    "label": "Display name",
                    "selector": selector.TextSelector(),
                },
            },
        }
    )


def _room_entities_selector() -> selector.EntitySelector:
    """Choose controls once; the CYD groups them by their assigned HA Area."""
    return selector.EntitySelector(
        {"multiple": True, "domain": ["climate", "light", "switch"]}
    )


def _sensor_metrics_selector() -> selector.ObjectSelector:
    """Choose up to five named sensors for the glanceable sensor monitor."""
    return selector.ObjectSelector(
        {
            "multiple": True,
            "fields": {
                CONF_METRIC_ENTITY_ID: {
                    "required": True,
                    "label": "Sensor entity",
                    "selector": selector.EntitySelector({"domain": "sensor"}),
                },
                CONF_METRIC_NAME: {
                    "required": True,
                    "label": "Display name",
                    "selector": selector.TextSelector(),
                },
            },
        }
    )


def _ai_providers_default(values: dict[str, Any]) -> list[dict[str, Any]]:
    """Migrate the legacy named-provider fields into the repeatable selector."""
    providers = values.get(CONF_AI_PROVIDERS)
    if providers is not None:
        return _sanitize_ai_provider_defaults(providers)
    session = values.get(CONF_CODEX_SESSION_ENTITY)
    week = values.get(CONF_CODEX_WEEK_ENTITY)
    session = _entity_selector_default(session)
    week = _entity_selector_default(week)
    if session is None and week is None:
        return []
    provider = {CONF_PROVIDER_NAME: values.get(CONF_CODEX_NAME, "Codex")}
    if session is not None:
        provider[CONF_PROVIDER_SESSION_ENTITY] = session
    if week is not None:
        provider[CONF_PROVIDER_WEEK_ENTITY] = week
    return [provider]


def _entity_selector_default(value: Any) -> str | None:
    """Return a valid entity ID default, never ``None``/empty values to HA selectors."""
    if not isinstance(value, str):
        return None
    entity_id = value.strip()
    return entity_id if _looks_like_entity_id(entity_id) else None


def _sanitize_ai_provider_defaults(providers: Any) -> list[dict[str, Any]]:
    """Drop empty optional entity fields from repeatable-selector defaults."""
    if not isinstance(providers, list):
        return []

    entity_fields = (
        CONF_PROVIDER_SESSION_ENTITY,
        CONF_PROVIDER_WEEK_ENTITY,
        CONF_PROVIDER_SESSION_RESET_ENTITY,
        CONF_PROVIDER_WEEK_RESET_ENTITY,
    )
    sanitized: list[dict[str, Any]] = []
    for provider in providers:
        if not isinstance(provider, dict):
            continue
        cleaned = dict(provider)
        for field in entity_fields:
            entity_id = _entity_selector_default(cleaned.get(field))
            if entity_id is None:
                cleaned.pop(field, None)
            else:
                cleaned[field] = entity_id
        sanitized.append(cleaned)
    return sanitized


def _ai_providers_selector() -> selector.ObjectSelector:
    """Select up to three providers with independently optional quota sensors."""
    return selector.ObjectSelector(
        {
            "multiple": True,
            "fields": {
                CONF_PROVIDER_NAME: {
                    "required": True,
                    "label": "Provider name",
                    "selector": selector.TextSelector(),
                },
                CONF_PROVIDER_SESSION_ENTITY: {
                    "required": False,
                    "label": "Session quota percentage",
                    "selector": selector.EntitySelector({"domain": "sensor"}),
                },
                CONF_PROVIDER_WEEK_ENTITY: {
                    "required": False,
                    "label": "Weekly quota percentage",
                    "selector": selector.EntitySelector({"domain": "sensor"}),
                },
                CONF_PROVIDER_SESSION_RESET_ENTITY: {
                    "required": False,
                    "label": "5-hour reset time",
                    "selector": selector.EntitySelector({"domain": "sensor"}),
                },
                CONF_PROVIDER_WEEK_RESET_ENTITY: {
                    "required": False,
                    "label": "7-day reset time",
                    "selector": selector.EntitySelector({"domain": "sensor"}),
                },
            },
        }
    )
