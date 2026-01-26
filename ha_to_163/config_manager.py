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
        try:
            # 尝试从bashio读取Add-on配置
            try:
                import bashio
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
            except ImportError:
                # 如果没有bashio，从环境变量或options.json读取
                logger.warning("bashio不可用，尝试从options.json读取配置")
                return self._load_from_options_file()
        except Exception as e:
            logger.error(f"加载配置失败: {str(e)}")
            return self.load_saved_config()
    
    def _load_from_options_file(self) -> Dict:
        """从options.json文件加载配置（备用方案）"""
        # 尝试多个可能的配置文件路径
        options_paths = ["/data/options.json", "/config/options.json", "options.json"]
        
        for options_path in options_paths:
            try:
                if os.path.exists(options_path):
                    logger.info(f"找到配置文件: {options_path}")
                    with open(options_path, "r", encoding="utf-8") as f:
                        options = json.load(f)
                    config = {
                        "ha_url": options.get("ha_url", "http://10.222.36.124:8123/api"),
                        "ha_token": options.get("ha_token", ""),
                        "gateway_triple": options.get("gateway_triple", {}),
                        "devices_triple": options.get("devices_triple", []),
                        "mqtt_config": {
                            "host": options.get("mqtt_host", "device.iot.163.com"),
                            "port": int(options.get("mqtt_port", 1883)),
                            "keepalive": 60
                        },
                        "report_interval": int(options.get("report_interval", 60)),
                        "discovery_retry_interval": int(options.get("discovery_retry_interval", 300)),
                        "retry_attempts": int(options.get("retry_attempts", 5)),
                        "retry_delay": int(options.get("retry_delay", 3))
                    }
                    self.config = config
                    self.save_config()
                    logger.info("配置从options.json加载成功")
                    return config
            except Exception as e:
                logger.error(f"从{options_path}加载配置失败: {str(e)}")
                continue
        
        # 尝试从环境变量加载基本配置
        logger.warning("未找到配置文件，尝试从环境变量加载")
        config = self.get_default_config()
        
        # 从环境变量覆盖配置
        if os.environ.get("HA_TOKEN"):
            config["ha_token"] = os.environ.get("HA_TOKEN")
        if os.environ.get("DEVICE_SECRET"):
            config["gateway_triple"]["device_secret"] = os.environ.get("DEVICE_SECRET")
            
        self.config = config
        logger.warning("使用默认配置（请在 Add-on 配置中填写必要信息）")
        return config

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

    def reload_config(self) -> Optional[Dict]:
        """重新加载配置（用于动态发现）"""
        try:
            logger.debug("重新加载配置...")
            fresh_config = self.load_from_env()
            if fresh_config:
                return fresh_config
            else:
                logger.warning("重新加载配置失败，使用缓存配置")
                return self.config
        except Exception as e:
            logger.error(f"重新加载配置异常: {str(e)}")
            return self.config

    def has_config_changed(self, last_check_time: float) -> bool:
        """检查配置是否已变更（基于文件修改时间）"""
        try:
            # 检查多个可能的配置文件
            config_files = ["/data/options.json", "/config/options.json", self.config_path]
            
            for config_file in config_files:
                if os.path.exists(config_file):
                    mtime = os.path.getmtime(config_file)
                    if mtime > last_check_time:
                        logger.debug(f"配置文件 {config_file} 已更新")
                        return True
            return False
        except Exception as e:
            logger.debug(f"检查配置变更异常: {str(e)}")
            return False

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
            "ha_url": "http://10.222.36.124:8123/api",
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
