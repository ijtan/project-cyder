"""Bounded codec and asynchronous camera cache regressions (no live cameras)."""
import asyncio
from io import BytesIO
import random
import unittest
from unittest.mock import patch

from PIL import Image

from custom_components.cyd_ha_monitor.camera_thumbnail import (
    WIDTH, HEIGHT, MAX_QOI_BYTES, MAX_SOURCE_BYTES, MAX_FRAME_AGE,
    ThumbnailStore, encode_rgb_qoi, normalize_thumbnail,
)


class CodecTests(unittest.TestCase):
    def test_qoi_roundtrip_black_runs_white_and_noisy_colour(self):
        noise = random.Random(7).randbytes(WIDTH * HEIGHT * 3)
        for raw in (bytes(WIDTH * HEIGHT * 3), b"\xff" * (WIDTH * HEIGHT * 3), noise):
            body = encode_rgb_qoi(raw, WIDTH, HEIGHT)
            self.assertLessEqual(len(body), MAX_QOI_BYTES)
            with Image.open(BytesIO(body)) as image:
                self.assertEqual(image.size, (WIDTH, HEIGHT))
                self.assertEqual(image.convert("RGB").tobytes(), raw)

    def test_normalizes_baseline_progressive_jpeg_png_and_portrait(self):
        for fmt, size, kwargs in (("JPEG", (1920, 1080), {}),
                                  ("JPEG", (640, 480), {"progressive": True}),
                                  ("PNG", (480, 640), {})):
            source = BytesIO()
            Image.new("RGB", size, (200, 40, 90)).save(source, format=fmt, **kwargs)
            body = normalize_thumbnail(source.getvalue())
            with Image.open(BytesIO(body)) as image:
                self.assertEqual(image.size, (WIDTH, HEIGHT))
                self.assertLessEqual(abs(image.getpixel((WIDTH // 2, HEIGHT // 2))[0] - 200), 4)
            self.assertLessEqual(len(body), MAX_QOI_BYTES)

    def test_rejects_bad_or_oversized_sources_and_dimensions(self):
        for source in (b"", b"not an image", b"x" * (MAX_SOURCE_BYTES + 1)):
            with self.assertRaises((ValueError, OSError)):
                normalize_thumbnail(source)
        source = BytesIO()
        Image.new("RGB", (4000, 4000)).save(source, format="PNG")
        with self.assertRaises(ValueError):
            normalize_thumbnail(source.getvalue())
        for width, height, pixels in ((129, 72, b""), (0, 72, b""), (128, 72, b"short")):
            with self.assertRaises(ValueError):
                encode_rgb_qoi(pixels, width, height)


class CacheTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.now = 100.0
        self.ready = asyncio.Event()
        self.calls = []
        async def fetch(entity):
            self.calls.append(entity)
            await self.ready.wait()
            return b"source"
        async def normalize(source):
            self.assertEqual(source, b"source")
            return encode_rgb_qoi(bytes(WIDTH * HEIGHT * 3), WIDTH, HEIGHT)
        self.store = ThumbnailStore(fetch, normalize, asyncio.create_task, lambda: self.now)

    async def asyncTearDown(self):
        await self.store.prune(set())

    async def test_http_path_returns_immediately_and_coalesces_to_one_fetch(self):
        self.assertIsNone(self.store.get("camera.one"))
        for _ in range(10):
            self.assertIsNone(self.store.get("camera.one"))
        self.assertIsNone(self.store.get("camera.two"))
        await asyncio.sleep(0)
        self.assertEqual(self.calls, ["camera.one"])
        self.ready.set()
        await self.store.frames["camera.one"].task
        self.assertTrue(self.store.get("camera.one").startswith(b"qoif"))
        self.assertEqual(self.calls, ["camera.one"])

    async def test_limits_cache_and_never_serves_expired_frames(self):
        self.ready.set()
        for index in range(6):
            entity = f"camera.{index}"
            self.store.get(entity)
            await self.store.frames[entity].task
        self.assertEqual(len(self.store.frames), 4)
        self.now += MAX_FRAME_AGE + 1
        self.ready.clear()
        self.assertIsNone(self.store.get("camera.5"))

    async def test_unload_cancels_pending_work_and_drops_cached_images(self):
        self.store.get("camera.one")
        task = self.store.frames["camera.one"].task
        await asyncio.sleep(0)
        await self.store.prune(set())
        self.assertTrue(task.cancelled())
        self.assertFalse(self.store.frames)

    async def test_camera_failure_is_throttled_and_never_logs_credentials(self):
        async def fail(_entity):
            raise RuntimeError("secret-token camera URL password")
        self.store.fetch = fail
        with self.assertLogs("custom_components.cyd_ha_monitor.camera_thumbnail", level="WARNING") as logs:
            self.store.get("camera.one")
            await self.store.frames["camera.one"].task
        self.assertNotIn("secret-token", str(logs.output))
        self.assertIsNone(self.store.get("camera.one"))
        self.assertIsNone(self.store.frames["camera.one"].task)
