import asyncio
import aiomqtt
from config import MQTT_BROKER_IP, MQTT_PORT, MQTT_USERNAME, MQTT_PASSWORD, TOPIC_CAMERA_TASKS

async def main():
    async with aiomqtt.Client(hostname=MQTT_BROKER_IP, port=MQTT_PORT, username=MQTT_USERNAME, password=MQTT_PASSWORD) as client:
        await client.subscribe("temperature/#")
        await client.subscribe("humidity/#")
        async for message in client.messages:
            if message.topic.matches("humidity/inside"):
                print("A:", message.payload)
            if message.topic.matches("+/outside"):
                print("B:", message.payload)
            if message.topic.matches("temperature/#"):
                print("C:", message.payload)
        print("Disconnected from MQTT Broker")


asyncio.run(main())