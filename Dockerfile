FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    THAMESWATER_EXPORTER_STATE_FILE=/data/state.json

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 9100

ENTRYPOINT ["thameswater-exporter"]
