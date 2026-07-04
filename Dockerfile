FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    STATE_FILE=/data/state.json

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY exporter.py tw_readings.py ./

# Persist the high-water-mark across restarts so we never re-push or re-order.
RUN mkdir -p /data
VOLUME ["/data"]

# Self-metrics / health endpoint.
EXPOSE 8000

ENTRYPOINT ["python", "exporter.py"]
