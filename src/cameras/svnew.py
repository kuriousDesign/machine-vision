import asyncio
from enum import Enum
import json
import threading
import time
import paho.mqtt.client as mqtt
from dataclasses import asdict
from cameras.camera_device import CameraDevice
from config import *


class CameraService:
    def __init__(self, mqtt_host: str, mqtt_port: int, cameras: dict[int, CameraDevice]):
        """
        cameras: dict[int, CameraDevice]
        """
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.cameras: dict[int, CameraDevice] = cameras
        # add status callback to cameras
        self.device_cfg = DeviceCfg()
        self.vis_sts = VisSts()
        self.vis_cfg = VisCfg()
        self.vis_sts.cfg = self.vis_cfg
        self.vis_sts.cameraStates.append(CameraStatus()) # dummy for index 0
        self.device_data = Device()
        self.device_data.cfg = self.device_cfg
        self.device_data.sts = self.vis_sts
        self.device_data.Is.stepNum = int(DeviceStates.ABORTING)


        for cam in self.cameras.values():
            self.vis_sts.cameraStates.append(CameraStatus())
            cam.state_callback = self.camera_state_callback


        # MQTT client
        self.client = mqtt.Client()
        self.mqtt_is_connected = False
        self.is_connecting_to_mqtt = False
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

        # Internal
        self._running = True
        self.device_topic = DEVICE_TOPIC

        # Start Paho networking thread
        self.client.loop_start()

    # ----------------------------------------------------------------------
    # MQTT CONNECT/DISCONNECT
    # ----------------------------------------------------------------------
    async def connect_mqtt(self):
        """Begin initial connection attempt; Paho will auto-reconnect."""
   
        try:
            print(f"[MQTT] Connecting to {self.mqtt_host}:{self.mqtt_port} ...")
            # self.client.on_connect = self._on_connect
            # self.client.on_disconnect = self._on_disconnect
            # self.client.on_message = self._on_message
            self.client.connect(self.mqtt_host, self.mqtt_port, keepalive=10)
            self.is_connecting_to_mqtt = True
            return
        except Exception as e:
            print(f"[MQTT] Connect failed: {e}. Retrying in 1 sec...")
            time.sleep(1)

    def _on_connect(self, client, userdata, flags, rc):
        print(f"[MQTT] Connected to broker")
        self.client.subscribe(SubscriptionTopics.API_HMI_REQ)
        self.client.subscribe(SubscriptionTopics.API_PLC_REQ)
        print(f"[MQTT] Subscribed to {SubscriptionTopics.API_HMI_REQ} and {SubscriptionTopics.API_PLC_REQ}")
        self.mqtt_is_connected = True
        self.is_connecting_to_mqtt = False
    

    def _on_disconnect(self, client, userdata, rc):
        print(f"[MQTT] Disconnected (rc={rc}). Paho will auto-reconnect.")
        self.mqtt_is_connected = False
        self.is_connecting_to_mqtt
     

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

        try:
            print(f"[MQTT] Message on {topic}: {payload}")
            data = json.loads(payload)
        except:
            print(f"[MQTT] Bad JSON: {payload}")
            return
        
        actionType = ""

        if actionType == "cmd":
            cmd = data.get("cmd")
            cam_id = data.get("params")[0] if "params" in data and len(data["params"]) > 0 else None
            print(f"[MQTT] Command for camera {cam_id}: {cmd}")

            # Map MQTT commands → CameraDevice commands
            if cmd == "connect":
                #cam_index_by_serial = get_camera_index_by_serial(cam.camera_serial)
                self.cameras[cam_id].connect_cmd()
            elif cmd == "disconnect":
                self.cameras[cam_id].disconnect_command = True
            elif cmd == "start_stream":
                self.cameras[cam_id].start_streaming_command = True
            elif cmd == "stop_stream":
                self.cameras[cam_id].stop_streaming_command = True
            elif cmd == "start_record":
                self.cameras[cam_id].start_recording_command = True
            elif cmd == "stop_record":
                self.cameras[cam_id].stop_recording_command = True
            else:
                print(f"[MQTT] Unknown command: {cmd}")

    # ----------------------------------------------------------------------
    # PUBLISHING (used by CameraDevices)
    # ----------------------------------------------------------------------

    def camera_state_callback(self,cam_index, state: CameraStatus):
        """
        Called by CameraDevice via a callback.
        Publishes to cameras/N/state
        """
        
        try:
            self.vis_sts.cameraStates[cam_index] = state
            #self.publish_vision_status()
        except Exception as e:
            print(f"[MQTT] Failed to publish state: {e}")

    def set_new_step_num(self, step_num: int):
        """Sets a new step number for the device."""
        self.device_data.Is.stepNum = step_num
        print(f"[SERVICE] stepNum: {step_num}")

    async def run_state_machine(self):
        """Main service loop."""
        print("[MQTT] Starting service loop...")
        last_publish_time_ms = 0

        while self._running :
            timeNowMs = int(time.time() * 1000)
            match self.device_data.Is.stepNum:
                case int(DeviceStates.ABORTING):
                    self.shutdown()
                    self.set_new_step_num(int(DeviceStates.INACTIVE))

                case int(DeviceStates.INACTIVE):
                    self.set_new_step_num(int(DeviceStates.RESETTING))

                case int(DeviceStates.RESETTING):
                    if self.mqtt_is_connected:
                        self.set_new_step_num(int(DeviceStates.IDLE))
                    elif not self.is_connecting_to_mqtt:
                        await self.connect_mqtt()

                case int(DeviceStates.IDLE):
                    pass
                case int(DeviceStates.RUNNING):
                    pass
            if timeNowMs - last_publish_time_ms >= 250:
                last_publish_time_ms = timeNowMs
                await self.publish_device_data()

            await asyncio.sleep(0.001)  # publish every second

    async def publish_device_data(self):
        """Publishes the overall vision status periodically."""
        if not self.mqtt_is_connected:
            return
        
        try:
            await self.publish_device_data_bridge_device_update()
            await self.publish_vision_status()
            await self.publish_cfg()

        except Exception as e:
            print(f"[MQTT] Error publishing vision status: {e}")
          
    async def publish_device_data_bridge_device_update(self):
        """Broadcasts the device data to the bridge."""
        topic = PublishTopics.UPDATE_DEVICE_DATA.value
        self.device_data.sts = self.vis_sts
        self.device_data.cfg = self.device_cfg
        device_dict = asdict(self.device_data)
        # replace the 'Is' key with 'is' to match expected casing
        device_dict['is'] = device_dict.pop('Is')
        # need to replace any key or sub key that has 'List' with 'list' to match expected casing
        device_dict['errors']['list'] = device_dict['errors'].pop('List')
        device_dict['warnings']['list'] = device_dict['warnings'].pop('List')


        message_dict = {
            "timestamp": int(time.time() * 1000),
            "payload": device_dict # This keeps the camera config as a nested dictionary, not a string
        }

        # 3. Encode the *entire* dictionary to a single JSON string *once*
        message_json = json.dumps(message_dict)
        print(f"Publishing DeviceData to {topic}: {message_json}")

        # 4. Publish the single, clean JSON string
        self.client.publish(topic, message_json, qos=0)

    async def publish_cfg(self):
        #tag = "machine.devices[13].Cfg"
        topic = DEVICE_TOPIC + '/cfg'
          # 1. Get the vis_cfg object as a standard Python dictionary
        cfg_dict = asdict(self.device_cfg)

        # 2. Build the final Python dictionary that has the "tag" and "value" keys
        message_dict = {
            "timestamp": int(time.time() * 1000),
            "payload": cfg_dict # This keeps the camera config as a nested dictionary, not a string
        }

        # 3. Encode the *entire* dictionary to a single JSON string *once*
        message_json = json.dumps(message_dict)
        #print(f"Publishing Cfg to {topic}: {message_json}")

        # 4. Publish the single, clean JSON string
        self.client.publish(topic, message_json, qos=0)

    async def publish_vision_status(self):
        print("publish_vision_status called")
        tag = "machine.visSts"
        topic = DEVICE_TOPIC + '/sts'
            # 1. Get the vis_sts object as a standard Python dictionary
        vis_sts_dict = asdict(self.vis_sts)

        # 2. Build the final Python dictionary that has the "tag" and "value" keys
        message_dict = {
            "timestamp": int(time.time() * 1000),
            "payload": vis_sts_dict # This keeps the camera config as a nested dictionary, not a string
        }

        # 3. Encode the *entire* dictionary to a single JSON string *once*
        message_json = json.dumps(message_dict)
        #print(f"Publishing Sts to {topic}: {message_json}")

        # 4. Publish the single, clean JSON string
        self.client.publish(topic, message_json, qos=0)


    # ----------------------------------------------------------------------
    # SERVICE LOOP
    # ----------------------------------------------------------------------
    async def run(self):
        """Main async supervisor loop."""

        # create thread for mqtt connect and handling
        mqtt_task = asyncio.create_task(self.connect_mqtt())
        run_state_machine_task = asyncio.create_task(self.run_state_machine())



        # Start all camera run-loops
        cam_tasks = [
            asyncio.create_task(cam.run())
            for cam in self.cameras.values()
        ]

        try:
            await asyncio.gather(*cam_tasks, run_state_machine_task, mqtt_task)
        except asyncio.CancelledError:
            pass
        finally:
            self._running = False
            self.shutdown()
            

    def shutdown(self):
        """Shuts down the service and its components."""
        print("[SERVICE] Shutting down...")
        self.is_connecting_to_mqtt = False
        self.shutdown_mqtt()


    def shutdown_mqtt(self):
        print("[MQTT] Shutting down...")
        
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