"""Tests for pushing configured dashboard values through ESPHome actions."""

from __future__ import annotations

import asyncio
import unittest

from custom_components.cyd_ha_monitor import Runtime, _schedule_dashboard_update
from custom_components.cyd_ha_monitor.alerts import RuleEngine
from custom_components.cyd_ha_monitor.const import (
    CONF_METRIC_ENTITY_ID,
    CONF_METRIC_NAME,
    CONF_SENSOR_METRICS,
    DOMAIN,
)
from custom_components.cyd_ha_monitor.dashboard import validate_dashboard
from custom_components.cyd_ha_monitor.service_map import service_names


class FakeState:
    def __init__(self, state: str, unit: str) -> None:
        self.state = state
        self.attributes = {"unit_of_measurement": unit}


class FakeStates:
    def __init__(self) -> None:
        self.values = {
            "sensor.main_power": FakeState("750", "W"),
            "sensor.indoor_temperature": FakeState("22.5", "°C"),
        }

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
        options = validate_dashboard(
            {
                "main_power_entity": "sensor.main_power",
                CONF_SENSOR_METRICS: [
                    {
                        CONF_METRIC_ENTITY_ID: "sensor.indoor_temperature",
                        CONF_METRIC_NAME: "Living room",
                    }
                ],
            }
        )
        runtime = Runtime(
            RuleEngine([]),
            names,
            "Desk HASS",
            dashboard_options=options,
            dashboard_entities={"sensor.main_power", "sensor.indoor_temperature"},
            dashboard_settings_saved=True,
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
                        "auto_rotation_enabled": False,
                        "rotation_interval_seconds": 30,
                        "page_ai_enabled": True,
                        "page_climate_enabled": True,
                        "page_sensors_enabled": True,
                        "page_energy_enabled": True,
                        "page_camera_enabled": False,
                        "rotation_page_1": 0,
                        "rotation_page_2": 1,
                        "rotation_page_3": 2,
                        "rotation_page_4": 3,
                        "rotation_page_5": 4,
                        "rotation_page_6": 5,
                        "camera_refresh_interval_seconds": 30,
                        "camera_snapshot_url": "",
                        "camera_name": "CAMERA",
                        "climate_configured": False,
                        "climate_entity": "",
                        "climate_current_text": "--.-°C",
                        "climate_target_text": "--.-°C",
                        "climate_target": 0.0,
                        "climate_target_low": 0.0,
                        "climate_target_high": 0.0,
                        "climate_target_available": False,
                        "climate_range_control": False,
                        "climate_mode_text": "Unavailable",
                        "climate_mode_previous": "",
                        "climate_mode_next": "",
                        "climate_mode_previous_label": "",
                        "climate_mode_next_label": "",
                        "climate_mode_control": False,
                        "climate_temperature_step": 0.5,
                        "climate_min_temp": -100.0,
                        "climate_max_temp": 100.0,
                        "room_devices_json": '{"rooms":[]}',
                        "claude_configured": False,
                        "power_available": True,
                        "power_kw": 0.75,
                        "power_text": "0.75 kW",
                        "energy_text": "--.-- kWh",
                        "extra_label": "Extra used",
                        "ai_provider_count": 0,
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
                        "sensor_monitor_configured": True,
                        "sensor_1_enabled": True,
                        "sensor_1_name": "Living room",
                        "sensor_1_text": "22.5 °C",
                        "sensor_2_enabled": False,
                        "sensor_2_name": "",
                        "sensor_2_text": "Unavailable",
                        "sensor_3_enabled": False,
                        "sensor_3_name": "",
                        "sensor_3_text": "Unavailable",
                        "sensor_4_enabled": False,
                        "sensor_4_name": "",
                        "sensor_4_text": "Unavailable",
                        "sensor_5_enabled": False,
                        "sensor_5_name": "",
                        "sensor_5_text": "Unavailable",
                        "session_enabled": False,
                        "session_bar_enabled": False,
                        "session_percent": 0.0,
                        "session_text": "--%",
                        "session_reset_epoch_minute": -1,
                        "week_enabled": False,
                        "week_bar_enabled": False,
                        "week_percent": 0.0,
                        "week_text": "--%",
                        "week_reset_epoch_minute": -1,
                        "extra_enabled": False,
                        "extra_bar_enabled": False,
                        "extra_percent": 0.0,
                        "extra_text": "-- credits",
                        "extra_summary_text": "-- credits",
                        "extra_limit_enabled": False,
                        "extra_limit_text": "-- credits",
                        "provider_1_name": "",
                        "provider_1_session_enabled": False,
                        "provider_1_session_bar_enabled": False,
                        "provider_1_session_percent": 0.0,
                        "provider_1_session_text": "--%",
                        "provider_1_session_reset_epoch_minute": -1,
                        "provider_1_week_enabled": False,
                        "provider_1_week_bar_enabled": False,
                        "provider_1_week_percent": 0.0,
                        "provider_1_week_text": "--%",
                        "provider_1_week_reset_epoch_minute": -1,
                        "provider_2_name": "",
                        "provider_2_session_enabled": False,
                        "provider_2_session_bar_enabled": False,
                        "provider_2_session_percent": 0.0,
                        "provider_2_session_text": "--%",
                        "provider_2_session_reset_epoch_minute": -1,
                        "provider_2_week_enabled": False,
                        "provider_2_week_bar_enabled": False,
                        "provider_2_week_percent": 0.0,
                        "provider_2_week_text": "--%",
                        "provider_2_week_reset_epoch_minute": -1,
                        "provider_3_name": "",
                        "provider_3_session_enabled": False,
                        "provider_3_session_bar_enabled": False,
                        "provider_3_session_percent": 0.0,
                        "provider_3_session_text": "--%",
                        "provider_3_session_reset_epoch_minute": -1,
                        "provider_3_week_enabled": False,
                        "provider_3_week_bar_enabled": False,
                        "provider_3_week_percent": 0.0,
                        "provider_3_week_text": "--%",
                        "provider_3_week_reset_epoch_minute": -1,
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
