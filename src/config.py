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
    API_PLC_REQ = DEVICE_TOPIC + '/api/action_req',
    API_HMI_REQ = "hmi/action_req/" + str(DEVICE_ID),

class PublishTopics(str, Enum):
    UPDATE_DEVICE_DATA = "bridge/api/update_device" + '/' + str(DEVICE_ID)

# SERIAL NUMBER MAP
CAMERA_MAP_PRODUCTION = {
    #0: "None",
    1: "N/A",
    #2: "6B9CA
    # 
    # 47E",
}

CAMERA_MAP_JAKES_HOUSE = {
    #0: "None",
    1: "A240125000107517",
    2: "6B9CA47E",
}

CAMERA_MAP = CAMERA_MAP_PRODUCTION if CAMERA_MAP_NAME == "production" else CAMERA_MAP_JAKES_HOUSE

@dataclass
class VisCfg:
    numCameras: int = len(CAMERA_MAP)
    cameraSerialNumbers: list[str] = field(default_factory=lambda: [CAMERA_MAP[i] for i in range(1, len(CAMERA_MAP)+1)])

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


# TYPE Device :
# STRUCT
	
# 	Is: DeviceSts;
# 	Errors: DeviceFaultData;
# 	Warnings: DeviceFaultData;
# 	Registration: DeviceRegistration;
# 	Cfg: DeviceCfg;
# 	instants: DeviceInstants;
	
# 	ExecMethod:ProcessData;
#   Task:ProcessData;
# 	Process:ProcessData; //read-only
# 	Script:ProcessData; //read-only
	
# 	Mission:ProcessData;
# 	Settings: DeviceSettings;
#   	connectionStatus:BOOL;
	
# 	//Requests: ARRAY[0.. DeviceConstants.NUM_ACTION_TYPES] OF DeviceActionRequestData; //DEPRECATE SOON: this can be written to outside of the device fb;
# 	//ActionReq: ApiOpcuaReqData; //written by sender, read by this device (this is internal)
# 	//ActionResp: ApiOpcuaReqData; //written by this device, read by sender (this is internal)
# 	ApiOpcua: ApiOpcuaData;
# 	Udp: UdpData;
	
# END_STRUCT
# END_TYPE


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