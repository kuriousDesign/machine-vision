import cv2
import asyncio
import numpy as np
from aiohttp import web, client_exceptions
from pathlib import Path



class CameraDevice:
    def __init__(self, device_id: int):
        self.device_id = device_id
        self.state = "INACTIVE"
        self.capture = None

        self.stream_port = 8000 + device_id  # Unique port per camera
        self.streaming_task = None
        self.recording_task = None
        self.record_lock = asyncio.Lock()

        self.recording = False
        self.record_writer = None

    async def poll_for_device(self):
        """Poll for USB/Ethernet cameras while INACTIVE"""
        while self.state == "INACTIVE":
            cap = cv2.VideoCapture(self.device_id)
            if cap.isOpened():
                self.capture = cap
                self.state = "IDLE"
                print(f"Camera {self.device_id} connected")
                # Start streaming when IDLE
                self.streaming_task = asyncio.create_task(self.start_stream())
            else:
                await asyncio.sleep(2)

    async def start_recording(self, filename: str, fps: int = 20):
        """Start async video recording"""
        async with self.record_lock:
            if self.state != "IDLE" or self.capture is None:
                print(f"Camera {self.device_id} not ready for recording")
                return

            self.state = "RECORDING"
            self.recording = True

            # Get video size
            width = int(self.capture.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(self.capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fourcc = cv2.VideoWriter_fourcc(*'XVID')
            self.record_writer = cv2.VideoWriter(filename, fourcc, fps, (width, height))

            print(f"Camera {self.device_id} started recording to {filename}")

            # Start recording loop in background
            self.recording_task = asyncio.create_task(self._record_loop())

    async def _record_loop(self):
        while self.recording and self.capture is not None:
            ret, frame = self.capture.read()
            if ret:
                self.record_writer.write(frame)
            await asyncio.sleep(0.01)  # yield control

    async def stop_recording(self):
        async with self.record_lock:
            if not self.recording:
                return
            self.recording = False
            self.state = "IDLE"
            if self.record_writer:
                self.record_writer.release()
                self.record_writer = None
            print(f"Camera {self.device_id} recording stopped")

    async def take_image(self, filename: str):
        """Capture a single image"""
        if self.state not in ["IDLE", "RECORDING"] or self.capture is None:
            return
        ret, frame = self.capture.read()
        if ret:
            Path(filename).parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(filename, frame)
            print(f"Camera {self.device_id} saved image to {filename}")

    async def start_stream(self):
        """Stream MJPEG frames over HTTP on self.stream_port"""
        async def mjpeg_handler(request):
            if self.capture is None:
                return web.Response(status=503)
            
            response = web.StreamResponse(
                status=200,
                reason='OK',
                headers={
                    'Content-Type': 'multipart/x-mixed-replace; boundary=frame'
                }
            )
            await response.prepare(request)

            try:
                while self.state in ["IDLE", "RECORDING"]:
                    ret, frame = self.capture.read()
                    if not ret:
                        await asyncio.sleep(0.03)
                        continue

                    # Encode frame as JPEG
                    ret2, jpeg = cv2.imencode('.jpg', frame)
                    if not ret2:
                        continue
                    data = jpeg.tobytes()

                    # The original place where the error occurred
                    await response.write(b"--frame\r\n")
                    await response.write(b"Content-Type: image/jpeg\r\n\r\n")
                    await response.write(data)
                    await response.write(b"\r\n")
                    await asyncio.sleep(0.03)
            
            except (client_exceptions.ClientConnectionResetError, BrokenPipeError):
                # Catch errors during the main streaming loop
                print(f"Client disconnected from Camera {self.device_id} during stream loop.")
            except asyncio.CancelledError:
                print(f"Camera {self.device_id} stream stopped by cancellation.")
            except Exception as e:
                print(f"An unexpected error occurred during streaming for Camera {self.device_id}: {e}")

            finally:
                # --- FIX: Ensure write_eof() doesn't cause a new traceback ---
                try:
                    await response.write_eof()
                    print(f"Handler cleanup complete for Camera {self.device_id}.")
                except (client_exceptions.ClientConnectionResetError, BrokenPipeError):
                    print(f"Connection already reset, skipping write_eof for Camera {self.device_id}.")
                except Exception as e:
                    print(f"Error during final write_eof cleanup: {e}")
            
            return response

        app = web.Application()
        app.router.add_get('/stream', mjpeg_handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', self.stream_port)
        await site.start()
        print(f"Camera {self.device_id} streaming on port {self.stream_port}/stream")
