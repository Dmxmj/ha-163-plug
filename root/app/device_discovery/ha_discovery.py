"""HA实体发现（适配米家插座 + HA Add-on）"""
import requests
import time
import logging
from typing import Dict, List
from .base_discovery import BaseDiscovery

# 属性映射（米家插座实体→内部字段）
PROPERTY_MAPPING = {
    # 原有传感器（保留）
    "temperature": "temperature",
    "humidity": "humidity",
    "battery": "battery",
    # 插座开关
    "on_p_2_1": "all_switch",
    "on_p_7_1": "jack_1",
    "on_p_8_1": "jack_2",
    "on_p_9_1": "jack_3",
    "on_p_10_1": "jack_4",
    "on_p_11_1": "jack_5",
    "on_p_12_1": "jack_6",
    # 电量相关
    "electric_power_p_3_2": "electric_power",
    "electric_current_p_3_4": "electric_current",
    "voltage_p_3_5": "voltage",
    "power_consumption_p_3_1": "power_consumption",
    # 默认上电状态
    "default_power_on_state_p_2_2": "default_power_on_state",
    # 兜底匹配
    "electric_power": "electric_power",
    "electric_current": "electric_current",
    "voltage": "voltage",
    "power_consumption": "power_consumption",
}

class HADiscovery(BaseDiscovery):
    """HA实体发现类（适配Add-on）"""
    def __init__(self, config, ha_headers):
        super().__init__(config, "ha_discovery")
        self.ha_url = config.get("ha_url")
        self.ha_headers = ha_headers
        self.entities = []
        self.sub_devices = [d for d in config.get("sub_devices", []) if d.get("enabled", True)]
    
    def load_ha_entities(self) -> bool:
        """加载HA实体列表（适配supervisor API）"""
        try:
            # HA Add-on中supervisor的API路径处理
            ha_api_url = self.ha_url if self.ha_url.endswith("/") else f"{self.ha_url}/"
            resp = None
            
            for attempt in range(self.config.get("retry_attempts", 5)):
                try:
                    resp = requests.get(
                        f"{ha_api_url}states",
                        headers=self.ha_headers,
                        timeout=10,
                        verify=False  # 忽略HA自签名证书
                    )
                    resp.raise_for_status()
                    break
                except requests.exceptions.RequestException as e:
                    self.logger.warning(f"加载实体失败（{attempt+1}）: {str(e)}")
                    time.sleep(self.config.get("retry_delay", 3))
            
            if not resp or resp.status_code != 200:
                self.logger.error(f"HA API响应异常: {resp.status_code if resp else '无响应'}")
                return False
            
            self.entities = resp.json()
            self.logger.info(f"成功加载{len(self.entities)}个HA实体")
            return True
        
        except Exception as e:
            self.logger.error(f"加载实体失败: {str(e)}", exc_info=True)
            return False
    
    def read_entity_value(self, entity_id: str) -> any:
        """读取HA实体值（适配switch/select/sensor）"""
        try:
            ha_api_url = self.ha_url if self.ha_url.endswith("/") else f"{self.ha_url}/"
            resp = requests.get(
                f"{ha_api_url}states/{entity_id}",
                headers=self.ha_headers,
                timeout=5,
                verify=False
            )
            resp.raise_for_status()
            entity_data = resp.json()
            state = entity_data.get("state")
            
            # 空值处理
            if state in ("unknown", "unavailable", ""):
                return None
            
            # 类型适配
            if entity_id.startswith("switch."):
                return 1 if state == "on" else 0
            elif entity_id.startswith("select."):
                state_map = {"off": 0, "on": 1, "memory": 2}
                return state_map.get(state, 0)
            elif entity_id.startswith("sensor."):
                try:
                    return float(state)
                except ValueError:
                    return None
            return state
        
        except Exception as e:
            self.logger.error(f"读取实体{entity_id}失败: {str(e)}")
            return None
    
    def match_entities_to_devices(self) -> Dict:
        """匹配实体到设备"""
        matched_devices = {}
        
        # 初始化设备
        for device in self.sub_devices:
            device_id = device["id"]
            matched_devices[device_id] = {
                "config": device,
                "sensors": {},
                "last_data": None
            }
            self.logger.info(f"开始匹配设备: {device_id}（前缀: {device['ha_entity_prefix']}）")
        
        # 遍历实体匹配
        for entity in self.entities:
            entity_id = entity.get("entity_id", "")
            if not entity_id.startswith(("sensor.", "switch.", "select.")):
                continue
            
            # 匹配设备前缀
            for device_id, device_data in matched_devices.items():
                prefix = device_data["config"]["ha_entity_prefix"]
                entity_core = entity_id.split(".", 1)[1] if "." in entity_id else ""
                
                if prefix not in entity_core:
                    continue
                
                # 提取特征字段
                feature = entity_core.replace(prefix, "").strip("_")
                if not feature:
                    continue
                
                # 匹配属性
                property_name = None
                if feature in PROPERTY_MAPPING:
                    property_name = PROPERTY_MAPPING[feature]
                else:
                    for key in PROPERTY_MAPPING:
                        if key in feature:
                            property_name = PROPERTY_MAPPING[key]
                            break
                
                # 验证并保存
                if property_name and property_name in device_data["config"]["supported_properties"]:
                    device_data["sensors"][property_name] = entity_id
                    self.logger.info(f"匹配成功: {entity_id} → {property_name}")
                    break
        
        # 输出匹配结果
        for device_id, data in matched_devices.items():
            self.logger.info(f"设备{device_id}匹配到{len(data['sensors'])}个实体: {list(data['sensors'].keys())}")
        
        return matched_devices
    
    def discover(self) -> Dict:
        """执行发现流程"""
        self.logger.info("开始设备发现...")
        if not self.load_ha_entities():
            return {}
        return self.match_entities_to_devices()
