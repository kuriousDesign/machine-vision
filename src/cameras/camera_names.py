import subprocess
import re
import sys
import threading
import time


_CAMERA_LIST_CACHE = []
_CAMERA_LIST_CACHE_TIME = 0.0
_CAMERA_LIST_CACHE_TTL_SECONDS = 0.5
_CAMERA_LIST_LOCK = threading.Lock()


def _normalize_camera_name(raw_name):
    return re.sub(r'\s*\([^)]*\)$', '', raw_name.rstrip(':')).strip()


def _parse_v4l2_devices_output(output):
    """Parse `v4l2-ctl --list-devices` output into device blocks.

    Each header block corresponds to one physical device and can expose
    multiple `/dev/video*` nodes. We keep the first video index from each
    block so identical camera models on different ports remain distinct.
    """
    cameras = []
    current_name = None
    current_index = None

    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            if current_name is not None and current_index is not None:
                cameras.append({"index": current_index, "name": current_name})
            current_name = None
            current_index = None
            continue

        if line.startswith('/dev/video'):
            if current_name is None or current_index is not None:
                continue
            match = re.search(r'/dev/video(\d+)', line)
            if match:
                current_index = int(match.group(1))
            continue

        if current_name is not None and current_index is not None:
            cameras.append({"index": current_index, "name": current_name})
            current_index = None

        current_name = _normalize_camera_name(line)

    if current_name is not None and current_index is not None:
        cameras.append({"index": current_index, "name": current_name})

    cameras.sort(key=lambda camera: camera['index'])
    return cameras


def _build_camera_list(v4l2_output):
    final_camera_list = []
    for camera in _parse_v4l2_devices_output(v4l2_output):
        serial_num = get_camera_serial(camera['index'])
        camera['serial'] = serial_num
        camera['usb_port'] = get_camera_usb_port(camera['index'])
        final_camera_list.append(camera)
    return final_camera_list

def get_camera_serial(camera_index):
    """
    Retrieves the unique USB serial number (ID_SERIAL_SHORT) for a given 
    camera index by calling udevadm via subprocess.
    """
    device_path = f"/dev/video{camera_index}"
    try:
        # Command to run: udevadm info --name=/dev/videoX
        cmd = ["udevadm", "info", "--name", device_path]
        #cmd = ["lsusb"]
        
        # FIX: Use capture_output=True ONLY. This captures both stdout and stderr.
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        output = result.stdout
        
        # Look for the specific line containing the short serial number
        for line in output.splitlines():
            if 'ID_SERIAL_SHORT=' in line:
                # Extract the value after the equals sign
                serial_match = re.search(r'ID_SERIAL_SHORT=(.*)', line)
                if serial_match:
                    return serial_match.group(1)

        # Fallback if serial short is not found but device exists
        return "N/A" 

    except subprocess.CalledProcessError as e:
        # If udevadm returns an error code, print the stderr for debugging
        print(f"udevadm failed for {device_path}: {e.stderr.strip()}", file=sys.stderr)
        return "Disconnected/Error"
    except FileNotFoundError:
        return "Command 'udevadm' not found."
    except Exception as e:
        # General error handling
        return f"Error: {e}"


def get_camera_usb_port(camera_index):
    """
    Retrieves the physical USB bus/port path (e.g. "1-3", "1-3.2") for a
    given camera index by calling udevadm via subprocess. This value is
    stable across reboots and reconnects as long as the camera stays
    plugged into the same physical USB port/hub position, but is
    independent of (and does not change with) the camera's serial number.
    """
    device_path = f"/dev/video{camera_index}"
    try:
        cmd = ["udevadm", "info", "--name", device_path]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        output = result.stdout

        # DEVPATH looks like:
        #   .../usb1/1-3/1-3:1.0/video4linux/video0
        # The USB bus/port segment is the one matching "<bus>-<port>[.<port>...]"
        # immediately preceding the "<bus>-<port>:<config>.<interface>" segment.
        devpath_match = None
        for line in output.splitlines():
            if line.startswith("P: "):
                devpath_match = line[len("P: "):]
                break

        if devpath_match:
            usb_port_match = re.search(r'/(\d+-\d+(?:\.\d+)*)/\1:', devpath_match)
            if usb_port_match:
                return usb_port_match.group(1)

        return "N/A"

    except subprocess.CalledProcessError as e:
        print(f"udevadm failed for {device_path}: {e.stderr.strip()}", file=sys.stderr)
        return "Disconnected/Error"
    except FileNotFoundError:
        return "Command 'udevadm' not found."
    except Exception as e:
        return f"Error: {e}"


def get_unique_camera_names_and_indices(force_refresh=False):
    """
    Generates a list of dictionaries for unique cameras, including their 
    index, name, and serial number.
    """
    global _CAMERA_LIST_CACHE, _CAMERA_LIST_CACHE_TIME

    try:
        now = time.monotonic()
        with _CAMERA_LIST_LOCK:
            if not force_refresh and _CAMERA_LIST_CACHE and (now - _CAMERA_LIST_CACHE_TIME) < _CAMERA_LIST_CACHE_TTL_SECONDS:
                return [camera.copy() for camera in _CAMERA_LIST_CACHE]

            cmd = ["v4l2-ctl", "--list-devices"]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            final_camera_list = _build_camera_list(result.stdout)

            _CAMERA_LIST_CACHE = [camera.copy() for camera in final_camera_list]
            _CAMERA_LIST_CACHE_TIME = now
            return [camera.copy() for camera in final_camera_list]

    except FileNotFoundError as e:
        print(f"Error: Required command-line tool not found: {e.filename}. Ensure v4l2-ctl is installed.", file=sys.stderr)
        return []
    except subprocess.CalledProcessError as e:
        if e.stderr.strip().startswith("Cannot open device /dev/video0"):
            #print("Error: No cameras found or /dev/video0 cannot be opened.", file=sys.stderr)
            pass
        else:
            print(f"Error: v4l2-ctl command failed with exit code {e.returncode}: {e.stderr.strip() if e.stderr else 'No error details available'}", file=sys.stderr)
        return []
    except Exception as e:
        print(f"An error occurred during camera listing: {e}", file=sys.stderr)
        return []


def get_camera_index_by_serial(target_serial, force_refresh=True):
    """
    Given a serial number, returns the corresponding camera index.
    If not found, returns None
    """
    cameras = get_unique_camera_names_and_indices(force_refresh=force_refresh)
    for camera in cameras:
        if camera['serial'] == target_serial:
            return camera['index']
    return None


def get_camera_index_by_usb_port(target_usb_port, force_refresh=True):
    """
    Given a physical USB bus/port string (e.g. "1-3"), returns the
    corresponding camera index. If not found, returns None
    """
    cameras = get_unique_camera_names_and_indices(force_refresh=force_refresh)
    for camera in cameras:
        if camera['usb_port'] == target_usb_port:
            return camera['index']
    return None

if __name__ == "__main__":
    cameras_list = get_unique_camera_names_and_indices()
    
    print("Available Cameras:")
    if len(cameras_list) == 0:
        print("  No cameras found.")
    for camera in cameras_list:
        print(f"  Index {camera['index']}: Name: {camera['name']}, Serial: {camera['serial']}, USB Port: {camera['usb_port']}")
