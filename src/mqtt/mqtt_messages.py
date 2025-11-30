from pydantic import BaseModel
from typing import Optional

class StartRecordMsg(BaseModel):
    cmd: str  # "record_start"
    camera_id: str  # camera identifier (index or uri)
    jobId: str
    batchId: str
    serialNumber: str
    partLocationId: int

class StopAndSaveMsg(BaseModel):
    cmd: str  # "record_stop_and_save"
    camera_id: str
    jobId: str
    batchId: str
    serialNumber: str
    partLocationId: int

class TakeImageMsg(BaseModel):
    cmd: str  # "take_image"
    camera_id: str
    jobId: str
    batchId: str
    serialNumber: str
    partLocationId: int
