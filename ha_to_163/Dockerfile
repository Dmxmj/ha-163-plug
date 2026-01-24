# 基础镜像（适配HA add-on）
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制插件启动脚本
COPY run.sh /
RUN chmod +x /run.sh

# 复制核心代码
COPY root/ /

# 设置权限
RUN chmod -R 755 /etc/services.d/163-gateway/run

# 启动命令
CMD ["/run.sh"]
