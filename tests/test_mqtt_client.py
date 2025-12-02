import asyncio
import json
import sys
import os
from aiomqtt import Client as AsyncMqttClient, MqttError


# --- Configuration using Environment Variables/Defaults ---
MQTT_BROKER_IP = os.getenv("MQTT_BROKER_IP", "192.168.86.24") 
MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", None)
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", None)
TOPIC_CAMERA_TASKS = os.getenv("TOPIC_CAMERA_TASKS", "camera/tasks")
# --------------------------------------------------------

import asyncio
import aiomqtt


async def main():
    async with aiomqtt.Client(MQTT_BROKER_IP, port=MQTT_PORT, username=MQTT_USERNAME, password=MQTT_PASSWORD) as client:
        await client.subscribe("temperature/#")
        await client.subscribe("humidity/#")
        async for message in client.messages:
            if message.topic.matches("humidity/inside"):
                print("A:", message.payload)
            if message.topic.matches("+/outside"):
                print("B:", message.payload)
            if message.topic.matches("temperature/#"):
                print("C:", message.payload)


asyncio.run(main())