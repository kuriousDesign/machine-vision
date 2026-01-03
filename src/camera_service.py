import asyncio
from enum import Enum
import json
import threading
import time
from dacite import from_dict
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
        self.last_heartbate_update_ms = 0
        self.heartbeat_detected = False

        # Internal
        self._running = True
        self.device_topic = DEVICE_TOPIC
        self._mqtt_connect_event = threading.Event()

        # Start Paho networking thread
        self.client.loop_start()

        self.connect_mqtt()

    # ----------------------------------------------------------------------
    # MQTT CONNECT/DISCONNECT
    # ----------------------------------------------------------------------
    def connect_mqtt(self):
        """Begin initial connection attempt; Paho will auto-reconnect."""
     
        if not self.mqtt_host.strip() or not self.mqtt_port:
            print("[MQTT] ERROR: host is empty after cleanup → using localhost")
            host = "localhost"

        if self._running:
            try:
                print(f"[MQTT] Connecting to {self.mqtt_host}:{self.mqtt_port} ...")
                # self.client.on_connect = self._on_connect
                # self.client.on_disconnect = self._on_disconnect
                self.client.on_message = self._on_message
                self.client.connect(self.mqtt_host, self.mqtt_port, keepalive=10)
                self.is_connecting_to_mqtt = True
                return
            except Exception as e:
                print(f"[MQTT] Connect failed: {e}. Retrying in 1 sec...")
                time.sleep(1)

    def _on_connect(self, client, userdata, flags, rc):
        print(f"[MQTT] Connected to broker")
        for topic in SubscriptionTopics:
            self.client.subscribe(topic.value)
            print(f"[MQTT] Subscribed to topic:", topic.value)
            
        self._mqtt_connect_event.set()
        self.mqtt_is_connected = True
        self.is_connecting_to_mqtt = False
    

    def _on_disconnect(self, client, userdata, rc):
        print(f"[MQTT] Disconnected (rc={rc}). Paho will auto-reconnect.")
        self.mqtt_is_connected = False
        self.is_connecting_to_mqtt = False
        self._mqtt_connect_event.clear()
     

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
        #msg_payload = msg.payload.decode("utf-8")
        try:
            msg = json.loads(msg.payload)
            data = msg.get('payload')
            if data is None:
                print(f"[MQTT] Missing payload in message on topic {topic}")
                return
            #print(f"[MQTT] Received message on topic {topic}: {data}")
            pass
        except json.JSONDecodeError:
            print(f"[MQTT] Bad JSON: {msg.payload}")
            return
        #payload = msg_payload.payload

        if topic == SubscriptionTopics.MACHINE_VIS_STATUS.value:
            # convert data to VisSts data class
            if data is None:
                print(f"[MQTT] Empty MACHINE_VIS_STATUS payload")
                return
            sts: VisSts = from_dict(data_class=VisSts, data=data)
            self.vis_sts.iExtService.o = sts.iExtService.o

            #print(f"[MQTT] Updated MACHINE_VIS_STATUS: heartbeatVal={self.vis_sts.iExtService.o.heartbeatVal}")
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
        print("[MQTT] Starting run_state_machine loop...")
        last_publish_time_ms = 0

        

        while self._running :
            timeNowMs = int(time.time() * 1000)
            self.checkHeartbeat()
            if self.device_data.Is.stepNum > int(DeviceStates.RESETTING) and not self.mqtt_is_connected:
                self.set_new_step_num(int(DeviceStates.ABORTING))

            match self.device_data.Is.stepNum:
                case int(DeviceStates.ABORTING):
                    #self.shutdown()
                    self.set_new_step_num(int(DeviceStates.INACTIVE))

                case int(DeviceStates.INACTIVE):
                    self.set_new_step_num(int(DeviceStates.RESETTING))

                case int(DeviceStates.RESETTING):
                    if self.mqtt_is_connected:
                        self.set_new_step_num(int(DeviceStates.IDLE))
                    elif not self.is_connecting_to_mqtt:
                        self.connect_mqtt()
                        

                case int(DeviceStates.IDLE):
                    pass
                case int(DeviceStates.RUNNING):
                    pass
            if timeNowMs - last_publish_time_ms >= 1000:
                last_publish_time_ms = timeNowMs
                await self.publish_device_data()

            await asyncio.sleep(0.001)  # publish every second

    def checkHeartbeat(self):   
        self.vis_sts.iExtService.i.stepNum = self.device_data.Is.stepNum
        if self.vis_sts.iExtService.i.heartbeatVal != self.vis_sts.iExtService.o.heartbeatVal:
            self.vis_sts.iExtService.i.heartbeatVal = self.vis_sts.iExtService.o.heartbeatVal
            self.last_heartbate_update_ms = int(time.time() * 1000)
            if not self.heartbeat_detected:
                print(f"[MQTT] Heartbeat detected.")
                self.heartbeat_detected = True
                self.set_new_step_num(int(DeviceStates.RUNNING))
            #print(f"[MQTT] Updated heartbeatVal to {self.vis_sts.iExtService.i.heartbeatVal}")
        elif self.heartbeat_detected and int(time.time() * 1000) - self.last_heartbate_update_ms > HEARTBEAT_TIMEOUT_MS:
            if not self.heartbeat_detected:
                print(f"[MQTT] Heartbeat timeout detected.")
                self.heartbeat_detected = True
                self.set_new_step_num(int(DeviceStates.ABORTING))

    async def publish_device_data(self):
        """Publishes the overall vision status periodically."""
        self.vis_sts.iExtService.i.stepNum = self.device_data.Is.stepNum
        self.device_data.sts = self.vis_sts
        self.device_data.cfg = self.device_cfg

        if not self.mqtt_is_connected:
            return
        
        try:
            #await self.publish_device_data_bridge_device_update()
            await self.publish_vision_status()
            #await self.publish_cfg()

        except Exception as e:
            print(f"[MQTT] Error publishing vision status: {e}")
          
    async def publish_device_data_bridge_device_update(self):
        """Broadcasts the device data to the bridge."""
        base_topic = PublishTopics.UPDATE_DEVICE_DATA.value
        
        
        device_dict = asdict(self.device_data)
        # replace the 'Is' key with 'is' to match expected casing
        device_dict['is'] = device_dict.pop('Is')
        # need to replace any key or sub key that has 'List' with 'list' to match expected casing
        device_dict['errors']['list'] = device_dict['errors'].pop('List')
        device_dict['warnings']['list'] = device_dict['warnings'].pop('List')

        #for each key in device_dict, add key to end of topic
        for key in device_dict:
            topic = f"{base_topic}/{key}".lower()
            message_dict = {
                "timestamp": int(time.time() * 1000),
                "payload": device_dict[key] # This keeps the camera config as a nested dictionary, not a string
            }
            #Encode the *entire* dictionary to a single JSON string *once*
            message_json = json.dumps(message_dict)
            #print(f"Publishing DeviceData to {topic}: {message_json}")

            # Publish the single, clean JSON string
            self.client.publish(topic, message_json, qos=0)

    async def publish_cfg(self):
        #tag = "machine.devices[13].Cfg"
        topic = PublishTopics.UPDATE_DEVICE_DATA.value + '/cfg'
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
        #tag = "machine.visSts"
        topic = PublishTopics.UPDATE_DEVICE_DATA.value + '/sts'
            # 1. Get the vis_sts object as a standard Python dictionary
        vis_sts_dict = asdict(self.vis_sts)
        #print(f"[MQTT] Publishing vision status with heartbeatVal={vis_sts_dict['iExtService']['i']['heartbeatVal']}")
        #print(f"[MQTT] step number: {vis_sts_dict['iExtService']['i']['stepNum']}")

        # 2. Build the final Python dictionary that has the "tag" and "value" keys
        message_dict = {
            "timestamp": int(time.time() * 1000),
            "payload": vis_sts_dict # This keeps the camera config as a nested dictionary, not a string
        }

        # 3. Encode the *entire* dictionary to a single JSON string *once*
        message_json = json.dumps(message_dict)
        #print(f"Publishing Sts to {topic}: {message_json}")

        # 4. Publish the single, clean JSON string
        self.client.publish(topic, message_json, qos=1)


    # ----------------------------------------------------------------------
    # SERVICE LOOP
    # ----------------------------------------------------------------------
    async def run(self):
        """Main async supervisor loop."""
        # self.connect_mqtt()

        # # Wait until connected
        # while not self._mqtt_connect_event.is_set():
        #     await asyncio.sleep(0.1)

        print("[MQTT] Service started. MQTT connected.")

        # create thread for mqtt connect and handling
        #mqtt_task = asyncio.create_task(self.connect_mqtt())
        run_state_machine_task = asyncio.create_task(self.run_state_machine())

        # Start all camera run-loops
        cam_tasks = [
            asyncio.create_task(cam.run())
            for cam in self.cameras.values()
        ]

        try:
            await asyncio.gather(*cam_tasks, run_state_machine_task)
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