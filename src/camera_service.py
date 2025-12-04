import asyncio
import json
import threading
import time
import paho.mqtt.client as mqtt

from cameras.camera_device import CameraDevice
from cameras.camera_names import get_camera_index_by_serial
from config import CAMERA_MAP


class CameraService:
    def __init__(self, mqtt_host: str, mqtt_port: int, cameras: dict[int, CameraDevice]):
        """
        cameras: dict[int, CameraDevice]
        """
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.cameras: dict[int, CameraDevice] = cameras

        # MQTT client
        self.client = mqtt.Client()
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

        # Internal
        self._connect_event = threading.Event()
        self._running = True
        self.topic_prefix = "cameras"

        # Start Paho networking thread
        self.client.loop_start()

    # ----------------------------------------------------------------------
    # MQTT CONNECT/DISCONNECT
    # ----------------------------------------------------------------------
    def connect(self):
        """Begin initial connection attempt; Paho will auto-reconnect."""
        while self._running:
            try:
                print(f"[MQTT] Connecting to {self.mqtt_host}:{self.mqtt_port} ...")
                self.client.connect(self.mqtt_host, self.mqtt_port, keepalive=10)
                return
            except Exception as e:
                print(f"[MQTT] Connect failed: {e}. Retrying in 5 sec...")
                time.sleep(5)

    def _on_connect(self, client, userdata, flags, rc):
        print(f"[MQTT] Connected to broker")

        # Subscribe to control topics for all cameras
        # e.g., cameras/2/control
        self.client.subscribe("cameras/1/cmd")
        self.client.subscribe("cameras/2/cmd")
        self.client.subscribe("cameras/3/cmd")
        print(f"[MQTT] Subscribed to cameras/+/cmd")

        self._connect_event.set()

    def _on_disconnect(self, client, userdata, rc):
        print(f"[MQTT] Disconnected (rc={rc}). Paho will auto-reconnect.")
        self._connect_event.clear()

    # ----------------------------------------------------------------------
    # MESSAGE HANDLER
    # ----------------------------------------------------------------------
    def _on_message(self, client, userdata, msg):
        """
        Handles messages like: cameras/2/cmd
        Payload example:
        { "cmd": "start_stream" }
        """
        topic = msg.topic
        payload = msg.payload.decode("utf-8")

        # Parse camera index from topic
        # cameras/<index>/control
        try:
            _, cam_id_str, suffix = topic.split("/")
            cam_id = int(cam_id_str)
        except:
            print(f"[MQTT] Invalid topic format: {topic}")
            return

        if cam_id not in self.cameras:
            print(f"[MQTT] Unknown camera index {cam_id}")
            return

        cam = self.cameras[cam_id]

        try:
            print(f"[MQTT] Message on {topic}: {payload}")
            data = json.loads(payload)
        except:
            print(f"[MQTT] Bad JSON: {payload}")
            return

        if suffix == "cmd":
            cmd = data.get("cmd")
            print(f"[MQTT] Command for camera {cam_id}: {cmd}")

            # Map MQTT commands → CameraDevice commands
            if cmd == "connect":
                #cam_index_by_serial = get_camera_index_by_serial(cam.camera_serial)
                cam.connect_cmd()
            elif cmd == "disconnect":
                cam.disconnect_command = True
            elif cmd == "start_stream":
                cam.start_streaming_command = True
            elif cmd == "stop_stream":
                cam.stop_streaming_command = True
            elif cmd == "start_record":
                cam.start_recording_command = True
            elif cmd == "stop_record":
                cam.stop_recording_command = True
            else:
                print(f"[MQTT] Unknown command: {cmd}")

    # ----------------------------------------------------------------------
    # PUBLISHING (used by CameraDevices)
    # ----------------------------------------------------------------------
    def publish_state(self, cam_index: int, state: dict):
        """
        Called by CameraDevice via a callback.
        Publishes to cameras/N/state
        """
        topic = f"{self.topic_prefix}/{cam_index}/state"
        try:
            self.client.publish(topic, json.dumps(state), qos=0)
            print(f"[MQTT] Published state to {topic}: {state}")
        except Exception as e:
            print(f"[MQTT] Failed to publish state: {e}")

    # ----------------------------------------------------------------------
    # SERVICE LOOP
    # ----------------------------------------------------------------------
    async def run(self):
        """Main async supervisor loop."""
        self.connect()

        # Wait until connected
        while not self._connect_event.is_set():
            await asyncio.sleep(0.1)

        print("[MQTT] Service started. MQTT ready.")

        # Start all camera run-loops
        cam_tasks = [
            asyncio.create_task(cam.run())
            for cam in self.cameras.values()
        ]

        # Run until cancelled
        try:
            await asyncio.gather(*cam_tasks)
        except asyncio.CancelledError:
            pass
        finally:
            self.shutdown()

    def shutdown(self):
        print("[MQTT] Shutting down...")
        self._running = False
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except:
            pass
