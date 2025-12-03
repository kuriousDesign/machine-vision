import asyncio
from mqtt.mqtt_client import AsyncMqttClientManager
from src.cameras.camera_manager_old import CameraManager

async def main():
    # Initialize cameras
    camera_manager = CameraManager(camera_count=1)
    await camera_manager.start()

    # Initialize MQTT client
    mqtt_client = AsyncMqttClientManager(camera_manager=camera_manager)
    print("Connecting to MQTT Broker...")
    asyncio.create_task(mqtt_client.run())

    # Keep service alive
    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())
