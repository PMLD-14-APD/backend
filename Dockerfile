# Backend + inferensi YOLO (GPU). Driver CUDA datang dari host lewat nvidia-container-toolkit;
# wheel torch cu130 sudah membawa runtime CUDA sendiri, jadi base cukup python slim.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 ffmpeg curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# torch dulu dari index CUDA 13.0 (RTX 5080 / Blackwell sm_120), baru requirements lain.
RUN pip install torch torchvision --index-url https://download.pytorch.org/whl/cu130
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN chmod +x docker/entrypoint.sh

ENV PORT=8000
ENTRYPOINT ["docker/entrypoint.sh"]
