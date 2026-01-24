# 基于 Home Assistant 插件标准基础镜像（适配 aarch64 架构）
# 可根据实际架构调整：amd64/armv7/armhf 等
FROM homeassistant/aarch64-base:3.19

# 维护者信息（可选，可修改为自己的信息）
LABEL maintainer="Your Name <your@email.com>"

# 设置工作目录
WORKDIR /app

# 设置环境变量（避免 Python 缓冲输出，便于日志查看）
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# 安装系统依赖和 Python 基础环境
# 修复核心：补全 RUN 和 apk add 指令，解决 unknown instruction 错误
RUN apk add --no-cache \
    # 系统工具依赖
    ntp \        # 替代 ntpdate，包含时间同步工具
    wget \       # 文件下载工具
    tar \        # 解压工具
    curl \       # HTTP 请求工具
    # Python 环境依赖
    python3 \
    py3-pip \
    python3-dev \
    # 清理缓存，减小镜像体积
    && rm -rf /var/cache/apk/* \
    # 建立 python/pip 软链接，统一命令（兼容 python/python3 调用）
    && ln -sf python3 /usr/bin/python \
    && ln -sf pip3 /usr/bin/pip

# 复制插件的依赖文件（如果有 requirements.txt，需确保文件存在）
# 若没有该文件，可注释掉这两行
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制插件的所有代码到工作目录
COPY . .

# 设置插件启动命令（根据实际入口文件调整，示例为 main.py）
CMD ["python", "/app/main.py"]
