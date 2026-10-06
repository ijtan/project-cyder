"""Tests for pushing configured dashboard values through ESPHome actions."""

from __future__ import annotations

import asyncio
import unittest

from custom_components.cyd_ha_monitor import Runtime, _schedule_dashboard_update
from custom_components.cyd_ha_monitor.alerts import RuleEngine
from custom_components.cyd_ha_monitor.const import DOMAIN
from custom_components.cyd_ha_monitor.dashboard import validate_dashboard
from custom_components.cyd_ha_monitor.service_map import service_names


class FakeState:
    def __init__(self, state: str, unit: str) -> None:
        self.state = state
        self.attributes = {"unit_of_measurement": unit}


class FakeStates:
    def __init__(self) -> None:
        self.values = {"sensor.main_power": FakeState("750", "W")}

    def get(self, entity_id: str) -> FakeState | None:
        return self.values.get(entity_id)


class FakeServices:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    async def async_call(
        self, domain: str, service: str, data: dict[str, object]
    ) -> None:
        self.calls.append((domain, service, data))


class FakeHass:
    def __init__(self) -> None:
        self.services = FakeServices()
        self.states = FakeStates()
        self.tasks: list[asyncio.Task[None]] = []

    def async_create_task(self, coroutine: object) -> asyncio.Task[None]:
        task = asyncio.create_task(coroutine)  # type: ignore[arg-type]
        self.tasks.append(task)
        return task


class DashboardCallTests(unittest.IsolatedAsyncioTestCase):
    async def test_schedules_one_update_for_latest_configured_sensor_values(self) -> None:
        hass = FakeHass()
        names = service_names("desk_hass")
        options = validate_dashboard({"main_power_entity": "sensor.main_power"})
        runtime = Runtime(
            RuleEngine([]),
            names,
            "Desk HASS",
            dashboard_options=options,
            dashboard_entities={"sensor.main_power"},
        )

        _schedule_dashboard_update(hass, runtime)
        _schedule_dashboard_update(hass, runtime)
        await asyncio.gather(*hass.tasks)

        self.assertEqual(
            hass.services.calls,
            [
                (
                    "esphome",
                    names.update_dashboard,
                    {
                        "power_configured": True,
                        "claude_configured": False,
                        "power_available": True,
                        "power_kw": 0.75,
                        "power_text": "0.75 kW",
                        "energy_text": "--.-- kWh",
                        "extra_label": "Extra used",
                        "metric_1_enabled": False,
                        "metric_1_name": "",
                        "metric_1_text": "-- W",
                        "metric_2_enabled": False,
                        "metric_2_name": "",
                        "metric_2_text": "-- W",
                        "metric_3_enabled": False,
                        "metric_3_name": "",
                        "metric_3_text": "-- W",
                        "metric_4_enabled": False,
                        "metric_4_name": "",
                        "metric_4_text": "-- W",
                        "session_enabled": False,
                        "session_bar_enabled": False,
                        "session_percent": 0.0,
                        "session_text": "--%",
                        "week_enabled": False,
                        "week_bar_enabled": False,
                        "week_percent": 0.0,
                        "week_text": "--%",
                        "extra_enabled": False,
                        "extra_bar_enabled": False,
                        "extra_percent": 0.0,
                        "extra_text": "-- credits",
                        "extra_limit_enabled": False,
                        "extra_limit_text": "-- credits",
                    },
                )
            ],
        )
        self.assertEqual(runtime.dashboard_update_scheduled, False)

    async def test_does_not_schedule_when_old_firmware_lacks_the_action(self) -> None:
        hass = FakeHass()
        names = service_names("desk_hass")
        names = type(names)(
            names.display_alert,
            names.clear_alert,
            names.dismiss_alert,
            None,
        )
        runtime = Runtime(RuleEngine([]), names, "Desk HASS")

        _schedule_dashboard_update(hass, runtime)

        self.assertEqual(hass.tasks, [])


if __name__ == "__main__":
    unittest.main()
