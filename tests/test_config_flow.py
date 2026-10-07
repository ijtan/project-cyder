"""Tests for Home Assistant options-form defaults."""

from __future__ import annotations

import importlib
import sys
import unittest
from types import ModuleType
from unittest.mock import patch

from custom_components.cyd_ha_monitor.const import (
    CONF_AI_PROVIDERS,
    CONF_CLAUDE_EXTRA_LIMIT_ENTITY,
    CONF_CLAUDE_EXTRA_PERCENT_ENTITY,
    CONF_CLAUDE_EXTRA_USED_ENTITY,
    CONF_MAIN_POWER_ENTITY,
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
    def __init__(self, name: str, default: object = _UNDEFINED) -> None:
        self.name = name
        self.default = default


class _Schema:
    def __init__(self, schema: dict[object, object]) -> None:
        self.schema = schema


class _Selector:
    def __init__(self, config: object = None) -> None:
        self.config = config


class _OptionsFlow:
    pass


class _ConfigFlow:
    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__()


def _load_config_flow():
    """Import config_flow with small HA/voluptuous stubs for this stdlib suite."""
    voluptuous = ModuleType("voluptuous")
    voluptuous.Optional = lambda name, default=_UNDEFINED: _SchemaKey(name, default)
    voluptuous.Required = lambda name, default=_UNDEFINED: _SchemaKey(name, default)
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
        self.assertEqual(main_power.default, "sensor.house_power")

        providers_key = next(
            key for key in schema.schema if key.name == CONF_AI_PROVIDERS
        )
        provider = providers_key.default[0]
        self.assertEqual(provider[CONF_PROVIDER_NAME], "Codex")
        self.assertNotIn(CONF_PROVIDER_SESSION_ENTITY, provider)
        self.assertNotIn(CONF_PROVIDER_WEEK_ENTITY, provider)
        self.assertNotIn(CONF_PROVIDER_SESSION_RESET_ENTITY, provider)
        self.assertEqual(
            provider[CONF_PROVIDER_WEEK_RESET_ENTITY], "sensor.codex_week_reset"
        )
