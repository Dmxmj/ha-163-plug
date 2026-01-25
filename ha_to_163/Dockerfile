# 适配 ha-163-plug 的 HA 插件 Dockerfile（aarch64架构）
FROM homeassistant/aarch64-base:latest

# 修复：用 chrony 替代 ntp（解决Alpine 3.18+ 包不存在问题）
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

# 修复：添加 s6-overlay 服务目录（解决pid 1问题）
RUN mkdir -p /etc/services.d/163-plug && \
    chmod 755 /etc/services.d/163-plug

# 复制 s6 启动脚本（关键：源文件是当前目录的run，不是其他路径）
COPY run /etc/services.d/163-plug/run
RUN chmod 755 /etc/services.d/163-plug/run

# 工作目录
WORKDIR /app

# 修复：COPY仓库的核心脚本 ha_to_163.py（不是main.py！）
COPY ha_to_163.py /app/ha_to_163.py

# 安装Python依赖（仓库如有requirements.txt则保留，无则删除）
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r /app/requirements.txt || true

# 禁用缓存，避免runc进程错误
ENV BUILDKIT_INLINE_CACHE=0
