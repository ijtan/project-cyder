"""Opt-in printer mapping, conditions, bounded formatting, transport and media."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace as NS
import unittest

from custom_components.cyd_ha_monitor.printer import (
    FIELDS, BAMBU_ROLES, PrinterBridge, bambu_mapping, bambu_printers, field_key,
    printer_entities, printer_visible, printer_action_data, validate_printer, media_url,
)
from custom_components.cyd_ha_monitor.camera_thumbnail import ThumbnailStore, selected_media, STORE_KEY


def state(value, **attrs):
    return NS(state=str(value), attributes=attrs)


def entity(role, device="selected", disabled=None, domain="sensor", name=None):
    return NS(entity_id=f"{domain}.{name or role}", device_id=device, platform="bambu_lab",
              unique_id=f"private_id_{role}", translation_key=role, disabled_by=disabled)


def device(id="selected"):
    return NS(id=id, name="A1", name_by_user=None, model="A1", identifiers={("bambu_lab", "private_id")})


class PrinterTests(unittest.TestCase):
    def setUp(self):
        self.states = {"sensor.status": state("running")}
        self.hass = NS(states=NS(get=self.states.get), config=NS(internal_url="http://ha.local:8123"), data={})
        self.options = validate_printer({"printer_enabled": True, "printer_status_entity": "sensor.status",
            "printer_condition_entity": "sensor.status"})

    def test_disabled_defaults_and_domains_and_conditions(self):
        self.assertFalse(printer_visible(self.hass, validate_printer({})))
        self.assertEqual(printer_entities(validate_printer({})), set())
        for values in ({"printer_status_entity": "camera.bad"}, {"printer_camera_entity": "http://bad"},
                       {"printer_condition_states": ["x" * 100]}, {"printer_condition_states": "running"},
                       {"printer_visibility_override": "toggle"}, {"printer_media_default": "auto"}):
            with self.assertRaises(ValueError):
                validate_printer(values)

    def test_bambu_list_excludes_children_and_other_integration(self):
        entities = [entity("print_status"), entity("humidity", "ams"), entity("print_status", "disabled", "user")]
        unrelated = entity("print_status", "other")
        unrelated.platform = "mqtt"
        entities.append(unrelated)
        self.assertEqual([d.id for d in bambu_printers([device(), device("ams"), device("disabled"), device("other")], entities)], ["selected"])
        with self.assertRaises(ValueError):
            bambu_mapping(device("ams"), entities)

    def test_mapping_renames_suffix_fallback_ambiguity_and_disabled(self):
        entities = [entity("print_status", name="renamed"), entity("bed_temp"),
                    entity("nozzle_temp", disabled="user"), entity("cover_image", domain="image"),
                    entity("camera", domain="camera"), entity("bed_temp", device="other")]
        result = bambu_mapping(device(), entities)
        self.assertEqual(result["printer_status_entity"], "sensor.renamed")
        self.assertEqual(result["printer_render_entity"], "image.cover_image")
        self.assertIsNone(result["printer_nozzle_entity"])
        entities[0].translation_key = None
        self.assertEqual(bambu_mapping(device(), entities)["printer_status_entity"], "sensor.renamed")
        entities.append(entity("bed_temp", name="duplicate"))
        self.assertIsNone(bambu_mapping(device(), entities)["printer_bed_entity"])

    def test_conditions_and_overrides_never_select_missing_source(self):
        self.assertTrue(printer_visible(self.hass, self.options))
        self.states["sensor.status"] = state("finish")
        self.assertFalse(printer_visible(self.hass, self.options))
        self.options["printer_visibility_override"] = "show"
        self.assertTrue(printer_visible(self.hass, self.options))
        self.options["printer_visibility_override"] = "hide"
        self.assertFalse(printer_visible(self.hass, self.options))
        self.options["printer_visibility_override"] = "show"
        self.options["printer_status_entity"] = None
        self.assertFalse(printer_visible(self.hass, self.options))

    def test_only_explicit_selections_are_read_and_hidden_is_clear(self):
        reads = []
        self.hass.states.get = lambda e: (reads.append(e), self.states.get(e))[1]
        self.options["printer_visibility_override"] = "hide"
        data = printer_action_data(self.hass, self.options)
        self.assertFalse(reads)
        self.assertEqual(len(data), 15)
        self.assertFalse(data["visible"])
        self.assertEqual(data["render_url"], "")
        self.options["printer_visibility_override"] = "auto"
        printer_action_data(self.hass, self.options)
        self.assertEqual(set(reads), {"sensor.status"})

    def test_units_elapsed_layers_temperatures_and_utf8_limits(self):
        now = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)
        data = {"start": state("2026-10-09T10:30:00+00:00"), "remaining": state(1.5, unit_of_measurement="h"),
                "layer": state(127), "total_layers": state(640), "bed": state(59.6, unit_of_measurement="°C"),
                "bed_target": state(60), "progress": state(42), "job": state("€" * 500)}
        for role, value in data.items():
            self.options[field_key(role)] = f"sensor.{role}"
            self.states[f"sensor.{role}"] = value
        formatted = printer_action_data(self.hass, self.options, now)
        self.assertEqual(formatted["elapsed"], "1h 30m")
        self.assertEqual(formatted["remaining"], "1h 30m")
        self.assertEqual(formatted["layers"], "127/640")
        self.assertEqual(formatted["bed"], "60/60°C")
        self.assertTrue(formatted["progress_available"])
        self.assertLessEqual(len(formatted["job"].encode()), 48)
        self.assertEqual(formatted["nozzle"], "")
        self.options["printer_end_entity"] = "sensor.end"
        self.states["sensor.end"] = state("2026-10-09T11:00:00Z")
        self.states["sensor.status"] = state("finish")
        self.options["printer_visibility_override"] = "show"
        self.assertEqual(printer_action_data(self.hass, self.options, now)["elapsed"], "30m")

    def test_malformed_and_unavailable_values_are_not_invented(self):
        for role in ("progress", "remaining", "bed", "start"):
            self.options[field_key(role)] = f"sensor.{role}"
            self.states[f"sensor.{role}"] = state("nan")
        data = printer_action_data(self.hass, self.options)
        self.assertFalse(data["progress_available"])
        self.assertEqual(data["remaining"], "--")
        self.assertEqual(data["elapsed"], "--")
        self.assertEqual(data["bed"], "--")
        self.options["printer_visibility_override"] = "show"
        self.states["sensor.status"] = state("unavailable")
        data = printer_action_data(self.hass, self.options)
        self.assertEqual(data["status"], "Unavailable")
        self.assertEqual(data["bed"], "")
        self.assertEqual(data["camera_url"], "")

    def test_local_image_and_camera_token_routes_not_raw_proxies(self):
        self.states["image.render"] = state("2026-10-09", access_token="testtoken")
        self.states["camera.printer"] = state("idle", access_token="testtoken")
        self.assertIn("/printer_image/image.render?token=testtoken", media_url(self.hass, "image.render"))
        self.assertIn("/camera_thumbnail/camera.printer?token=testtoken", media_url(self.hass, "camera.printer"))
        self.hass.config.internal_url = "http://user:password@remote"
        self.assertEqual(media_url(self.hass, "image.render"), "")

    def test_media_authorization_follows_condition_selection_and_firmware(self):
        self.options["printer_render_entity"] = "image.render"
        self.options["printer_camera_entity"] = "camera.printer"
        runtime = NS(stopped=False, printer_options=self.options, dashboard_options={}, service_names=NS(update_printer="desk_update_printer"))
        self.hass.data["cyd_ha_monitor"] = {"selected": runtime}
        self.assertEqual(selected_media(self.hass), {"image.render", "camera.printer"})
        runtime.dashboard_options = {"camera_entity": "camera.ordinary", "show_camera_page": True}
        self.assertEqual(selected_media(self.hass), {"image.render", "camera.printer"})
        runtime.service_names.update_printer = None
        self.assertEqual(selected_media(self.hass), {"camera.ordinary"})
        runtime.service_names.update_printer = "desk_update_printer"
        self.options["printer_visibility_override"] = "hide"
        self.assertEqual(selected_media(self.hass), {"camera.ordinary"})

    def test_old_job_cover_is_rejected_and_full_job_identity_not_truncated(self):
        self.options.update(printer_render_entity="image.render", printer_start_entity="sensor.start", printer_job_entity="sensor.job")
        self.states.update({"sensor.start": state("2026-10-09T12:00:00Z"),
            "image.render": state("2026-10-09T11:00:00Z", access_token="testtoken"),
            "sensor.job": state("x" * 100 + "one")})
        data = printer_action_data(self.hass, self.options)
        self.assertEqual(data["render_url"], "")
        first = data["job_key"]
        self.states["sensor.job"] = state("x" * 100 + "two")
        self.assertNotEqual(printer_action_data(self.hass, self.options)["job_key"], first)
        self.states["image.render"] = state("2026-10-09T12:01:00Z", access_token="testtoken")
        self.assertIn("/printer_image/", printer_action_data(self.hass, self.options)["render_url"])


class PrinterBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.calls = []
        self.states = {"sensor.status": state("running")}
        async def call(domain, service, data, **kwargs):
            self.calls.append((domain, service, data))
        self.hass = NS(states=NS(get=self.states.get), config=NS(internal_url="http://ha.local"),
                       data={}, services=NS(async_call=call), async_create_task=asyncio.create_task)
        self.runtime = NS(stopped=False, transition_lock=asyncio.Lock(), service_names=NS(update_printer="desk_update_printer"))
        self.options = validate_printer({"printer_enabled": True, "printer_status_entity": "sensor.status",
                                        "printer_condition_entity": "sensor.status", "printer_render_entity": "image.render"})
        self.bridge = PrinterBridge(self.hass, self.runtime, self.options)

    async def asyncTearDown(self):
        await self.bridge.close()

    async def test_coalesced_latest_values_wait_for_dashboard_lock(self):
        await self.runtime.transition_lock.acquire()
        self.bridge.schedule()
        await asyncio.sleep(0.25)
        self.assertFalse(self.calls)
        for _ in range(20): self.bridge.schedule()
        self.states["sensor.status"] = state("finish")
        self.runtime.transition_lock.release()
        await self.bridge.task
        self.assertLessEqual(len(self.calls), 2)
        self.assertTrue(all(len(c[2]) == 15 for c in self.calls))
        self.assertFalse(self.calls[-1][2]["visible"])

    async def test_job_change_cancels_old_media_once_and_close_cancels_sender(self):
        invalidated = []
        async def invalidate(entities): invalidated.append(entities)
        async def prune(entities): pass
        self.hass.data[STORE_KEY] = NS(invalidate=invalidate, prune=prune)
        self.bridge.schedule()
        await self.bridge.task
        self.bridge.schedule()
        await self.bridge.task
        self.assertEqual(invalidated, [{"image.render"}])
        self.bridge.schedule()
        task = self.bridge.task
        await self.bridge.close()
        self.assertTrue(task.cancelled())
        self.bridge.schedule()
        self.assertIsNone(self.bridge.task)

    async def test_store_invalidation_drains_old_request_before_new_generation(self):
        block = asyncio.Event()
        async def fetch(entity):
            await block.wait()
            return b"source"
        async def normalize(source): return b"qoif" + source
        now = [100.0]
        store = ThumbnailStore(fetch, normalize, asyncio.create_task, clock=lambda: now[0])
        store.get("image.render")
        old = store.frames["image.render"].task
        await asyncio.sleep(0)
        await store.invalidate({"image.render"})
        self.assertTrue(old.cancelled())
        self.assertIsNone(store.frames["image.render"].body)
        self.assertIsNone(store.get("image.render"))
        self.assertIsNone(store.frames["image.render"].task)
        now[0] += 10
        block.set()
        store.get("image.render")
        await store.frames["image.render"].task
        self.assertEqual(store.get("image.render"), b"qoifsource")
        await store.prune(set())
