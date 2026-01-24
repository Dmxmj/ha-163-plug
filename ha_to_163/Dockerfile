# 使用稳定的Alpine 3.18基础镜像（多架构兼容，aarch64/amd64都能拉取）
FROM alpine:3.18

# 安装系统依赖（保留参考模板的核心，补充bash/s6/ntpdate等HA Add-on必需依赖）
RUN apk add --no-cache \
    python3 \
    py3-pip \
    gcc \
    python3-dev \
    musl-dev \
    ca-certificates \
    # 补充HA Add-on必需依赖
    bash \
    ntpdate \
    wget \
    tar \
    curl \
    && rm -rf /var/cache/apk/* \
    # 建立python/pip软链接，统一命令
    && ln -sf python3 /usr/bin/python \
    && ln -sf pip3 /usr/bin/pip

# 手动安装s6-overlay（适配aarch64架构，支持s6-svscan进程管理）
ENV S6_OVERLAY_VERSION=3.1.6.2
RUN wget -q -O /tmp/s6-overlay-noarch.tar.xz https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-noarch.tar.xz \
    && wget -q -O /tmp/s6-overlay-aarch64.tar.xz https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-aarch64.tar.xz \
    && tar -C / -Jxpf /tmp/s6-overlay-noarch.tar.xz \
    && tar -C / -Jxpf /tmp/s6-overlay-aarch64.tar.xz \
    && rm -rf /tmp/s6-overlay-*.tar.xz

# 手动安装bashio（支持bashio::config读取HA Add-on配置）
ENV BASHIO_VERSION=0.19.0
RUN mkdir -p /usr/lib/bashio \
    && wget -q -O /tmp/bashio.tar.gz https://github.com/hassio-addons/bashio/archive/v${BASHIO_VERSION}.tar.gz \
    && tar zxvf /tmp/bashio.tar.gz -C /usr/lib/bashio --strip=1 \
    && rm /tmp/bashio.tar.gz \
    && ln -s /usr/lib/bashio/bashio /usr/bin/bashio \
    # 补充with-contenv脚本（HA Add-on标准，适配run.sh的shebang）
    && ln -s /usr/lib/bashio/lib/with-contenv /usr/bin/with-contenv

WORKDIR /app

# 复制依赖文件并按固定版本安装（完全保留参考模板的国内源逻辑）
COPY requirements.txt .
RUN pip install --no-cache-dir \
    --index-url https://pypi.tuna.tsinghua.edu.cn/simple \
    --extra-index-url https://pypi.org/simple \
    -r requirements.txt  # 直接使用requirements.txt确保版本一致

# 验证版本是否匹配（保留参考模板的校验逻辑）
RUN grep -E "paho-mqtt==|requests==|typing-extensions==" requirements.txt | while read -r line; do \
    if ! pip list | grep -q "$line"; then \
        echo "依赖版本不匹配: $line"; \
        exit 1; \
    fi; \
done

# 复制应用代码（保留所有文件）
COPY . .

# 创建s6服务目录（适配原有run.sh的s6-svscan逻辑）
RUN mkdir -p /etc/services.d/163-gateway \
    # 给run.sh添加执行权限
    && chmod +x /app/run.sh \
    # 链接s6服务启动脚本
    && ln -s /app/run.sh /etc/services.d/163-gateway/run \
    # 统一权限
    && chown -R root:root /app /etc/services.d

# HA Add-on标准入口（s6-overlay管理服务）
CMD ["/init"]
