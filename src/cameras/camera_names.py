import subprocess
import re
import sys

def get_camera_serial(camera_index):
    """
    Retrieves the unique USB serial number (ID_SERIAL_SHORT) for a given 
    camera index by calling udevadm via subprocess.
    """
    device_path = f"/dev/video{camera_index}"
    try:
        # Command to run: udevadm info --name=/dev/videoX
        cmd = ["udevadm", "info", "--name", device_path]
        
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


def get_unique_camera_names_and_indices():
    """
    Generates a list of dictionaries for unique cameras, including their 
    index, name, and serial number.
    """
    try:
        cmd = ["v4l2-ctl", "--list-devices"]
        # Use capture_output=True only
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        output_lines = result.stdout.strip().split('\n')

        intermediate_list = []
        current_name = None
        seen_names = set()
        
        for line in output_lines:
            line = line.strip()
            if not line:
                continue
                
            if not line.startswith('/dev/'):
                # Clean up the name by removing the bus ID in parentheses (this also removes the trailing :)
                current_name = re.sub(r'\s*\(.*\)$|:', '', line).strip()
            
            elif line.startswith('/dev/video'):
                match = re.search(r'/dev/video(\d+)', line)
                if match and current_name:
                    index = int(match.group(1))
                    
                    if current_name not in seen_names:
                        seen_names.add(current_name)
                        intermediate_list.append({
                            'index': index,
                            'name': current_name,
                        })
        
        intermediate_list.sort(key=lambda x: x['index'])

        # Second pass: fetch the serial number for each unique entry
        final_camera_list = []
        for camera in intermediate_list:
            serial_num = get_camera_serial(camera['index'])
            camera['serial'] = serial_num
            final_camera_list.append(camera)

        return final_camera_list

    except (subprocess.CalledProcessError, FileNotFoundError):
        print("Error: Required command-line tools (v4l2-ctl or udevadm) not found or failed.", file=sys.stderr)
        return []
    except Exception as e:
        print(f"An error occurred during camera listing: {e}", file=sys.stderr)
        return []


def get_camera_index_by_serial(target_serial):
    """
    Given a serial number, returns the corresponding camera index.
    If not found, returns None
    """
    cameras = get_unique_camera_names_and_indices()
    for camera in cameras:
        if camera['serial'] == target_serial:
            return camera['index']
    return None

if __name__ == "__main__":
    cameras_list = get_unique_camera_names_and_indices()
    
    print("Available Cameras:")
    for camera in cameras_list:
        print(f"  Index {camera['index']}: Name: {camera['name']}, Serial: {camera['serial']}")
