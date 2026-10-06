"""Tests for dashboard settings and Home Assistant sensor formatting."""

from __future__ import annotations

import unittest
from dataclasses import dataclass

from custom_components.cyd_ha_monitor.const import (
    CONF_CLAUDE_EXTRA_LIMIT_ENTITY,
    CONF_CLAUDE_EXTRA_MODE,
    CONF_CLAUDE_EXTRA_PERCENT_ENTITY,
    CONF_CLAUDE_EXTRA_USED_ENTITY,
    CONF_CLAUDE_EXTRA_LIMIT_ENTITY,
    CONF_CLAUDE_SESSION_ENTITY,
    CONF_CLAUDE_WEEK_ENTITY,
    CONF_DAILY_ENERGY_ENTITY,
    CONF_MAIN_POWER_ENTITY,
    CONF_METRIC_ENTITY_ID,
    CONF_METRIC_NAME,
    CONF_POWER_METRICS,
)
from custom_components.cyd_ha_monitor.dashboard import (
    dashboard_action_data,
    dashboard_entities,
    validate_dashboard,
)


@dataclass
class FakeState:
    state: str
    attributes: dict[str, str]


class FakeStates:
    def __init__(self, values: dict[str, FakeState]) -> None:
        self.values = values

    def get(self, entity_id: str) -> FakeState | None:
        return self.values.get(entity_id)


class FakeHass:
    def __init__(self, values: dict[str, FakeState]) -> None:
        self.states = FakeStates(values)


class DashboardValidationTests(unittest.TestCase):
    def test_accepts_optional_entity_sources_and_named_power_metrics(self) -> None:
        config = validate_dashboard(
            {
                CONF_MAIN_POWER_ENTITY: "sensor.house_power",
                CONF_POWER_METRICS: [
                    {
                        CONF_METRIC_ENTITY_ID: "sensor.freezer_power",
                        CONF_METRIC_NAME: "Freezer",
                    }
                ],
                CONF_CLAUDE_EXTRA_MODE: "remaining",
            }
        )

        self.assertEqual(config[CONF_MAIN_POWER_ENTITY], "sensor.house_power")
        self.assertEqual(config[CONF_CLAUDE_EXTRA_MODE], "remaining")
        self.assertEqual(len(dashboard_entities(config)), 2)

    def test_rejects_invalid_mode_too_many_metrics_and_missing_names(self) -> None:
        invalid_configs = (
            {CONF_CLAUDE_EXTRA_MODE: "percent"},
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
        )
        for config in invalid_configs:
            with self.subTest(config=config), self.assertRaises(ValueError):
                validate_dashboard(config)


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
            }
        )
        options = validate_dashboard(
            {
                CONF_MAIN_POWER_ENTITY: "sensor.house_power",
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
                CONF_CLAUDE_EXTRA_MODE: "remaining",
            }
        )

        data = dashboard_action_data(hass, options)

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
        self.assertEqual(data["extra_limit_text"], "10.0 credits")

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


if __name__ == "__main__":
    unittest.main()
