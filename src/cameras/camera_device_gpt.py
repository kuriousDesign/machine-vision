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

# -----------------------
# Configuration
# -----------------------
CAMERA_INDEX = 2                    # camera device index (v4l2 / Windows device number)
OUTPUT_FILENAME = "output_video.mp4"
REQUESTED_FPS = 30.0
CAPTURE_WIDTH = 1920
CAPTURE_HEIGHT = 1080

# Recording settings
RECORD_FOURCC = cv2.VideoWriter_fourcc(*"mp4v")
REC_QUEUE_MAXSIZE = 12              # bounded queue for frames to record (drop when full)

# Streaming settings (lighter than recording)
STREAM_TARGET_WIDTH = 1280
STREAM_JPEG_QUALITY = 60            # 0-100
STREAM_FPS = 20.0                   # target FPS for MJPEG streaming (lower than capture)

# Server
STREAM_PORT = 8000

# Diagnostic interval (s)
DIAG_INTERVAL = 1.0

# -----------------------
# CameraDevice class
# -----------------------
class CameraDevice:
    def __init__(self, camera_index: int, stream_port: int = STREAM_PORT):
        self.camera_index = camera_index
        self.stream_port = stream_port

        # OpenCV capture & writer
        self.cap: Optional[cv2.VideoCapture] = None

        # State flags
        self.is_connected = False
        self.recording_state = "stopped"   # "stopped" | "recording" | "saving" | "disconnected"
        self.streaming_state = "stopped"   # "stopped" | "streaming" | "disconnected"

        # Shared frame buffer & lock
        self.current_frame = None
        self.frame_lock = asyncio.Lock()

        # Commands (used by keyboard or external control)
        self.start_recording_command = False
        self.stop_recording_command = False
        self.start_streaming_command = False
        self.stop_streaming_command = False
        self.connect_command = False
        self.disconnect_command = False

        # Recording queue & worker
        self.rec_queue: "queue.Queue" = queue.Queue(maxsize=REC_QUEUE_MAXSIZE)
        self._rec_thread: Optional[threading.Thread] = None
        self._rec_running = threading.Event()
        self._recording_filename = OUTPUT_FILENAME

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
                print(f"[cam{self.camera_index}] Failed to open capture device {self.camera_index}")
                if self.cap:
                    self.cap.release()
                self.cap = None
                self.is_connected = False
                return False

            # Report actual settings
            actual_fps = self.cap.get(cv2.CAP_PROP_FPS)
            actual_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            print(f"[cam{self.camera_index}] Opened. Actual resolution: {actual_w}x{actual_h} @ {actual_fps} FPS (requested {REQUESTED_FPS})")
            self.is_connected = True
            return True

        except Exception as e:
            print(f"[cam{self.camera_index}] Exception while opening capture: {e}")
            if self.cap:
                self.cap.release()
                self.cap = None
            self.is_connected = False
            return False

    async def close_capture(self):
        """Close capture and cleanup."""
        self.is_connected = False
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None

    # -----------------------
    # Recording worker (thread)
    # -----------------------
    def _rec_worker(self, filename, fourcc, fps, frame_size):
        """Background thread: consume frames from rec_queue and write via VideoWriter."""
        try:
            writer = cv2.VideoWriter(filename, fourcc, fps, frame_size)
            if not writer.isOpened():
                print(f"[cam{self.camera_index}] Record worker: VideoWriter failed to open {filename}")
                return
            print(f"[cam{self.camera_index}] Record worker started (writing to {filename})")
            while self._rec_running.is_set() or not self.rec_queue.empty():
                try:
                    frame = self.rec_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                try:
                    writer.write(frame)
                    self.stats["record_written"] += 1
                except Exception as e:
                    print(f"[cam{self.camera_index}] Error writing frame in record worker: {e}")
            writer.release()
            print(f"[cam{self.camera_index}] Record worker stopped, file finalized.")
        except Exception as e:
            print(f"[cam{self.camera_index}] Record worker crashed: {e}")

    def start_record_worker(self, filename=None):
        if filename:
            self._recording_filename = filename
        if self._rec_thread and self._rec_thread.is_alive():
            return
        # Determine frame size and fps from current capture if possible
        if not self.cap:
            print(f"[cam{self.camera_index}] Cannot start recorder; capture not open.")
            return False
        frame_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        frame_rate = max(1.0, float(self.cap.get(cv2.CAP_PROP_FPS) or REQUESTED_FPS))
        frame_size = (frame_width, frame_height)
        self._rec_running.set()
        self._rec_thread = threading.Thread(
            target=self._rec_worker,
            args=(self._recording_filename, RECORD_FOURCC, frame_rate, frame_size),
            daemon=True,
        )
        self._rec_thread.start()
        return True

    def stop_record_worker(self, join_timeout=3.0):
        # Signal worker to finish and join
        self._rec_running.clear()
        if self._rec_thread:
            self._rec_thread.join(timeout=join_timeout)
            if self._rec_thread.is_alive():
                print(f"[cam{self.camera_index}] Warning: record worker did not exit within timeout")
            self._rec_thread = None

    # -----------------------
    # aiohttp streaming
    # -----------------------
    async def start_http_server(self):
        self._runner = web.AppRunner(self.app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, "0.0.0.0", self.stream_port)
        await self._site.start()
        print(f"[cam{self.camera_index}] MJPEG stream available at http://0.0.0.0:{self.stream_port}/stream")

    async def stop_http_server(self):
        if self._site:
            await self._site.stop()
            self._site = None
        if self._runner:
            await self._runner.cleanup()
            self._runner = None

    async def mjpeg_handler(self, request):
        """Stream latest frames as MJPEG. Always use latest frame; downscale and lower quality for stream."""
        if not self.is_connected or self.cap is None:
            return web.Response(status=503, text="Camera not connected")

        if self.streaming_state != "streaming":
            return web.Response(status=503, text="Streaming not enabled")

        response = web.StreamResponse(
            status=200,
            reason="OK",
            headers={"Content-Type": "multipart/x-mixed-replace; boundary=frame"},
        )
        await response.prepare(request)

        try:
            while self.streaming_state == "streaming" and self.is_connected:
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
                    print(f"[cam{self.camera_index}] Error writing to client: {e}")
                    break

                # Aim for streaming FPS
                await asyncio.sleep(max(0, 1.0 / STREAM_FPS))
        finally:
            try:
                await response.write_eof()
            except Exception:
                pass

        return response

    # -----------------------
    # Main loop & processing
    # -----------------------
    async def run(self):
        """Main async loop: manages connect state and reads frames."""
        # Start HTTP server
        await self.start_http_server()

        # Start diagnostics logger
        self._logging_task = asyncio.create_task(self._log_stats())

        print(f"[cam{self.camera_index}] Entering main run loop. Press 'c' to connect, 'r' to record, 't' to stream, 'q' to quit.")

        try:
            while True:
                # Handle connect/disconnect commands
                if self.connect_command and not self.is_connected:
                    self.connect_command = False
                    await self.open_capture()

                if self.disconnect_command and self.is_connected:
                    self.disconnect_command = False
                    await self.close_capture()
                    # ensure recorder is stopped
                    if self.recording_state == "recording":
                        self.recording_state = "saving"
                # If connected, read frames
                if self.is_connected and self.cap:
                    # Read frame (this blocks until next frame)
                    try:
                        ret, frame = self.cap.read()
                    except Exception as e:
                        print(f"[cam{self.camera_index}] Capture read exception: {e}")
                        await self.close_capture()
                        await asyncio.sleep(0.1)
                        continue

                    if not ret:
                        # failed to grab frame -> try to reconnect
                        print(f"[cam{self.camera_index}] Failed to read frame; disconnecting.")
                        await self.close_capture()
                        await asyncio.sleep(0.5)
                        continue

                    # Update stats & shared buffer
                    self.stats["captured"] += 1
                    async with self.frame_lock:
                        self.current_frame = frame.copy()

                    # Handle start/stop streaming commands (state machine)
                    if self.start_streaming_command:
                        self.start_streaming_command = False
                        if self.streaming_state != "streaming":
                            self.streaming_state = "streaming"
                            print(f"[cam{self.camera_index}] Streaming enabled on /stream")

                    if self.stop_streaming_command:
                        self.stop_streaming_command = False
                        if self.streaming_state == "streaming":
                            self.streaming_state = "stopped"
                            print(f"[cam{self.camera_index}] Streaming disabled")

                    # Handle recording commands & queue frames for recorder
                    if self.recording_state in ("stopped", "disconnected"):
                        if self.start_recording_command:
                            self.start_recording_command = False
                            # Initialize recorder worker
                            started = self.start_record_worker()
                            if started:
                                self.recording_state = "recording"
                                print(f"[cam{self.camera_index}] Recording started to {self._recording_filename}")
                            else:
                                print(f"[cam{self.camera_index}] Failed to start recording worker")
                    elif self.recording_state == "recording":
                        if self.stop_recording_command:
                            self.stop_recording_command = False
                            self.recording_state = "saving"
                            print(f"[cam{self.camera_index}] Stopping recording, finalizing file...")
                        else:
                            # enqueue frame non-blocking; drop if full
                            try:
                                self.rec_queue.put_nowait(frame.copy())
                            except queue.Full:
                                self.stats["dropped_for_rec"] += 1

                    elif self.recording_state == "saving":
                        # finalize recording: stop worker and transition to stopped
                        self.stop_record_worker()
                        self.recording_state = "stopped"
                        print(f"[cam{self.camera_index}] Recording saved and worker stopped.")

                # Tiny sleep to yield to event loop (do not make this large)
                await asyncio.sleep(0.0005)

        except asyncio.CancelledError:
            # expected on shutdown
            pass
        finally:
            # Cleanup
            if self.recording_state == "recording":
                self.stop_record_worker()
            if self._logging_task:
                self._logging_task.cancel()
            await self.stop_http_server()
            await self.close_capture()
            print(f"[cam{self.camera_index}] Run loop exiting.")

    # -----------------------
    # Diagnostics logger
    # -----------------------
    async def _log_stats(self):
        while True:
            now = time.time()
            if now - self.stats["last_diag"] >= DIAG_INTERVAL:
                print(
                    f"[cam{self.camera_index}] stats (last {DIAG_INTERVAL}s): "
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
    cam = CameraDevice(CAMERA_INDEX, stream_port=STREAM_PORT)

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
