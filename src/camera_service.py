import asyncio
from enum import Enum
import json
import threading
import time
import paho.mqtt.client as mqtt
from dataclasses import dataclass, asdict, field
from cameras.camera_device import CameraDevice, CameraStatus
from cameras.camera_names import get_camera_index_by_serial
from config import CAMERA_MAP

@dataclass
class VisSts:
    camera_states: list[CameraStatus] = field(default_factory=list)

WRITE_TAG_TOPIC = 'machine/write_tag' 

class CameraService:
    def __init__(self, mqtt_host: str, mqtt_port: int, cameras: dict[int, CameraDevice]):
        """
        cameras: dict[int, CameraDevice]
        """
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.cameras: dict[int, CameraDevice] = cameras
        # add status callback to cameras
        self.vis_sts = VisSts()
        self.vis_sts.camera_states.append(CameraStatus()) # dummy for index 0

        for cam in self.cameras.values():
            self.vis_sts.camera_states.append(CameraStatus())
            cam.state_callback = self.camera_state_callback


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

    # Inject callback into cameras
    def camera_state_callback(self,cam_index, state: CameraStatus):
        """
        Called by CameraDevice via a callback.
        Publishes to cameras/N/state
        """
        self.vis_sts.camera_states[cam_index] = state
        topic = f"{self.topic_prefix}/{cam_index}/state"
        try:
            self.client.publish(topic, json.dumps(state.__dict__), qos=0)
            print(f"[MQTT] Published state to {topic}: {state}")
        except Exception as e:
            print(f"[MQTT] Failed to publish state: {e}")

    async def publish_vision_status(self):
        while True:
            print("publish_vision_status called")
            tag = "machine.visSts"
              # 1. Get the vis_sts object as a standard Python dictionary
            vis_sts_dict = asdict(self.vis_sts)
    
            # 2. Build the final Python dictionary that has the "tag" and "value" keys
            payload_dict = {
                "tag": tag, 
                "value": vis_sts_dict # This keeps the camera status as a nested dictionary, not a string
            }
    
            # 3. Encode the *entire* dictionary to a single JSON string *once*
            final_message_json = json.dumps(payload_dict)
            print(f"Publishing to {WRITE_TAG_TOPIC}: {final_message_json}")
    
            # 4. Publish the single, clean JSON string
            self.client.publish(WRITE_TAG_TOPIC, final_message_json, qos=0)
            await asyncio.sleep(1)

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

        publish_status_task = asyncio.create_task(self.publish_vision_status())

        # Run until cancelled
        try:
            await asyncio.gather(*cam_tasks, publish_status_task)
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


def serialize_to_json(data_object) -> str:
    """Converts a dataclass object to a JSON string."""
    
    # asdict() does the heavy lifting of converting the object to a dictionary.
    data_dict = asdict(data_object)
    
    # We still need a custom encoder to handle the Enum conversion automatically.
    # The default json.dumps won't know how to handle Enums in the dict.
    class EnumEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, Enum):
                return obj.value
            return json.JSONEncoder.default(self, obj)

    json_payload = json.dumps(data_dict, indent=4, cls=EnumEncoder)
    return json_payload