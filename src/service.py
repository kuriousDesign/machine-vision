import asyncio
from camera_service import CameraService
from cameras.camera_device import CameraDevice
from config import CAMERA_MAP, MQTT_BROKER_IP, MQTT_PORT


async def main():
    # Create camera devices
    # for each camera in CAMERA_MAP, create a CameraDevice
    
    
    # Inject callback into cameras
    def state_callback(cam_index, state_message):
        service.publish_state(cam_index, {"state": state_message})

    cameras = {}
    for cam_id in CAMERA_MAP.keys():
        camera_serial = CAMERA_MAP[cam_id]
        cameras[cam_id] = CameraDevice(cam_id, camera_serial, stream_port=8000 + cam_id - 1)
        cameras[cam_id].status_callback = state_callback

    # Create service
    service = CameraService(
        mqtt_host=MQTT_BROKER_IP,
        mqtt_port=MQTT_PORT,
        cameras= cameras,
    )

    # Run service
    await service.run()

asyncio.run(main())
