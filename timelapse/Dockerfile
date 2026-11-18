FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg v4l-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY app.py /app/app.py

ENV PYTHONUNBUFFERED=1 \
    CARVERA_CAM=/dev/video0 \
    CARVERA_JOB_STATE=/config/job-state.json \
    CARVERA_JOBS_DIR=/jobs

EXPOSE 8081
CMD ["python", "/app/app.py"]
