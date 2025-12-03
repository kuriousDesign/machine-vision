import asyncio
import cv2
import sys
import select
import termios
import tty
import subprocess
import re

from src.cameras.camera_names import get_unique_camera_names_and_indices

# --- Configuration (These would typically come from your CameraManager) ---
output_filename = 'output_video.mp4'
frames_per_second = 30.0
# We write the *output file* using the mp4v codec for standard playback compatibility.
fourcc_codec = cv2.VideoWriter_fourcc(*'mp4v') 
# ---------------------


class CameraDevice:    
    """
    Manages a single camera, handling connection states, streaming, and recording.
    Requires an async callback function for status updates (e.g., MQTT).
    """
    def __init__(self, camera_index, status_callback_func):
        self.camera_index = camera_index
        self.publish_status = status_callback_func # The async callback method
        self.is_connected = False
        self.state = "disconnected"
        self.recording_state = "stopped"
        self.streaming_state = "stopped"
        self.cap = None
        self.video_writer = None
        self.cameras=get_unique_camera_names_and_indices()
        #self.camera_name, self.camera_serial = get_camera_name_and_serial(camera_index)
        self.output_filename = f"video_cam_{self.camera_index}_{self.camera_serial}.mp4"


        # Requests (Commands received via keyboard listener/MQTT)
        self.start_recording_command = False
        self.stop_recording_command = False
        self.start_streaming_command = False
        self.stop_streaming_command = False
     

    async def run(self):
        """Main state machine for the camera device lifecycle."""
        while True:
            if not self.is_connected and self.state != "disconnected":
                 # Gracefully handle unexpected disconnections
                 self.state = "disconnected" 
                 if self.cap: self.cap.release()
                 if self.video_writer: self.video_writer.release()
                 cv2.destroyWindow(f'Camera {self.camera_index}')
                 await self.publish_status(self.camera_index, "Warning: Unexpected Disconnection")

            match self.state:
                case "disconnected":
                    await self.handle_disconnected_state()
                case "connected":
                    self.state = "streaming" 
                    await self.handle_streaming_loop()
                case "streaming":
                    pass


    async def handle_disconnected_state(self):
        """Tries to connect to the camera index using openCV."""
        self.is_connected = False
        try:
            self.cap = cv2.VideoCapture(self.camera_index)
            if self.cap.isOpened():
                # --- Configuration for 1080p @ 30 FPS using MJPG ---
                fourcc_mjpg = cv2.VideoWriter_fourcc(*'MJPG')
                self.cap.set(cv2.CAP_PROP_FOURCC, fourcc_mjpg)
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920) 
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
                self.cap.set(cv2.CAP_PROP_FPS, frames_per_second)

                self.is_connected = True
                self.state = "connected"
                actual_fps = self.cap.get(cv2.CAP_PROP_FPS)
                actual_width = self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)
                print(f"[Cam {self.camera_index}] Connected: {self.camera_name}, Serial: {self.camera_serial}")
                print(f"[Cam {self.camera_index}] Configured Resolution: {actual_width}x{self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)} at {actual_fps} FPS (via MJPG)")
                
                await self.publish_status(self.camera_index, "Connected")
                
            else:
                self.cap.release()
                await asyncio.sleep(2) # Wait before retrying
        except Exception as e:
            if self.cap: self.cap.release()
            await asyncio.sleep(2) # Wait before retrying


    async def handle_streaming_loop(self):
        """The main loop for reading frames and processing commands."""
        while self.is_connected:
            ret, frame = self.cap.read()
            if not ret:
                print(f"[Cam {self.camera_index}] Failed to read frame, transitioning to disconnected.")
                self.is_connected = False
                break
            
            await asyncio.gather(
                self.handle_streaming_display(frame),
                self.handle_video_recording(frame)
            )
            
            await asyncio.sleep(0.0001) 
        
        cv2.destroyWindow(f'Camera {self.camera_index}')
        await self.publish_status(self.camera_index, "Disconnected")


    async def handle_streaming_display(self, frame):
        # STREAMING (DISPLAY) LOGIC
        if not self.is_connected: return

        match self.streaming_state:
            case "stopped":
                if self.start_streaming_command:
                    self.streaming_state = "streaming"
                    print(f"[Cam {self.camera_index}] Streaming display started.")
            case "streaming":
                if self.stop_streaming_command:
                    self.streaming_state = "stopped"
                    cv2.destroyWindow(f'Camera {self.camera_index}')
                    print(f"[Cam {self.camera_index}] Streaming display stopped.")
                else:
                    cv2.imshow(f'Camera {self.camera_index}', frame)
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                       self.stop_streaming_command = True 
        
        self.start_streaming_command = False
        self.stop_streaming_command = False

    
    async def handle_video_recording(self, frame):
        # RECORDING LOGIC
        if not self.is_connected: return

        match self.recording_state:
            case "stopped":
                if self.start_recording_command:
                    frame_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    frame_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    frame_size = (frame_width, frame_height)
                    frame_rate = self.cap.get(cv2.CAP_PROP_FPS) 
                    
                    self.video_writer = cv2.VideoWriter(self.output_filename, fourcc_codec, frame_rate, frame_size)

                    if not self.video_writer.isOpened():
                         print(f"[Cam {self.camera_index}] Error: VideoWriter failed to open {self.output_filename}.")
                         await self.publish_status(self.camera_index, "Recording Failed to Start")
                         self.recording_state = "stopped"
                    else:
                        self.recording_state = "recording"
                        print(f"[Cam {self.camera_index}] Recording started to {self.output_filename}")
                        await self.publish_status(self.camera_index, "Recording")

            case "recording":
                if self.stop_recording_command:
                    self.recording_state = "saving"
                    print(f"[Cam {self.camera_index}] Saving and finalizing recording.")
                    await self.publish_status(self.camera_index, "Saving")
                else:
                    if self.video_writer is not None:
                        self.video_writer.write(frame)

            case "saving":
                if self.video_writer is not None:
                    self.video_writer.release()
                    self.video_writer = None
                    print(f"[Cam {self.camera_index}] Recording saved successfully.")
                self.recording_state = "stopped"
                await self.publish_status(self.camera_index, "Idle")
        
        self.start_recording_command = False
        self.stop_recording_command = False

# ------------------------------------------------------------------
# Example of a Manager class and main execution loop (for demonstration)
# ------------------------------------------------------------------

async def manager_status_callback(camera_index, status_message):
    """Placeholder for your CameraManager's MQTT publishing method."""
    print(f"[MQTT Placeholder] Status Update for Index {camera_index}: {status_message}")

async def keyboard_listener(cam_devices):
    """Listens for keyboard input in the terminal to send commands."""
    old_settings = termios.tcgetattr(sys.stdin)
    try:
        tty.setcbreak(sys.stdin.fileno())
        while True:
            if select.select([sys.stdin], [], [], 0.0):
                key = sys.stdin.read(1)
                if key in ['r', 'f', 't', 'y']:
                    # Send command to all connected cameras for this example
                    for cam in cam_devices:
                        if cam.is_connected:
                            if key == 'r': cam.start_recording_command = True
                            elif key == 'f': cam.stop_recording_command = True
                            elif key == 't': cam.start_streaming_command = True
                            elif key == 'y': cam.stop_streaming_command = True
                    print(f"\nCommand sent: {key}")
                elif key == 'q':
                     print("\nCommand: Quit application (q)")
                     break
            await asyncio.sleep(0.01)
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
        for cam in cam_devices:
            cam.is_connected = False # Signal all cams to stop gracefully

async def main():
    """Main application entry point."""
    print("Starting Camera System...")
    # Example: Initialize two cameras using the callback
    camera_devices = [
        CameraDevice(0, manager_status_callback), # Chicony camera index
        CameraDevice(2, manager_status_callback)  # C922 camera index
    ]
    
    camera_tasks = [camera.run() for camera in camera_devices]
    
    await asyncio.gather(
        *camera_tasks,
        keyboard_listener(camera_devices)
    )
    
    print("Application closing cleanly.")
    cv2.destroyAllWindows()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Program interrupted by user (KeyboardInterrupt).")
        pass
