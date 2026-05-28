#!/usr/bin/env python3
"""
camera_service.py

Combined single-file camera service:
- captures from a camera via OpenCV
- serves an MJPEG stream at /stream
- records video to disk in a background thread via a bounded queue
- supports keyboard controls for local testing
- provides diagnostic logging
"""

import asyncio
from datetime import datetime
from enum import IntEnum
import threading
import time
import sys
import select
import termios
import tty
import queue
from aiohttp import web, client_exceptions
import cv2
import os
from typing import Optional
from dataclasses import dataclass
from cameras.camera_names import get_camera_index_by_serial
from cameras.types import *
import subprocess
# -----------------------
# Configuration
# -----------------------
CAMERA_INDEX = 2                    # camera device index (v4l2 / Windows device number)

REQUESTED_FPS = 30.0
CAPTURE_WIDTH = 1920
CAPTURE_HEIGHT = 1080

# Recording settings
RECORD_FOURCC = cv2.VideoWriter_fourcc(*"mp4v")
#RECORD_FOURCC = cv2.VideoWriter_fourcc(*'x264')   # If libx264 is built into OpenCV
#RECORD_FOURCC = cv2.VideoWriter_fourcc(*'avc1') 
REC_QUEUE_MAXSIZE = 12              # bounded queue for frames to record (drop when full)
RECORDINGS_DIR = "/opt/recordings"
TEMP_RECORDING_DIR = os.path.join(RECORDINGS_DIR, "temp")
# Streaming settings (lighter than recording)
STREAM_TARGET_WIDTH = 1280
STREAM_JPEG_QUALITY = 60            # 0-100
STREAM_FPS = 20.0                   # target FPS for MJPEG streaming (lower than capture)

# Server
STREAM_PORT = 8000

# Diagnostic interval (s)
DIAG_INTERVAL = 1.0
RECORD_WORKER_WAIT_LOG_INTERVAL_MS = 5000
FFMPEG_CONVERSION_TIMEOUT_SECONDS = 120
FFMPEG_CONVERSION_PRESET = "ultrafast"



# -----------------------
# CameraDevice class
# -----------------------
class CameraDevice:
    def __init__(self, id: int, camera_name: str, camera_serial: int, stream_port: int, auto_connect: bool = False, auto_start_stream: bool = False):
        self.id = id
        self.camera_index = 0
        self.camera_name = camera_name
        self.camera_serial = camera_serial
        self.stream_port = stream_port
        self.auto_connect = auto_connect
        self.auto_start_stream = auto_start_stream

        self.temp_filename = TEMP_RECORDING_DIR + f"/live_recording_cam{self.id}.mp4"
        self.temp_stopped_filename = TEMP_RECORDING_DIR + f"/stopped_recording_cam{self.id}.mp4"
        self.save_filename = "unspecified_filename.mp4"
     

        self.state_callback = None

        # OpenCV capture & writer
        self.cap: Optional[cv2.VideoCapture] = None

        # State flags
        self.state = CameraStatus()
        self.state.isConnected = False
        self.state.recordingState = CameraRecordingStates.STOPPED
        self.state.isStreaming = False 
        self.state.videoDeviceNodeString = "not set - waiting for connection"


        # Shared frame buffer & lock
        self.current_frame = None
        self.frame_lock = asyncio.Lock()

        # Commands (used by keyboard or external control)
        self.start_recording_command = False
        self.stop_recording_command = False
        self.stop_and_save_recording_command = False
        self.start_streaming_command = False
        self.stop_streaming_command = False
        self.connect_command = False
        self.disconnect_command = False

        self.save_requested = False
        self._record_session_id = 0
        self._active_record_session_id = 0

        # Recording queue & worker
        self.rec_queue: "queue.Queue" = queue.Queue(maxsize=REC_QUEUE_MAXSIZE)
        self._rec_thread: Optional[threading.Thread] = None
        self._rec_running = threading.Event()
        self._recording_filename = None
        self._rec_worker_done = threading.Event()
        self._rec_worker_done.set()
        self._rec_worker_last_error: Optional[str] = None
        self._rec_worker_save_success: Optional[bool] = None
        self._rec_worker_last_join_timed_out = False
        self._rec_stop_requested = False
        self._rec_stop_requested_at_ms = 0.0
        self._last_rec_wait_log_ms = 0.0
        self._active_ffmpeg_log_path: Optional[str] = None
        self._last_ffmpeg_progress_line = ""

        # Stats
        self.stats = {
            "captured": 0,
            "stream_sent": 0,
            "record_written": 0,
            "dropped_for_rec": 0,
            "last_diag": time.time(),
        }

        # aiohttp app
        self.app = web.Application()
        self.app.router.add_get("/stream", self.mjpeg_handler)
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None

        # internal control
        self._run_loop_task: Optional[asyncio.Task] = None
        self._logging_task: Optional[asyncio.Task] = None

        self.print_header = f"[cam_{self.camera_name}]"

        print(f"{self.print_header} Initialized CameraDevice with id {self.id}, serial {self.camera_serial}")


    def updateState(self):
        if self.state_callback:
            self.state_callback(self.id, self.state)

    def _clear_record_queue(self):
        while True:
            try:
                self.rec_queue.get_nowait()
            except queue.Empty:
                return

    def _cleanup_finished_record_worker(self):
        if self._rec_thread and not self._rec_thread.is_alive():
            self._rec_thread = None

    def is_record_worker_active(self) -> bool:
        self._cleanup_finished_record_worker()
        return self._rec_thread is not None

    def is_record_worker_done(self) -> bool:
        return self._rec_worker_done.is_set() and not self.is_record_worker_active()

    def request_record_worker_stop(self):
        if not self._rec_stop_requested:
            self._rec_stop_requested = True
            self._rec_stop_requested_at_ms = time.time() * 1000
            self._last_rec_wait_log_ms = 0.0
            print(
                f"{self.print_header} Stop signal sent to record worker session {self._active_record_session_id} "
                f"(save_requested={self.save_requested}, queue={self.rec_queue.qsize()})"
            )
        self._rec_running.clear()

    def poll_record_worker_stop(self) -> bool:
        self._cleanup_finished_record_worker()
        if self._rec_thread is None:
            if self._rec_stop_requested:
                elapsed_ms = int((time.time() * 1000) - self._rec_stop_requested_at_ms)
                print(
                    f"{self.print_header} Record worker session {self._active_record_session_id} exited "
                    f"after {elapsed_ms} ms"
                )
                self._rec_stop_requested = False
                self._last_rec_wait_log_ms = 0.0
            return self._rec_worker_done.is_set()

        now_ms = time.time() * 1000
        if now_ms - self._last_rec_wait_log_ms >= RECORD_WORKER_WAIT_LOG_INTERVAL_MS:
            elapsed_ms = int(now_ms - self._rec_stop_requested_at_ms) if self._rec_stop_requested_at_ms else 0
            print(
                f"{self.print_header} Record worker session {self._active_record_session_id} still finalizing "
                f"after {elapsed_ms} ms (save_requested={self.save_requested}, queue={self.rec_queue.qsize()})"
            )
            if self.save_requested:
                progress_line = self._get_ffmpeg_progress_line()
                if progress_line and progress_line != self._last_ffmpeg_progress_line:
                    print(
                        f"{self.print_header} FFmpeg progress for session {self._active_record_session_id}: "
                        f"{progress_line}"
                    )
                    self._last_ffmpeg_progress_line = progress_line
            self._last_rec_wait_log_ms = now_ms
        return False

    def _resolve_unique_save_filename(self, filename: str) -> str:
        if not os.path.exists(filename):
            return filename

        directory, basename = os.path.split(filename)
        stem, extension = os.path.splitext(basename)
        tube_prefix = stem.split("_")[0]

        while True:
            refreshed_timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            candidate = os.path.join(
                directory,
                f"{tube_prefix}_{refreshed_timestamp}{extension}",
            )

            if not os.path.exists(candidate):
                print(
                    f"{self.print_header} Save target exists, using refreshed timestamp: {candidate}",
                )
                return candidate

    def _read_ffmpeg_log(self, log_path: str) -> str:
        if not os.path.exists(log_path):
            return ""
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as handle:
                return handle.read().replace("\r", "\n").strip()
        except Exception as exc:
            return f"failed to read ffmpeg log {log_path}: {exc}"

    def _get_ffmpeg_progress_line(self) -> str:
        if not self._active_ffmpeg_log_path:
            return ""
        ffmpeg_log = self._read_ffmpeg_log(self._active_ffmpeg_log_path)
        if not ffmpeg_log or ffmpeg_log.startswith("failed to read ffmpeg log"):
            return ffmpeg_log
        for line in reversed(ffmpeg_log.splitlines()):
            stripped = line.strip()
            if stripped.startswith("frame="):
                return stripped
        return ""

    # -----------------------
    # Capture & device control
    # -----------------------


    async def open_capture(self):
        """Open the camera device and apply requested settings."""
        try:
            # Use V4L2 backend on Linux if available for better behavior:
            # self.cap = cv2.VideoCapture(self.camera_index, cv2.CAP_V4L2)
            self.cap = cv2.VideoCapture(self.camera_index)
            # Try to set MJPG first (reduces CPU usage)
            fourcc_mjpg = cv2.VideoWriter_fourcc(*"MJPG")
            self.cap.set(cv2.CAP_PROP_FOURCC, fourcc_mjpg)
            # Set resolution and fps
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAPTURE_WIDTH)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAPTURE_HEIGHT)
            self.cap.set(cv2.CAP_PROP_FPS, REQUESTED_FPS)

            # Validate
            if not self.cap.isOpened():
                print(f"{self.print_header} Failed to open capture device {self.camera_index}")
                if self.cap:
                    self.cap.release()
                self.cap = None
                self.state.isConnected = False
                return False

            # Report actual settings
            actual_fps = self.cap.get(cv2.CAP_PROP_FPS)
            actual_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            print(f"{self.print_header} Opened. Actual resolution: {actual_w}x{actual_h} @ {actual_fps} FPS (requested {REQUESTED_FPS})")
            self.state.videoDeviceNodeString = f"/dev/video{self.camera_index}"
            self.state.isConnected = True
            print(f"{self.print_header} Camera connected: {self.state.videoDeviceNodeString}")
            return True

        except Exception as e:
            print(f"{self.print_header} Exception while opening capture: {e}")
            if self.cap:
                self.cap.release()
                self.cap = None
            self.state.isConnected = False
            self.state.videoDeviceNodeString = "not set - waiting for connection"
            return False

    async def close_capture(self):
        """Close capture and cleanup."""
        print(f"{self.print_header} Closing camera capture.")
        self.state.isConnected = False
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None

    # -----------------------
    # Recording worker (thread)
    # -----------------------
    def _rec_worker(self, session_id, filename, fourcc, fps, frame_size):
        """Background thread: consume frames from rec_queue and write via VideoWriter."""

        try:
            self._rec_worker_last_error = None
            self._rec_worker_save_success = None
            writer = cv2.VideoWriter(filename, fourcc, fps, frame_size)
            if not writer.isOpened():
                self._rec_worker_last_error = f"VideoWriter failed to open {filename}"
                print(f"{self.print_header} Record worker session {session_id}: {self._rec_worker_last_error}")
                return
            print(
                f"{self.print_header} Record worker session {session_id} started "
                f"(writing to {filename}, queue={self.rec_queue.qsize()})"
            )
            while self._rec_running.is_set() or not self.rec_queue.empty():
                try:
                    frame = self.rec_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                try:
                    writer.write(frame)
                    self.stats["record_written"] += 1
                except Exception as e:
                    print(f"{self.print_header} Error writing frame in record worker: {e}")
            print(
                f"{self.print_header} Record worker session {session_id} is stopping "
                f"(save_requested={self.save_requested}, queue={self.rec_queue.qsize()}, "
                f"frames_written={self.stats['record_written']})"
            )
            writer.release()
            if self.save_requested:
                converted = self._resolve_unique_save_filename(self.save_filename)
                source_exists = os.path.exists(filename)
                source_size = os.path.getsize(filename) if source_exists else 0
                print(
                    f"{self.print_header} Converting to browser-friendly codec and saving as: {converted} "
                    f"(source={filename}, exists={source_exists}, size={source_size} bytes, "
                    f"preset={FFMPEG_CONVERSION_PRESET}, timeout={FFMPEG_CONVERSION_TIMEOUT_SECONDS}s)"
                )

                ffmpeg_command = [
                    'ffmpeg', '-nostdin', '-y', '-i', filename,
                    '-c:v', 'libx264', '-preset', FFMPEG_CONVERSION_PRESET, '-crf', '23',
                    '-movflags', '+faststart',
                    converted
                ]
                ffmpeg_started_at = time.time()
                ffmpeg_log_path = os.path.join(
                    TEMP_RECORDING_DIR,
                    f"ffmpeg_cam{self.id}_session{session_id}.log",
                )
                self._active_ffmpeg_log_path = ffmpeg_log_path
                try:
                    with open(ffmpeg_log_path, "w", encoding="utf-8") as ffmpeg_log_file:
                        process = subprocess.Popen(
                            ffmpeg_command,
                            stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL,
                            stderr=ffmpeg_log_file,
                            text=True,
                        )
                        try:
                            return_code = process.wait(timeout=FFMPEG_CONVERSION_TIMEOUT_SECONDS)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
                            elapsed_seconds = time.time() - ffmpeg_started_at
                            stderr_output = self._read_ffmpeg_log(ffmpeg_log_path)
                            self._rec_worker_save_success = False
                            self._rec_worker_last_error = (
                                f"FFmpeg conversion timed out after {elapsed_seconds:.1f}s for file {converted}: "
                                f"{stderr_output or 'no ffmpeg log output'}"
                            )
                            print(f"{self.print_header} {self._rec_worker_last_error}")
                            if os.path.exists(filename):
                                print(
                                    f"{self.print_header} Preserving temp recording after timed out conversion: "
                                    f"{filename} ({os.path.getsize(filename)} bytes)"
                                )
                            return
                except Exception as exc:
                    elapsed_seconds = time.time() - ffmpeg_started_at
                    self._rec_worker_save_success = False
                    self._rec_worker_last_error = (
                        f"FFmpeg conversion process failed after {elapsed_seconds:.1f}s for file {converted}: "
                        f"{exc}"
                    )
                    print(f"{self.print_header} {self._rec_worker_last_error}")
                    if os.path.exists(filename):
                        print(
                            f"{self.print_header} Preserving temp recording after failed conversion launch: "
                            f"{filename} ({os.path.getsize(filename)} bytes)"
                        )
                    return

                stderr_output = self._read_ffmpeg_log(ffmpeg_log_path)

                if return_code != 0:
                    self._rec_worker_save_success = False
                    self._rec_worker_last_error = (
                        f"FFmpeg conversion failed for file {converted}: "
                        f"{stderr_output or 'no ffmpeg log output'}"
                    )
                    print(f"{self.print_header} {self._rec_worker_last_error}")
                    if os.path.exists(filename):
                        print(
                            f"{self.print_header} Preserving temp recording after failed conversion: "
                            f"{filename} ({os.path.getsize(filename)} bytes)"
                        )
                else:
                    elapsed_seconds = time.time() - ffmpeg_started_at
                    self._rec_worker_save_success = True
                    print(f"{self.print_header} FFmpeg conversion succeeded in {elapsed_seconds:.1f}s")
                    print(f"{self.print_header} File saved at: {converted}")
                    if os.path.exists(filename):
                        print(
                            f"{self.print_header} Removing temp recording after successful conversion: "
                            f"{filename} ({os.path.getsize(filename)} bytes)"
                        )
                        os.remove(filename)
            else:
                self._rec_worker_save_success = False
                if os.path.exists(filename):
                    print(
                        f"{self.print_header} Recording stopped without save; temp file remains at "
                        f"{filename} ({os.path.getsize(filename)} bytes)"
                    )

            self.save_filename = "unspecified_filename.mp4"
            self._active_ffmpeg_log_path = None
            print(f"{self.print_header} Record worker session {session_id} stopped")

        except Exception as e:
            self._rec_worker_last_error = str(e)
            print(f"{self.print_header} Record worker session {session_id} crashed: {e}")
        finally:
            self._active_ffmpeg_log_path = None
            self._rec_running.clear()
            self._rec_worker_done.set()


    def start_record_worker(self, filename=None):
        # Ensure temp recording directory exists before opening VideoWriter.
        os.makedirs(TEMP_RECORDING_DIR, exist_ok=True)

        self._cleanup_finished_record_worker()
        self._recording_filename = self.temp_filename
        if self._rec_thread and self._rec_thread.is_alive():
            print(f"{self.print_header} Cannot start recording; previous worker is still active")
            return
        # Determine frame size and fps from current capture if possible
        if not self.cap:
            print(f"{self.print_header} Cannot start recorder; capture not open.")
            return False
        frame_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        frame_rate = max(1.0, float(self.cap.get(cv2.CAP_PROP_FPS) or REQUESTED_FPS))
        frame_size = (frame_width, frame_height)
        self._clear_record_queue()
        self.save_requested = False
        self._record_session_id += 1
        self._active_record_session_id = self._record_session_id
        self._rec_worker_done.clear()
        self._rec_worker_last_error = None
        self._rec_worker_save_success = None
        self._rec_worker_last_join_timed_out = False
        self._rec_stop_requested = False
        self._rec_stop_requested_at_ms = 0.0
        self._last_rec_wait_log_ms = 0.0
        self._active_ffmpeg_log_path = None
        self._last_ffmpeg_progress_line = ""
        self._rec_running.set()
        self._rec_thread = threading.Thread(
            target=self._rec_worker,
            args=(self._active_record_session_id, self._recording_filename, RECORD_FOURCC, frame_rate, frame_size),
            daemon=True,
        )
        self._rec_thread.start()
        print(
            f"{self.print_header} Recording worker session {self._active_record_session_id} armed "
            f"(temp={self._recording_filename}, fps={frame_rate}, size={frame_size})"
        )
        return True

    def stop_record_worker(self, join_timeout=3.0):
        # Signal worker to finish and join
        self.request_record_worker_stop()
        if self._rec_thread:
            print(
                f"{self.print_header} Waiting for record worker session {self._active_record_session_id} "
                f"to exit (save_requested={self.save_requested}, queue={self.rec_queue.qsize()}, "
                f"timeout={join_timeout}s)"
            )
            self._rec_thread.join(timeout=join_timeout)
            if self._rec_thread.is_alive():
                self._rec_worker_last_join_timed_out = True
                print(f"{self.print_header} Warning: record worker did not exit within timeout")
                return False
            self._rec_worker_last_join_timed_out = False
            print(f"{self.print_header} Record worker session {self._active_record_session_id} exited")
            self._rec_thread = None
            self._rec_stop_requested = False
            self._last_rec_wait_log_ms = 0.0
        return self.is_record_worker_done()

    # -----------------------
    # aiohttp streaming
    # -----------------------
    async def start_http_server(self):
        self._runner = web.AppRunner(self.app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, "0.0.0.0", self.stream_port)
        await self._site.start()
        print(f"{self.print_header} MJPEG stream available at http://0.0.0.0:{self.stream_port}/stream")

    async def stop_http_server(self):
        if self._site:
            await self._site.stop()
            self._site = None
        if self._runner:
            await self._runner.cleanup()
            self._runner = None

    async def mjpeg_handler(self, request):
        """Stream latest frames as MJPEG. Always use latest frame; downscale and lower quality for stream."""
        if not self.state.isConnected or self.cap is None:
            return web.Response(status=503, text="Camera not connected")

        if not self.state.isStreaming:
            return web.Response(status=503, text="Streaming not enabled")

        response = web.StreamResponse(
            status=200,
            reason="OK",
            headers={"Content-Type": "multipart/x-mixed-replace; boundary=frame"},
        )
        await response.prepare(request)

        try:
            while self.state.isStreaming and self.state.isConnected:
                # Grab latest frame quickly
                frame = None
                try:
                    # Acquire lock but don't block long
                    await asyncio.wait_for(self.frame_lock.acquire(), timeout=0.01)
                    if self.current_frame is not None:
                        frame = self.current_frame.copy()
                    self.frame_lock.release()
                except asyncio.TimeoutError:
                    # skip this tick if lock busy
                    await asyncio.sleep(0.01)
                    continue

                if frame is None:
                    await asyncio.sleep(0.01)
                    continue

                # Downscale if necessary for streaming
                h, w = frame.shape[:2]
                if w > STREAM_TARGET_WIDTH:
                    scale = STREAM_TARGET_WIDTH / w
                    frame = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_LINEAR)

                # Encode JPEG at lower quality for stream
                ret, jpeg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), STREAM_JPEG_QUALITY])
                if not ret:
                    await asyncio.sleep(0.01)
                    continue

                try:
                    await response.write(b"--frame\r\n")
                    await response.write(b"Content-Type: image/jpeg\r\n\r\n")
                    await response.write(jpeg.tobytes())
                    await response.write(b"\r\n")
                    self.stats["stream_sent"] += 1
                except (client_exceptions.ClientConnectionResetError, BrokenPipeError):
                    # Client disconnected
                    break
                except Exception as e:
                    print(f"{self.print_header} Error writing to client: {e}")
                    break

                # Aim for streaming FPS
                await asyncio.sleep(max(0, 1.0 / STREAM_FPS))
        finally:
            try:
                await response.write_eof()
            except Exception:
                pass

        return response

    def connect_cmd(self, index = None):
        if index is None:
            cam_index = get_camera_index_by_serial(self.camera_serial)
        else:
            cam_index = index

        if cam_index is None:
            print(f"{self.print_header} Cannot connect: camera with serial {self.camera_serial} not found")
            return
        if(cam_index != self.camera_index):
            print(f"{self.print_header} Camera index is changing to: /dev/video{cam_index}")
        self.camera_index = cam_index
        self.state.videoDeviceNodeString = f"/dev/video{self.camera_index}"
        self.connect_command = True

    # -----------------------
    # Main loop & processing
    # -----------------------
    async def run(self):
        """Main async loop: manages connect state and reads frames."""

        # Start diagnostics logger
        self._logging_task = asyncio.create_task(self._log_stats())

        #self._update_status_task = asyncio.create_task(self._update_status_loop())

        print(f"{self.print_header} Entering main run loop. Press 'c' to connect, 'r' to record, 't' to stream, 'q' to quit.")

        lastUpdateTimeMs = time.time() * 1000

        try:
            while True:
                timeNowMs = time.time() * 1000
                if timeNowMs - lastUpdateTimeMs >= 1000:
                    lastUpdateTimeMs = timeNowMs
                    self.updateState()

                # Handle connect/disconnect commands
                if (self.connect_command or self.auto_connect):
                    self.connect_command = False
                    if not self.state.isConnected:
                        await self.open_capture()

                if self.disconnect_command:
                    self.disconnect_command = False
                    if self.state.isConnected:
                        print(f"{self.print_header} Disconnect command received")
                        await self.close_capture()
                        # ensure recorder is stopped
                        if self.state.recordingState == CameraRecordingStates.RECORDING:
                            started = self.stop_record_worker()
                        self.state.recordingState == CameraRecordingStates.STOPPED
      
                # If connected, read frames
                if self.state.isConnected and self.cap:
                    # Read frame (this blocks until next frame)
                    try:
                        ret, frame = self.cap.read()
                    except Exception as e:
                        print(f"{self.print_header} Capture read exception: {e}")
                        await self.close_capture()
                        await asyncio.sleep(0.1)
                        continue

                    if not ret:
                        # failed to grab frame -> try to reconnect
                        print(f"{self.print_header} Failed to read frame; disconnecting.")
                        await self.close_capture()
                        await asyncio.sleep(0.5)
                        self.state.isConnected = False
                        continue

                    # Update stats & shared buffer
                    self.stats["captured"] += 1
                    async with self.frame_lock:
                        self.current_frame = frame.copy()

                    # Handle start/stop streaming commands (state machine)
                    if (self.start_streaming_command or self.auto_start_stream):
                        self.start_streaming_command = False
                        if not self.state.isStreaming:
                            self.start_streaming_command = False
                            await self.start_http_server()
                            self.state.isStreaming = True
                            print(f"{self.print_header} Streaming enabled on /stream")

                    if self.stop_streaming_command:
                        self.stop_streaming_command = False
                        if self.state.isStreaming:
                            await self.stop_http_server()
                            self.state.isStreaming = False
                            print(f"{self.print_header} Streaming disabled")

                    # Handle recording commands & queue frames for recorder
                    if self.start_recording_command:
                        self.start_recording_command = False
                        if self.state.recordingState == CameraRecordingStates.STOPPED or self.state.recordingState == CameraRecordingStates.SAVED:
                            # Initialize recorder worker
                            started = self.start_record_worker()
                            if started:
                                self.state.recordingState = CameraRecordingStates.RECORDING
                                print(f"{self.print_header} Recording started to {self._recording_filename}")
                            else:
                                print(f"{self.print_header} Failed to start recording worker")

                    if self.stop_recording_command:
                        self.stop_recording_command = False
                        if self.state.recordingState == CameraRecordingStates.RECORDING:
                            self.save_requested = False
                            self.state.recordingState = CameraRecordingStates.STOPPING
                            self.request_record_worker_stop()
                            print(f"{self.print_header} Stop requested; waiting for record worker to exit without saving")
                        elif self.state.recordingState == CameraRecordingStates.SAVED:
                            self.state.recordingState = CameraRecordingStates.STOPPED
                            print(f"{self.print_header} Recording already finalized; marking state as stopped")

                    if self.stop_and_save_recording_command:
                        self.stop_and_save_recording_command = False
                        if self.state.recordingState == CameraRecordingStates.RECORDING:
                            self.save_requested = True
                            self.state.recordingState = CameraRecordingStates.SAVING
                            self.request_record_worker_stop()
                            print(
                                f"{self.print_header} Stopping recording, finalizing file "
                                f"to {self.save_filename}"
                            )

                    if self.state.recordingState == CameraRecordingStates.RECORDING:
                        # enqueue frame non-blocking; drop if full
                        try:
                            self.rec_queue.put_nowait(frame.copy())
                        except queue.Full:
                            self.stats["dropped_for_rec"] += 1

                    elif self.state.recordingState == CameraRecordingStates.STOPPING:
                        worker_stopped = self.poll_record_worker_stop()
                        if worker_stopped:
                            self.state.recordingState = CameraRecordingStates.STOPPED
                            print(f"{self.print_header} Recording stopped without saving; worker fully stopped.")

                    elif self.state.recordingState == CameraRecordingStates.SAVING:
                        # finalize recording: stop worker and transition to stopped
                        worker_stopped = self.poll_record_worker_stop()
                        if worker_stopped:
                            if self._rec_worker_save_success:
                                self.state.recordingState = CameraRecordingStates.SAVED
                                print(f"{self.print_header} Recording saved and worker stopped.")
                            else:
                                self.state.recordingState = CameraRecordingStates.STOPPED
                                print(
                                    f"{self.print_header} Recording worker stopped but save did not complete: "
                                    f"{self._rec_worker_last_error or 'unknown error'}"
                                )
                       
                else:
                    # Not connected: ensure streaming and recording are stopped
                    self.stop_streaming_command = False
                    self.start_streaming_command = False
                    self.start_recording_command = False
                    self.start_recording_command = False
                    self.stop_and_save_recording_command = False
                    self.stop_recording_command = False

                    if self.state.isStreaming:
                        await self.stop_http_server()
                        self.state.isStreaming = False
                        print(f"{self.print_header} Streaming disabled")

                    if self.state.recordingState in (
                        CameraRecordingStates.RECORDING,
                        CameraRecordingStates.SAVING,
                        CameraRecordingStates.STOPPING,
                    ):
                        self.stop_record_worker()
                        self.state.recordingState = CameraRecordingStates.STOPPED
                        print(f"{self.print_header} Lost connection: stopping")
                # Tiny sleep to yield to event loop (do not make this large)
                await asyncio.sleep(0.0005)

        except asyncio.CancelledError:
            # expected on shutdown
            pass
        finally:
            # Cleanup
            if self.state.recordingState in (
                CameraRecordingStates.RECORDING,
                CameraRecordingStates.SAVING,
                CameraRecordingStates.STOPPING,
            ):
                self.stop_record_worker()
            if self._logging_task:
                self._logging_task.cancel()
            await self.stop_http_server()
            await self.close_capture()
            print(f"{self.print_header} Run loop exiting.")



    # -----------------------
    # Diagnostics logger
    # -----------------------
    async def _log_stats(self):
        while False:
            now = time.time()
            if now - self.stats["last_diag"] >= DIAG_INTERVAL:
                print(
                    f"{self.print_header} stats (last {DIAG_INTERVAL}s): "
                    f"captured={self.stats['captured']} stream_sent={self.stats['stream_sent']} "
                    f"written={self.stats['record_written']} dropped_rec={self.stats['dropped_for_rec']}"
                )
                # reset counters for interval
                self.stats.update(captured=0, stream_sent=0, record_written=0, dropped_for_rec=0, last_diag=now)
            await asyncio.sleep(0.2)

# -----------------------
# Keyboard listener (linux terminal)
# -----------------------
async def keyboard_listener(cam: CameraDevice):
    """
    Non-blocking keyboard listener for local demo.
    Keys:
      c - connect camera
      d - disconnect camera
      r - start recording
      f - stop recording
      t - start streaming
      y - stop streaming
      q - quit
    """
    print("[keyboard] Listening for commands: c=connect, d=disconnect, r=start rec, f=stop rec, t=start stream, y=stop stream, q=quit")
    # Save terminal settings
    try:
        old = termios.tcgetattr(sys.stdin)
    except Exception:
        # Not a TTY or unsupported environment
        print("[keyboard] Terminal input not available (not a TTY). Skipping keyboard listener.")
        return

    try:
        tty.setcbreak(sys.stdin.fileno())
        while True:
            if select.select([sys.stdin], [], [], 0.1)[0]:
                ch = sys.stdin.read(1)
                if ch == "c":
                    cam.connect_command = True
                elif ch == "d":
                    cam.disconnect_command = True
                elif ch == "r":
                    cam.start_recording_command = True
                elif ch == "f":
                    cam.stop_recording_command = True
                elif ch == "t":
                    cam.start_streaming_command = True
                elif ch == "y":
                    cam.stop_streaming_command = True
                elif ch == "q":
                    print("[keyboard] Quit requested")
                    # Cancel run loop by raising CancelledError externally (we'll signal via event loop)
                    return
            await asyncio.sleep(0.05)
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old)

# -----------------------
# Entrypoint
# -----------------------
async def main():
    id = 1
    cam = CameraDevice(id, CAMERA_INDEX, stream_port=STREAM_PORT)

    # create tasks: main run loop and keyboard listener
    run_task = asyncio.create_task(cam.run())
    kb_task = asyncio.create_task(keyboard_listener(cam))

    # Wait for keyboard quit to stop service
    try:
        await kb_task
        # keyboard signalled quit; cancel run loop
        run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)
    except asyncio.CancelledError:
        pass
    finally:
        # Ensure full cleanup
        if not run_task.done():
            run_task.cancel()
            await asyncio.gather(run_task, return_exceptions=True)
        print("Service shutting down.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Interrupted by user (KeyboardInterrupt).")
