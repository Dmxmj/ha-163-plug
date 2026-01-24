# 改用HA官方Add-on基础镜像（兼容HA生态，自带Python3.11）
FROM homeassistant/amd64-base-python:3.11

# 设置工作目录
WORKDIR /app

# 安装系统依赖（ntpdate用于校时，bash是bashio必需）
RUN apk add --no-cache bash ntpdate && rm -rf /var/cache/apk/*

# 复制Python依赖文件并安装（仅安装真正的Python包）
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt \
    # 升级pip避免版本提示干扰
    && pip3 install --upgrade pip

# 正确安装bashio（HA Add-on必需，通过下载脚本而非pip）
ENV BASHIO_VERSION=0.19.0
RUN mkdir -p /usr/lib/bashio \
    && wget -q -O /tmp/bashio.tar.gz https://github.com/hassio-addons/bashio/archive/v${BASHIO_VERSION}.tar.gz \
    && tar zxvf /tmp/bashio.tar.gz -C /usr/lib/bashio --strip=1 \
    && rm /tmp/bashio.tar.gz \
    && ln -s /usr/lib/bashio/bashio /usr/bin/bashio

# 复制应用代码（确保所有脚本/代码都被复制）
COPY . /app/

# 设置启动脚本执行权限
RUN chmod +x /app/run.sh

# HA Add-on入口（通过bashio启动）
CMD ["/app/run.sh"]
