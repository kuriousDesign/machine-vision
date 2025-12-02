import asyncio
import sys
# Make sure you import PlatformError for robust Windows handling
from aiomqtt import Client as AsyncMqttClient, MqttError, PlatformError 
import aiomqtt

# --- Configuration (Replace with your actual config values or use environment variables) ---
MQTT_BROKER_IP = "192.168.86.24" 
MQTT_PORT = 1883
# ... (username/password configs remain the same)
# -----------------------------------------------------------------------------------------

print(f"Python Version: {sys.version}")
print(f"aiomqtt Version: {aiomqtt.__version__}")

async def check_mqtt_connection():
    reconnect_interval = 5  # seconds
    
    while True:
        try:
            print(f"Attempting to connect to MQTT Broker at {MQTT_BROKER_IP}:{MQTT_PORT}...")
            
            # Using 'host' or 'hostname' depending on your specific library install
            # We'll use 'host' as it's correct for v2.4.0
            async with AsyncMqttClient(
                host=MQTT_BROKER_IP, 
                port=MQTT_PORT,
            ) as client:
                print("-" * 40)
                print(f"✅ SUCCESS: Connected to MQTT Broker at {MQTT_BROKER_IP}:{MQTT_PORT}")
                print("Connection is active within the 'async with' block.")
                print("-" * 40)

                # Keep the connection alive for a moment
                await asyncio.sleep(60) 

        except (MqttError, PlatformError) as err: # Added PlatformError handling
            print("-" * 40)
            print(f"❌ FAILED: MQTT connection lost or failed: {err}")
            print(f"Retrying connection in {reconnect_interval} seconds...")
            print("-" * 40)
            await asyncio.sleep(reconnect_interval)
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            await asyncio.sleep(reconnect_interval)


if __name__ == "__main__":
    # >>>>>>>> THE WINDOWS FIX GOES HERE <<<<<<<<
    # Set the event loop policy specifically for Windows compatibility
    if sys.platform.startswith("win"):
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        except AttributeError:
            print("Warning: WindowsSelectorEventLoopPolicy not available in this Python version/install. Proceeding with default.")
            
    try:
        asyncio.run(check_mqtt_connection())
    except KeyboardInterrupt:
        print("Connection check stopped manually.")
