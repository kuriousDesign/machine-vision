import asyncio
from aiohttp import web, client_exceptions
import cv2
import sys
import select
import termios
import tty

# --- Configuration ---
# output_filename is a global in the original user code, 
# but a real application should probably generate unique filenames 
# (e.g., using a timestamp) for each recording session.
output_filename = 'output_video.mp4'

# Use index 2 for the C922 Pro Stream Webcam based on the user's v4l2 output
camera_index = 2

# Frames per second requested. Will negotiate with the camera hardware.
frames_per_second = 30.0

# Use 'mp4v' for MP4 format. 
# We requested MJPG from the camera itself for faster streaming, 
# but we write the *output file* using the mp4v codec for standard playback compatibility.
fourcc_codec = cv2.VideoWriter_fourcc(*'mp4v') 

# i need a camera_device class that connects to a camera index, streams video frames and starts and stops recording also while streaming
class CameraDevice:    
    def __init__(self, camera_index, status_callback: callable):
        self.camera_index = camera_index
        self.is_connected = False
        self.state = "disconnected"  # Possible values: "disconnected", "connected"
        self.recording_state = "stopped"  # Possible values: "stopped", "recording", "saving", "disconnected"
        self.streaming_state = "stopped"  # Possible values: "stopped", "streaming", "disconnected"
        self.recording_task = None
        self.streaming_task = None
        self.cap = None
        self.video_writer = None
        self.status_callback = status_callback
        self.current_frame = None  # Shared frame buffer for streaming and recording
        self.frame_lock = asyncio.Lock()  # Protect frame access

        # requests 
        self.start_recording_command = False
        self.stop_recording_command = False
        self.start_streaming_command = False
        self.stop_streaming_command = False
        self.connect_command = False
        self.disconnect_command = False



    async def setup_streaming_server(self):
        self.app = web.Application()
        self.app.router.add_get('/stream', self.mjpeg_handler)
        runner = web.AppRunner(self.app)
        await runner.setup()
        self.stream_port = 8000 # + self.camera_index  # Unique port per camera
        site = web.TCPSite(runner, '0.0.0.0', self.stream_port)
        await site.start()
        #print(f"Camera {self.device_id} streaming on port {self.stream_port}/stream")

    async def run(self):
        """Main state machine for the camera device lifecycle."""
        previous_state = ""
        await self.setup_streaming_server()
        while True:
            if self.state != previous_state:
                previous_state = self.state
                asyncio.create_task(self.status_callback(self.camera_index, f"Camera {self.camera_index} state changed to: {self.state}"))
            match self.state:
                case "disconnected":
                    if self.is_connected:
                        await self.handle_disconnected()
                        #print(f"Camera {self.camera_index} disconnected.")
                    if self.connect_command:
                        await self.handle_connect()
                        self.connect_command = False  # Reset connect command after attempting
                case "connected":
                    if self.disconnect_command:
                        await self.handle_disconnected()
                        self.disconnect_command = False  # Reset disconnect command after attempting
                    else:
                        await self.read_camera()


            await asyncio.sleep(0.00001)  # Small delay to prevent tight loop

    async def handle_connect(self):
        """Attempts to connect to the camera index using openCV."""
        try:
            self.cap = cv2.VideoCapture(self.camera_index)
            if self.cap.isOpened():
                self.is_connected = True
                self.state = "connected"

                # --- CRITICAL CHANGE HERE ---
                # Force the camera to use MJPG compression first
                fourcc_mjpg = cv2.VideoWriter_fourcc(*'MJPG')
                self.cap.set(cv2.CAP_PROP_FOURCC, fourcc_mjpg)
                
                # Now set the resolution and FPS, which should work because MJPG supports these speeds
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920) 
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
                self.cap.set(cv2.CAP_PROP_FPS, frames_per_second)

                # Report actual settings used by the hardware
                actual_fps = self.cap.get(cv2.CAP_PROP_FPS)
                actual_width = self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)
                actual_height = self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
                print(f"Camera {self.camera_index} connected.")
                print(f"Actual Resolution: {actual_width}x{actual_height} at {actual_fps} FPS (via MJPG)")
                print("Press 'r' (record start), 'f' (record stop), 't' (stream start), 'y' (stream stop) in terminal.")
                
            else:
                self.cap.release()

        except Exception as e:
            if self.cap:
                self.cap.release()
 

    async def handle_disconnected(self):
        """Tries to connect to the camera index using openCV."""
        self.is_connected = False
        self.state = "disconnected"
        if self.video_writer is not None:
            self.video_writer.release()
            self.video_writer = None
        if self.cap:
            self.cap.release()

        self.recording_state = "disconnected"
        self.streaming_state = "disconnected"
      
    async def read_camera(self):
        """The main loop for reading frames and processing commands."""
      
        try:
            # Read frame blocks until a frame is ready
            ret, frame = self.cap.read()
            if not ret:
                print(f"Failed to read frame from camera {self.camera_index}")
                await self.handle_disconnected()
                return

        except Exception as e:
            print(f"Error during main loop from camera {self.camera_index}: {e}")
            await self.handle_disconnected()
            return

        # Store frame in shared buffer for HTTP streaming to access
        async with self.frame_lock:
            self.current_frame = frame.copy()  # Copy to avoid race conditions
             
        await asyncio.gather(
            self.handle_streaming_display(),
            self.handle_video_recording(frame)
        )
        # This needs to run faster than a simple sleep to process frames immediately
        # yield control back to the async event loop without sleeping for a specific duration
        await asyncio.sleep(0.0001) 
                
    async def handle_streaming_display(self):
        # STREAMING (DISPLAY) LOGIC - just manages state
        # The actual streaming happens in mjpeg_handler which runs independently
      
        match self.streaming_state:
            case "stopped":
                if self.start_streaming_command:
                    self.streaming_state = "streaming"
                    print(f"HTTP streaming available at http://0.0.0.0:{self.stream_port}/stream")
            case "streaming":
                if self.stop_streaming_command:
                    self.streaming_state = "stopped"
                    print(f"HTTP streaming stopped for camera {self.camera_index}")
        
        # Acknowledge commands were processed
        self.start_streaming_command = False
        self.stop_streaming_command = False

    async def handle_video_recording(self, frame):
        # RECORDING LOGIC
        try:
            # Handle state transitions based on connectivity
            if not self.is_connected and self.recording_state != "disconnected":
                self.recording_state = "disconnected"
                print(f"Recording stopped due to disconnection for camera {self.camera_index}")
            
            match self.recording_state:
                case "stopped" | "disconnected":
                    if self.start_recording_command:
                        # Setup the VideoWriter when the command is received
                        frame_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                        frame_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                        frame_size = (frame_width, frame_height)
                        # Use the actual FPS the camera provides
                        frame_rate = self.cap.get(cv2.CAP_PROP_FPS) 
                        
                        self.video_writer = cv2.VideoWriter(output_filename, fourcc_codec, frame_rate, frame_size)

                        if not self.video_writer.isOpened():
                             print(f"Error: VideoWriter could not open file {output_filename}. Check codec/permissions.")
                             self.recording_state = "stopped"
                        else:
                            self.recording_state = "recording"
                            print(f"Recording started to {output_filename} for camera {self.camera_index}")

                case "recording":
                    # Stop cmd received
                    if self.stop_recording_command:
                        self.recording_state = "saving" # Transition to saving state
                        # Saving actually happens immediately when we exit this match case and the video_writer is released
                        print(f"Saving and finalizing recording for camera {self.camera_index}")

                    else:
                        # write frame to video file
                        if self.video_writer is not None:
                            self.video_writer.write(frame)

                case "saving":
                    # Finalize the file and transition back to stopped state
                    if self.video_writer is not None:
                        self.video_writer.release()
                        self.video_writer = None
                        print(f"Recording saved successfully.")
                    self.recording_state = "stopped"

        except Exception as e:
            print(f"Error during video recording from camera {self.camera_index}: {e}")
            if self.video_writer is not None:
                 self.video_writer.release()
                 self.video_writer = None
            self.recording_state = "disconnected"
            self.is_connected = False
        
        # Acknowledge commands were processed
        self.start_recording_command = False
        self.stop_recording_command = False

    async def mjpeg_handler(self, request):
        """HTTP handler for MJPEG streaming - runs continuously per connected client."""
        if self.cap is None or not self.is_connected:
            return web.Response(status=503, text="Camera not connected")
        
        # Check if streaming is enabled
        if self.streaming_state != "streaming":
            return web.Response(status=503, text="Streaming not enabled. Press 't' to start.")
        
        response = web.StreamResponse(
            status=200,
            reason='OK',
            headers={
                'Content-Type': 'multipart/x-mixed-replace; boundary=frame'
            }
        )
        await response.prepare(request)

        try:
            while self.streaming_state == "streaming" and self.is_connected:
                # Get the current frame from shared buffer
                async with self.frame_lock:
                    if self.current_frame is None:
                        await asyncio.sleep(0.01)
                        continue
                    frame = self.current_frame.copy()
                
                # Encode frame as JPEG
                ret, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                if not ret:
                    await asyncio.sleep(0.01)
                    continue
                
                # Send frame to client
                await response.write(b"--frame\r\n")
                await response.write(b"Content-Type: image/jpeg\r\n\r\n")
                await response.write(jpeg.tobytes())
                await response.write(b"\r\n")
                
                # Control streaming framerate (~30 fps)
                await asyncio.sleep(0.063)
        
        except (client_exceptions.ClientConnectionResetError, BrokenPipeError):
            print(f"Client disconnected from Camera {self.camera_index}")
        except asyncio.CancelledError:
            print(f"Camera {self.camera_index} stream cancelled")
        except Exception as e:
            print(f"Streaming error for Camera {self.camera_index}: {e}")

        finally:
            try:
                await response.write_eof()
            except (client_exceptions.ClientConnectionResetError, BrokenPipeError):
                pass  # Client already disconnected
            except Exception as e:
                print(f"Error during cleanup: {e}")
        
        return response


async def keyboard_listener(cam_device):
    """Listens for keyboard input in the terminal to send commands to the camera device."""
    # This function requires non-blocking terminal I/O setup, 
    # which is OS-specific (this works on Linux/Ubuntu)

    # Save original terminal settings
    print('listening for keyboard commands)')
    old_settings = termios.tcgetattr(sys.stdin)
    try:
        # Set terminal to non-blocking raw mode
        tty.setcbreak(sys.stdin.fileno())
        while True:
            # Use select to check for input availability without blocking the asyncio loop
            if select.select([sys.stdin], [], [], 0.0)[0]:
                key = sys.stdin.read(1)
                if key == 'r':
                    cam_device.start_recording_command = True
                    print("\nCommand: Start recording (r)")
                elif key == 'f':
                    cam_device.stop_recording_command = True
                    print("\nCommand: Stop recording (f)")
                elif key == 't':
                    cam_device.start_streaming_command = True
                    print("\nCommand: Start streaming display (t)")
                elif key == 'y':
                    cam_device.stop_streaming_command = True
                    print("\nCommand: Stop streaming display (y)")
                elif key == 'q': # 'q' to quit the entire application
                     print("\nCommand: Quit application (q)")
                     break
                elif key == 'c':
                     cam_device.connect_command = True
                     print("\nCommand: Connect to camera (c)")
                elif key == 'd':
                     cam_device.disconnect_command = True
                     print("\nCommand: Disconnect from camera (d)")

            await asyncio.sleep(0.001) # Small sleep to not busy-wait
    finally:
        # Restore original terminal settings
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
        # Signal camera to disconnect and close gracefully before exiting program
        cam_device.is_connected = False






async def manager_status_callback(camera_index, status_message):
    """Placeholder for your CameraManager's MQTT publishing method."""
    print(f"[MQTT Placeholder] Status Update for Index {camera_index}: {status_message}")

async def main():
    """Main application entry point."""
    camera = CameraDevice(camera_index, manager_status_callback)
    
    # Run the camera logic and keyboard listener concurrently
    await asyncio.gather(
        camera.run(),
        keyboard_listener(camera)
    )
    # Ensure all resources are cleaned up on exit
    if camera.cap:
        camera.cap.release()
    if camera.video_writer:
        camera.video_writer.release()
    cv2.destroyAllWindows()
    print("Application closed.")

if __name__ == "__main__":
    try:
        # Run the asynchronous main function
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Program interrupted by user.")
        # asyncio.run handles cleanup automatically if structured correctly
        pass

