"""Tests for pushing configured dashboard values through ESPHome actions."""

from __future__ import annotations

import asyncio
import unittest

from custom_components.cyd_ha_monitor import Runtime, _schedule_dashboard_update
from custom_components.cyd_ha_monitor import async_unload_entry
from custom_components.cyd_ha_monitor.alerts import RuleEngine
from custom_components.cyd_ha_monitor.const import (
    CONF_METRIC_ENTITY_ID,
    CONF_METRIC_NAME,
    CONF_SENSOR_METRICS,
    DOMAIN,
)
from custom_components.cyd_ha_monitor.dashboard import validate_dashboard
from custom_components.cyd_ha_monitor.service_map import service_names
from custom_components.cyd_ha_monitor.dashboard_transport import MAX_DASHBOARD_ARGUMENTS


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
        self, domain: str, service: str, data: dict[str, object], *, blocking: bool = False
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

        self.assertEqual([call[1] for call in hass.services.calls], list(names.dashboard_actions))
        self.assertTrue(all(len(call[2]) <= MAX_DASHBOARD_ARGUMENTS for call in hass.services.calls))
        self.assertNotIn("desk_hass_update_dashboard", [call[1] for call in hass.services.calls])
        # Preserve the original complete-snapshot assertion below while checking
        # transport sends eight bounded messages rather than one giant action.
        combined = {key: value for _, _, data in hass.services.calls for key, value in data.items()}

        self.assertEqual(
            [("esphome", names.update_dashboard, combined)],
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
                        "claude_configured": True,
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
                        "sensor_1_status": 0,
                        "sensor_2_enabled": False,
                        "sensor_2_name": "",
                        "sensor_2_text": "Unavailable",
                        "sensor_2_status": 0,
                        "sensor_3_enabled": False,
                        "sensor_3_name": "",
                        "sensor_3_text": "Unavailable",
                        "sensor_3_status": 0,
                        "sensor_4_enabled": False,
                        "sensor_4_name": "",
                        "sensor_4_text": "Unavailable",
                        "sensor_4_status": 0,
                        "sensor_5_enabled": False,
                        "sensor_5_name": "",
                        "sensor_5_text": "Unavailable",
                        "sensor_5_status": 0,
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

    async def test_changes_during_send_are_coalesced_into_latest_followup(self) -> None:
        hass = FakeHass()
        runtime = Runtime(
            RuleEngine([]), service_names("desk_hass"), "Desk HASS",
            dashboard_options=validate_dashboard({"main_power_entity": "sensor.main_power"}),
        )
        original_call = hass.services.async_call

        async def change_during_send(domain, service, data, *, blocking=False):
            await original_call(domain, service, data, blocking=blocking)
            if len(hass.services.calls) == 1:
                hass.states.values["sensor.main_power"] = FakeState("1200", "W")
                for _ in range(5):
                    _schedule_dashboard_update(hass, runtime)

        hass.services.async_call = change_during_send
        _schedule_dashboard_update(hass, runtime)
        await asyncio.gather(*hass.tasks)
        self.assertEqual(len(hass.tasks), 1)
        self.assertEqual(len(hass.services.calls), 16)
        energy_calls = [data for _, service, data in hass.services.calls if service.endswith("_energy")]
        self.assertEqual([data["power_text"] for data in energy_calls], ["0.75 kW", "1.20 kW"])

    async def test_disable_cancels_pending_updates(self) -> None:
        hass = FakeHass()
        runtime = Runtime(RuleEngine([]), service_names("desk_hass"), "Desk HASS")
        hass.data = {DOMAIN: {"entry": runtime}}
        _schedule_dashboard_update(hass, runtime)
        await async_unload_entry(hass, type("Entry", (), {"entry_id": "entry"})())
        self.assertEqual(hass.services.calls, [])
        self.assertTrue(runtime.stopped)
        _schedule_dashboard_update(hass, runtime)
        self.assertEqual(len(hass.tasks), 1)

    async def test_disable_mid_snapshot_stops_remaining_sections(self) -> None:
        hass = FakeHass()
        runtime = Runtime(RuleEngine([]), service_names("desk_hass"), "Desk HASS")
        hass.data = {DOMAIN: {"entry": runtime}}
        first_sent = asyncio.Event()
        original_call = hass.services.async_call

        async def signal_first(domain, service, data, *, blocking=False):
            await original_call(domain, service, data, blocking=blocking)
            first_sent.set()

        hass.services.async_call = signal_first
        _schedule_dashboard_update(hass, runtime)
        await first_sent.wait()
        await async_unload_entry(hass, type("Entry", (), {"entry_id": "entry"})())
        self.assertEqual(len(hass.services.calls), 1)
        self.assertFalse(runtime.dashboard_update_scheduled)
        self.assertIsNone(runtime.dashboard_task)

    async def test_failure_stops_batch_without_logging_payload_and_can_resync(self) -> None:
        hass = FakeHass()
        runtime = Runtime(RuleEngine([]), service_names("desk_hass"), "Desk HASS")
        original_call = hass.services.async_call

        async def fail_call(domain, service, data, *, blocking=False):
            raise RuntimeError("private-camera-token")

        hass.services.async_call = fail_call
        with self.assertLogs("custom_components.cyd_ha_monitor", level="WARNING") as logs:
            _schedule_dashboard_update(hass, runtime)
            await asyncio.gather(*hass.tasks)
        self.assertNotIn("private-camera-token", " ".join(logs.output))
        self.assertFalse(runtime.dashboard_update_scheduled)
        hass.services.async_call = original_call
        _schedule_dashboard_update(hass, runtime)
        await asyncio.gather(*hass.tasks)
        self.assertEqual(len(hass.services.calls), 8)

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
