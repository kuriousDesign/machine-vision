import os

MQTT_BROKER = os.getenv("MQTT_BROKER", "mqtt://host.docker.internal:9002")
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "admin")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "Admin1234")

VIDEO_PATH = os.getenv("VIDEO_PATH", "/app/videos")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongo:27017")
