#!/usr/bin/with-contenv bashio
# ==============================================================================
# 163 Gateway 插件启动脚本
# ==============================================================================

# 日志初始化
bashio::log.info "=== 163 Gateway 启动脚本开始执行 ==="

# 读取HA add-on配置并写入环境变量（保留你的原有逻辑）
bashio::log.info "读取Add-on配置并设置环境变量..."
export HA_URL=$(bashio::config 'ha_url')
export HA_TOKEN=$(bashio::config 'ha_token')
export HA_ENTITY_PREFIX=$(bashio::config 'ha_entity_prefix')
export MQTT_HOST=$(bashio::config 'mqtt_host')
export MQTT_PORT=$(bashio::config 'mqtt_port')
export MQTT_USERNAME=$(bashio::config 'mqtt_username')
export MQTT_PASSWORD=$(bashio::config 'mqtt_password')
export REPORT_INTERVAL=$(bashio::config 'report_interval')
export RETRY_ATTEMPTS=$(bashio::config 'retry_attempts')
export RETRY_DELAY=$(bashio::config 'retry_delay')

# 网易NTP校时（补充你的业务需求，失败不中断）
bashio::log.info "同步网易NTP服务器时间..."
ntpdate ntp.n.netease.com || bashio::log.warning "NTP校时失败，继续启动服务"

#!/usr/bin/with-contenv sh
# 适配 ha-163-plug 的 s6 启动脚本（解决pid 1问题）
cd /app

# 关键：执行仓库的核心脚本 ha_to_163.py（不是main.py）
exec python /app/ha_to_163.py

# 异常捕获
bashio::log.error "服务启动失败，进程异常退出"
exit 1
