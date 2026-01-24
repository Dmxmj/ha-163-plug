"""配置管理模块（支持动态加载/导入设备三元组）"""
import json
import logging
import os
from typing import Dict, List, Optional

logger = logging.getLogger("config_manager")

class ConfigManager:
    """配置管理器"""
    def __init__(self):
        self.config = {}
        self.config_path = "/data/config.json"  # HA Add-on持久化目录
        self._ensure_config_dir()

    def _ensure_config_dir(self):
        """确保配置目录存在"""
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)

    def load_from_env(self) -> Dict:
        """从环境变量加载配置（HA Add-on传递）"""
        import bashio
        try:
            # 从bashio读取Add-on配置
            config = {
                "ha_url": bashio.config.get("ha_url"),
                "ha_token": bashio.config.get("ha_token"),
                "gateway_triple": {
                    "product_key": bashio.config.get("gateway_triple.product_key"),
                    "device_name": bashio.config.get("gateway_triple.device_name"),
                    "device_secret": bashio.config.get("gateway_triple.device_secret")
                },
                "devices_triple": bashio.config.get("devices_triple"),
                "mqtt_config": {
                    "host": bashio.config.get("mqtt_host"),
                    "port": int(bashio.config.get("mqtt_port")),
                    "keepalive": 60
                },
                "report_interval": int(bashio.config.get("report_interval")),
                "discovery_retry_interval": int(bashio.config.get("discovery_retry_interval")),
                "retry_attempts": int(bashio.config.get("retry_attempts")),
                "retry_delay": int(bashio.config.get("retry_delay"))
            }
            self.config = config
            self.save_config()
            logger.info("配置从HA Add-on加载成功")
            return config
        except Exception as e:
            logger.error(f"加载配置失败: {str(e)}")
            return self.load_saved_config()

    def load_saved_config(self) -> Dict:
        """加载本地保存的配置"""
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, "r", encoding="utf-8") as f:
                    self.config = json.load(f)
                logger.info("配置从本地文件加载成功")
                return self.config
        except Exception as e:
            logger.error(f"加载本地配置失败: {str(e)}")
        return self.get_default_config()

    def save_config(self):
        """保存配置到本地"""
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            logger.info("配置已保存到本地")
        except Exception as e:
            logger.error(f"保存配置失败: {str(e)}")

    def import_config(self, import_data: str) -> bool:
        """导入配置（JSON字符串）"""
        try:
            import_config = json.loads(import_data)
            # 验证配置结构
            required_fields = ["gateway_triple", "devices_triple"]
            for field in required_fields:
                if field not in import_config:
                    logger.error(f"导入配置缺少字段: {field}")
                    return False
            
            self.config.update(import_config)
            self.save_config()
            logger.info("配置导入成功")
            return True
        except json.JSONDecodeError:
            logger.error("导入配置格式错误（非JSON）")
            return False
        except Exception as e:
            logger.error(f"导入配置失败: {str(e)}")
            return False

    def get_device_triple(self, device_id: str) -> Optional[Dict]:
        """获取指定设备的三元组"""
        for device in self.config.get("devices_triple", []):
            if device.get("device_id") == device_id and device.get("enabled", True):
                return device
        return None

    def get_all_enabled_devices(self) -> List[Dict]:
        """获取所有启用的设备"""
        return [d for d in self.config.get("devices_triple", []) if d.get("enabled", True)]

    def update_device_triple(self, device_id: str, new_config: Dict) -> bool:
        """更新设备三元组"""
        devices = self.config.get("devices_triple", [])
        for i, device in enumerate(devices):
            if device.get("device_id") == device_id:
                devices[i].update(new_config)
                self.config["devices_triple"] = devices
                self.save_config()
                logger.info(f"设备{device_id}配置已更新")
                return True
        logger.error(f"设备{device_id}不存在")
        return False

    def update_gateway_triple(self, new_config: Dict) -> bool:
        """更新网关三元组"""
        try:
            self.config["gateway_triple"].update(new_config)
            self.save_config()
            logger.info("网关三元组已更新")
            return True
        except Exception as e:
            logger.error(f"更新网关三元组失败: {str(e)}")
            return False

    def get_default_config(self) -> Dict:
        """获取默认配置"""
        return {
            "ha_url": "http://supervisor/core/api",
            "ha_token": "",
            "gateway_triple": {
                "product_key": "y8qxef45aaeuly4",
                "device_name": "gateway_default",
                "device_secret": ""
            },
            "devices_triple": [
                {
                    "device_id": "mi_smart_socket",
                    "product_key": "y8qxef45aaeuly4",
                    "device_name": "socket_001",
                    "device_secret": "",
                    "entity_prefix": "iot_cn_2004109533_pw6u1",
                    "enabled": True
                }
            ],
            "mqtt_config": {
                "host": "device.iot.163.com",
                "port": 1883,
                "keepalive": 60
            },
            "report_interval": 60,
            "discovery_retry_interval": 300,
            "retry_attempts": 5,
            "retry_delay": 3
        }
