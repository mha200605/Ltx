FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    COMFYUI_DIR=/opt/ComfyUI \
    COMFYUI_HOST=127.0.0.1 \
    COMFYUI_PORT=8188 \
    MODEL_DIR=/runpod-volume/ltx25-models \
    STARTUP_TIMEOUT_SECONDS=900 \
    JOB_TIMEOUT_SECONDS=1800 \
    WORKFLOW_PATH=/app/workflow_api.json

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates git curl ffmpeg build-essential libgl1 libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

# ComfyUI, pinned to a fixed commit
RUN git clone https://github.com/comfyanonymous/ComfyUI.git /opt/ComfyUI && \
    cd /opt/ComfyUI && \
    git checkout e087d8f6cb7c6cdb11b59dc7c9bf17c79f8d877d

# PyTorch (CUDA 12.8 wheels bundle their own CUDA libraries), then ComfyUI deps
RUN pip install --upgrade pip && \
    pip install torch==2.7.1 torchvision==0.22.1 torchaudio==2.7.1 \
      --index-url https://download.pytorch.org/whl/cu128 && \
    pip install -r /opt/ComfyUI/requirements.txt

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY handler.py workflow_api.json start.sh prepare_models.sh /app/
RUN chmod +x /app/start.sh /app/prepare_models.sh

# Model weights are NOT in the image; they come from the network volume.
CMD ["/app/start.sh"]
