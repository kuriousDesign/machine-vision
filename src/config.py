from enum import Enum
import os
from pickle import STRING
import sys
from pathlib import Path

from click import STRING
from dataclasses import dataclass, field
from device import *
from cameras.types import *
from ext_service import *

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from machine_cfg import MachineIds, getMachineCfg

# Load .env from parent directory
from dotenv import load_dotenv
load_dotenv(ROOT_DIR / ".env")


MQTT_FULL_URI = os.getenv("MQTT_LOCAL_BROKER_URI", "ws://localhost:9002/mqtt")
MQTT_BROKER_IP = os.getenv("MQTT_BROKER_IP", "localhost")
print(f"MQTT_BROKER_IP: {MQTT_BROKER_IP}")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
RECORDINGS_DIR = os.getenv("RECORDINGS_DIR", "/recordings_drive")
MAX_NUM_CAMERAS = 2
MAX_NUM_PLUGGED_IN_CAMERAS = 5

HEARTBEAT_TIMEOUT_MS = 3000  # 3 seconds

# GET MACHINE CONFIG FROM ENV
MACHINE_ID = os.getenv("MACHINE_ID", "UNKNOWN_MACHINE")

def normalize_machine_topic_id(machine_id: str) -> str:
    trimmed_machine_id = machine_id.strip()
    if not trimmed_machine_id:
        raise ValueError("MACHINE_ID is required to build MQTT topic namespaces")

    trailing_digits = ""
    for character in reversed(trimmed_machine_id):
        if character.isdigit():
            trailing_digits = character + trailing_digits
            continue
        break

    if trailing_digits:
        return trailing_digits

    sanitized_machine_id = "".join(
        character if character.isalnum() or character in {"_", "-"} else "_"
        for character in trimmed_machine_id
    ).strip("_")

    if not sanitized_machine_id:
        raise ValueError(f"Unable to normalize MACHINE_ID for MQTT topics: {machine_id}")

    return sanitized_machine_id


MACHINE_TOPIC_ROOT = f"machine_{normalize_machine_topic_id(MACHINE_ID)}"
BRIDGE_TOPIC_ROOT = f"bridge_{normalize_machine_topic_id(MACHINE_ID)}"
MACHINE_CFG = getMachineCfg(MachineIds(MACHINE_ID))
NUM_CAMERAS = MACHINE_CFG.numCameras
DEVICE_ID = MACHINE_CFG.deviceId
DEVICE_TOPIC = "ext_service/" + str(DEVICE_ID)
VISION_DEVICE_TOPIC_PATH = MACHINE_CFG.visionDeviceTopicPath.replace("machine/", f"{MACHINE_TOPIC_ROOT}/", 1)


def cameraIdToString(camera_id):
    return MACHINE_CFG.cameraCfgs[camera_id].name if 0 <= camera_id < len(MACHINE_CFG.cameraCfgs) else f"Unknown Camera Id {camera_id}"

class SubscriptionTopics(str, Enum):
    API_PLC_ACTION_REQ = DEVICE_TOPIC + '/api/action_req',
    MACHINE_VIS_STATUS = VISION_DEVICE_TOPIC_PATH + '/sts',
    MACHINE_VIS_META = VISION_DEVICE_TOPIC_PATH + '/meta',
    MACHINE_JOBDATA = f"{MACHINE_TOPIC_ROOT}/job"

class PublishTopics(str, Enum):
    UPDATE_DEVICE_DATA = BRIDGE_TOPIC_ROOT + "/api/update_device" + '/' + str(DEVICE_ID)
    UPDATE_DEVICE_INTERFACE = BRIDGE_TOPIC_ROOT + "/api/update_interface" + '/' + str(DEVICE_ID)

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


# DO NOT CHANGE: THESE ARE COUPLED TO PLC CLASSES
@dataclass
class CameraCfg:
    serialNumber: str = ""
    streamingPort: int = False
    id: int = 0

@dataclass
class VisCfg:
    numCameras: int = MACHINE_CFG.numCameras
    autoConnect: bool = False
    autoStream: bool = True
    cameraCfgs: list[CameraCfg] = field(default_factory=lambda: [CameraCfg(serialNumber=MACHINE_CFG.cameraCfgs[i].serialNumber, id=i, streamingPort=8000 + i) for i in range(0, MACHINE_CFG.numCameras)])


@dataclass
class VisSts(ExtServiceSts):
    cfg : VisCfg = field(default_factory=VisCfg)
    cameraStates: list[CameraStatus] = field(default_factory=list)
    isRecording: bool = False
    allDisconnected: bool = False
    pluggedInSerialNumbers:list[str] = field(default_factory=lambda: ["" for _ in range(MAX_NUM_PLUGGED_IN_CAMERAS)])

@dataclass
class VisMeta:
    recordingFolderPath: str = ""
    recordingFilenameMetaData: str = ""
    flipBit: bool = False

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