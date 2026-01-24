#!/usr/bin/with-contenv bashio
# ==============================================================================
# 163 Gateway 插件启动脚本
# ==============================================================================

# 读取HA add-on配置并写入环境变量
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

# 启动服务（由supervisor管理）
exec /usr/bin/s6-svscan /etc/services.d/
