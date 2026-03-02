import cv2
import os

RECORDINGS_DIR = "/opt/recordings"
test_filename = os.path.join(RECORDINGS_DIR, "test_codec.mp4")

# Try different fourcc values
fourcc_options = [
    cv2.VideoWriter_fourcc(*'H264'),
    cv2.VideoWriter_fourcc(*'avc1'),
    cv2.VideoWriter_fourcc(*'x264'),
    cv2.VideoWriter_fourcc(*'mp4v'),  # original for comparison
]

for fourcc in fourcc_options:
    print(f"\nTesting fourcc: {fourcc} (tag: {fourcc.to_bytes(4, 'big').decode(errors='ignore')})")
    
    writer = cv2.VideoWriter(
        test_filename,
        fourcc,
        30.0,
        (1920, 1080)
    )
    
    if not writer.isOpened():
        print("  → FAILED: VideoWriter.isOpened() == False")
    else:
        print("  → Opened successfully")
        # Write a dummy frame to force creation
        dummy = cv2.imread("/path/to/some/image.jpg")  # or create black frame
        if dummy is None:
            dummy = cv2.zeros((1080, 1920, 3), dtype='uint8')
        writer.write(dummy)
        writer.release()
        size = os.path.getsize(test_filename) if os.path.exists(test_filename) else 0
        print(f"  → File size after write: {size} bytes")
        if size > 0:
            print("  → File was actually written!")