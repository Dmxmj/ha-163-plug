FROM homeassistant/aarch64-base:latest
WORKDIR /app
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

RUN apk add --no-cache ntp wget tar curl python3 py3-pip python3-dev && \
    rm -rf /var/cache/apk/* && \
    ln -sf python3 /usr/bin/python && \
    ln -sf pip3 /usr/bin/pip

COPY . .

CMD ["python", "/app/main.py"]
