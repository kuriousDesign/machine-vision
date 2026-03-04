# Stable Bookworm-based Python 3.12
FROM python:3.12-slim-bookworm

# 1. Environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

# 2. Install System Deps + USB/Hardware Support
# v4l-utils is included so you can use 'v4l2-ctl' to debug cameras
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ffmpeg \
    libsm6 \
    libxext6 \
    libglib2.0-0 \
    libusb-1.0-0 \
    v4l-utils \
    udev \
    python3-bpfcc \
    libbpfcc-dev \
    && rm -rf /var/lib/apt/lists/*

# 3. venv with system access for BCC kernel hooks
RUN python -m venv --system-site-packages $VIRTUAL_ENV

# 4. Set workdir (aligned to /app for your compose mount)
WORKDIR /app

# 5. Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 6. Copy the rest of the application code
COPY . .

# 7. Default command
CMD ["python", "src/service.py"]
