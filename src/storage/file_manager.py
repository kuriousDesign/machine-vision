import os
from config import VIDEO_PATH

def get_video_path(jobId, batchId):
    path = os.path.join(VIDEO_PATH, str(jobId), str(batchId))
    os.makedirs(path, exist_ok=True)
    return path

def save_file_path(filename, jobId, batchId):
    folder = get_video_path(jobId, batchId)
    return os.path.join(folder, filename)
