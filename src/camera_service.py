import asyncio
from datetime import datetime
from enum import Enum
import json
from re import match
import threading
import time
from unittest import case
from dacite import from_dict
import paho.mqtt.client as mqtt
from dataclasses import asdict
from cameras.camera_device import RECORDINGS_DIR, TEMP_RECORDING_DIR, CameraDevice, CameraRecordingStates
from cameras.camera_names import *
from config import *
from machine import JobData, convert_JobData_ULINT_to_int


DEFAULT_TASK_TIMEOUT_MS = 3000
STOP_RECORDING_TASK_TIMEOUT_MS = 10000
STOP_AND_SAVE_TASK_TIMEOUT_MS = 60000
TASK_WAIT_LOG_INTERVAL_MS = 5000


class CameraService:
    def __init__(self, mqtt_host: str, mqtt_port: int, cameras: dict[int, CameraDevice]):
        """
        cameras: dict[int, CameraDevice]
        """
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.cameras: dict[int, CameraDevice] = cameras
        # add status callback to cameras
        self.device_cfg = DeviceCfg()
        self.job = JobData()
        self.vis_sts = VisSts()
        self.vis_meta = VisMeta()
        self.vis_cfg = VisCfg()
        self.vis_sts.cfg = self.vis_cfg
        #self.vis_sts.cameraStates.append(CameraStatus()) # dummy for index 0
        self.device_data = Device()
        self.device_data.cfg = self.device_cfg
        self.device_data.sts = self.vis_sts
        self.device_data.Is.stepNum = int(DeviceStates.ABORTING)

      
        for cam in self.cameras.values():
            self.vis_sts.cameraStates.append(CameraStatus())
            cam.state_callback = self.camera_state_callback


        # MQTT client
        self.client = mqtt.Client()
        self.mqtt_is_connected = False
        self.is_connecting_to_mqtt = False
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.last_heartbate_update_ms = 0
        self.heartbeat_detected = False

        # Internal
        self._running = True
        self.device_topic = DEVICE_TOPIC
        self._mqtt_connect_event = threading.Event()

        self.prev_task_req_id = 0
        self.task_start_time_ms = 0
        self.cam_id = 0
        self.video_index_id = 0
        self._last_task_wait_log_ms = 0

        # Start Paho networking thread
        self.client.loop_start()

            # Start the hardware monitor in its own thread
        self.hw_thread = threading.Thread(target=self._hardware_monitor_worker, daemon=True)
        self.hw_thread.start()

        self.connect_mqtt()

    # ----------------------------------------------------------------------
    # MQTT CONNECT/DISCONNECT
    # ----------------------------------------------------------------------
    def connect_mqtt(self):
        """Begin initial connection attempt; Paho will auto-reconnect."""
     
        if not self.mqtt_host.strip() or not self.mqtt_port:
            print("[MQTT] ERROR: host is empty after cleanup → using localhost")
            host = "localhost"

        if self._running:
            try:
                print(f"[MQTT] Connecting to {self.mqtt_host}:{self.mqtt_port} ...")
                # self.client.on_connect = self._on_connect
                # self.client.on_disconnect = self._on_disconnect
                self.client.on_message = self._on_message
                self.client.connect(self.mqtt_host, self.mqtt_port, keepalive=10)
                self.is_connecting_to_mqtt = True
                return
            except Exception as e:
                print(f"[MQTT] Connect failed: {e}. Retrying in 1 sec...")
                time.sleep(1)

    def _on_connect(self, client, userdata, flags, rc):
        print(f"[MQTT] Connected to broker")
        for topic in SubscriptionTopics:
            self.client.subscribe(topic.value)
            print(f"[MQTT] Subscribed to topic:", topic.value)
            
        self._mqtt_connect_event.set()
        self.mqtt_is_connected = True
        self.is_connecting_to_mqtt = False
    

    def _on_disconnect(self, client, userdata, rc):
        print(f"[MQTT] Disconnected (rc={rc}). Paho will auto-reconnect.")
        self.mqtt_is_connected = False
        self.is_connecting_to_mqtt = False
        self._mqtt_connect_event.clear()

    def update_cameras_plugged_in_status(self):
        # if any cameras are connected, do not update the plugged in status, to avoid overwriting with bad data from the tool
        for cam in self.cameras.values():
            if cam.state.isConnected:
                return

        #print(f"[SERVICE] Updating plugged in cameras list...")
        plugged_cameras_list = get_unique_camera_names_and_indices()
        
        # If the tool failed or returned nothing, don't update anything

        if not plugged_cameras_list and len(self.cameras) > 0:
            self.vis_sts.pluggedInSerialNumbers = ["" for _ in range(MAX_NUM_PLUGGED_IN_CAMERAS)]
            return
        
        for plugged_camera in plugged_cameras_list:
            if plugged_camera['serial'] not in self.vis_sts.pluggedInSerialNumbers:
                for i in range(MAX_NUM_PLUGGED_IN_CAMERAS):
                    if self.vis_sts.pluggedInSerialNumbers[i] == "":
                        self.vis_sts.pluggedInSerialNumbers[i] = plugged_camera['serial']
                        break
        

        for cam in self.cameras.values():
            is_plugged_in = any(camera['serial'] == cam.camera_serial for camera in plugged_cameras_list)
          
            if is_plugged_in != self.vis_sts.cameraStates[cam.id].isPluggedIn:
                
                status = "plugged in" if is_plugged_in else "unplugged"
                print(f"[SERVICE] Camera {cam.camera_name} ({cam.camera_serial}) {status}.")
                
                # Logic: If unplugged, force a disconnect command to the device
                if not is_plugged_in:
                    cam.disconnect_command = True

            self.vis_sts.cameraStates[cam.id].isPluggedIn = is_plugged_in

    def handleTaskRequest(self, ext_service_o: IExtServiceOutputs):
        """Checks if PLC has requested a task change via the stepNum."""
        if ext_service_o.taskReqId != 0 and self.prev_task_req_id != ext_service_o.taskReqId:
            if self.vis_sts.iExtService.i.activeTaskId == 0:
                self.task_start_time_ms = int(time.time() * 1000)
                self.vis_sts.iExtService.i.activeTaskId = ext_service_o.taskReqId
                self.vis_sts.iExtService.i.uniqueTaskActiveId = ext_service_o.uniqueTaskReqId
                self.vis_sts.iExtService.i.taskStepNum = 0
                cam_id = round(ext_service_o.taskParam0)
                self.cam_id = cam_id
                index_id = round(ext_service_o.taskParam1)
                self.video_index_id = index_id
                print(f"[SERVICE] New task requested: {visTaskToString(ext_service_o.taskReqId)} for camera {cam_id}")
                match ext_service_o.taskReqId:
                    case int(VisTasks.START_RECORDING):
                        print(
                            f"[SERVICE] Start Recording request details: cam={cam_id} "
                            f"state={self.cameras[cam_id].state.recordingState}"
                        )
                        self.cameras[cam_id].start_recording_command = True
                    case int(VisTasks.STOP_RECORDING):
                        print(
                            f"[SERVICE] Stop Recording request details: cam={cam_id} "
                            f"state={self.cameras[cam_id].state.recordingState} "
                            f"worker_active={self.cameras[cam_id].is_record_worker_active()}"
                        )
                        self.cameras[cam_id].stop_recording_command = True
                    case int(VisTasks.STOP_AND_SAVE_RECORDING):
                        index_id = round(ext_service_o.taskParam1)
                        self.video_index_id = index_id
                        try:
                            self.cameras[cam_id].save_filename = self.build_save_filename(self.vis_meta, index_id)
                        except PermissionError as e:
                            fallback_subfolder = os.path.join(
                                TEMP_RECORDING_DIR,
                                "saved",
                            )
                            os.makedirs(fallback_subfolder, exist_ok=True)
                            fallback_timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                            fallback_filename = os.path.join(
                                fallback_subfolder,
                                f"Tube{index_id:02d}_{fallback_timestamp}.mp4",
                            )
                            self.cameras[cam_id].save_filename = fallback_filename
                            print(f"[SERVICE] Save path permission denied ({e}). Falling back to {fallback_filename}")
                        
                        print(
                            f"[SERVICE] Stop and Save request details: cam={cam_id} "
                            f"state={self.cameras[cam_id].state.recordingState} "
                            f"target={self.cameras[cam_id].save_filename}"
                        )
                        self.cameras[cam_id].stop_and_save_recording_command = True
                    case int(VisTasks.CONNECT):
                        self.cameras[cam_id].connect_command = True
                    case int(VisTasks.DISCONNECT):
                        self.cameras[cam_id].disconnect_command = True
                    case _:
                        print(f"[SERVICE] Unknown task request: {ext_service_o.taskReqId}")
            else:
                print(f"[SERVICE] Task request {visTaskToString(ext_service_o.taskReqId)} ignored because another task {visTaskToString(self.vis_sts.iExtService.i.activeTaskId)} is active.")

        self.prev_task_req_id = ext_service_o.taskReqId

    # ----------------------------------------------------------------------
    # MESSAGE HANDLER
    # ----------------------------------------------------------------------
    def _on_message(self, client, userdata, msg):
        """
        Handles messages like: cameras/2/cmd
        Payload example:
        { "cmd": "start_stream" }
        """
        

        topic = msg.topic
        #msg_payload = msg.payload.decode("utf-8")
        try:
            msg = json.loads(msg.payload)
            data = msg.get('payload')
            if data is None:
                #print(f"[MQTT] Missing payload key in message on msg {msg}")
                # remove topic from msg and then 
                data = msg
            #print(f"[MQTT] Received message on topic {topic}: {data}")
            pass
        except json.JSONDecodeError:
            print(f"[MQTT] Bad JSON: {msg.payload}")
            return
        #payload = msg_payload.payload
        try:
            match topic:
                case SubscriptionTopics.MACHINE_VIS_STATUS.value:
                # convert data to VisSts data class
                    if data is None:
                        print(f"[MQTT] Empty MACHINE_VIS_STATUS payload")
                        return
                    vis_sts_from_plc: VisSts = from_dict(data_class=VisSts, data=data)
                    # only copy the iExtService.o part of the status, since that's where the PLC writes heartbeat and step number
                    self.vis_sts.iExtService.o = vis_sts_from_plc.iExtService.o

                    self.handleTaskRequest(self.vis_sts.iExtService.o)

                    #print(f"[MQTT] Updated MACHINE_VIS_STATUS: heartbeatVal={self.vis_sts.iExtService.o.heartbeatVal}")
                    return

                case SubscriptionTopics.MACHINE_VIS_META.value:
                # convert data to VisMeta data class
                    if data is None:
                        print(f"[MQTT] Empty MACHINE_VIS_META payload")
                        return
                    vis_meta_from_plc: VisMeta = from_dict(data_class=VisMeta, data=data)
                    self.vis_meta = vis_meta_from_plc
                    #print(f"[MQTT] Updated MACHINE_VIS_META: recordingFolderPath={self.vis_meta.recordingFolderPath}, recordingFilenameMetaData={self.vis_meta.recordingFilenameMetaData}")
                    return
            
                case SubscriptionTopics.MACHINE_JOBDATA.value:
                    # convert data to JobData data class
                    if data is None:
                        print(f"[MQTT] Empty MACHINE_JOBDATA payload")
                        return
                    if not isinstance(data, dict):
                        print(f"[MQTT] Invalid MACHINE_JOBDATA payload type: {type(data).__name__}")
                        return
                    # ULINT comes as an array from the PLC, multiple tags of job data (anythign iwth time)
                    #converted_data = JobData(data).convert_ULINT_to_int()
                    # convert ULINT fields to int
                    #converted_data = convert_JobData_ULINT_to_int(data)
               

                    self.job = from_dict(data_class=JobData, data=data)
                    # print startTime
                    #print(f"[MQTT] Updated MACHINE_JOBDATA: setupStartTime={self.job.setupStartTime}")
                    #print(f"[MQTT] Updated MACHINE_JOBDATA: jobName={self.job.jobName}, lotQty={self.job.lotQty}")

                case _:
                    print(f"[MQTT] Unknown subscription topic: {topic}, sent a message")

        except Exception as e:
            print(f"[MQTT] Error processing message: {e}")

        # if topic == SubscriptionTopics.API_HMI_ACTION_REQ.value:
        #     actionType = ""

        #     if actionType == "cmd":
        #         cmd = data.get("cmd")
        #         cam_id = data.get("params")[0] if "params" in data and len(data["params"]) > 0 else None
        #         print(f"[MQTT] Command for camera {cam_id}: {cmd}")

        #         # Map MQTT commands → CameraDevice commands
        #         if cmd == "connect":
        #             #cam_index_by_serial = get_camera_index_by_serial(cam.camera_serial)
        #             self.cameras[cam_id].connect_cmd()
        #         elif cmd == "disconnect":
        #             self.cameras[cam_id].disconnect_command = True
        #         elif cmd == "start_stream":
        #             self.cameras[cam_id].start_streaming_command = True
        #         elif cmd == "stop_stream":
        #             self.cameras[cam_id].stop_streaming_command = True
        #         elif cmd == "start_record":
        #             self.cameras[cam_id].start_recording_command = True
        #         elif cmd == "stop_record":
        #             self.cameras[cam_id].stop_recording_command = True
        #         else:
        #             print(f"[MQTT] Unknown command: {cmd}")

    # ----------------------------------------------------------------------
    # PUBLISHING (used by CameraDevices)
    # ----------------------------------------------------------------------

    def camera_state_callback(self,cam_index, state: CameraStatus):
        """
        Called by CameraDevice via a callback.
        Publishes to cameras/N/state
        """
        
        try:
            self.vis_sts.cameraStates[cam_index] = state
            #self.publish_vision_status()
        except Exception as e:
            print(f"[MQTT] Failed to publish state: {e}")

    def set_new_step_num(self, step_num: int):
        """Sets a new step number for the device."""
        self.device_data.Is.stepNum = step_num
        print(f"[SERVICE] stepNum: {step_num}")

    def checkAllCamerasDisconnected(self):  
        all_disconnected = True
        for cam in self.cameras.values():
            if cam.state.isConnected:
                all_disconnected = False

        self.vis_sts.allDisconnected = all_disconnected

    def build_save_filename(self, meta: VisMeta, index: int):
        """Builds the save filename based on the meta data."""
        if not meta.recordingFolderPath:
            raise ValueError("Recording folder path is empty in VisMeta.")
        if not meta.recordingFilenameMetaData:
            print("Recording filename metadata is empty in VisMeta.")
        subfolder = os.path.join(RECORDINGS_DIR, meta.recordingFolderPath)
        #print(f"[SERVICE] Creating subfolder for recordings: {subfolder}")
        os.makedirs(subfolder, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        save_filename = os.path.join(
            subfolder,
            f"Tube{index:02d}_{timestamp}_{meta.recordingFilenameMetaData}.mp4",
        )
        #print(f"[SERVICE] Save filename built: {save_filename}")
        return save_filename


    def build_save_filename_deprecated(self, job: JobData, part_location_id: int):
        """Builds the save filename based on the job data."""

        # saved videos or stored in RECORDINGS_DIR in subfolders based on job.TubeTypeString, job SetupTime, job ActiveBatchNumber and part_location_id
        #convert ms after 1970 to local string with  don't use seconds or ms
        #start_time_str = job.setupStartTime
        #format like this: YYYY_MM_DD_HHMM where HH is military time
        job_start_str= "Job_" + job.jobName
        raw_batch_id = job.batchId.strip()
        batch_folder_id = raw_batch_id.zfill(3) if raw_batch_id.isdigit() else raw_batch_id
        if not batch_folder_id:
            batch_folder_id = str(job.activeBatchNumber).zfill(3)
        #job_name_str = "Job_" + job.jobName
        subfolder = os.path.join(RECORDINGS_DIR, "TubeType_" + job.tubeTypeString, job_start_str, "Batch_" + batch_folder_id)
        os.makedirs(subfolder, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        save_filename = os.path.join(
            subfolder,
            f"Tube{part_location_id:02d}_{timestamp}.mp4",
        )
        return save_filename

    def get_active_task_timeout_ms(self, task_id: int) -> int:
        if task_id == int(VisTasks.STOP_RECORDING):
            return STOP_RECORDING_TASK_TIMEOUT_MS
        if task_id == int(VisTasks.STOP_AND_SAVE_RECORDING):
            return STOP_AND_SAVE_TASK_TIMEOUT_MS
        return DEFAULT_TASK_TIMEOUT_MS


    def monitorActiveTask(self):
        """Monitors the active task and updates the state accordingly."""
        cam_id = self.cam_id
        part_location_id = self.video_index_id
        task_was_successful = False
        match self.vis_sts.iExtService.i.activeTaskId:
            case int(VisTasks.NONE):
                pass
            case int(VisTasks.START_RECORDING):
                task_was_successful = self.cameras[cam_id].state.recordingState == CameraRecordingStates.RECORDING
            case int(VisTasks.STOP_RECORDING):
                task_was_successful = (
                    self.cameras[cam_id].state.recordingState == CameraRecordingStates.STOPPED
                    and not self.cameras[cam_id].is_record_worker_active()
                    and self.cameras[cam_id].is_record_worker_done()
                )
            case int(VisTasks.STOP_AND_SAVE_RECORDING):
                task_was_successful = (
                    self.cameras[cam_id].state.recordingState == CameraRecordingStates.SAVED
                    and not self.cameras[cam_id].is_record_worker_active()
                    and self.cameras[cam_id].is_record_worker_done()
                    and self.cameras[cam_id]._rec_worker_save_success is True
                )
            case int(VisTasks.CONNECT):
                task_was_successful = self.cameras[cam_id].state.isConnected
            case int(VisTasks.DISCONNECT):
                task_was_successful = not self.cameras[cam_id].state.isConnected
            case _:
                print(f"[SERVICE] Unknown Active Task Id: {self.vis_sts.iExtService.i.activeTaskId}")

        if self.vis_sts.iExtService.i.activeTaskId in (
            int(VisTasks.STOP_RECORDING),
            int(VisTasks.STOP_AND_SAVE_RECORDING),
        ) and not task_was_successful:
            now_ms = time.time() * 1000
            if now_ms - self._last_task_wait_log_ms >= TASK_WAIT_LOG_INTERVAL_MS:
                print(
                    f"[SERVICE] Waiting for task {visTaskToString(self.vis_sts.iExtService.i.activeTaskId)}: "
                    f"cam={cam_id} state={self.cameras[cam_id].state.recordingState} "
                    f"worker_active={self.cameras[cam_id].is_record_worker_active()} "
                    f"worker_done={self.cameras[cam_id].is_record_worker_done()} "
                    f"save_success={self.cameras[cam_id]._rec_worker_save_success} "
                    f"last_error={self.cameras[cam_id]._rec_worker_last_error}"
                )
                self._last_task_wait_log_ms = now_ms

        if task_was_successful:
            print(f"[SERVICE] Completed active task {visTaskToString(self.vis_sts.iExtService.i.activeTaskId)} with unique ID {self.vis_sts.iExtService.i.uniqueTaskActiveId}")
            self.prev_task_req_id = self.vis_sts.iExtService.i.activeTaskId
            self.vis_sts.iExtService.i.lastTaskId = self.vis_sts.iExtService.i.uniqueTaskActiveId
            self.vis_sts.iExtService.i.activeTaskId = 0
            self.vis_sts.iExtService.i.taskStepNum = 0
            self._last_task_wait_log_ms = 0
            

        elif (
            self.vis_sts.iExtService.i.activeTaskId != 0
            and time.time() * 1000 - self.task_start_time_ms > self.get_active_task_timeout_ms(self.vis_sts.iExtService.i.activeTaskId)
        ):
            print(
                f"[SERVICE] Resetting active task {visTaskToString(self.vis_sts.iExtService.i.activeTaskId)} "
                f"due to timeout after {self.get_active_task_timeout_ms(self.vis_sts.iExtService.i.activeTaskId)} ms."
            )
            self.vis_sts.iExtService.i.activeTaskId = 0
            self.vis_sts.iExtService.i.taskStepNum = 0
            self._last_task_wait_log_ms = 0

    async def run_state_machine(self):
        """Main service loop."""
        print("[MQTT] Starting run_state_machine loop...")
        last_publish_time_ms = 0

        

        while self._running :
            timeNowMs = int(time.time() * 1000)
            self.checkHeartbeat()
            self.checkAllCamerasDisconnected()

            if self.device_data.Is.stepNum > int(DeviceStates.RESETTING) and not self.mqtt_is_connected:
                self.set_new_step_num(int(DeviceStates.ABORTING))

            if self.vis_sts.iExtService.o.deviceCmdReqId == DeviceCmds.KILL.value and self.device_data.Is.stepNum > int(DeviceStates.INACTIVE):
                self.set_new_step_num(int(DeviceStates.ABORTING))

            if self.vis_sts.iExtService.o.deviceCmdReqId == DeviceCmds.CLEAR.value:
                self.device_data.errors = DeviceFaultData() #this clears the errors

            match self.device_data.Is.stepNum:
                case int(DeviceStates.ABORTING):
                    #self.shutdown()
                    self.set_new_step_num(int(DeviceStates.INACTIVE))
                    # disconect all cameras
                    for cam in self.cameras.values():
                        cam.disconnect_command = True

                    if self.vis_sts.allDisconnected:
                        self.set_new_step_num(int(DeviceStates.INACTIVE))

                case int(DeviceStates.INACTIVE):
                    if self.vis_sts.iExtService.o.deviceCmdReqId == DeviceCmds.RESET.value:
                        self.set_new_step_num(int(DeviceStates.RESETTING))

                case int(DeviceStates.RESETTING):
                    if self.mqtt_is_connected:
                        self.set_new_step_num(int(DeviceStates.IDLE))
                    elif not self.is_connecting_to_mqtt:
                        self.connect_mqtt()
                        
                case int(DeviceStates.IDLE):
                    self.monitorActiveTask()

                case int(DeviceStates.RUNNING):
                    if self.vis_sts.iExtService.o.deviceCmdReqId == DeviceCmds.STOP.value:
                        self.set_new_step_num(int(DeviceStates.STOPPING))

                case int(DeviceStates.STOPPING):
                    # Handle stopping logic here
                    # stop recording all cameras if camera recording state is not stopped
                    all_stopped = True
                    for cam in self.cameras.values():
                        if cam.state.recordingState != CameraRecordingStates.STOPPED:
                            cam.stop_recording_command = True
                            all_stopped = False

                    if all_stopped:
                        self.set_new_step_num(int(DeviceStates.IDLE))

            if timeNowMs - last_publish_time_ms >= 1000:
                last_publish_time_ms = timeNowMs
                await self.publish_device_data()

            await asyncio.sleep(0.001)  # publish every second

    def _hardware_monitor_worker(self):
        """Periodically check hardware status without blocking MQTT or Cameras."""
        print("[SERVICE] Hardware monitor thread started.")
        while True:
            try:
                self.update_cameras_plugged_in_status()
            except Exception as e:
                print(f"[SERVICE] HW Monitor Error: {e}")
            
            # Check every 2-5 seconds. 
            # Frequent enough to catch a plug/unplug, slow enough to stay stable.
            time.sleep(3.0) 


    def checkHeartbeat(self):   
        self.vis_sts.iExtService.i.stepNum = self.device_data.Is.stepNum
        if self.vis_sts.iExtService.i.heartbeatVal != self.vis_sts.iExtService.o.heartbeatVal:
            self.vis_sts.iExtService.i.heartbeatVal = self.vis_sts.iExtService.o.heartbeatVal
            self.last_heartbate_update_ms = int(time.time() * 1000)
            if not self.heartbeat_detected:
                print(f"[MQTT] Heartbeat detected.")
                self.heartbeat_detected = True
                #self.set_new_step_num(int(DeviceStates.RUNNING))
            #print(f"[MQTT] Updated heartbeatVal to {self.vis_sts.iExtService.i.heartbeatVal}")
        elif self.heartbeat_detected and int(time.time() * 1000) - self.last_heartbate_update_ms > HEARTBEAT_TIMEOUT_MS:
            if not self.heartbeat_detected:
                print(f"[MQTT] Heartbeat timeout detected.")
                self.heartbeat_detected = True
                self.set_new_step_num(int(DeviceStates.ABORTING))

    async def publish_device_data(self):
        """Publishes the overall vision status periodically."""
        self.vis_sts.iExtService.i.stepNum = self.device_data.Is.stepNum
        self.device_data.sts = self.vis_sts
        self.device_data.cfg = self.device_cfg

        if not self.mqtt_is_connected:
            return
        
        try:
            #await self.publish_device_data_bridge_device_update()
            await self.publish_vision_status()
            #await self.publish_cfg()

        except Exception as e:
            print(f"[MQTT] Error publishing vision status: {e}")
          
    async def publish_device_data_bridge_device_update(self):
        """Broadcasts the device data to the bridge."""
        base_topic = PublishTopics.UPDATE_DEVICE_DATA.value
        
        
        device_dict = asdict(self.device_data)
        # replace the 'Is' key with 'is' to match expected casing
        device_dict['is'] = device_dict.pop('Is')
        # need to replace any key or sub key that has 'List' with 'list' to match expected casing
        device_dict['errors']['list'] = device_dict['errors'].pop('List')
        device_dict['warnings']['list'] = device_dict['warnings'].pop('List')

        #for each key in device_dict, add key to end of topic
        for key in device_dict:
            topic = f"{base_topic}/{key}".lower()
            message_dict = {
                "timestamp": int(time.time() * 1000),
                "payload": device_dict[key] # This keeps the camera config as a nested dictionary, not a string
            }
            #Encode the *entire* dictionary to a single JSON string *once*
            message_json = json.dumps(message_dict)
            #print(f"Publishing DeviceData to {topic}: {message_json}")

            # Publish the single, clean JSON string
            self.client.publish(topic, message_json, qos=0)

    async def publish_cfg(self):
        #tag = "machine.devices[13].Cfg"
        topic = PublishTopics.UPDATE_DEVICE_DATA.value + '/cfg'
          # 1. Get the vis_cfg object as a standard Python dictionary
        cfg_dict = asdict(self.device_cfg)

        # 2. Build the final Python dictionary that has the "tag" and "value" keys
        message_dict = {
            "timestamp": int(time.time() * 1000),
            "payload": cfg_dict # This keeps the camera config as a nested dictionary, not a string
        }

        # 3. Encode the *entire* dictionary to a single JSON string *once*
        message_json = json.dumps(message_dict)
        #print(f"Publishing Cfg to {topic}: {message_json}")

        # 4. Publish the single, clean JSON string
        self.client.publish(topic, message_json, qos=0)

    async def send_udp_packet(self, packet: bytes, ip: str, port: int):
        """Sends a UDP packet to the specified IP and port."""
        loop = asyncio.get_running_loop()
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: asyncio.DatagramProtocol(),
            remote_addr=(ip, port)
        )
        transport.sendto(packet)
        transport.close()

    async def publish_vision_status(self):
        #tag = "machine.visSts"
        topic = PublishTopics.UPDATE_DEVICE_DATA.value + '/sts'
        self.vis_sts.iExtService.i.flipBit = not self.vis_sts.iExtService.i.flipBit

            # 1. Get the vis_sts object as a standard Python dictionary
        vis_sts_dict = asdict(self.vis_sts)
        #print(f"[MQTT] Publishing vision status with heartbeatVal={vis_sts_dict['iExtService']['i']['heartbeatVal']}")
        #print(f"[MQTT] step number: {vis_sts_dict['iExtService']['i']['stepNum']}")
        # print the plugged in cameras
        #print(f"[MQTT] Plugged in cameras: {self.vis_sts.pluggedInSerialNumbers}")

        # 2. Build the final Python dictionary that has the "tag" and "value" keys
        message_dict = {
            "timestamp": int(time.time() * 1000),
            "payload": vis_sts_dict # This keeps the camera config as a nested dictionary, not a string
        }

        #print(f"[MQTT] Publishing vision status with cameraStates={vis_sts_dict['cameraStates']}")

        # 3. Encode the *entire* dictionary to a single JSON string *once*
        message_json = json.dumps(message_dict)
        #print(f"Publishing Sts to {topic}: {message_json}")

        # 4. Publish the single, clean JSON string
        self.client.publish(topic, message_json, qos=1)


    # ----------------------------------------------------------------------
    # SERVICE LOOP
    # ----------------------------------------------------------------------
    async def run(self):
        """Main async supervisor loop."""
        # self.connect_mqtt()

        # # Wait until connected
        # while not self._mqtt_connect_event.is_set():
        #     await asyncio.sleep(0.1)

        print("[MQTT] Service started. MQTT connected.")

        # create thread for mqtt connect and handling
        #mqtt_task = asyncio.create_task(self.connect_mqtt())
        run_state_machine_task = asyncio.create_task(self.run_state_machine())

        # Start all camera run-loops
        cam_tasks = [
            asyncio.create_task(cam.run())
            for cam in self.cameras.values()
        ]

        try:
            await asyncio.gather(*cam_tasks, run_state_machine_task)
        except asyncio.CancelledError:
            pass
        finally:
            self._running = False
            self.shutdown()
            

    def shutdown(self):
        """Shuts down the service and its components."""
        print("[SERVICE] Shutting down...")
        self.is_connecting_to_mqtt = False
        self.shutdown_mqtt()


    def shutdown_mqtt(self):
        print("[MQTT] Shutting down...")
        
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except:
            pass


def serialize_to_json(data_object) -> str:
    """Converts a dataclass object to a JSON string."""
    
    # asdict() does the heavy lifting of converting the object to a dictionary.
    data_dict = asdict(data_object)
    
    # We still need a custom encoder to handle the Enum conversion automatically.
    # The default json.dumps won't know how to handle Enums in the dict.
    class EnumEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, Enum):
                return obj.value
            return json.JSONEncoder.default(self, obj)

    json_payload = json.dumps(data_dict, indent=4, cls=EnumEncoder)
    return json_payload