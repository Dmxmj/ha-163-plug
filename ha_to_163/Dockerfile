FROM homeassistant/aarch64-base:latest

RUN apk add --no-cache chrony wget tar curl python3 py3-pip python3-dev && \
    rm -rf /var/cache/apk/* && \
    ln -sf python3 /usr/bin/python && \
    ln -sf pip3 /usr/bin/pip

RUN mkdir -p /etc/services.d/163-gateway

COPY run /etc/services.d/163-gateway/run

RUN chmod +x /etc/services.d/163-gateway/run

WORKDIR /app
COPY . .

RUN if [ -f "requirements.txt" ]; then pip install --no-cache-dir -r requirements.txt; fi
