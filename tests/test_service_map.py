"""Tests for mapping a selected ESPHome registry device to action services."""

from __future__ import annotations

import unittest
from dataclasses import dataclass

from custom_components.cyd_ha_monitor.service_map import (
    _linked_esphome_config_entry_ids,
    resolve_action_services,
    service_names,
)


@dataclass
class FakeEntry:
    domain: str
    title: str
    data: dict[str, str]


@dataclass
class FakeDevice:
    identifiers: set[tuple[str, str]]
    name: str | None = None
    name_by_user: str | None = None


@dataclass
class FakeService:
    description: str


@dataclass
class FakeEntity:
    device_id: str
    platform: str
    config_entry_id: str | None


def registered_actions(names, description=""):
    return {
        name: FakeService(description)
        for name in (
            names.display_alert, names.clear_alert, names.dismiss_alert,
            names.focus_page, *names.dashboard_actions,
        )
        if name is not None
    }


class ServiceMapTests(unittest.TestCase):
    def test_weather_is_optional_and_never_uses_another_devices_service(self) -> None:
        names = service_names("desk_hass")
        device = FakeDevice({("esphome", "desk-hass")})
        entry = FakeEntry("esphome", "Desk", {"node_name": "desk-hass"})
        registered = registered_actions(names)
        registered["other_update_weather"] = FakeService("")
        registered["other_update_weather_forecasts"] = FakeService("")
        result = resolve_action_services(device, [entry], registered)
        self.assertIsNone(result.update_weather)
        self.assertIsNone(result.update_weather_forecasts)
        self.assertEqual(result.dashboard_actions, names.dashboard_actions)
        registered["desk_hass_update_weather"] = FakeService("")
        result = resolve_action_services(device, [entry], registered)
        self.assertEqual(result.update_weather, "desk_hass_update_weather")
        self.assertIsNone(result.update_weather_forecasts)
        self.assertEqual(result.dashboard_actions, names.dashboard_actions)
        registered["desk_hass_update_weather_forecasts"] = FakeService("")
        result = resolve_action_services(device, [entry], registered)
        self.assertEqual(result.update_weather_forecasts, "desk_hass_update_weather_forecasts")
        registered.pop("desk_hass_update_weather")
        self.assertIsNone(resolve_action_services(device, [entry], registered).update_weather_forecasts)

    def test_uses_selected_device_node_identifier_and_hyphen_replacement(self) -> None:
        names = service_names("monitor_node")
        device = FakeDevice({("esphome", "monitor-node")}, name="A user label")
        entry = FakeEntry("esphome", "A different title", {"node_name": "monitor-node"})
        registered = registered_actions(names)

        self.assertEqual(resolve_action_services(device, [entry], registered), names)

    def test_printer_action_is_optional_and_selected_device_only(self) -> None:
        names = service_names("desk_hass")
        device = FakeDevice({("esphome", "desk-hass")})
        entry = FakeEntry("esphome", "Desk", {"node_name": "desk-hass"})
        registered = registered_actions(names)
        registered["other_update_printer"] = FakeService("")
        self.assertIsNone(resolve_action_services(device, [entry], registered).update_printer)
        registered["desk_hass_update_printer"] = FakeService("")
        self.assertEqual(resolve_action_services(device, [entry], registered).update_printer, "desk_hass_update_printer")

    def test_uses_service_descriptions_when_registry_name_is_edited(self) -> None:
        names = service_names("cyd_node")
        device = FakeDevice({("esphome", "old-node-name")}, name="CYD Display")
        entry = FakeEntry("esphome", "CYD Display", {"device_name": "CYD Display"})
        registered = registered_actions(names, "ESPHome action for CYD Display")

        self.assertEqual(resolve_action_services(device, [entry], registered), names)

    def test_uses_linked_esphome_config_entry_device_name(self) -> None:
        names = service_names("desk_hass")
        device = FakeDevice(set(), name="Desk HASS")
        entry = FakeEntry("esphome", "Desk HASS", {"device_name": "desk-hass"})
        registered = registered_actions(names)

        self.assertEqual(resolve_action_services(device, [entry], registered), names)

    def test_dashboard_action_is_optional_for_older_firmware(self) -> None:
        names = service_names("monitor_node")
        device = FakeDevice({("esphome", "monitor-node")})
        entry = FakeEntry("esphome", "Monitor", {"node_name": "monitor-node"})
        registered = {
            names.display_alert: FakeService(""),
            names.clear_alert: FakeService(""),
            names.dismiss_alert: FakeService(""),
        }

        result = resolve_action_services(device, [entry], registered)

        self.assertIsNotNone(result)
        self.assertIsNone(result.update_dashboard)
        self.assertIsNone(result.focus_page)
        self.assertEqual(result.dashboard_actions, ())

    def test_refuses_legacy_or_incomplete_dashboard_protocol(self) -> None:
        names = service_names("monitor_node")
        device = FakeDevice({("esphome", "monitor-node")})
        entry = FakeEntry("esphome", "Monitor", {"node_name": "monitor-node"})
        registered = registered_actions(names)
        registered.pop(names.dashboard_actions[-1])
        registered["monitor_node_update_dashboard"] = FakeService("")
        result = resolve_action_services(device, [entry], registered)
        self.assertIsNotNone(result)
        self.assertIsNone(result.update_dashboard)
        self.assertEqual(result.dashboard_actions, ())

    def test_recovers_missing_device_config_entries_from_esphome_entities(self) -> None:
        device = FakeDevice(set(), name="Desk HASS")
        entities = [
            FakeEntity("selected", "esphome", "entry-esphome"),
            FakeEntity("selected", "mqtt", "entry-mqtt"),
            FakeEntity("other", "esphome", "entry-other"),
        ]

        self.assertEqual(
            _linked_esphome_config_entry_ids("selected", device, entities),
            {"entry-esphome"},
        )

    def test_does_not_guess_from_unlinked_or_incomplete_services(self) -> None:
        names = service_names("monitor_node")
        device = FakeDevice({("esphome", "monitor-node")})
        entry = FakeEntry("esphome", "Monitor", {"node_name": "monitor-node"})
        self.assertIsNone(resolve_action_services(device, [], {}))
        self.assertIsNone(
            resolve_action_services(
                device, [entry], {names.display_alert: FakeService("")}
            )
        )

    def test_ignores_other_integration_config_entries(self) -> None:
        names = service_names("monitor_node")
        device = FakeDevice({("esphome", "monitor-node")})
        unrelated = FakeEntry("mqtt", "Monitor", {"node_name": "monitor-node"})
        registered = registered_actions(names)
        self.assertIsNone(resolve_action_services(device, [unrelated], registered))


if __name__ == "__main__":
    unittest.main()
