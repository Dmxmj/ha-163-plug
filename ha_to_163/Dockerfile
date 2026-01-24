# 使用HA官方多架构基础镜像（自动适配aarch64/amd64）
# base:3.19 是HA Add-on最新稳定版，内置s6-overlay+bashio
FROM homeassistant/base:3.19

# 安装系统依赖（适配aarch64的Python3.11+ntpdate）
RUN apk add --no-cache \
    python3.11 \
    python3.11-pip \
    python3.11-dev \
    bash \
    ntpdate \
    wget \
    tar \
    && ln -sf python3.11 /usr/bin/python \
    && ln -sf pip3.11 /usr/bin/pip \
    && rm -rf /var/cache/apk/*

# 设置工作目录
WORKDIR /app

# 复制Python依赖文件并安装（移除无效的bashio/typing）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --upgrade pip

# 复制应用代码和启动脚本（保留你的原有文件）
COPY . /app/

# 创建s6服务目录（适配你原有的s6-svscan逻辑）
RUN mkdir -p /etc/services.d/163-gateway \
    # 给run.sh添加执行权限（关键）
    && chmod +x /app/run.sh \
    # 链接s6服务启动脚本（和你原逻辑一致）
    && ln -s /app/run.sh /etc/services.d/163-gateway/run \
    # 若有finish脚本，同样设置权限
    && if [ -f /app/finish ]; then \
        chmod +x /app/finish && ln -s /app/finish /etc/services.d/163-gateway/finish; \
       fi \
    # 统一权限
    && chown -R root:root /app /etc/services.d

# HA Add-on标准入口（s6-overlay自动管理服务）
CMD ["/init"]
