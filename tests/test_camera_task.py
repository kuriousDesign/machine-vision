import asyncio
import json
import paho.mqtt.client as mqtt

from src.config import MQTT_BROKER_IP, MQTT_PASSWORD, MQTT_PORT, MQTT_USERNAME

class MqttClientManager:
    def __init__(self):
        self.client = mqtt.Client()
        self.client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)  

    async def connect(self):
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.connect_async(MQTT_BROKER_IP, MQTT_PORT)
        self.client.loop_start()



def publish_camera_task(broker_address, topic, task_data):
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    
    client.connect(broker_address, 1883, 60)
    client.loop_start()
    
    message = json.dumps(task_data)
    client.publish(topic, message)
    
    client.loop_stop()
    client.disconnect()

if __name__ == "__main__":
    client = MqttClientManager()
    
    publish_camera_task(broker, topic, task)