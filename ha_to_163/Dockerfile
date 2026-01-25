FROM homeassistant/aarch64-base:latest

RUN apk add --no-cache \
    chrony \
    wget \
    tar \
    curl \
    python3 \
    py3-pip \
    python3-dev \
    && rm -rf /var/cache/apk/* \
    && ln -sf python3 /usr/bin/python \
    && ln -sf pip3 /usr/bin/pip

RUN mkdir -p /etc/services.d/gateway

COPY run /etc/services.d/gateway/run

RUN chmod 755 /etc/services.d/gateway/run

WORKDIR /app

COPY main.py /app/main.py

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r /app/requirements.txt
