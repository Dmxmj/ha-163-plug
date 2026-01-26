# HA 163 Gateway Add-on Dockerfile
FROM homeassistant/aarch64-base:latest

# 安装依赖包
RUN apk add --no-cache \
    chrony \
    python3 \
    py3-pip \
    python3-dev \
    gcc \
    musl-dev \
    && rm -rf /var/cache/apk/* \
    && ln -sf python3 /usr/bin/python \
    && ln -sf pip3 /usr/bin/pip

# 创建 s6-overlay 服务目录
RUN mkdir -p /etc/services.d/gateway

# 复制启动脚本
COPY run /etc/services.d/gateway/run
RUN chmod 755 /etc/services.d/gateway/run

# 设置工作目录
WORKDIR /app

# 复制 Python 依赖文件并安装
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用程序文件
COPY main.py /app/
COPY config_manager.py /app/
COPY ntp_sync.py /app/
COPY device_discovery/ /app/device_discovery/
COPY iot_push/ /app/iot_push/

# 设置环境变量
ENV PYTHONUNBUFFERED=1
