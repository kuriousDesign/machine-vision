import asyncio
import json
import paho.mqtt.client as mqtt
from config import MQTT_BROKER, MQTT_USERNAME, MQTT_PASSWORD
from cameras.camera_manager import CameraManager

class MqttClientManager:
    def __init__(self, camera_manager: CameraManager):
        self.camera_manager = camera_manager
        self.client = mqtt.Client()
        self.client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

    async def connect(self):
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.connect_async(MQTT_BROKER.replace("mqtt://","").split(":")[0], 9002)
        self.client.loop_start()

    def on_connect(self, client, userdata, flags, rc):
        print("Connected to MQTT Broker")
        client.subscribe("camera/tasks")

    def on_message(self, client, userdata, msg):
        payload = json.loads(msg.payload.decode())
        task = payload.get("task")
        args = payload.get("args", {})
        asyncio.create_task(self.handle_task(task, args))

    async def handle_task(self, task, args):
        cam = self.camera_manager.get_idle_camera()
        if not cam:
            print("No idle camera available")
            return
        if task == "record_stop_and_save":
            filename = f"{args['jobId']}_{args['batchId']}_{args['serialNumber']}_{args['partLocationId']}.mp4"
            await cam.start_recording(filename)
        elif task == "take_image":
            filename = f"{args['jobId']}_{args['batchId']}_{args['serialNumber']}_{args['partLocationId']}.png"
            await cam.take_image(filename)
