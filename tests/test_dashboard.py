"""Tests for dashboard settings and Home Assistant sensor formatting."""

from __future__ import annotations

import unittest
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import sys
from types import ModuleType
from unittest.mock import patch

from custom_components.cyd_ha_monitor.const import (
    CONF_AI_PROVIDERS,
    CONF_CLAUDE_EXTRA_LIMIT_ENTITY,
    CONF_CLAUDE_EXTRA_MODE,
    CONF_CLAUDE_EXTRA_PERCENT_ENTITY,
    CONF_CLAUDE_EXTRA_USED_ENTITY,
    CONF_CLAUDE_EXTRA_LIMIT_ENTITY,
    CONF_DASHBOARD_SETTINGS_SAVED,
    CONF_CLAUDE_SESSION_ENTITY,
    CONF_CLAUDE_SESSION_RESET_ENTITY,
    CONF_CLAUDE_WEEK_ENTITY,
    CONF_CLAUDE_WEEK_RESET_ENTITY,
    CONF_AUTO_ROTATION,
    CONF_CAMERA_ENTITY,
    CONF_CAMERA_REFRESH_INTERVAL,
    CONF_CLIMATE_ENTITY,
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
    CONF_SHOW_AI_PAGE,
    CONF_SHOW_CAMERA_PAGE,
    CONF_SHOW_CLIMATE_PAGE,
    CONF_SHOW_SENSORS_PAGE,
    CONF_SHOW_ENERGY_PAGE,
    CONF_ROTATION_PAGE_1,
    CONF_ROTATION_PAGE_2,
    CONF_ROTATION_PAGE_3,
    CONF_ROTATION_PAGE_4,
    CONF_ROTATION_PAGE_5,
    CONF_ROTATION_PAGE_6,
    CONF_ROOM_ENTITIES,
    CONF_SENSOR_METRICS,
)
from custom_components.cyd_ha_monitor.alerts import RuleEngine
from custom_components.cyd_ha_monitor.dashboard import (
    dashboard_action_data,
    dashboard_entities,
    validate_dashboard,
)


@dataclass
class FakeState:
    state: str
    attributes: dict[str, object]


class FakeStates:
    def __init__(self, values: dict[str, FakeState]) -> None:
        self.values = values

    def get(self, entity_id: str) -> FakeState | None:
        return self.values.get(entity_id)


class FakeHass:
    def __init__(
        self,
        values: dict[str, FakeState],
        internal_url: str | None = None,
    ) -> None:
        self.states = FakeStates(values)
        self.config = type("Config", (), {"internal_url": internal_url})()
        self.data = {}


class DashboardValidationTests(unittest.TestCase):
    def test_accepts_optional_entity_sources_and_named_power_metrics(self) -> None:
        config = validate_dashboard(
            {
                CONF_MAIN_POWER_ENTITY: "sensor.house_power",
                CONF_CLIMATE_ENTITY: "climate.downstairs",
                CONF_CAMERA_ENTITY: "camera.driveway",
                CONF_POWER_METRICS: [
                    {
                        CONF_METRIC_ENTITY_ID: "sensor.freezer_power",
                        CONF_METRIC_NAME: "Freezer",
                    }
                ],
                CONF_SENSOR_METRICS: [
                    {
                        CONF_METRIC_ENTITY_ID: "sensor.living_room_temperature",
                        CONF_METRIC_NAME: "Living room",
                    }
                ],
                CONF_CODEX_NAME: "Codex",
                CONF_CODEX_SESSION_ENTITY: "sensor.codex_session",
                CONF_CODEX_WEEK_ENTITY: "sensor.codex_week",
                CONF_CLAUDE_SESSION_RESET_ENTITY: "sensor.claude_session_reset",
                CONF_CLAUDE_WEEK_RESET_ENTITY: "sensor.claude_week_reset",
                CONF_CLAUDE_EXTRA_MODE: "remaining",
                CONF_AUTO_ROTATION: True,
                CONF_ROTATION_INTERVAL: 60,
                CONF_SHOW_AI_PAGE: False,
                CONF_SHOW_CLIMATE_PAGE: True,
                CONF_SHOW_SENSORS_PAGE: False,
                CONF_SHOW_ENERGY_PAGE: True,
                CONF_ROTATION_PAGE_1: "energy",
                CONF_ROTATION_PAGE_2: "home",
                CONF_ROTATION_PAGE_3: "ai",
                CONF_ROTATION_PAGE_4: "climate",
                CONF_ROTATION_PAGE_5: "sensors",
                CONF_ROTATION_PAGE_6: "camera",
                CONF_CAMERA_REFRESH_INTERVAL: 45,
                CONF_SHOW_CAMERA_PAGE: True,
            }
        )

        self.assertEqual(config[CONF_MAIN_POWER_ENTITY], "sensor.house_power")
        self.assertEqual(config[CONF_CLIMATE_ENTITY], "climate.downstairs")
        self.assertEqual(config[CONF_CAMERA_ENTITY], "camera.driveway")
        self.assertEqual(config[CONF_ROOM_ENTITIES], [])
        self.assertEqual(config[CONF_CAMERA_REFRESH_INTERVAL], 45)
        self.assertEqual(config[CONF_CLAUDE_EXTRA_MODE], "remaining")
        self.assertTrue(config[CONF_AUTO_ROTATION])
        self.assertEqual(config[CONF_ROTATION_INTERVAL], 60)
        self.assertFalse(config[CONF_SHOW_AI_PAGE])
        self.assertFalse(config[CONF_SHOW_SENSORS_PAGE])
        self.assertEqual(config[CONF_ROTATION_PAGE_1], "energy")
        self.assertEqual(config[CONF_ROTATION_PAGE_5], "sensors")
        self.assertEqual(config[CONF_ROTATION_PAGE_6], "camera")
        self.assertEqual(
            config[CONF_AI_PROVIDERS][0][CONF_PROVIDER_NAME], "Codex"
        )
        self.assertEqual(
            dashboard_entities(config),
            {
                "sensor.house_power",
                "climate.downstairs",
                "camera.driveway",
                "sensor.freezer_power",
                "sensor.codex_session",
                "sensor.codex_week",
                "sensor.claude_session_reset",
                "sensor.claude_week_reset",
                "sensor.living_room_temperature",
            },
        )

    def test_rejects_invalid_mode_too_many_metrics_and_missing_names(self) -> None:
        invalid_configs = (
            {CONF_CLAUDE_EXTRA_MODE: "percent"},
            {CONF_CLIMATE_ENTITY: "sensor.not_a_climate"},
            {CONF_AUTO_ROTATION: "yes"},
            {CONF_ROTATION_INTERVAL: 9},
            {CONF_ROTATION_INTERVAL: 12},
            {CONF_ROTATION_INTERVAL: 125},
            {CONF_CAMERA_REFRESH_INTERVAL: 9},
            {CONF_CAMERA_REFRESH_INTERVAL: 12},
            {CONF_CAMERA_ENTITY: "sensor.not_a_camera"},
            {CONF_ROOM_ENTITIES: ["sensor.not_a_device"]},
            {CONF_ROOM_ENTITIES: ["light.kitchen", "light.kitchen"]},
            {CONF_ROOM_ENTITIES: [f"switch.device_{index}" for index in range(21)]},
            {CONF_SHOW_AI_PAGE: "false"},
            {
                CONF_AI_PROVIDERS: [
                    {
                        CONF_PROVIDER_NAME: "Provider name is too long",
                        CONF_PROVIDER_SESSION_ENTITY: "sensor.session",
                    }
                ]
            },
            {
                CONF_AI_PROVIDERS: [
                    {CONF_PROVIDER_NAME: "Same", CONF_PROVIDER_SESSION_ENTITY: "sensor.one"},
                    {CONF_PROVIDER_NAME: "same", CONF_PROVIDER_WEEK_ENTITY: "sensor.two"},
                ]
            },
            {
                CONF_AI_PROVIDERS: [
                    {CONF_PROVIDER_NAME: "Empty"}
                ]
            },
            {
                CONF_AI_PROVIDERS: [
                    {
                        CONF_PROVIDER_NAME: f"AI{index}",
                        CONF_PROVIDER_SESSION_ENTITY: f"sensor.provider_{index}",
                    }
                    for index in range(4)
                ]
            },
            {
                CONF_ROTATION_PAGE_1: "home",
                CONF_ROTATION_PAGE_2: "ai",
                CONF_ROTATION_PAGE_3: "climate",
                CONF_ROTATION_PAGE_4: "energy",
                CONF_ROTATION_PAGE_5: "energy",
                CONF_ROTATION_PAGE_6: "camera",
            },
            {
                CONF_POWER_METRICS: [
                    {
                        CONF_METRIC_ENTITY_ID: f"sensor.power_{index}",
                        CONF_METRIC_NAME: f"Power {index}",
                    }
                    for index in range(5)
                ]
            },
            {
                CONF_POWER_METRICS: [
                    {CONF_METRIC_ENTITY_ID: "sensor.power", CONF_METRIC_NAME: " "}
                ]
            },
            {
                CONF_SENSOR_METRICS: [
                    {
                        CONF_METRIC_ENTITY_ID: "binary_sensor.front_door",
                        CONF_METRIC_NAME: "Front door",
                    }
                ]
            },
            {
                CONF_SENSOR_METRICS: [
                    {
                        CONF_METRIC_ENTITY_ID: "sensor.temperature",
                        CONF_METRIC_NAME: "This display name is too long",
                    }
                ]
            },
            {
                CONF_SENSOR_METRICS: [
                    {
                        CONF_METRIC_ENTITY_ID: f"sensor.reading_{index}",
                        CONF_METRIC_NAME: f"Reading {index}",
                    }
                    for index in range(6)
                ]
            },
        )
        for config in invalid_configs:
            with self.subTest(config=config), self.assertRaises(ValueError):
                validate_dashboard(config)

    def test_accepts_selected_room_devices_and_tracks_them(self) -> None:
        options = validate_dashboard(
            {CONF_ROOM_ENTITIES: [" climate.downstairs ", "light.kitchen", "switch.fan"]}
        )

        self.assertEqual(
            options[CONF_ROOM_ENTITIES],
            ["climate.downstairs", "light.kitchen", "switch.fan"],
        )
        self.assertTrue(
            {"climate.downstairs", "light.kitchen", "switch.fan"}.issubset(
                dashboard_entities(options)
            )
        )

    def test_limits_area_and_room_capacity(self) -> None:
        from custom_components.cyd_ha_monitor import dashboard

        entities = [f"light.device_{index}" for index in range(6)]
        groups = [
            {"name": "Living Room", "area_id": "living", "devices": entities}
        ]
        with patch.object(dashboard, "_group_room_entities", return_value=groups):
            with self.assertRaisesRegex(ValueError, "at most 5 selected devices"):
                validate_dashboard(
                    {CONF_ROOM_ENTITIES: entities},
                    hass=object(),
                    enforce_room_capacity=True,
                )

        groups = [
            {"name": f"Area {index}", "area_id": str(index), "devices": [entity]}
            for index, entity in enumerate(entities[:5])
        ]
        with patch.object(dashboard, "_group_room_entities", return_value=groups):
            with self.assertRaisesRegex(ValueError, "At most 4 Home Assistant Areas"):
                validate_dashboard(
                    {CONF_ROOM_ENTITIES: entities[:5]},
                    hass=object(),
                    enforce_room_capacity=True,
                )
            # HA Area changes after setup must not invalidate every other
            # dashboard option; runtime payload formatting remains bounded.
            self.assertEqual(
                validate_dashboard({CONF_ROOM_ENTITIES: entities[:5]}, hass=object())[
                    CONF_ROOM_ENTITIES
                ],
                entities[:5],
            )


class RoomPayloadTests(unittest.TestCase):
    def test_groups_selected_entities_by_entity_or_device_area(self) -> None:
        from custom_components.cyd_ha_monitor import dashboard

        class AreasRegistry:
            def async_get_area(self, area_id: str):
                name = {"living": "Living Room", "upstairs": "Upstairs"}.get(area_id)
                return type("Area", (), {"name": name})() if name else None

        class EntityRegistry:
            entries = {
                "light.lamp": type("Entity", (), {"area_id": "living", "device_id": None})(),
                "climate.upstairs": type("Entity", (), {"area_id": None, "device_id": "thermostat"})(),
                "switch.fan": type("Entity", (), {"area_id": None, "device_id": None})(),
            }

            def async_get(self, entity_id: str):
                return self.entries.get(entity_id)

        class DeviceRegistry:
            def async_get(self, device_id: str):
                if device_id == "thermostat":
                    return type("Device", (), {"area_id": "upstairs"})()
                return None

        hass = FakeHass({})
        ha_module = ModuleType("homeassistant")
        helpers_module = ModuleType("homeassistant.helpers")
        registry_modules = {
            name: ModuleType(f"homeassistant.helpers.{name}")
            for name in ("area_registry", "entity_registry", "device_registry")
        }
        registry_modules["area_registry"].async_get = lambda _hass: AreasRegistry()
        registry_modules["entity_registry"].async_get = lambda _hass: EntityRegistry()
        registry_modules["device_registry"].async_get = lambda _hass: DeviceRegistry()
        ha_module.helpers = helpers_module
        for name, module in registry_modules.items():
            setattr(helpers_module, name, module)
        modules = {
            "homeassistant": ha_module,
            "homeassistant.helpers": helpers_module,
            **{
                f"homeassistant.helpers.{name}": module
                for name, module in registry_modules.items()
            },
        }
        with patch.dict(sys.modules, modules):
            groups = dashboard._group_room_entities(
                hass, ["light.lamp", "climate.upstairs", "switch.fan"]
            )

        self.assertEqual(
            [(group["name"], group["devices"]) for group in groups],
            [
                ("Living Room", ["light.lamp"]),
                ("Upstairs", ["climate.upstairs"]),
                ("Unassigned", ["switch.fan"]),
            ],
        )

    def test_serializes_ha_area_devices_and_controls(self) -> None:
        from custom_components.cyd_ha_monitor import dashboard

        hass = FakeHass(
            {
                "climate.downstairs": FakeState(
                    "heat",
                    {
                        "friendly_name": "Downstairs thermostat",
                        "current_temperature": 20.5,
                        "temperature": 22.0,
                        "temperature_unit": "°C",
                        "hvac_modes": ["off", "heat", "cool"],
                        "target_temp_step": 0.5,
                        "min_temp": 5.0,
                        "max_temp": 35.0,
                    },
                ),
                "light.kitchen": FakeState(
                    "on", {"friendly_name": "Kitchen pendants"}
                ),
                "switch.extractor": FakeState(
                    "off", {"friendly_name": "Extractor fan"}
                ),
            }
        )
        groups = [
            {
                "area_id": "kitchen",
                "name": "Kitchen",
                "devices": [
                    "climate.downstairs",
                    "light.kitchen",
                    "switch.extractor",
                ],
            }
        ]
        options = validate_dashboard(
            {
                CONF_ROOM_ENTITIES: [
                    "climate.downstairs",
                    "light.kitchen",
                    "switch.extractor",
                ]
            }
        )
        with patch.object(dashboard, "_group_room_entities", return_value=groups):
            payload = dashboard.dashboard_action_data(hass, options)

        rooms = json.loads(payload["room_devices_json"])["rooms"]
        self.assertEqual(rooms[0]["name"], "Kitchen")
        self.assertEqual(
            [(item["domain"], item["name"], item["state"]) for item in rooms[0]["devices"]],
            [
                ("climate", "Downstairs thermostat", "heat"),
                ("light", "Kitchen pendants", "on"),
                ("switch", "Extractor fan", "off"),
            ],
        )
        self.assertEqual(rooms[0]["devices"][0]["climate"]["target"], "22.0°C")
        self.assertEqual(rooms[0]["devices"][0]["climate"]["next"], "cool")


class DashboardFormattingTests(unittest.TestCase):
    def test_normalizes_power_and_energy_units_and_formats_selected_metrics(self) -> None:
        hass = FakeHass(
            {
                "sensor.house_power": FakeState("2500", {"unit_of_measurement": "W"}),
                "sensor.daily_energy": FakeState("3500", {"unit_of_measurement": "Wh"}),
                "sensor.freezer": FakeState("0.125", {"unit_of_measurement": "kW"}),
                "sensor.session": FakeState("71.6", {"unit_of_measurement": "%"}),
                "sensor.week": FakeState("unknown", {"unit_of_measurement": "%"}),
                "sensor.extra_used": FakeState("2.5", {"unit_of_measurement": "credits"}),
                "sensor.extra_limit": FakeState("10", {"unit_of_measurement": "credits"}),
                "sensor.extra_percent": FakeState("25", {"unit_of_measurement": "%"}),
                "sensor.codex_session": FakeState("35.6", {"unit_of_measurement": "%"}),
                "sensor.codex_week": FakeState("81.2", {"unit_of_measurement": "%"}),
                "camera.driveway": FakeState(
                    "idle",
                    {
                        "access_token": "rotating-token",
                        "friendly_name": "Driveway camera",
                    },
                ),
                "sensor.gemini_session": FakeState("46.8", {"unit_of_measurement": "%"}),
                "sensor.gemini_week": FakeState("73.1", {"unit_of_measurement": "%"}),
                "sensor.openai_session": FakeState("24.2", {"unit_of_measurement": "%"}),
                "sensor.openai_week": FakeState("49.1", {"unit_of_measurement": "%"}),
                "climate.downstairs": FakeState(
                    "heat_cool",
                    {
                        "current_temperature": 20.5,
                        "target_temp_low": 20.0,
                        "target_temp_high": 23.0,
                        "temperature_unit": "°C",
                        "hvac_modes": ["off", "heat", "cool", "heat_cool"],
                        "target_temp_step": 0.5,
                        "min_temp": 7.0,
                        "max_temp": 35.0,
                    },
                ),
            },
            internal_url="http://homeassistant.local:8123",
        )
        options = validate_dashboard(
            {
                CONF_MAIN_POWER_ENTITY: "sensor.house_power",
                CONF_CLIMATE_ENTITY: "climate.downstairs",
                CONF_DAILY_ENERGY_ENTITY: "sensor.daily_energy",
                CONF_POWER_METRICS: [
                    {
                        CONF_METRIC_ENTITY_ID: "sensor.freezer",
                        CONF_METRIC_NAME: "Freezer",
                    }
                ],
                CONF_CLAUDE_SESSION_ENTITY: "sensor.session",
                CONF_CLAUDE_WEEK_ENTITY: "sensor.week",
                CONF_CLAUDE_EXTRA_USED_ENTITY: "sensor.extra_used",
                CONF_CLAUDE_EXTRA_LIMIT_ENTITY: "sensor.extra_limit",
                CONF_CLAUDE_EXTRA_PERCENT_ENTITY: "sensor.extra_percent",
                CONF_AI_PROVIDERS: [
                    {
                        CONF_PROVIDER_NAME: "Codex",
                        CONF_PROVIDER_SESSION_ENTITY: "sensor.codex_session",
                        CONF_PROVIDER_WEEK_ENTITY: "sensor.codex_week",
                    },
                    {
                        CONF_PROVIDER_NAME: "Gemini",
                        CONF_PROVIDER_SESSION_ENTITY: "sensor.gemini_session",
                        CONF_PROVIDER_WEEK_ENTITY: "sensor.gemini_week",
                    },
                    {
                        CONF_PROVIDER_NAME: "OpenAI",
                        CONF_PROVIDER_SESSION_ENTITY: "sensor.openai_session",
                        CONF_PROVIDER_WEEK_ENTITY: "sensor.openai_week",
                    },
                ],
                CONF_CLAUDE_EXTRA_MODE: "remaining",
                CONF_AUTO_ROTATION: True,
                CONF_ROTATION_INTERVAL: 60,
                CONF_SHOW_AI_PAGE: False,
                CONF_SHOW_SENSORS_PAGE: False,
                CONF_SHOW_CLIMATE_PAGE: True,
                CONF_ROTATION_PAGE_1: "energy",
                CONF_ROTATION_PAGE_2: "home",
                CONF_ROTATION_PAGE_3: "ai",
                CONF_ROTATION_PAGE_4: "climate",
                CONF_ROTATION_PAGE_5: "sensors",
                CONF_ROTATION_PAGE_6: "camera",
                CONF_CAMERA_ENTITY: "camera.driveway",
                CONF_CAMERA_REFRESH_INTERVAL: 45,
            }
        )

        data = dashboard_action_data(hass, options)

        self.assertTrue(data["climate_configured"])
        self.assertEqual(data["climate_entity"], "climate.downstairs")
        self.assertEqual(data["climate_current_text"], "20.5°C")
        self.assertEqual(data["climate_target_text"], "20-23°C")
        self.assertEqual(data["climate_target"], 21.5)
        self.assertEqual(data["climate_target_low"], 20.0)
        self.assertEqual(data["climate_target_high"], 23.0)
        self.assertEqual(data["climate_mode_text"], "Heat Cool")
        self.assertTrue(data["auto_rotation_enabled"])
        self.assertEqual(data["rotation_interval_seconds"], 60)
        self.assertFalse(data["page_ai_enabled"])
        self.assertTrue(data["page_climate_enabled"])
        self.assertTrue(data["page_camera_enabled"])
        self.assertEqual(data["camera_refresh_interval_seconds"], 45)
        self.assertEqual(
            data["camera_snapshot_url"],
            "http://homeassistant.local:8123/api/camera_proxy/camera.driveway"
            "?token=rotating-token&width=256&height=144",
        )
        self.assertEqual(data["camera_name"], "Driveway camera")
        self.assertEqual(
            [data[f"rotation_page_{index}"] for index in range(1, 7)],
            [4, 0, 1, 2, 3, 5],
        )
        self.assertEqual(data["climate_mode_previous"], "cool")
        self.assertEqual(data["climate_mode_next"], "off")
        self.assertEqual(data["climate_mode_previous_label"], "< COOL")
        self.assertEqual(data["climate_mode_next_label"], "OFF >")
        self.assertTrue(data["climate_mode_control"])
        self.assertTrue(data["climate_target_available"])
        self.assertTrue(data["climate_range_control"])
        self.assertEqual(data["climate_temperature_step"], 0.5)
        self.assertEqual(data["climate_min_temp"], 7.0)
        self.assertEqual(data["climate_max_temp"], 35.0)
        self.assertTrue(data["power_available"])
        self.assertEqual(data["power_kw"], 2.5)
        self.assertEqual(data["power_text"], "2.50 kW")
        self.assertEqual(data["energy_text"], "3.50 kWh")
        self.assertEqual(data["metric_1_text"], "125 W")
        self.assertTrue(data["session_bar_enabled"])
        self.assertEqual(data["session_text"], "72%")
        self.assertFalse(data["week_bar_enabled"])
        self.assertEqual(data["week_text"], "--%")
        self.assertEqual(data["extra_label"], "Extra remaining")
        self.assertEqual(data["extra_text"], "7.5 credits")
        self.assertEqual(data["extra_summary_text"], "7.5/10.0 cr")
        self.assertEqual(data["extra_limit_text"], "10.0 credits")
        self.assertEqual(data["ai_provider_count"], 3)
        self.assertEqual(data["provider_1_name"], "Codex")
        self.assertEqual(data["provider_1_session_text"], "36%")
        self.assertEqual(data["provider_1_week_text"], "81%")
        self.assertEqual(data["provider_2_name"], "Gemini")
        self.assertEqual(data["provider_2_session_text"], "47%")
        self.assertEqual(data["provider_2_week_text"], "73%")
        self.assertEqual(data["provider_3_name"], "OpenAI")
        self.assertEqual(data["provider_3_session_text"], "24%")
        self.assertEqual(data["provider_3_week_text"], "49%")

    def test_ai_reset_timestamps_read_entities_and_quota_attributes(self) -> None:
        hass = FakeHass(
            {
                "sensor.claude_session": FakeState(
                    "42", {"unit_of_measurement": "%", "resets_at": "2025-01-01T02:11:00Z"}
                ),
                "sensor.claude_week": FakeState("68", {"unit_of_measurement": "%"}),
                "sensor.claude_week_reset": FakeState(
                    "2025-01-06T11:00:00+00:00", {}
                ),
                "sensor.codex_session": FakeState("36", {"unit_of_measurement": "%"}),
                "sensor.codex_week": FakeState(
                    "81",
                    {
                        "unit_of_measurement": "%",
                        "resets_at": "2025-01-06T11:00:00+00:00",
                    },
                ),
                "sensor.codex_session_reset": FakeState(
                    "1735697460", {"unit_of_measurement": "timestamp"}
                ),
            }
        )
        options = validate_dashboard(
            {
                CONF_CLAUDE_SESSION_ENTITY: "sensor.claude_session",
                CONF_CLAUDE_WEEK_ENTITY: "sensor.claude_week",
                CONF_CLAUDE_WEEK_RESET_ENTITY: "sensor.claude_week_reset",
                CONF_AI_PROVIDERS: [
                    {
                        CONF_PROVIDER_NAME: "Codex",
                        CONF_PROVIDER_SESSION_ENTITY: "sensor.codex_session",
                        CONF_PROVIDER_WEEK_ENTITY: "sensor.codex_week",
                        CONF_PROVIDER_SESSION_RESET_ENTITY: "sensor.codex_session_reset",
                    }
                ],
            }
        )

        data = dashboard_action_data(hass, options)

        self.assertEqual(
            data["session_reset_epoch_minute"],
            int(datetime(2025, 1, 1, 2, 11, tzinfo=timezone.utc).timestamp() // 60),
        )
        self.assertEqual(
            data["week_reset_epoch_minute"],
            int(datetime(2025, 1, 6, 11, 0, tzinfo=timezone.utc).timestamp() // 60),
        )
        self.assertEqual(
            data["provider_1_session_reset_epoch_minute"],
            int(datetime(2025, 1, 1, 2, 11, tzinfo=timezone.utc).timestamp() // 60),
        )
        self.assertEqual(
            data["provider_1_week_reset_epoch_minute"],
            int(datetime(2025, 1, 6, 11, 0, tzinfo=timezone.utc).timestamp() // 60),
        )
        self.assertEqual(
            dashboard_entities(options),
            {
                "sensor.claude_session",
                "sensor.claude_week",
                "sensor.claude_week_reset",
                "sensor.codex_session",
                "sensor.codex_week",
                "sensor.codex_session_reset",
            },
        )

    def test_missing_or_expired_ai_reset_timestamps_remain_explicit(self) -> None:
        hass = FakeHass(
            {
                "sensor.session": FakeState("unknown", {"resets_at": "unknown"}),
                "sensor.week": FakeState("68", {"resets_at": "2024-12-31T23:59:00Z"}),
            }
        )
        options = validate_dashboard(
            {
                CONF_CLAUDE_SESSION_ENTITY: "sensor.session",
                CONF_CLAUDE_WEEK_ENTITY: "sensor.week",
            }
        )

        data = dashboard_action_data(hass, options)

        self.assertEqual(data["session_reset_epoch_minute"], -1)
        self.assertEqual(
            data["week_reset_epoch_minute"],
            int(datetime(2024, 12, 31, 23, 59, tzinfo=timezone.utc).timestamp() // 60),
        )

    def test_camera_proxy_url_requires_safe_internal_url_and_stays_ephemeral(self) -> None:
        hass = FakeHass(
            {"camera.driveway": FakeState("idle", {"access_token": "rotating-token"})}
        )
        options = validate_dashboard({CONF_CAMERA_ENTITY: "camera.driveway"})

        self.assertTrue(options[CONF_SHOW_CAMERA_PAGE])
        self.assertEqual(dashboard_action_data(hass, options)["camera_snapshot_url"], "")
        self.assertNotIn("rotating-token", repr(options))

        hass.config.internal_url = "http://ha.local:8123/base?q=unsafe"
        self.assertEqual(
            dashboard_action_data(hass, options)["camera_snapshot_url"], ""
        )

    def test_hidden_camera_page_does_not_send_or_track_its_proxy_token(self) -> None:
        camera = FakeState("idle", {"access_token": "rotating-token"})
        hass = FakeHass(
            {"camera.driveway": camera},
            internal_url="http://homeassistant.local:8123",
        )
        options = validate_dashboard(
            {CONF_CAMERA_ENTITY: "camera.driveway", CONF_SHOW_CAMERA_PAGE: False}
        )

        self.assertNotIn("camera.driveway", dashboard_entities(options))
        data = dashboard_action_data(hass, options)
        self.assertFalse(data["page_camera_enabled"])
        self.assertEqual(data["camera_snapshot_url"], "")
        self.assertEqual(data["camera_name"], "CAMERA")
        self.assertNotIn("rotating-token", repr(data))

    def test_unavailable_provider_quota_is_not_rendered_as_a_real_percentage(self) -> None:
        hass = FakeHass(
            {
                "sensor.codex_session": FakeState(
                    "unavailable", {"unit_of_measurement": "%"}
                )
            }
        )
        options = validate_dashboard(
            {
                CONF_AI_PROVIDERS: [
                    {
                        CONF_PROVIDER_NAME: "Codex",
                        CONF_PROVIDER_SESSION_ENTITY: "sensor.codex_session",
                    }
                ]
            }
        )

        data = dashboard_action_data(hass, options)

        self.assertEqual(data["ai_provider_count"], 1)
        self.assertTrue(data["provider_1_session_enabled"])
        self.assertFalse(data["provider_1_session_bar_enabled"])
        self.assertEqual(data["provider_1_session_text"], "--%")

    def test_unavailable_entities_use_placeholders_and_unknown_units_are_not_graphed(self) -> None:
        hass = FakeHass(
            {
                "sensor.house_power": FakeState("12", {"unit_of_measurement": "amps"}),
                "sensor.energy": FakeState("unavailable", {"unit_of_measurement": "kWh"}),
            }
        )
        options = validate_dashboard(
            {
                CONF_MAIN_POWER_ENTITY: "sensor.house_power",
                CONF_DAILY_ENERGY_ENTITY: "sensor.energy",
            }
        )

        data = dashboard_action_data(hass, options)

        self.assertFalse(data["power_available"])
        self.assertEqual(data["power_text"], "12.00 amps")
        self.assertEqual(data["energy_text"], "--.-- kWh")

    def test_sensor_monitor_formats_numeric_text_and_unavailable_values(self) -> None:
        hass = FakeHass(
            {
                "sensor.living_room": FakeState(
                    "21.4", {"unit_of_measurement": "°C"}
                ),
                "sensor.front_door": FakeState("closed", {}),
                "sensor.outdoor": FakeState("unavailable", {}),
                "sensor.particulate": FakeState(
                    "0.00042", {"unit_of_measurement": "ppm"}
                ),
            }
        )
        options = validate_dashboard(
            {
                CONF_SENSOR_METRICS: [
                    {
                        CONF_METRIC_ENTITY_ID: "sensor.living_room",
                        CONF_METRIC_NAME: "Living room",
                    },
                    {
                        CONF_METRIC_ENTITY_ID: "sensor.front_door",
                        CONF_METRIC_NAME: "Front door",
                    },
                    {
                        CONF_METRIC_ENTITY_ID: "sensor.outdoor",
                        CONF_METRIC_NAME: "Outdoor",
                    },
                    {
                        CONF_METRIC_ENTITY_ID: "sensor.particulate",
                        CONF_METRIC_NAME: "Particulates",
                    },
                ]
            }
        )

        data = dashboard_action_data(hass, options)

        self.assertTrue(data["sensor_monitor_configured"])
        self.assertEqual(data["sensor_1_name"], "Living room")
        self.assertEqual(data["sensor_1_text"], "21.4 °C")
        self.assertEqual(data["sensor_1_status"], 0)
        self.assertEqual(data["sensor_2_text"], "closed")
        self.assertEqual(data["sensor_3_text"], "Unavailable")
        self.assertTrue(data["sensor_4_enabled"])
        self.assertEqual(data["sensor_4_text"], "0.00042 ppm")
        self.assertFalse(data["sensor_5_enabled"])
        self.assertEqual(data["sensor_5_text"], "Unavailable")

    def test_saved_empty_sensor_selection_clears_firmware_fallback_rows(self) -> None:
        options = validate_dashboard({})
        options[CONF_DASHBOARD_SETTINGS_SAVED] = True

        data = dashboard_action_data(FakeHass({}), options)

        self.assertTrue(data["sensor_monitor_configured"])
        self.assertFalse(data["sensor_1_enabled"])
        self.assertFalse(data["sensor_5_enabled"])

    def test_alert_rule_status_is_included_with_sensor_rows(self) -> None:
        hass = FakeHass(
            {"sensor.living_room": FakeState("26", {"unit_of_measurement": "°C"})}
        )
        options = validate_dashboard(
            {
                CONF_SENSOR_METRICS: [
                    {
                        CONF_METRIC_ENTITY_ID: "sensor.living_room",
                        CONF_METRIC_NAME: "Living room",
                    }
                ]
            }
        )
        engine = RuleEngine(
            [
                {
                    "entity_id": "sensor.living_room",
                    "direction": "above",
                    "threshold": 30,
                    "warning_threshold": 25,
                    "hysteresis": 1,
                    "priority": 2,
                    "title": "Warm",
                    "message": "Room is warm",
                }
            ]
        )
        engine.seed(
            {"sensor.living_room": "26"}, {"sensor.living_room": "°C"}
        )

        self.assertEqual(
            dashboard_action_data(hass, options, engine)["sensor_1_status"], 2
        )

        engine.update("sensor.living_room", "31", "°C")
        self.assertEqual(engine.sensor_status("sensor.living_room"), 3)

    def test_remaining_is_not_calculated_from_different_units(self) -> None:
        hass = FakeHass(
            {
                "sensor.used": FakeState("2", {"unit_of_measurement": "credits"}),
                "sensor.limit": FakeState("10", {"unit_of_measurement": "USD"}),
            }
        )
        options = validate_dashboard(
            {
                CONF_CLAUDE_EXTRA_USED_ENTITY: "sensor.used",
                CONF_CLAUDE_EXTRA_LIMIT_ENTITY: "sensor.limit",
                CONF_CLAUDE_EXTRA_MODE: "remaining",
            }
        )

        data = dashboard_action_data(hass, options)

        self.assertEqual(data["extra_text"], "-- credits")

    def test_unconfigured_or_unavailable_climate_uses_safe_placeholders(self) -> None:
        hass = FakeHass(
            {
                "climate.downstairs": FakeState(
                    "unavailable",
                    {
                        "current_temperature": None,
                        "temperature": None,
                        "hvac_modes": ["off", "heat"],
                    },
                )
            }
        )

        unconfigured = dashboard_action_data(hass, validate_dashboard({}))
        self.assertFalse(unconfigured["climate_configured"])
        self.assertEqual(unconfigured["climate_entity"], "")
        self.assertEqual(unconfigured["climate_current_text"], "--.-°C")
        self.assertFalse(unconfigured["climate_target_available"])
        self.assertFalse(unconfigured["climate_range_control"])
        self.assertFalse(unconfigured["climate_mode_control"])

        configured = dashboard_action_data(
            hass, validate_dashboard({CONF_CLIMATE_ENTITY: "climate.downstairs"})
        )
        self.assertTrue(configured["climate_configured"])
        self.assertEqual(configured["climate_mode_text"], "Unavailable")
        self.assertFalse(configured["climate_target_available"])
        self.assertFalse(configured["climate_range_control"])
        self.assertFalse(configured["climate_mode_control"])

    def test_single_target_preserves_a_fahrenheit_unit(self) -> None:
        hass = FakeHass(
            {
                "climate.guest_room": FakeState(
                    "heat",
                    {
                        "current_temperature": 68.0,
                        "temperature": 70.0,
                        "temperature_unit": "°F",
                        "hvac_modes": ["off", "heat"],
                    },
                )
            }
        )
        data = dashboard_action_data(
            hass,
            validate_dashboard({CONF_CLIMATE_ENTITY: "climate.guest_room"}),
        )

        self.assertEqual(data["climate_current_text"], "68.0°F")
        self.assertEqual(data["climate_target_text"], "70.0°F")
        self.assertEqual(data["climate_temperature_step"], 0.5)
        self.assertFalse(data["climate_range_control"])


if __name__ == "__main__":
    unitte
