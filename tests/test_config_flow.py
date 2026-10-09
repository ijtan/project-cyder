"""Tests for Home Assistant options-form defaults."""

from __future__ import annotations

import importlib
import asyncio
import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from custom_components.cyd_ha_monitor.const import (
    CONF_AI_PROVIDERS,
    CONF_CAMERA_ENTITY,
    CONF_CLIMATE_ENTITY,
    CONF_CLAUDE_SESSION_ENTITY,
    CONF_CLAUDE_WEEK_ENTITY,
    CONF_CLAUDE_SESSION_RESET_ENTITY,
    CONF_CLAUDE_WEEK_RESET_ENTITY,
    CONF_DAILY_ENERGY_ENTITY,
    CONF_DASHBOARD_SETTINGS_SAVED,
    CONF_CLAUDE_EXTRA_LIMIT_ENTITY,
    CONF_CLAUDE_EXTRA_PERCENT_ENTITY,
    CONF_CLAUDE_EXTRA_USED_ENTITY,
    CONF_MAIN_POWER_ENTITY,
    CONF_POWER_METRICS,
    CONF_SENSOR_METRICS,
    CONF_ROOM_ENTITIES,
    CONF_RULES,
    CONF_PRIORITY,
    CONF_PROVIDER_NAME,
    CONF_PROVIDER_SESSION_ENTITY,
    CONF_PROVIDER_SESSION_RESET_ENTITY,
    CONF_PROVIDER_WEEK_ENTITY,
    CONF_PROVIDER_WEEK_RESET_ENTITY,
    migrate_entry_title,
)


_UNDEFINED = object()


class EntryTitleMigrationTests(unittest.TestCase):
    def test_renames_only_automatically_generated_legacy_title(self) -> None:
        self.assertEqual(
            migrate_entry_title("Project Cyder - Office CYD"),
            "Project Cydex - Office CYD",
        )
        self.assertEqual(
            migrate_entry_title("My custom display name"), "My custom display name"
        )


class _SchemaKey:
    def __init__(
        self, name: str, default: object = _UNDEFINED, description: object = None
    ) -> None:
        self.name = name
        self.default = default
        self.description = description


class _Schema:
    def __init__(self, schema: dict[object, object]) -> None:
        self.schema = schema

    def __call__(self, values: dict[str, object]) -> dict[str, object]:
        """Model omitted-field default insertion, not selector validation."""
        result = dict(values)
        for key in self.schema:
            if key.name not in result and key.default is not _UNDEFINED:
                result[key.name] = key.default
        return result


class _Selector:
    def __init__(self, config: object = None) -> None:
        self.config = config

    def __call__(self, value: object) -> object:
        return value


class _OptionsFlow:
    def async_create_entry(self, *, title: str, data: dict[str, object]) -> dict:
        return {"type": "create_entry", "title": title, "data": data}


class _ConfigFlow:
    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__()


def _load_config_flow():
    """Import config_flow with small HA/voluptuous stubs for this stdlib suite."""
    voluptuous = ModuleType("voluptuous")
    voluptuous.Optional = _SchemaKey
    voluptuous.Required = _SchemaKey
    voluptuous.Schema = _Schema

    selector = ModuleType("homeassistant.helpers.selector")
    for name in (
        "BooleanSelector",
        "DeviceSelector",
        "EntitySelector",
        "NumberSelector",
        "ObjectSelector",
        "SelectSelector",
        "TextSelector",
    ):
        setattr(selector, name, _Selector)

    homeassistant = ModuleType("homeassistant")
    config_entries = ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = type("ConfigEntry", (), {})
    config_entries.ConfigFlow = _ConfigFlow
    config_entries.ConfigFlowResult = dict
    config_entries.OptionsFlow = _OptionsFlow
    core = ModuleType("homeassistant.core")
    core.callback = lambda function: function
    helpers = ModuleType("homeassistant.helpers")
    helpers.selector = selector
    issues = ModuleType("homeassistant.helpers.issue_registry")
    helpers.issue_registry = issues
    homeassistant.helpers = helpers

    modules = {
        "voluptuous": voluptuous,
        "homeassistant": homeassistant,
        "homeassistant.config_entries": config_entries,
        "homeassistant.core": core,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.selector": selector,
        "homeassistant.helpers.issue_registry": issues,
    }
    module_name = "custom_components.cyd_ha_monitor.config_flow"
    sys.modules.pop(module_name, None)
    with patch.dict(sys.modules, modules):
        return importlib.import_module(module_name)


class DashboardFormDefaultTests(unittest.TestCase):
    def test_weather_clear_is_authoritative_and_preserves_other_options(self):
        from custom_components.cyd_ha_monitor.weather import CONF_WEATHER_ENTITY, CONF_WEATHER_ENABLED

        config_flow = _load_config_flow()
        flow = config_flow.CydHAMonitorOptionsFlow()
        original = {CONF_WEATHER_ENTITY: "weather.old", CONF_WEATHER_ENABLED: True,
                    CONF_CAMERA_ENTITY: "camera.saved", CONF_RULES: []}
        flow.config_entry = SimpleNamespace(options=original)
        schema = flow._weather_schema(original)
        field = next(key for key in schema.schema if key.name == CONF_WEATHER_ENTITY)
        self.assertIs(field.default, _UNDEFINED)
        self.assertEqual(schema.schema[field].config["domain"], "weather")
        result = asyncio.run(flow.async_step_weather(schema({CONF_WEATHER_ENABLED: True})))
        self.assertIsNone(result["data"][CONF_WEATHER_ENTITY])
        self.assertEqual(result["data"][CONF_CAMERA_ENTITY], "camera.saved")
        self.assertEqual(result["data"][CONF_RULES], [])
        self.assertEqual(original[CONF_WEATHER_ENTITY], "weather.old")

    def test_alert_form_priorities_are_strings_without_mutating_saved_rules(self) -> None:
        config_flow = _load_config_flow()
        for priority in (1, 2, 3, "2"):
            rules = [{"entity_id": "sensor.power", CONF_PRIORITY: priority}]
            schema = config_flow.CydHAMonitorOptionsFlow._rules_schema(rules)
            field = next(key for key in schema.schema if key.name == CONF_RULES)
            self.assertEqual(field.default[0][CONF_PRIORITY], str(priority))
            self.assertEqual(rules[0][CONF_PRIORITY], priority)
        schema = config_flow.CydHAMonitorOptionsFlow._rules_schema([{"entity_id": "sensor.power"}])
        field = next(key for key in schema.schema if key.name == CONF_RULES)
        self.assertEqual(field.default[0][CONF_PRIORITY], "2")

    def test_alert_save_reopen_save_keeps_engine_priorities_numeric(self) -> None:
        config_flow = _load_config_flow()
        rules = [
            {"direction": "above", "entity_id": "sensor.main_power_meter_wifi_phase_a_power",
             "hysteresis": 0, "message": "Power is high!", "priority": 2,
             "threshold": 2000, "title": "Power", "attention_page": "none"},
            {"direction": "above", "entity_id": "sensor.msi_acpitz_0_temperature",
             "hysteresis": 0, "message": "high", "priority": 2,
             "threshold": 75, "title": "Msi lap temp", "attention_page": "none"},
        ]
        flow = config_flow.CydHAMonitorOptionsFlow()
        flow.config_entry = SimpleNamespace(options={CONF_CAMERA_ENTITY: "camera.door", CONF_RULES: rules})
        for _ in range(2):
            schema = flow._rules_schema(flow.config_entry.options[CONF_RULES])
            field = next(key for key in schema.schema if key.name == CONF_RULES)
            submitted = field.default
            self.assertTrue(all(rule[CONF_PRIORITY] == "2" for rule in submitted))
            result = asyncio.run(flow.async_step_alerts({CONF_RULES: submitted}))
            self.assertEqual(result["data"][CONF_CAMERA_ENTITY], "camera.door")
            self.assertTrue(all(rule[CONF_PRIORITY] == 2 for rule in result["data"][CONF_RULES]))
            flow.config_entry = SimpleNamespace(options=result["data"])

    def test_optional_entity_selectors_omit_empty_defaults(self) -> None:
        config_flow = _load_config_flow()
        values = {
            CONF_CLAUDE_EXTRA_USED_ENTITY: None,
            CONF_CLAUDE_EXTRA_LIMIT_ENTITY: "",
            CONF_CLAUDE_EXTRA_PERCENT_ENTITY: "None",
            CONF_MAIN_POWER_ENTITY: "sensor.house_power",
            CONF_AI_PROVIDERS: [
                {
                    CONF_PROVIDER_NAME: "Codex",
                    CONF_PROVIDER_SESSION_ENTITY: None,
                    CONF_PROVIDER_WEEK_ENTITY: "",
                    CONF_PROVIDER_SESSION_RESET_ENTITY: "None",
                    CONF_PROVIDER_WEEK_RESET_ENTITY: "sensor.codex_week_reset",
                }
            ],
        }

        schema = config_flow.CydHAMonitorOptionsFlow()._dashboard_schema(values)

        for field in (
            CONF_CLAUDE_EXTRA_USED_ENTITY,
            CONF_CLAUDE_EXTRA_LIMIT_ENTITY,
            CONF_CLAUDE_EXTRA_PERCENT_ENTITY,
        ):
            key = next(key for key in schema.schema if key.name == field)
            self.assertIs(key.default, _UNDEFINED)

        main_power = next(
            key for key in schema.schema if key.name == CONF_MAIN_POWER_ENTITY
        )
        self.assertIs(main_power.default, _UNDEFINED)
        self.assertEqual(
            main_power.description, {"suggested_value": "sensor.house_power"}
        )

        providers_key = next(
            key for key in schema.schema if key.name == CONF_AI_PROVIDERS
        )
        self.assertEqual(providers_key.default, [])
        provider = providers_key.description["suggested_value"][0]
        self.assertEqual(provider[CONF_PROVIDER_NAME], "Codex")
        self.assertNotIn(CONF_PROVIDER_SESSION_ENTITY, provider)
        self.assertNotIn(CONF_PROVIDER_WEEK_ENTITY, provider)
        self.assertNotIn(CONF_PROVIDER_SESSION_RESET_ENTITY, provider)
        self.assertEqual(
            provider[CONF_PROVIDER_WEEK_RESET_ENTITY], "sensor.codex_week_reset"
        )

    def test_cleared_entities_and_lists_stay_cleared_after_save_and_reopen(self) -> None:
        config_flow = _load_config_flow()
        entity_fields = (
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
        options = {field: "sensor.old_source" for field in entity_fields}
        options.update(
            {
                CONF_CLIMATE_ENTITY: "climate.office",
                CONF_CAMERA_ENTITY: "camera.door",
                CONF_ROOM_ENTITIES: ["switch.office_light"],
                CONF_AI_PROVIDERS: [
                    {
                        CONF_PROVIDER_NAME: "Codex",
                        CONF_PROVIDER_SESSION_ENTITY: "sensor.codex_session",
                    }
                ],
                CONF_POWER_METRICS: [{"entity_id": "sensor.power", "name": "Power"}],
                CONF_SENSOR_METRICS: [{"entity_id": "sensor.temp", "name": "Temp"}],
                CONF_RULES: [{"preserved": True}],
            }
        )
        flow = config_flow.CydHAMonitorOptionsFlow()
        flow.config_entry = SimpleNamespace(options=options)
        flow.hass = None
        # HA omits optional selectors after their contents are removed.
        submitted = flow._dashboard_schema(options)({})
        for field in entity_fields:
            self.assertNotIn(field, submitted)
        result = asyncio.run(flow.async_step_dashboard(submitted))
        saved = result["data"]
        for field in entity_fields:
            self.assertIsNone(saved[field])
        for field in (
            CONF_ROOM_ENTITIES, CONF_AI_PROVIDERS, CONF_POWER_METRICS, CONF_SENSOR_METRICS
        ):
            self.assertEqual(saved[field], [])
        self.assertEqual(saved[CONF_RULES], options[CONF_RULES])
        self.assertTrue(saved[CONF_DASHBOARD_SETTINGS_SAVED])
        from custom_components.cyd_ha_monitor.dashboard import dashboard_action_data

        # A cleared saved form must yield a clearing snapshot, not old readings.
        hass = SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None))
        payload = dashboard_action_data(hass, saved)
        self.assertTrue(payload["power_configured"])
        self.assertTrue(payload["claude_configured"])
        self.assertTrue(payload["sensor_monitor_configured"])
        self.assertFalse(payload["power_available"])
        self.assertFalse(payload["session_enabled"])
        self.assertFalse(payload["climate_configured"])
        self.assertEqual(payload["camera_snapshot_url"], "")
        reopened = flow._dashboard_schema(saved)
        for field in entity_fields:
            key = next(key for key in reopened.schema if key.name == field)
            self.assertIs(key.default, _UNDEFINED)
            self.assertIsNone(key.description)

    def test_submitted_entity_selection_is_preserved(self) -> None:
        config_flow = _load_config_flow()
        flow = config_flow.CydHAMonitorOptionsFlow()
        flow.config_entry = SimpleNamespace(
            options={CONF_MAIN_POWER_ENTITY: "sensor.old_power"}
        )
        flow.hass = None
        submitted = flow._dashboard_schema(flow.config_entry.options)(
            {CONF_MAIN_POWER_ENTITY: "sensor.new_power"}
        )
        result = asyncio.run(flow.async_step_dashboard(submitted))
        self.assertEqual(result["data"][CONF_MAIN_POWER_ENTITY], "sensor.new_power")
