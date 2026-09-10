import asyncio
from dataclasses import dataclass, field
import time
from typing import Any

from aiohttp import client_exceptions, web
import cv2

from cameras.camera_names import get_camera_index_by_serial, get_camera_index_by_usb_port
from machine_cfg import ConnectionSearchType
from cameras.types import CameraRecordingStates, CameraStatus
from stream_only_config import StreamOnlyConfig
from stream_status_publisher import StreamStatusPublisher



CAPTURE_WIDTH = 1280
CAPTURE_HEIGHT = 720


@dataclass
class StreamOnlyCameraRuntime:
    id: int
    camera_name: str
    camera_serial: str
    hw_port: str
    stream_port: int
    state: CameraStatus = field(default_factory=CameraStatus)
    stream_path: str = "/stream"
    stream_protocol: str = "mjpeg"
    camera_index: int | None = None
    current_frame: Any = None
    frame_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    latest_frame_timestamp_ms: int | None = None
    latest_segment_timestamp_ms: int | None = None
    _capture_fps_estimate: float | None = None
    _last_capture_frame_time: float | None = None

class StreamOnlyService:
    def __init__(self, cfg: StreamOnlyConfig):
        self.cfg = cfg
        self.camera = StreamOnlyCameraRuntime(
            id=cfg.camera_id,
            camera_name=cfg.camera_name,
            camera_serial=cfg.camera_serial,
            hw_port=cfg.camera_hw_port,
            stream_port=cfg.stream_port,
        )
        self.status_publisher = StreamStatusPublisher(cfg, self.camera)

        self.current_device_path = ""
        self.cap: cv2.VideoCapture | None = None
        self._next_restart_allowed_at_ms = 0.0
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._app = web.Application()
        self._app.router.add_get("/stream", self.mjpeg_handler)

    def _defer_restart(self):
        self._next_restart_allowed_at_ms = (time.time() * 1000) + self.cfg.reconnect_delay_ms

    def _ready_for_restart(self) -> bool:
        return (time.time() * 1000) >= self._next_restart_allowed_at_ms

    def _clear_restart_backoff(self):
        self._next_restart_allowed_at_ms = 0.0

    async def start_http_server(self):
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, "0.0.0.0", self.cfg.stream_port)
        await self._site.start()
        print(f"[STREAM_ONLY] MJPEG server available at http://0.0.0.0:{self.cfg.stream_port}{self.camera.stream_path}")

    async def stop_http_server(self):
        if self._site:
            await self._site.stop()
            self._site = None
        if self._runner:
            await self._runner.cleanup()
            self._runner = None

    def _resolve_camera_index(self):
        if self.cfg.connection_search_type == ConnectionSearchType.USB_PORT:
            return get_camera_index_by_usb_port(self.cfg.camera_hw_port, force_refresh=True)
        return get_camera_index_by_serial(self.cfg.camera_serial, force_refresh=True)

    async def _open_capture(self, camera_index: int, device_path: str):
        print(f"[STREAM_ONLY] Opening MJPEG capture for camera {self.cfg.camera_id} from {device_path}")
        cap = cv2.VideoCapture(camera_index)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAPTURE_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAPTURE_HEIGHT)
        cap.set(cv2.CAP_PROP_FPS, float(self.cfg.requested_fps))

        if not cap.isOpened():
            cap.release()
            print(f"[STREAM_ONLY] Failed to open capture device {device_path}")
            self.camera.state.isConnected = False
            self.camera.state.videoDeviceNodeString = "not set - waiting for connection"
            return False

        self.cap = cap
        self.camera.camera_index = camera_index
        self.current_device_path = device_path
        self.camera.state.isConnected = True
        self.camera.state.isStreaming = False
        self.camera.state.videoDeviceNodeString = device_path
        self.camera.state.recordingState = CameraRecordingStates.STOPPED
        async with self.camera.frame_lock:
            self.camera.current_frame = None
        self.camera.latest_frame_timestamp_ms = None
        self.camera.latest_segment_timestamp_ms = None
        self.camera._capture_fps_estimate = None
        self.camera._last_capture_frame_time = None
        self._clear_restart_backoff()
        return True

    async def _close_capture(self, reason: str = ""):
        if reason:
            print(f"[STREAM_ONLY] {reason}")

        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass

        self.cap = None
        self.current_device_path = ""
        self.camera.camera_index = None
        self.camera.state.isConnected = False
        self.camera.state.isStreaming = False
        self.camera.state.recordingState = CameraRecordingStates.STOPPED
        self.camera.state.videoDeviceNodeString = "not set - waiting for connection"
        async with self.camera.frame_lock:
            self.camera.current_frame = None
        self.camera.latest_frame_timestamp_ms = None
        self.camera.latest_segment_timestamp_ms = None
        self.camera._capture_fps_estimate = None
        self.camera._last_capture_frame_time = None

    def _update_capture_fps_estimate(self):
        now = time.perf_counter()
        if self.camera._last_capture_frame_time is not None:
            elapsed = now - self.camera._last_capture_frame_time
            if elapsed > 0:
                instantaneous_fps = 1.0 / elapsed
                if self.camera._capture_fps_estimate is None:
                    self.camera._capture_fps_estimate = instantaneous_fps
                else:
                    self.camera._capture_fps_estimate = (
                        (self.camera._capture_fps_estimate * 0.9) + (instantaneous_fps * 0.1)
                    )
        self.camera._last_capture_frame_time = now

    async def mjpeg_handler(self, request: web.Request) -> web.StreamResponse:
        if not self.camera.state.isConnected or self.cap is None:
            return web.Response(status=503, text="Camera not connected")

        if not self.camera.state.isStreaming:
            return web.Response(status=503, text="Streaming not enabled")

        response = web.StreamResponse(
            status=200,
            reason="OK",
            headers={
                "Content-Type": "multipart/x-mixed-replace; boundary=frame",
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            },
        )
        await response.prepare(request)

        try:
            while self.camera.state.isStreaming and self.camera.state.isConnected:
                async with self.camera.frame_lock:
                    frame = self.camera.current_frame.copy() if self.camera.current_frame is not None else None

                if frame is None:
                    await asyncio.sleep(0.01)
                    continue

                ok, jpeg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                if not ok:
                    await asyncio.sleep(0.01)
                    continue

                try:
                    await response.write(b"--frame\r\n")
                    await response.write(b"Content-Type: image/jpeg\r\n\r\n")
                    await response.write(jpeg.tobytes())
                    await response.write(b"\r\n")
                except (client_exceptions.ClientConnectionResetError, BrokenPipeError):
                    break
                except Exception as exc:
                    print(f"[STREAM_ONLY] MJPEG client write failed for camera {self.cfg.camera_id}: {exc}")
                    break

                await asyncio.sleep(max(0.0, 1.0 / max(self.cfg.requested_fps, 1)))
        finally:
            try:
                await response.write_eof()
            except Exception:
                pass

        return response

    def _clear_frame_timestamp(self):
        if self.camera.state.isStreaming:
            return

        self.camera.latest_frame_timestamp_ms = None
        self.camera.latest_segment_timestamp_ms = None

    async def monitor_camera(self):
        print(
            f"[STREAM_ONLY] Monitoring camera {self.cfg.camera_id} "
            f"at {CAPTURE_WIDTH}x{CAPTURE_HEIGHT} @ {self.cfg.requested_fps} FPS "
            f"on stream port {self.cfg.stream_port}"
        )

        while True:
            resolved_camera_index = self._resolve_camera_index()
            is_plugged_in = resolved_camera_index is not None
            resolved_device_path = f"/dev/video{resolved_camera_index}" if resolved_camera_index is not None else ""

            if is_plugged_in != self.camera.state.isPluggedIn:
                status = "plugged in" if is_plugged_in else "unplugged"
                print(
                    f"[STREAM_ONLY] Camera {self.cfg.camera_name} "
                    f"({self.cfg.connection_search_type.value}="
                    f"{self.cfg.camera_hw_port if self.cfg.connection_search_type == ConnectionSearchType.USB_PORT else self.cfg.camera_serial}) {status}"
                )

            self.camera.state.isPluggedIn = is_plugged_in

            if not is_plugged_in:
                if self.cap is not None:
                    await self._close_capture(
                        f"Camera {self.cfg.camera_name} unplugged; stopping MJPEG capture"
                    )
                    self._defer_restart()
                self._clear_frame_timestamp()
                await asyncio.sleep(self.cfg.poll_period_ms / 1000)
                continue

            if self.cap is not None and self.current_device_path and resolved_device_path != self.current_device_path:
                await self._close_capture(
                    f"Camera {self.cfg.camera_name} moved from {self.current_device_path} to {resolved_device_path}; restarting MJPEG capture"
                )
                self._defer_restart()

            if is_plugged_in and self.cap is None and self._ready_for_restart():
                opened = await self._open_capture(resolved_camera_index, resolved_device_path)
                if not opened:
                    self._defer_restart()
                    await asyncio.sleep(self.cfg.poll_period_ms / 1000)
                    continue

            if self.cap is None:
                self.camera.state.isConnected = False
                self.camera.state.isStreaming = False
                self._clear_frame_timestamp()
                await asyncio.sleep(self.cfg.poll_period_ms / 1000)
                continue

            try:
                read_ok, frame = self.cap.read()
            except Exception as exc:
                await self._close_capture(
                    f"Camera {self.cfg.camera_name} read exception; restarting MJPEG capture: {exc}"
                )
                self._defer_restart()
                await asyncio.sleep(self.cfg.poll_period_ms / 1000)
                continue

            if not read_ok:
                await self._close_capture(
                    f"Camera {self.cfg.camera_name} failed to read frame; restarting MJPEG capture"
                )
                self._defer_restart()
                await asyncio.sleep(self.cfg.poll_period_ms / 1000)
                continue

            self._update_capture_fps_estimate()
            frame_timestamp_ms = int(time.time() * 1000)
            async with self.camera.frame_lock:
                self.camera.current_frame = frame.copy()
            self.camera.latest_frame_timestamp_ms = frame_timestamp_ms
            self.camera.latest_segment_timestamp_ms = frame_timestamp_ms
            self.camera.state.isConnected = True
            self.camera.state.isStreaming = bool(self.cfg.auto_stream and self.camera.current_frame is not None)
            self.camera.state.recordingState = CameraRecordingStates.STOPPED

            await asyncio.sleep(0)

    async def run(self):
        self.status_publisher.start()
        await self.start_http_server()

        monitor_task = asyncio.create_task(self.monitor_camera())
        publisher_task = asyncio.create_task(self.status_publisher.run())

        try:
            await asyncio.gather(monitor_task, publisher_task)
        finally:
            await self._close_capture(f"Stopping MJPEG capture for camera {self.cfg.camera_id}")
            if self.status_publisher.mqtt_is_connected:
                self.status_publisher.publish_status()
            await self.stop_http_server()
            self.status_publisher.stop()