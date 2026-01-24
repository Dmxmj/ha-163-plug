# 使用HA官方Add-on基础镜像（内置s6-overlay+bashio环境）
FROM homeassistant/amd64-base:12

# 安装Python3.11及系统依赖
RUN apk add --no-cache \
    python3.11 \
    python3.11-pip \
    python3.11-dev \
    bash \
    ntpdate \
    && ln -sf python3.11 /usr/bin/python \
    && ln -sf pip3.11 /usr/bin/pip \
    && rm -rf /var/cache/apk/*

# 设置工作目录
WORKDIR /app

# 复制Python依赖文件并安装（移除无效的bashio/typing）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --upgrade pip

# 复制应用代码和启动脚本
COPY . /app/

# 创建s6服务目录（适配你的s6-svscan逻辑）
RUN mkdir -p /etc/services.d/163-gateway \
    # 设置run.sh执行权限
    && chmod +x /app/run.sh \
    # 链接s6服务启动脚本
    && ln -s /app/run.sh /etc/services.d/163-gateway/run \
    # 设置目录权限
    && chown -R root:root /app /etc/services.d

# HA Add-on默认入口（s6-overlay会自动启动/etc/services.d/下的服务）
CMD ["/init"]
