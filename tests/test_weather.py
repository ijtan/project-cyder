"""Weather source ownership, bounded formatting, throttling and lifecycle."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from zoneinfo import ZoneInfo

from custom_components.cyd_ha_monitor.weather import (
    CONF_WEATHER_ENTITY, CONF_WEATHER_ENABLED, CONF_WEATHER_FORECAST,
    WeatherBridge, forecast_rows, forecast_type, validate_weather, weather_action_data, weather_forecasts_data,
)


def state(features=3, condition="partlycloudy", unit="°C"):
    return SimpleNamespace(state=condition, attributes={
        "friendly_name": "Home weather", "supported_features": features,
        "temperature": 23, "apparent_temperature": 24, "temperature_unit": unit,
        "wind_speed": 12, "wind_speed_unit": "km/h",
    })


class WeatherFormattingTests(unittest.TestCase):
    def test_defaults_disabled_and_selection_is_explicit(self):
        self.assertEqual(validate_weather({})[CONF_WEATHER_ENTITY], None)
        self.assertFalse(validate_weather({})[CONF_WEATHER_ENABLED])
        for value in ("sensor.temperature", "weather.bad-name", True, 42):
            with self.assertRaises(ValueError):
                validate_weather({CONF_WEATHER_ENTITY: value})
        for mode in ("weekly", None, []):
            with self.assertRaises(ValueError):
                validate_weather({CONF_WEATHER_FORECAST: mode})

    def test_auto_chooses_only_advertised_forecast_features(self):
        self.assertEqual(forecast_type(state(3), "auto"), "hourly")
        self.assertEqual(forecast_type(state(1), "auto"), "daily")
        self.assertEqual(forecast_type(state(4), "auto"), "twice_daily")
        self.assertIsNone(forecast_type(state(1), "hourly"))
        self.assertIsNone(forecast_type(state(0), "auto"))

    def test_three_local_time_forecasts_no_past_hours_and_provider_units(self):
        now = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)
        raw = [{"datetime": (now + timedelta(hours=i)).isoformat(),
                "condition": "sunny", "temperature": 70 + i} for i in range(-1, 7)]
        rows = forecast_rows(raw, "hourly", "°F", now, ZoneInfo("Europe/Malta"))
        self.assertEqual(rows[0], ("14:00", "Sunny", "70°F"))
        self.assertEqual(len(rows), 3)
        daily = forecast_rows([{"datetime": "2026-10-09T00:00:00Z", "temperature": 25,
                                "templow": 18, "condition": "rainy"}], "daily", "°C", now, ZoneInfo("UTC"))
        self.assertEqual(daily[0][2], "18/25°C")

    def test_payload_is_bounded_and_clear_or_unavailable_removes_old_values(self):
        options = validate_weather({CONF_WEATHER_ENTITY: "weather.selected", CONF_WEATHER_ENABLED: True})
        selected = state()
        selected.attributes["friendly_name"] = "x" * 10000
        data = weather_action_data(selected, options, [("14:00", "Rainy", "23°C")], "hourly")
        self.assertEqual(len(data), 17)
        self.assertEqual(len(data["location"]), 24)
        self.assertIn("Feels 24°C", data["details"])
        for unavailable in (None, state(condition="unavailable"), state(condition="unknown")):
            cleared = weather_action_data(unavailable, options, [("old", "old", "99")], "hourly")
            self.assertFalse(cleared["available"])
            self.assertEqual(cleared["forecast_1_label"], "")
            self.assertEqual(cleared["temperature"], "")
        options[CONF_WEATHER_ENTITY] = None
        self.assertFalse(weather_action_data(selected, options, [], None)["enabled"])

    def test_malformed_numbers_dates_and_utf8_are_safe(self):
        selected = state()
        selected.attributes["temperature"] = float("nan")
        selected.attributes["wind_speed"] = 10 ** 500
        options = validate_weather({CONF_WEATHER_ENTITY: "weather.selected", CONF_WEATHER_ENABLED: True})
        data = weather_action_data(selected, options, [], None)
        self.assertEqual(data["temperature"], "--")
        self.assertNotIn("Wind", data["details"])
        self.assertEqual(forecast_rows([{}, {"datetime": "bad"}, {"datetime": "2026-10-09"}],
                                      "hourly", "°C", datetime.now(timezone.utc), ZoneInfo("UTC")), [])

    def test_fractional_temperatures_are_short_enough_for_the_display(self):
        options = validate_weather({CONF_WEATHER_ENTITY: "weather.selected", CONF_WEATHER_ENABLED: True})
        selected = state()
        selected.attributes["temperature"] = 23.456789
        self.assertEqual(weather_action_data(selected, options, [], None)["temperature"], "23.5°C")
        now = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)
        rows = forecast_rows([{"datetime": "2026-10-09T12:00:00Z", "temperature": 24.6,
                               "templow": 17.9}], "daily", "°C", now, ZoneInfo("UTC"))
        self.assertEqual(rows[0][2], "18/25°C")

    def test_dual_payload_is_twenty_bounded_fields_and_capability_gated(self):
        options = validate_weather({CONF_WEATHER_ENTITY: "weather.selected", CONF_WEATHER_ENABLED: True})
        modes = {"hourly": [("x" * 100, "Rainy" * 100, "20°C" * 100)],
                 "daily": [("Fri", "Sunny", "18/25°C")]}
        data = weather_forecasts_data(state(), options, modes)
        self.assertEqual(len(data), 20)
        self.assertTrue(data["hourly_supported"])
        self.assertTrue(data["daily_supported"])
        self.assertEqual(len(data["hourly_1_label"]), 10)
        self.assertEqual(len(data["hourly_1_condition"]), 24)
        self.assertEqual(len(data["hourly_1_temperature"]), 20)
        data = weather_forecasts_data(state(features=1), options, modes)
        self.assertFalse(data["hourly_supported"])
        self.assertEqual(data["hourly_1_label"], "")
        self.assertEqual(data["daily_1_label"], "Fri")
        for selected in (None, state(condition="unavailable")):
            cleared = weather_forecasts_data(selected, options, modes)
            self.assertFalse(cleared["daily_supported"])
            self.assertEqual(cleared["daily_1_temperature"], "")
        options[CONF_WEATHER_ENTITY] = None
        self.assertFalse(weather_forecasts_data(state(), options, modes)["daily_supported"])


class WeatherBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.now = 1000
        self.selected = state()
        self.calls = []
        self.gets = []
        self.block = None
        async def call(domain, service, data, **kwargs):
            self.calls.append((domain, service, data, kwargs))
            if domain == "weather":
                if self.block:
                    await self.block.wait()
                future = datetime.now(timezone.utc) + timedelta(hours=1)
                return {"weather.selected": {"forecast": [{"datetime": future.isoformat(),
                                                           "condition": "rainy", "temperature": 20}]}}
        def get(entity):
            self.gets.append(entity)
            return self.selected
        hass = SimpleNamespace(config=SimpleNamespace(time_zone="UTC"),
                               states=SimpleNamespace(get=get), services=SimpleNamespace(async_call=call),
                               async_create_task=asyncio.create_task)
        runtime = SimpleNamespace(stopped=False, transition_lock=asyncio.Lock(),
                                  service_names=SimpleNamespace(update_weather="desk_update_weather"))
        self.bridge = WeatherBridge(hass, runtime, validate_weather({
            CONF_WEATHER_ENTITY: "weather.selected", CONF_WEATHER_ENABLED: True}), lambda: self.now)

    async def asyncTearDown(self):
        await self.bridge.close()

    async def run_update(self):
        self.bridge.schedule()
        await self.bridge.task

    async def test_only_selected_source_and_forecast_fetch_is_throttled(self):
        await self.run_update()
        await self.run_update()
        self.assertEqual(sum(c[0] == "weather" for c in self.calls), 1)
        self.assertEqual(set(self.gets), {"weather.selected"})
        self.assertTrue(all(len(c[2]) == 17 for c in self.calls if c[0] == "esphome"))
        self.now += 900
        await self.run_update()
        self.assertEqual(sum(c[0] == "weather" for c in self.calls), 2)

    async def test_disable_sends_empty_and_makes_no_weather_requests(self):
        self.bridge.options[CONF_WEATHER_ENABLED] = False
        await self.run_update()
        self.assertFalse(self.gets)
        self.assertEqual([c[0] for c in self.calls], ["esphome"])
        self.assertFalse(self.calls[0][2]["enabled"])

    async def test_failure_is_throttled_without_hiding_current_weather(self):
        async def failed_forecast(domain, service, data, **kwargs):
            self.calls.append((domain, service, data, kwargs))
            if domain == "weather":
                raise RuntimeError("provider failed")
        self.bridge.hass.services.async_call = failed_forecast
        await self.run_update()
        await self.run_update()
        self.assertEqual(sum(c[0] == "weather" for c in self.calls), 1)
        sent = [c[2] for c in self.calls if c[0] == "esphome"]
        self.assertTrue(sent[-1]["available"])
        self.assertEqual(sent[-1]["status"], "Forecast unavailable")
        self.assertEqual(sent[-1]["forecast_1_label"], "")

    async def test_unsupported_forecast_never_calls_provider(self):
        self.selected = state(features=0)
        await self.run_update()
        self.assertEqual([c[0] for c in self.calls], ["esphome"])
        self.assertEqual(self.calls[0][2]["status"], "Forecast not supported")

    async def test_transport_waits_for_dashboard_lock(self):
        await self.bridge.runtime.transition_lock.acquire()
        self.bridge.schedule()
        task = self.bridge.task
        await asyncio.sleep(0.3)
        self.assertFalse(any(c[0] == "esphome" for c in self.calls))
        self.bridge.runtime.transition_lock.release()
        await task
        self.assertTrue(any(c[0] == "esphome" for c in self.calls))

    async def test_coalesces_events_and_reads_latest_state_after_fetch(self):
        self.block = asyncio.Event()
        self.bridge.schedule()
        await asyncio.sleep(0.25)
        for _ in range(20):
            self.bridge.schedule()
        self.selected = state(condition="unavailable")
        self.block.set()
        await self.bridge.task
        sent = [c for c in self.calls if c[0] == "esphome"]
        self.assertLessEqual(len(sent), 2)
        self.assertFalse(sent[-1][2]["available"])

    async def test_state_flapping_does_not_bypass_forecast_throttle(self):
        await self.run_update()
        self.selected = state(condition="unavailable")
        await self.run_update()
        self.selected = state()
        await self.run_update()
        self.assertEqual(sum(c[0] == "weather" for c in self.calls), 1)

    async def test_close_cancels_fetch_and_does_not_send_device_action(self):
        self.block = asyncio.Event()
        self.bridge.schedule()
        task = self.bridge.task
        await asyncio.sleep(0.25)
        await self.bridge.close()
        self.assertTrue(task.cancelled())
        self.assertFalse(any(c[0] == "esphome" for c in self.calls))
        self.bridge.schedule()
        self.assertIsNone(self.bridge.task)

    def enable_dual(self):
        self.bridge.dual_service = "desk_update_weather_forecasts"

    async def test_new_firmware_gets_two_modes_once_and_paced_actions(self):
        self.enable_dual()
        await self.run_update()
        await self.run_update()
        requests = [c for c in self.calls if c[0] == "weather"]
        self.assertEqual([c[2]["type"] for c in requests], ["hourly", "daily"])
        self.assertEqual({c[2]["entity_id"] for c in requests}, {"weather.selected"})
        sent = [c for c in self.calls if c[0] == "esphome"]
        self.assertEqual([len(c[2]) for c in sent], [17, 20, 17, 20])
        self.assertTrue(sent[-1][2]["daily_supported"])
        self.now += 900
        await self.run_update()
        self.assertEqual(sum(c[0] == "weather" for c in self.calls), 4)

    async def test_daily_only_does_not_request_hourly_or_invent_it(self):
        self.enable_dual()
        self.selected = state(features=1)
        await self.run_update()
        self.assertEqual([c[2]["type"] for c in self.calls if c[0] == "weather"], ["daily"])
        dual = next(c[2] for c in self.calls if c[1] == self.bridge.dual_service)
        self.assertTrue(dual["daily_supported"])
        self.assertFalse(dual["hourly_supported"])

    async def test_dual_disabled_clears_both_caches_without_fetches(self):
        self.enable_dual()
        await self.run_update()
        self.calls.clear()
        self.bridge.options[CONF_WEATHER_ENABLED] = False
        await self.run_update()
        self.assertEqual([len(c[2]) for c in self.calls], [17, 20])
        self.assertFalse(self.calls[-1][2]["hourly_supported"])
        self.assertFalse(self.calls[-1][2]["daily_supported"])
        self.assertEqual(self.bridge.mode_rows, {})

    async def test_one_mode_failure_does_not_poison_the_other_or_retry_on_tap_refresh(self):
        self.enable_dual()
        original = self.bridge.hass.services.async_call
        async def fails_hourly(domain, service, data, **kwargs):
            if domain == "weather" and data["type"] == "hourly":
                self.calls.append((domain, service, data, kwargs))
                raise RuntimeError("hourly unavailable")
            return await original(domain, service, data, **kwargs)
        self.bridge.hass.services.async_call = fails_hourly
        await self.run_update()
        await self.run_update()
        self.assertEqual(sum(c[0] == "weather" for c in self.calls), 2)
        dual = [c[2] for c in self.calls if c[1] == self.bridge.dual_service][-1]
        self.assertEqual(dual["hourly_1_label"], "")
        self.assertNotEqual(dual["daily_1_label"], "")

    async def test_capability_loss_clears_cached_mode_without_fetching_unsupported(self):
        self.enable_dual()
        await self.run_update()
        self.selected = state(features=1)
        await self.run_update()
        self.assertEqual(sum(c[0] == "weather" for c in self.calls), 2)
        dual = [c[2] for c in self.calls if c[1] == self.bridge.dual_service][-1]
        self.assertFalse(dual["hourly_supported"])
        self.assertTrue(dual["daily_supported"])
        self.assertEqual(dual["hourly_1_temperature"], "")
