"""网易IoT MQTT客户端（支持动态设备管理）"""
import json
import logging
import time
from typing import Dict, Any, Optional
import paho.mqtt.client as mqtt
from iot_model.config import RESPONSE_CODE, VALUE_MEANING
import requests

class NeteaseIoTClient:
    """IoT客户端（动态设备版）"""
    def __init__(self, device_config: Dict, mqtt_config: Dict):
        # 设备三元组
        self.device_id = device_config["device_id"]
        self.product_key = device_config["product_key"]
        self.device_name = device_config["device_name"]
        self.device_secret = device_config["device_secret"]
        self.entity_prefix = device_config["entity_prefix"]
        
        # MQTT配置
        self.mqtt_host = mqtt_config.get("host")
        self.mqtt_port = mqtt_config.get("port")
        self.keepalive = mqtt_config.get("keepalive", 60)
        
        # MQTT客户端（长连接配置）
        self.client_id = f"{self.product_key}_{self.device_name}"
        self.client = mqtt.Client(
            client_id=self.client_id,
            clean_session=False,
            protocol=mqtt.MQTTv311
        )
        # 如果有密钥，添加认证（根据网易IoT实际认证方式调整）
        if self.device_secret:
            self.client.username_pw_set(self.device_name, self.device_secret)
        
        # 回调函数
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect
        self.client.on_publish = self._on_publish
        self.client.on_subscribe = self._on_subscribe
        
        # 状态管理
        self.connected = False
        self.last_heartbeat = 0
        self.reconnect_count = 0
        self.max_reconnect = 10
        self.enabled = device_config.get("enabled", True)
        
        # Topic配置（动态生成）
        self.topic_control = f"sys/{self.product_key}/{self.device_name}/service/CommonService"
        self.topic_control_reply = f"sys/{self.product_key}/{self.device_name}/service/CommonService_reply"
        self.topic_property_post = f"sys/{self.product_key}/{self.device_name}/event/property/post"
        
        # 日志
        self.logger = logging.getLogger(f"iot_client_{self.device_id}")
        
        # HA配置
        self.ha_config = {}

    def set_ha_config(self, ha_config: Dict):
        """设置HA配置"""
        self.ha_config = ha_config

    def _on_connect(self, client, userdata, flags, rc):
        """连接回调"""
        if rc == 0:
            self.connected = True
            self.last_heartbeat = time.time()
            self.reconnect_count = 0
            self.logger.info(f"IoT长连接成功: {self.device_id} (ClientID: {self.client_id})")
            self.client.subscribe(self.topic_control, qos=1)
        else:
            self.connected = False
            self.reconnect_count += 1
            self.logger.error(f"连接失败，错误码{rc}，重连次数{self.reconnect_count}/{self.max_reconnect}")

    def _on_message(self, client, userdata, msg):
        """消息回调"""
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            self.logger.info(f"收到命令: {payload}")
            
            cmd_id = payload.get("id")
            params = payload.get("params", {})
            reply = {"id": cmd_id, "code": RESPONSE_CODE["success"], "data": {}}
            
            # 处理命令（简化版，可根据实际需求扩展）
            for param, value in params.items():
                reply["data"][param] = value
            
            self._publish(reply, self.topic_control_reply)
            self._sync_to_ha(params)
        except Exception as e:
            self.logger.error(f"处理命令失败: {str(e)}")
            error_reply = {
                "id": str(int(time.time()*1000)),
                "code": RESPONSE_CODE["failed"],
                "data": {}
            }
            self._publish(error_reply, self.topic_control_reply)

    def _on_disconnect(self, client, userdata, rc):
        """断开回调"""
        self.connected = False
        if rc != 0 and self.reconnect_count < self.max_reconnect:
            self.logger.warning(f"连接断开，{5}秒后重连")
            time.sleep(5)
            self.reconnect()

    def _on_publish(self, client, userdata, mid):
        """发布回调"""
        self.last_heartbeat = time.time()
        self.logger.debug(f"消息发布成功，Mid: {mid}")

    def _on_subscribe(self, client, userdata, mid, granted_qos):
        """订阅回调"""
        self.logger.debug(f"订阅成功，Mid: {mid}，QoS: {granted_qos}")

    def _publish(self, data: Dict, topic: str):
        """安全发布消息"""
        if not self.connected or not self.enabled:
            return
        
        try:
            payload = json.dumps(data, ensure_ascii=False)
            result = self.client.publish(topic, payload, qos=1)
            result.wait_for_publish()
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                self.logger.error(f"发布失败，错误码{result.rc}")
        except Exception as e:
            self.logger.error(f"发布异常: {str(e)}")

    def _sync_to_ha(self, params: Dict):
        """同步命令到HA"""
        ha_url = self.ha_config.get("ha_url")
        ha_headers = self.ha_config.get("ha_headers")
        if not ha_url or not ha_headers:
            return
        
        try:
            # 简化版同步逻辑，可根据实际属性映射扩展
            ha_api_url = ha_url if ha_url.endswith("/") else f"{ha_url}/"
            for param, value in params.items():
                # 映射参数到实体ID
                entity_id = self._map_param_to_entity(param)
                if not entity_id:
                    continue
                
                # 转换状态值
                ha_state = "on" if value == 1 else "off"
                if param == "default":
                    state_map = {0: "off", 1: "on", 2: "memory"}
                    ha_state = state_map.get(value, "off")
                
                # 调用HA API
                resp = requests.post(
                    f"{ha_api_url}states/{entity_id}",
                    headers=ha_headers,
                    json={"state": ha_state},
                    timeout=5,
                    verify=False
                )
                resp.raise_for_status()
                self.logger.info(f"同步到HA成功: {entity_id} = {ha_state}")
        except Exception as e:
            self.logger.error(f"同步到HA失败: {str(e)}")

    def _map_param_to_entity(self, param: str) -> Optional[str]:
        """映射IoT参数到HA实体ID"""
        param_map = {
            "state0": f"switch.{self.entity_prefix}_on_p_2_1",
            "state1": f"switch.{self.entity_prefix}_on_p_7_1",
            "state2": f"switch.{self.entity_prefix}_on_p_8_1",
            "state3": f"switch.{self.entity_prefix}_on_p_9_1",
            "state4": f"switch.{self.entity_prefix}_on_p_10_1",
            "state5": f"switch.{self.entity_prefix}_on_p_11_1",
            "state6": f"switch.{self.entity_prefix}_on_p_12_1",
            "default": f"select.{self.entity_prefix}_default_power_on_state_p_2_2"
        }
        return param_map.get(param)

    def connect(self):
        """建立连接"""
        if not self.enabled:
            self.logger.info(f"设备{self.device_id}已禁用，跳过连接")
            return
        
        try:
            self.client.auto_reconnect = True
            self.client.connect(self.mqtt_host, self.mqtt_port, self.keepalive)
            self.client.loop_start()
            
            # 等待连接
            for _ in range(10):
                if self.connected:
                    break
                time.sleep(1)
        except Exception as e:
            self.logger.error(f"连接失败: {str(e)}")
            self.reconnect()

    def reconnect(self):
        """重连"""
        if self.reconnect_count >= self.max_reconnect or not self.enabled:
            return
        try:
            self.client.reconnect()
        except Exception as e:
            self.logger.error(f"重连失败: {str(e)}")
            time.sleep(5)
            self.reconnect()

    def disconnect(self):
        """断开连接"""
        self.client.loop_stop()
        self.client.disconnect()
        self.connected = False

    def push_property(self, ha_data: Dict):
        """推送属性数据"""
        if not self.connected or not self.enabled:
            return
        
        payload = {
            "id": str(int(time.time()*1000)),
            "params": self._convert_ha_data(ha_data)
        }
        self._publish(payload, self.topic_property_post)
        self.logger.info(f"属性推送成功: {payload}")

    def _convert_ha_data(self, ha_data: Dict) -> Dict:
        """转换HA数据为IoT格式"""
        data_map = {
            "all_switch": "state0",
            "jack_1": "state1",
            "jack_2": "state2",
            "jack_3": "state3",
            "jack_4": "state4",
            "jack_5": "state5",
            "jack_6": "state6",
            "default_power_on_state": "default",
            "electric_power": "active_power",
            "electric_current": "current",
            "voltage": "voltage",
            "power_consumption": "energy"
        }
        
        converted = {}
        for ha_key, value in ha_data.items():
            iot_key = data_map.get(ha_key)
            if iot_key and value is not None:
                converted[iot_key] = value
        return converted

    def update_config(self, new_config: Dict):
        """动态更新设备配置"""
        self.product_key = new_config.get("product_key", self.product_key)
        self.device_name = new_config.get("device_name", self.device_name)
        self.device_secret = new_config.get("device_secret", self.device_secret)
        self.entity_prefix = new_config.get("entity_prefix", self.entity_prefix)
        self.enabled = new_config.get("enabled", self.enabled)
        
        # 更新Topic
        self.topic_control = f"sys/{self.product_key}/{self.device_name}/service/CommonService"
        self.topic_control_reply = f"sys/{self.product_key}/{self.device_name}/service/CommonService_reply"
        self.topic_property_post = f"sys/{self.product_key}/{self.device_name}/event/property/post"
        
        # 更新认证
        if self.device_secret:
            self.client.username_pw_set(self.device_name, self.device_secret)
        
        self.logger.info(f"设备{self.device_id}配置已更新，enabled={self.enabled}")
        
        # 重新连接
        if self.enabled and not self.connected:
            self.reconnect()
        elif not self.enabled and self.connected:
            self.disconnect()
