"""HA Add-on 主程序：米家插座实体发现 + 网易IoT数据推送"""
import logging
import time
import json
import os
from device_discovery.ha_discovery import HADiscovery
from iot_push.iot_client import NeteaseIoTClient

# 配置日志（适配HA Add-on）
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("163_gateway")

# 从环境变量读取配置（HA Add-on配置传递）
def load_config_from_env():
    """从环境变量加载配置"""
    return {
        "ha_url": os.getenv("HA_URL", "http://supervisor/core/api"),
        "ha_headers": {
            "Authorization": f"Bearer {os.getenv('HA_TOKEN', '')}",
            "Content-Type": "application/json"
        },
        "ha_entity_prefix": os.getenv("HA_ENTITY_PREFIX", "iot_cn_2004109533_pw6u1"),
        "retry_attempts": int(os.getenv("RETRY_ATTEMPTS", 5)),
        "retry_delay": int(os.getenv("RETRY_DELAY", 3)),
        "sub_devices": [
            {
                "id": "mi_smart_socket",
                "enabled": True,
                "ha_entity_prefix": os.getenv("HA_ENTITY_PREFIX", "iot_cn_2004109533_pw6u1"),
                "supported_properties": [
                    "all_switch", "jack_1", "jack_2", "jack_3", "jack_4", "jack_5", "jack_6",
                    "default_power_on_state", "electric_power", "electric_current", "voltage", "power_consumption"
                ]
            }
        ],
        "mqtt_config": {
            "host": os.getenv("MQTT_HOST", "device.iot.163.com"),
            "port": int(os.getenv("MQTT_PORT", 1883)),
            "username": os.getenv("MQTT_USERNAME", ""),
            "password": os.getenv("MQTT_PASSWORD", ""),
            "keepalive": 60
        },
        "report_interval": int(os.getenv("REPORT_INTERVAL", 30))
    }

def main():
    # 1. 加载配置
    config = load_config_from_env()
    logger.info("配置加载完成，开始初始化...")
    
    # 2. 初始化HA发现模块
    ha_discovery = HADiscovery(config, config["ha_headers"])
    
    # 等待HA API就绪（Add-on启动时HA可能未完全加载）
    for attempt in range(config["retry_attempts"]):
        if ha_discovery.load_ha_entities():
            break
        logger.warning(f"HA实体加载失败，{config['retry_delay']}秒后重试（{attempt+1}/{config['retry_attempts']}）")
        time.sleep(config["retry_delay"])
    else:
        logger.error("HA实体加载超时，程序退出")
        return
    
    # 匹配设备
    matched_devices = ha_discovery.match_entities_to_devices()
    if not matched_devices:
        logger.error("未匹配到任何米家插座设备，程序退出")
        return
    
    # 3. 初始化网易IoT客户端
    iot_clients = {}
    for device_id, device_data in matched_devices.items():
        client = NeteaseIoTClient(device_id, config["mqtt_config"])
        client.set_ha_config(config)
        client.connect()
        iot_clients[device_id] = {
            "client": client,
            "device_data": device_data
        }
        logger.info(f"IoT客户端初始化成功: {device_id}")
    
    # 4. 循环上报数据
    report_interval = config["report_interval"]
    logger.info(f"开始循环上报，间隔{report_interval}秒...")
    
    try:
        while True:
            for device_id, client_data in iot_clients.items():
                client = client_data["client"]
                device_data = client_data["device_data"]
                sensors = device_data["sensors"]
                
                # 读取HA实体值
                ha_data = {}
                for ha_field, entity_id in sensors.items():
                    value = ha_discovery.read_entity_value(entity_id)
                    if value is not None:
                        ha_data[ha_field] = value
                        logger.debug(f"读取实体: {entity_id} = {value}")
                
                # 推送数据
                if ha_data:
                    client.push_property(ha_data)
                else:
                    logger.warning(f"设备{device_id}无有效数据")
            
            time.sleep(report_interval)
    
    except KeyboardInterrupt:
        logger.info("程序被手动终止")
    except Exception as e:
        logger.error(f"程序异常: {str(e)}", exc_info=True)
    finally:
        # 清理资源
        for device_id, client_data in iot_clients.items():
            client_data["client"].disconnect()
            logger.info(f"断开IoT连接: {device_id}")

if __name__ == "__main__":
    main()
