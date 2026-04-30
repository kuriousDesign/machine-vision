from config import MQTT_BROKER_IP, MQTT_PORT, VisCfg, cameraIdToString
import asyncio
from camera_service import CameraService
from cameras.camera_device import CameraDevice

async def main():
    # Create camera devices
    # for each camera in CAMERA_MAP, create a CameraDevice
    cameras = {}
    vis_cfg = VisCfg()
    for cam_cfg in vis_cfg.cameraCfgs:
        cam_id = cam_cfg.id
        camera_serial = cam_cfg.serialNumber
        camera_name = cameraIdToString(cam_id)
        stream_port = cam_cfg.streamingPort
        cameras[cam_id] = CameraDevice(cam_id, camera_name, camera_serial, stream_port=stream_port, auto_connect=vis_cfg.autoConnect, auto_start_stream=vis_cfg.autoStream)
        #cameras[cam_id].status_callback = state_callback
    print(f"[SERVICE] Created cameras: {list(cameras.keys())}")
    # Create service
    camera_service = CameraService(
        mqtt_host=MQTT_BROKER_IP,
        mqtt_port=MQTT_PORT,
        cameras= cameras,
    )

    # Run service
    await camera_service.run()

asyncio.run(main())
