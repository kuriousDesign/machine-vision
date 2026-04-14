from dataclasses import dataclass

ULINT_WARN_EVERY_N = 50
_ulint_invalid_count = 0


def _warn_invalid_ulint(field_name: str, value) -> None:
    global _ulint_invalid_count
    _ulint_invalid_count += 1
    if _ulint_invalid_count % ULINT_WARN_EVERY_N == 0:
        print(
            f"[MQTT][WARN] Invalid ULINT payload for '{field_name}' "
            f"(count={_ulint_invalid_count}, type={type(value).__name__}, sample={value!r})"
        )


@dataclass
class JobData:
    activeRecipeIndex: int = 0
    jobName: str = ""
    tubeTypeString: str = ""
    lotQty: int = 0
    goodCnt: int = 0
    scrapCnt: int = 0
    setupStartTime: str = ""
    setupEndTime: str = ""
    setupCompleted: bool = False
    jobStartTime: str = ""
    jobEndTime: str = ""
    jobCompleted: bool = False
    activeBatchNumber: int = 0
    batchId: str = ""
    workOrderId: str = ""
    lotId: str = ""
    salesOrderId: str = ""
    assemblyName: str = ""
    assemblyNumber: str = ""
    workInstruction: str = ""
    operationNumber: str = ""
    operatorId: str = ""


    #HELPER METHER to convert ULINT to int
def convert_JobData_ULINT_to_int(data: dict) -> dict:
    #data['setupStartTime'] = ULINT_to_int(data.get('setupStartTime'), 'setupStartTime')
    #data['setupEndTime'] = ULINT_to_int(data.get('setupEndTime'), 'setupEndTime')
    #data['jobStartTime'] = ULINT_to_int(data.get('jobStartTime'), 'jobStartTime')
    #data['jobEndTime'] = ULINT_to_int(data.get('jobEndTime'), 'jobEndTime')
    return data

# ulint value comes as an array of two integers [low, high]
# def ULINT_to_int(ulint_value, field_name: str = 'unknown') -> int:
#     # Accept common payload forms and fall back to 0 for missing/invalid values.
#     if isinstance(ulint_value, int):
#         return ulint_value

#     if isinstance(ulint_value, (list, tuple)):
#         if len(ulint_value) < 2:
#             _warn_invalid_ulint(field_name, ulint_value)
#             return 0
#         try:
#             low = int(ulint_value[0])
#             high = int(ulint_value[1])
#         except (TypeError, ValueError):
#             _warn_invalid_ulint(field_name, ulint_value)
#             return 0
#         return high + (low << 32)

#     if isinstance(ulint_value, dict):
#         low = ulint_value.get('low', ulint_value.get('lo', 0))
#         high = ulint_value.get('high', ulint_value.get('hi', 0))
#         try:
#             return int(high) + (int(low) << 32)
#         except (TypeError, ValueError):
#             _warn_invalid_ulint(field_name, ulint_value)
#             return 0

#     _warn_invalid_ulint(field_name, ulint_value)
#     return 0

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