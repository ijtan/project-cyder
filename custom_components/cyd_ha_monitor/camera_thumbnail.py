"""Bounded colour thumbnails; expensive camera work stays off the CYD and HTTP path."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from io import BytesIO
import logging
import struct
import time
from typing import Any, Awaitable, Callable

from .const import CONF_CAMERA_ENTITY, CONF_SHOW_CAMERA_PAGE, DOMAIN

WIDTH = 128
HEIGHT = 72
MAX_QOI_BYTES = WIDTH * HEIGHT * 4 + 22
MAX_SOURCE_BYTES = 4 * 1024 * 1024
MAX_SOURCE_PIXELS = 12_000_000
MIN_FETCH_INTERVAL = 10.0
MAX_FRAME_AGE = 60.0
MAX_CACHE_ENTRIES = 4
STORE_KEY = f"{DOMAIN}_camera_thumbnails"
ROUTE = f"/api/{DOMAIN}/camera_thumbnail"
_LOGGER = logging.getLogger(__name__)


def encode_rgb_qoi(pixels: bytes, width: int, height: int) -> bytes:
    """Small standard QOI encoder using only RGB and RUN opcodes (no dependency).

    Worst case is four bytes/pixel plus 22 bytes. The decoder can stream this;
    unlike JPEG it never needs the whole response buffered on the device.
    """
    if not (0 < width <= WIDTH and 0 < height <= HEIGHT) or len(pixels) != width * height * 3:
        raise ValueError("Invalid thumbnail dimensions")
    output = bytearray(b"qoif" + struct.pack(">IIBB", width, height, 3, 0))
    previous = b"\x00\x00\x00"
    run = 0
    for offset in range(0, len(pixels), 3):
        pixel = pixels[offset:offset + 3]
        if pixel == previous:
            run += 1
            if run == 62:
                output.append(0xC0 | (run - 1))
                run = 0
            continue
        if run:
            output.append(0xC0 | (run - 1))
            run = 0
        output.append(0xFE)
        output.extend(pixel)
        previous = pixel
    if run:
        output.append(0xC0 | (run - 1))
    output.extend(b"\x00" * 7 + b"\x01")
    if len(output) > MAX_QOI_BYTES:
        raise ValueError("Thumbnail exceeds byte budget")
    return bytes(output)


def normalize_thumbnail(source: bytes) -> bytes:
    """Decode on HA, preserve aspect ratio, letterbox and emit bounded 128x72 QOI."""
    from PIL import Image, ImageOps

    if not source or len(source) > MAX_SOURCE_BYTES:
        raise ValueError("Snapshot exceeds source-byte limit")
    with Image.open(BytesIO(source)) as original:
        if original.width * original.height > MAX_SOURCE_PIXELS:
            raise ValueError("Snapshot exceeds source-pixel limit")
        # JPEG draft downsampling avoids a full-resolution decode when supported.
        original.draft("RGB", (WIDTH * 2, HEIGHT * 2))
        upright = ImageOps.exif_transpose(original)
        thumbnail = upright.convert("RGB")
        thumbnail.thumbnail((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
        canvas.paste(thumbnail, ((WIDTH - thumbnail.width) // 2, (HEIGHT - thumbnail.height) // 2))
        return encode_rgb_qoi(canvas.tobytes(), WIDTH, HEIGHT)


@dataclass
class _Frame:
    body: bytes | None = None
    generated: float = 0
    attempted: float = float("-inf")
    task: asyncio.Task | None = None


class ThumbnailStore:
    """At most one camera acquisition at a time, four bounded cached thumbnails."""

    def __init__(self, fetch: Callable[[str], Awaitable[bytes]],
                 normalize: Callable[[bytes], Awaitable[bytes]],
                 create_task: Callable[[Awaitable], asyncio.Task],
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.fetch = fetch
        self.normalize = normalize
        self.create_task = create_task
        self.clock = clock
        self.frames: OrderedDict[str, _Frame] = OrderedDict()

    def get(self, entity_id: str) -> bytes | None:
        now = self.clock()
        frame = self.frames.get(entity_id)
        if frame is None:
            if len(self.frames) >= MAX_CACHE_ENTRIES:
                victim = next((key for key, item in self.frames.items() if item.task is None), None)
                if victim is None:
                    return None
                self.frames.pop(victim)
            frame = self.frames[entity_id] = _Frame()
        self.frames.move_to_end(entity_id)
        if (frame.task is None and now - frame.attempted >= MIN_FETCH_INTERVAL
                and not any(item.task is not None for item in self.frames.values())):
            frame.attempted = now
            frame.task = self.create_task(self._refresh(entity_id, frame))
            # HA may eagerly run a coroutine whose awaits all finish immediately.
            if frame.task.done():
                frame.task = None
        if frame.body is not None and now - frame.generated <= MAX_FRAME_AGE:
            return frame.body
        return None

    async def _refresh(self, entity_id: str, frame: _Frame) -> None:
        try:
            async with asyncio.timeout(20):
                source = await self.fetch(entity_id)
                body = await self.normalize(source)
            if len(body) > MAX_QOI_BYTES or not body.startswith(b"qoif"):
                raise ValueError("Invalid normalized thumbnail")
            frame.body = body
            frame.generated = self.clock()
        except asyncio.CancelledError:
            raise
        except Exception as err:
            # Exceptions from cameras may contain credentials: never log the message.
            _LOGGER.warning("Camera thumbnail unavailable (%s)", type(err).__name__)
        finally:
            frame.attempted = self.clock()
            frame.task = None

    async def prune(self, selected: set[str]) -> None:
        tasks = []
        for key in list(self.frames):
            if key not in selected:
                frame = self.frames.pop(key)
                if frame.task is not None:
                    frame.task.cancel()
                    tasks.append(frame.task)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


def selected_cameras(hass: Any) -> set[str]:
    return {
        runtime.dashboard_options[CONF_CAMERA_ENTITY]
        for runtime in hass.data.get(DOMAIN, {}).values()
        if not runtime.stopped
        and runtime.dashboard_options.get(CONF_SHOW_CAMERA_PAGE)
        and isinstance(runtime.dashboard_options.get(CONF_CAMERA_ENTITY), str)
    }


async def async_setup_thumbnails(hass: Any) -> None:
    from aiohttp import web
    from homeassistant.components.camera import CameraImageView, async_get_image
    from homeassistant.components.camera.const import DATA_COMPONENT
    from homeassistant.const import EVENT_HOMEASSISTANT_STOP

    async def fetch(entity_id: str) -> bytes:
        # Do our own magic-byte decoding and strict resizing. Passing dimensions
        # here could invoke HA's MIME-dependent JPEG scaler before normalization
        # (some integrations mislabel PNG bytes as image/jpeg).
        image = await async_get_image(hass, entity_id, timeout=18)
        return image.content

    async def normalize(source: bytes) -> bytes:
        return await hass.async_add_executor_job(normalize_thumbnail, source)

    store = ThumbnailStore(fetch, normalize,
                           lambda job: hass.async_create_background_task(job, "Cydex camera thumbnail"))
    hass.data[STORE_KEY] = store

    class ThumbnailView(CameraImageView):
        # Inherit native camera authentication (logged-in HA or rotating camera
        # access token), camera lookup and off-state handling. No new credential.
        url = ROUTE + "/{entity_id}"
        name = f"api:{DOMAIN}:camera_thumbnail"

        async def handle(self, request: Any, camera: Any) -> Any:
            if camera.entity_id not in selected_cameras(hass):
                raise web.HTTPNotFound
            body = store.get(camera.entity_id)
            headers = {"Cache-Control": "no-store"}
            if body is None:
                # Never wait for a cloud/RTSP snapshot in the CYD HTTP request.
                return web.Response(status=503, headers={**headers, "Retry-After": "10"})
            return web.Response(body=body, content_type="image/qoi", headers=headers)

    hass.http.register_view(ThumbnailView(hass.data[DATA_COMPONENT]))

    async def stop(_event: Any) -> None:
        await store.prune(set())

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop)
