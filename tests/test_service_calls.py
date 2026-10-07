"""Tests for fire-and-forget ESPHome service transition calls."""

from __future__ import annotations

import asyncio
import unittest

from custom_components.cyd_ha_monitor import (
    Runtime,
    _schedule_transition,
    async_unload_entry,
)
from custom_components.cyd_ha_monitor.alerts import AlertCommand, RuleEngine
from custom_components.cyd_ha_monitor.const import DOMAIN
from custom_components.cyd_ha_monitor.service_map import service_names


class FakeServices:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    async def async_call(
        self, domain: str, service: str, data: dict[str, object]
    ) -> None:
        self.calls.append((domain, service, data))


class BlockingFirstCallServices(FakeServices):
    def __init__(self) -> None:
        super().__init__()
        self.first_call_started = asyncio.Event()
        self.release_first_call = asyncio.Event()

    async def async_call(
        self, domain: str, service: str, data: dict[str, object]
    ) -> None:
        self.calls.append((domain, service, data))
        if len(self.calls) == 1:
            self.first_call_started.set()
            await self.release_first_call.wait()


class FakeHass:
    def __init__(self, services: FakeServices | None = None) -> None:
        self.services = services or FakeServices()
        self.tasks: list[asyncio.Task[None]] = []
        self.data: dict[str, object] = {}

    def async_create_task(self, coroutine: object) -> asyncio.Task[None]:
        task = asyncio.create_task(coroutine)  # type: ignore[arg-type]
        self.tasks.append(task)
        return task


class ServiceCallTests(unittest.IsolatedAsyncioTestCase):
    async def test_unload_awaits_clear_before_returning(self) -> None:
        services = BlockingFirstCallServices()
        hass = FakeHass(services)
        names = service_names("desk_hass")
        runtime = Runtime(
            RuleEngine([]), names, "Desk HASS", AlertCommand(2, "Warning", "Hot")
        )
        hass.data[DOMAIN] = {"entry": runtime}

        unload = asyncio.create_task(
            async_unload_entry(hass, type("Entry", (), {"entry_id": "entry"})())
        )
        await services.first_call_started.wait()
        self.assertFalse(unload.done())
        self.assertEqual(services.calls[0][1:], (names.clear_alert, {"priority": 2}))

        services.release_first_call.set()
        self.assertTrue(await unload)
        self.assertNotIn(DOMAIN, hass.data)

    async def test_replacement_clears_then_displays_non_dismissible_alert(self) -> None:
        hass = FakeHass()
        names = service_names("living_room_cyd")
        runtime = Runtime(RuleEngine([]), names, "Living Room CYD")
        _schedule_transition(
            hass,
            runtime,
            AlertCommand(3, "Critical", "Old"),
            AlertCommand(2, "Warning", "New"),
        )
        await asyncio.gather(*hass.tasks)

        self.assertEqual(
            hass.services.calls,
            [
                ("esphome", names.clear_alert, {"priority": 3}),
                (
                    "esphome",
                    names.display_alert,
                    {
                        "priority": 2,
                        "title": "Warning",
                        "message": "New",
                        "dismissible": False,
                    },
                ),
            ],
        )

    async def test_new_alert_is_scheduled_without_a_clear(self) -> None:
        hass = FakeHass()
        names = service_names("hallway_cyd")
        runtime = Runtime(RuleEngine([]), names, "Hallway CYD")
        _schedule_transition(hass, runtime, None, AlertCommand(1, "Notice", "Started"))
        await asyncio.gather(*hass.tasks)

        self.assertEqual(len(hass.services.calls), 1)
        self.assertEqual(hass.services.calls[0][0:2], ("esphome", names.display_alert))
        self.assertFalse(hass.services.calls[0][2]["dismissible"])

    async def test_attention_page_routes_on_activation_and_restores_on_clear(self) -> None:
        hass = FakeHass()
        names = service_names("hallway_cyd")
        runtime = Runtime(RuleEngine([]), names, "Hallway CYD")
        attention = AlertCommand(2, "Freezer", "Too warm", "sensors")

        _schedule_transition(hass, runtime, None, attention)
        await asyncio.gather(*hass.tasks)
        _schedule_transition(hass, runtime, attention, None)
        await asyncio.gather(*hass.tasks)

        self.assertEqual(
            [(service, data) for _domain, service, data in hass.services.calls],
            [
                (
                    names.display_alert,
                    {
                        "priority": 2,
                        "title": "Freezer",
                        "message": "Too warm",
                        "dismissible": False,
                    },
                ),
                (names.focus_page, {"page": "sensors"}),
                (names.clear_alert, {"priority": 2}),
                (names.focus_page, {"page": "none"}),
            ],
        )

    async def test_attention_route_replacement_does_not_restore_between_alerts(self) -> None:
        hass = FakeHass()
        names = service_names("hallway_cyd")
        runtime = Runtime(RuleEngine([]), names, "Hallway CYD")
        previous = AlertCommand(2, "Warm", "Too warm", "climate")
        current = AlertCommand(3, "Power", "Power high", "energy")

        _schedule_transition(hass, runtime, previous, current)
        await asyncio.gather(*hass.tasks)

        self.assertEqual(
            [(service, data) for _domain, service, data in hass.services.calls],
            [
                (names.clear_alert, {"priority": 2}),
                (
                    names.display_alert,
                    {
                        "priority": 3,
                        "title": "Power",
                        "message": "Power high",
                        "dismissible": False,
                    },
                ),
                (names.focus_page, {"page": "energy"}),
            ],
        )

    async def test_concurrent_transitions_remain_ordered(self) -> None:
        services = BlockingFirstCallServices()
        hass = FakeHass(services)
        names = service_names("desk_hass")
        runtime = Runtime(RuleEngine([]), names, "Desk HASS")
        _schedule_transition(
            hass,
            runtime,
            AlertCommand(3, "Old", "Critical"),
            AlertCommand(2, "Middle", "Warning"),
        )
        await services.first_call_started.wait()
        _schedule_transition(
            hass,
            runtime,
            AlertCommand(2, "Middle", "Warning"),
            AlertCommand(1, "New", "Notice"),
        )
        await asyncio.sleep(0)
        self.assertEqual(len(services.calls), 1)

        services.release_first_call.set()
        await asyncio.gather(*hass.tasks)
        self.assertEqual(
            [(service, data.get("priority")) for _, service, data in services.calls],
            [
                (names.clear_alert, 3),
                (names.display_alert, 2),
                (names.clear_alert, 2),
                (names.display_alert, 1),
            ],
        )


if __name__ == "__main__":
    unittest.main()
