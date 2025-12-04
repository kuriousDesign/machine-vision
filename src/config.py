import os

MQTT_BROKER_IP = os.getenv("MQTT_BROKER_IP", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")

VIDEO_PATH = os.getenv("VIDEO_PATH", "/app/videos")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://root:example@mongodb:27017")

TOPIC_CAMERA_TASKS = "camera/tasks"

CAMERA_MAP = {
    #0: "None",
    1: "A240125000107517",
    2: "6B9CA47E",
}