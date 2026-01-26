# HA 163 Gateway Add-on Dockerfile
FROM homeassistant/aarch64-base:latest

# 安装依赖包
RUN apk add --no-cache \
    bash \
    chrony \
    python3 \
    py3-pip \
    python3-dev \
    gcc \
    musl-dev \
    && rm -rf /var/cache/apk/* \
    && ln -sf python3 /usr/bin/python \
    && ln -sf pip3 /usr/bin/pip

# 设置工作目录
WORKDIR /app

# 复制 Python 依赖文件并安装
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用程序文件
COPY config_manager.py /app/
COPY main.py /app/
COPY ntp_sync.py /app/
COPY iot_push/ /app/iot_push/
COPY device_discovery/ /app/device_discovery/

# 复制启动脚本
COPY run /app/run.sh
RUN chmod +x /app/run.sh

# 设置环境变量
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# 创建数据目录
RUN mkdir -p /data

# 设置入口点
CMD ["/app/run.sh"]
