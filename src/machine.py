from dataclasses import dataclass

@dataclass
class JobData:
    activeRecipeIndex: int = 0
    jobName: str = ""
    tubeTypeString: str = ""
    activeBatchNumber: int = 0
    lotQty: int = 0
    goodCnt: int = 0
    scrapCnt: int = 0
    setupStartTime: int = 0 #ULINT
    setupEndTime: int = 0 #ULINT
    setupCompleted: bool = False
    jobStartTime: int = 0 #ULINT
    jobEndTime: int = 0 #ULINT
    jobComplete: bool = False

    #HELPER METHER to convert ULINT to int
def convert_JobData_ULINT_to_int(data: dict) -> dict:
    data['setupStartTime'] = ULINT_to_int(data['setupStartTime'])
    data['setupEndTime'] = ULINT_to_int(data['setupEndTime'])
    data['jobStartTime'] = ULINT_to_int(data['jobStartTime'])
    data['jobEndTime'] = ULINT_to_int(data['jobEndTime'])
    return data

# ulint value comes as an array of two integers [low, high]
def ULINT_to_int(ulint_value: list[int]) -> int:
    #output just an int
    return ulint_value[1] + (ulint_value[0] << 32)

@dataclass
class Machine:
    estopCircuit_OK: bool
    estopCircuitDelayed_OK: bool
    fenceCircuit_OK: bool
    guardDoors_LOCKED: bool
    networkHealth_OK: bool
    ethercatMaster_OK: bool
    ethercatSlaves_OK: bool
    manualMode: bool
    supplyAir_OK: bool
    #cfg: MachineCfg
    #pdmSts: PartDataStatus
    #errors: SystemFaultData
    #warnings: SystemFaultData
    #taskQueue: TaskQueue
    #registeredDevices: list[DeviceRegistration]
    heartbeatPlc: int
    heartbeatHmi: int
    #machineLog: LogRecordData
    #recipeStore: RecipeStore
    job: JobData
    currentTimeMs: int
    activeUserId: int
    #activeRecipe: RecipeData