import asyncio
from mqtt.mqtt_client import MqttClientManager
from cameras.camera_manager import CameraManager

async def main():
    # Initialize cameras
    camera_manager = CameraManager(camera_count=1)
    await camera_manager.start()

    # Initialize MQTT client
    mqtt_client = MqttClientManager(camera_manager=camera_manager)
    await mqtt_client.connect()

    # Keep service alive
    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())
