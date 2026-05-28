from enum import Enum, IntEnum
from dataclasses import dataclass, field

class CameraRecordingStates(IntEnum):
    STOPPED = 0
    RECORDING = 1
    SAVING = 2
    SAVED = 3
    STOPPING = 4

# create camera status structure which has isConnected, RecordingState and Stream State
@dataclass
class CameraStatus:
    isPluggedIn: bool = False
    isConnected: bool = False
    recordingState: int = CameraRecordingStates.STOPPED
    isStreaming: bool = False
    videoDeviceNodeString: str = "" #example is "dev/video0"