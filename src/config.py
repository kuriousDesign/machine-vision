from enum import Enum
import os
from dataclasses import dataclass, field
from device import *
from cameras.types import *
from ext_service import *

MQTT_BROKER_IP = os.getenv("MQTT_BROKER_IP", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")

VIDEO_PATH = os.getenv("VIDEO_PATH", "/app/videos")
CAMERA_MAP_NAME = os.getenv("CAMERA_MAP_NAME", "production")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://root:example@mongodb:27017")
DEVICE_ID = 13

DEVICE_TOPIC = "ext_service/" + str(DEVICE_ID)

# Create string enum for subscripton topics


class SubscriptionTopics(str, Enum):
    API_PLC_ACTION_REQ = DEVICE_TOPIC + '/api/action_req',
    #API_HMI_ACTION_REQ = "hmi/action_req/" + str(DEVICE_ID),
    #API_UPDATE_INTERFACE = DEVICE_TOPIC + '/api/update_interface',
    MACHINE_VIS_STATUS = "machine/1/4/10/13/sts"

class PublishTopics(str, Enum):
    UPDATE_DEVICE_DATA = "bridge/api/update_device" + '/' + str(DEVICE_ID)
    UPDATE_DEVICE_INTERFACE = "bridge/api/update_interface" + '/' + str(DEVICE_ID)

# SERIAL NUMBER MAP
CAMERA_MAP_PRODUCTION = {
    #0: "None",
    0: "200901010001",
    1: "AN20250306003",
    # 
    # 47E",
}

def cameraIdToString(camera_id):
    match camera_id:
        case 0:
            return "Short"
        case 1:
            return "Tall"
        case _:
            return f"Unknown Camera Id {camera_id}"

CAMERA_MAP_JAKES_HOUSE = {
    #0: "None",
    0: "A240125000107517",
    1: "6B9CA47E",
}

CAMERA_MAP = CAMERA_MAP_PRODUCTION if CAMERA_MAP_NAME == "production" else CAMERA_MAP_JAKES_HOUSE

HEARTBEAT_TIMEOUT_MS = 3000  # 3 seconds

MAX_NUM_CAMERAS = 2

class VisTasks(IntEnum):
    NONE = 0  # do not remove or change this
    START_RECORDING = 1  # param0: cameraId
    STOP_RECORDING = 2  # param0: cameraId (this does NOT save the recording)
    STOP_AND_SAVE_RECORDING = 3  # param0: cameraId, param1: partLocationId
    CONNECT = 4  # param0: cameraId
    DISCONNECT = 5  # param0: cameraId

def visTaskToString(task):
    match task:
        case VisTasks.NONE:
            return "None"
        case VisTasks.START_RECORDING:
            return "Start Recording"
        case VisTasks.STOP_RECORDING:
            return "Stop Recording"
        case VisTasks.STOP_AND_SAVE_RECORDING:
            return "Stop and Save Recording"
        case VisTasks.CONNECT:
            return "Connect"
        case VisTasks.DISCONNECT:
            return "Disconnect"
        case _:
            return f"Unknown Task {task}"

@dataclass
class VisCfg:
    numCameras: int = MAX_NUM_CAMERAS
    cameraSerialNumbers: list[str] = field(default_factory=lambda: [CAMERA_MAP[i] for i in range(0, MAX_NUM_CAMERAS)])


@dataclass
class VisSts(ExtServiceSts):
    cfg : VisCfg = field(default_factory=VisCfg)
    cameraStates: list[CameraStatus] = field(default_factory=list)
    isRecording: bool = False

@dataclass
class DeviceCfg:
    safetyZoneId: int = 0
    controllableByHmi: bool = True
    autoReset: bool = True
    ignore: bool = False


@dataclass
class Device:
    Is: DeviceSts = field(default_factory=DeviceSts)
    errors: DeviceFaultData = field(default_factory=DeviceFaultData)
    warnings: DeviceFaultData = field(default_factory=DeviceFaultData)
    task: ProcessData = field(default_factory=ProcessData)
    process: ProcessData = field(default_factory=ProcessData)  # read-only
    script: ProcessData = field(default_factory=ProcessData)  # read-only
    cfg: DeviceCfg = field(default_factory=DeviceCfg)
    sts: VisSts = field(default_factory=VisSts)
    #ApiOpcuaReqData: ApiOpcuaReqData = field(default_factory=ApiOpcuaReqData) # DO NOT UPDATE THIS FIELD