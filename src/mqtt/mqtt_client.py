import asyncio
import json
import sys
# Import Client and MqttError from aiomqtt instead of asyncio_mqtt
from aiomqtt import Client as AsyncMqttClient, MqttError, ProtocolVersion
import aiomqtt

from src.config import MQTT_BROKER_IP, MQTT_PORT, MQTT_USERNAME, MQTT_PASSWORD, TOPIC_CAMERA_TASKS
from src.cameras.camera_manager import CameraManager

print(f"Python Version: {sys.version}")
print(f"aiomqtt Version: {aiomqtt.__version__}")

class AsyncMqttClientManager:
    def __init__(self, camera_manager: CameraManager):
        self.camera_manager = camera_manager
        self.broker_ip = MQTT_BROKER_IP
        self.port = MQTT_PORT
        self.username = MQTT_USERNAME
        self.password = MQTT_PASSWORD
        self.topic_tasks = TOPIC_CAMERA_TASKS

    async def run(self):
        """
        The main loop for connecting, subscribing, and processing messages.
        Includes robust automatic reconnection logic.
        """
        reconnect_interval = 5  # seconds
        while True:
            try:
                # aiomqtt handles the connection as a simple async context manager
                print(f"Attempting to connect to MQTT Broker at {self.broker_ip}:{self.port}...")
                async with AsyncMqttClient(
                    hostname=self.broker_ip, # Use 'host' instead of 'hostname'
                    port=self.port,
                ) as client:
                    print(f"Connected to MQTT Broker at {self.broker_ip}:{self.port}")
                    # Start the listener task concurrently with the subscription
                    await self._subscribe_and_listen(client)
                    
            # aiomqtt raises its own specific exceptions
            except MqttError as err:
                print(f"MQTT connection lost or failed: {err}. Reconnecting in {reconnect_interval} seconds...")
                await asyncio.sleep(reconnect_interval)
            except Exception as e:
                # Catching general exceptions might not be ideal in production, 
                # but it ensures the reconnection loop keeps running.
                print(f"An unexpected error occurred: {e}. Reconnecting...")
                await asyncio.sleep(reconnect_interval)


    async def _subscribe_and_listen(self, client: AsyncMqttClient):
        """Internal method to manage subscriptions and message processing loop."""
        # aiomqtt simplifies subscribing and message iteration significantly
        async with client.messages() as messages:
            # Subscribing in aiomqtt is non-blocking and immediate
            await client.subscribe(self.topic_tasks)
            print(f"Subscribed to topic '{self.topic_tasks}'. Waiting for tasks...")

            # Asynchronously iterate over received messages
            async for message in messages:
                # In aiomqtt, message.payload is already bytes, no need for message.payload.decode()
                payload = json.loads(message.payload) 
                task = payload.get("task")
                args = payload.get("args", {})
                
                # Keep create_task for concurrent handling of camera operations
                asyncio.create_task(self.handle_task(task, args))


    async def handle_task(self, task, args):
        """Handles the camera tasks asynchronously."""
        cam = self.camera_manager.get_idle_camera()
        if not cam:
            print("No idle camera available")
            return
            
        try:
            if task == "record_stop_and_save":
                filename = f"{args['jobId']}_{args['batchId']}_{args['serialNumber']}_{args['partLocationId']}.mp4"
                await cam.start_recording(filename)
                print(f"Started recording: {filename}")
            elif task == "take_image":
                filename = f"{args['jobId']}_{args['batchId']}_{args['serialNumber']}_{args['partLocationId']}.png"
                await cam.take_image(filename)
                print(f"Captured image: {filename}")
            else:
                print(f"Unknown task received: {task}")

        except KeyError as e:
            print(f"Missing required argument in payload for task {task}: {e}")
        except Exception as e:
            print(f"Error handling task '{task}': {e}")


# Example of how you might run this new manager in your main application entry point:
if __name__ == "__main__":
    # You would initialize your CameraManager here
    dummy_camera_manager = CameraManager(1) 
    mqtt_manager = AsyncMqttClientManager(dummy_camera_manager)
    
    try:
        asyncio.run(mqtt_manager.run())
    except KeyboardInterrupt:
        print("Application stopped manually.")

