"""HA实体发现（容错优化版）"""
import requests
import time
import logging
from typing import Dict, List, Optional
from .base_discovery import BaseDiscovery

# 属性映射（使用IoT原生参数名，避免双重转换）
PROPERTY_MAPPING = {
    # 标准开关插座属性映射（直接映射到IoT参数名）
    "child_lock_p_14_9": "child_lock",
    "switch_status_p_10_1": "switch_status", 
    "toggle_a_2_1": "toggle",
    "on_p_2_1": "state0",      # 总开关 → state0
    "on_p_7_1": "state1",      # 插口1 → state1
    "on_p_8_1": "state2",      # 插口2 → state2
    "on_p_9_1": "state3",      # 插口3 → state3
    "on_p_10_1": "state4",     # 插口4 → state4
    "on_p_11_1": "state5",     # 插口5 → state5
    "on_p_12_1": "state6",     # 插口6 → state6
    "default_power_on_state_p_2_2": "default",
    "electric_power_p_2_6": "active_power",
    "electric_power_p_": "active_power",  # 新格式
    "electric_current_p_": "current", 
    "electric_current_p_3_4": "current",     # 新格式
    "voltage_p_": "voltage",
    "power_consumption_p_": "energy",
    "power_consumption": "energy",     # 新格式 - 你的实体使用的格式
    "power_consumption_accumulation_way_p_3_3": "power_consumption_accumulation_way",
    "indicator_light_p_2_4": "indicator_light",
    # 数值传感器
    "power": "active_power",
    "current": "current",
    "energy": "energy"
}

class HADiscovery(BaseDiscovery):
    """HA实体发现类（容错优化）"""
    def __init__(self, config, ha_headers):
        super().__init__(config, "ha_discovery")
        self.ha_url = config.get("ha_url")
        self.ha_headers = ha_headers
        self.entities = []
        self.failed_devices = {}  # 记录发现失败的设备 {device_id: last_attempt_time}
        self.discovered_devices = {}  # 已发现的设备 {device_id: sensor_map}

    def load_ha_entities(self) -> bool:
        """加载HA实体列表（容错优化）"""
        try:
            ha_api_url = self.ha_url if self.ha_url.endswith("/") else f"{self.ha_url}/"
            resp = None

            for attempt in range(self.config.get("retry_attempts", 5)):
                try:
                    resp = requests.get(
                        f"{ha_api_url}states",
                        headers=self.ha_headers,
                        timeout=10,
                        verify=False
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

    def read_entity_value_safe(self, entity_id: str) -> Optional[any]:
        """安全读取实体值（单个实体失败不影响）"""
        try:
            return self.read_entity_value(entity_id)
        except Exception as e:
            self.logger.warning(f"读取实体{entity_id}失败（跳过）: {str(e)}")
            return None

    def read_entity_value(self, entity_id: str) -> any:
        """读取HA实体值"""
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

            if state in ("unknown", "unavailable", ""):
                return None

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
            raise e  # 抛出异常由上层处理

    def discover_single_device(self, device_config: Dict) -> Optional[Dict]:
        """发现单个设备（容错：单个失败不影响其他）"""
        device_id = device_config["device_id"]
        prefix = device_config["entity_prefix"]
        supported_props = device_config.get("supported_properties", [])

        try:
            self.logger.info(f"开始发现设备: {device_id}（前缀: {prefix}）")
            sensor_map = {}

            # 遍历实体匹配当前设备
            for entity in self.entities:
                entity_id = entity.get("entity_id", "")
                if not entity_id.startswith(("sensor.", "switch.", "select.")):
                    continue

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
                if property_name and property_name in supported_props:
                    sensor_map[property_name] = entity_id
                    self.logger.debug(f"设备{device_id}匹配到: {entity_id} → {property_name}")

            if sensor_map:
                self.logger.info(f"设备{device_id}发现成功，匹配到{len(sensor_map)}个实体")
                # 保存为统一的数据结构
                device_result = {
                    "device_id": device_id,
                    "config": device_config,
                    "sensors": sensor_map
                }
                self.discovered_devices[device_id] = device_result
                # 从失败列表移除
                if device_id in self.failed_devices:
                    del self.failed_devices[device_id]
                return device_result
            else:
                self.logger.warning(f"设备{device_id}未匹配到任何实体")
                self.failed_devices[device_id] = time.time()
                return None

        except Exception as e:
            self.logger.error(f"发现设备{device_id}失败（跳过）: {str(e)}")
            self.failed_devices[device_id] = time.time()
            return None

    def discover_all_devices(self, device_configs: List[Dict]) -> Dict:
        """发现所有设备（容错优化）"""
        matched_devices = {}
        
        # 先加载实体列表
        if not self.load_ha_entities():
            self.logger.error("实体列表加载失败，使用缓存的发现结果")
            return self.discovered_devices

        # 逐个发现设备（单个失败不影响）
        for device_config in device_configs:
            device_id = device_config["device_id"]
            if not device_config.get("enabled", True):
                self.logger.info(f"设备{device_id}已禁用，跳过发现")
                continue
            
            device_result = self.discover_single_device(device_config)
            if device_result:
                matched_devices[device_id] = device_result

        self.logger.info(f"批量发现完成，成功发现{len(matched_devices)}个设备，失败{len(self.failed_devices)}个")
        return matched_devices

    def retry_failed_devices(self, device_configs: List[Dict], retry_interval: int) -> Dict:
        """重试发现失败的设备"""
        now = time.time()
        retry_devices = []
        
        # 筛选需要重试的设备
        for device_id, last_attempt in self.failed_devices.items():
            if now - last_attempt >= retry_interval:
                # 找到设备配置
                for config in device_configs:
                    if config["device_id"] == device_id and config.get("enabled", True):
                        retry_devices.append(config)
                        break

        if not retry_devices:
            return {}

        self.logger.info(f"开始重试发现{len(retry_devices)}个失败设备")
        retry_results = {}
        for device_config in retry_devices:
            result = self.discover_single_device(device_config)
            if result:
                retry_results[device_config["device_id"]] = result

        self.logger.info(f"重试完成，成功恢复{len(retry_results)}个设备")
        return retry_results

    def get_discovered_devices(self) -> Dict:
        """获取已发现的设备"""
        return self.discovered_devices.copy()
