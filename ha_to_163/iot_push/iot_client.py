"""网易IoT MQTT客户端（支持动态设备管理）"""
import json
import logging
import time
import hmac
import hashlib
from typing import Dict, Any, Optional
import paho.mqtt.client as mqtt
import requests

# 网易IoT响应码配置
RESPONSE_CODE = {
    "success": 200,
    "failed": 500,
    "timeout": 408,
    "param_error": 400
}

# 值映射配置
VALUE_MEANING = {
    "on": 1,
    "off": 0,
    True: 1,
    False: 0,
    "True": 1,
    "False": 0
}

class NeteaseIoTClient:
    """网易IoT MQTT客户端（正确的认证方式）"""
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
        
        # 状态管理
        self.connected = False
        self.last_heartbeat = 0
        self.last_time_sync = 0
        self.reconnect_count = 0
        self.max_reconnect = 10
        self.enabled = device_config.get("enabled", True)
        self.reconnect_delay = 1
        
        # Topic配置（动态生成）
        self.topic_control = f"sys/{self.product_key}/{self.device_name}/service/CommonService"
        self.topic_control_reply = f"sys/{self.product_key}/{self.device_name}/service/CommonService_reply"
        self.topic_property_post = f"sys/{self.product_key}/{self.device_name}/event/property/post"
        
        # 日志
        self.logger = logging.getLogger(f"iot_client_{self.device_id}")
        
        # HA配置
        self.ha_config = {}
        
        # MQTT客户端（将在连接时初始化）
        self.client = None
        
    def _generate_mqtt_password(self, device_secret: str) -> str:
        """生成MQTT连接密码（基于HMAC-SHA256的动态令牌）"""
        try:
            # 每5分钟同步一次时间
            if time.time() - self.last_time_sync > 300:
                self._sync_time()
            
            timestamp = int(time.time())
            counter = timestamp // 300  # 每5分钟更新一次计数器
            self.logger.debug(f"生成密码 - counter: {counter}, 时间戳: {timestamp}")
            
            counter_bytes = str(counter).encode('utf-8')
            secret_bytes = device_secret.encode('utf-8')
            hmac_obj = hmac.new(secret_bytes, counter_bytes, hashlib.sha256)
            token = hmac_obj.digest()[:10].hex().upper()
            password = f"v1:{token}"
            self.logger.debug(f"生成的MQTT密码: {password}")
            return password
        except Exception as e:
            self.logger.error(f"生成MQTT密码失败: {e}")
            raise
    
    def _sync_time(self):
        """通过NTP服务器同步时间（确保密码生成的时间准确性）"""
        try:
            from ntp_sync import sync_time_with_netease_ntp
            if sync_time_with_netease_ntp():
                self.last_time_sync = time.time()
                self.logger.info("NTP时间同步成功")
            else:
                self.logger.warning("NTP时间同步失败，使用本地时间")
        except Exception as e:
            self.logger.warning(f"时间同步异常: {e}")
    
    def _init_mqtt_client(self):
        """初始化MQTT客户端，设置正确的认证信息"""
        try:
            # 网易IoT平台认证参数
            client_id = self.device_name  # 使用设备名作为客户端ID
            username = self.product_key   # 使用产品密钥作为用户名
            password = self._generate_mqtt_password(self.device_secret)
            
            self.logger.info(f"初始化MQTT客户端 - ClientID: {client_id}, Username: {username}")
            
            self.client = mqtt.Client(
                client_id=client_id,
                clean_session=True,  # 网易IoT建议使用clean_session=True
                protocol=mqtt.MQTTv311
            )
            self.client.username_pw_set(username=username, password=password)
            
            # 设置回调函数
            self.client.on_connect = self._on_connect
            self.client.on_message = self._on_message
            self.client.on_disconnect = self._on_disconnect
            self.client.on_publish = self._on_publish
            self.client.on_subscribe = self._on_subscribe
            
            self.logger.info("MQTT客户端初始化完成")
        except Exception as e:
            self.logger.error(f"MQTT客户端初始化失败: {e}")
            raise

    def set_ha_config(self, ha_config: Dict):
        """设置HA配置"""
        self.ha_config = ha_config

    def _on_connect(self, client, userdata, flags, rc):
        """连接成功回调函数"""
        if rc == 0:
            self.connected = True
            self.last_heartbeat = time.time()
            self.reconnect_count = 0
            self.reconnect_delay = 1  # 重置重连延迟
            self.logger.info(f"MQTT连接成功: {self.device_id} (ClientID: {self.device_name})")
            
            # 订阅控制主题
            client.subscribe(self.topic_control, qos=1)
            self.logger.info(f"订阅控制Topic: {self.topic_control}")
        else:
            self.connected = False
            self.reconnect_count += 1
            # 详细的错误码说明
            error_messages = {
                1: "连接被拒绝 - MQTT 协议版本不正确",
                2: "连接被拒绝 - 客户端ID不可接受", 
                3: "连接被拒绝 - 服务器不可用",
                4: "连接被拒绝 - 用户名或密码错误",
                5: "连接被拒绝 - 未授权"
            }
            error_msg = error_messages.get(rc, f"未知错误码: {rc}")
            self.logger.error(f"MQTT连接失败: {error_msg}")
            self.logger.error(f"连接参数: Host={self.mqtt_host}, Port={self.mqtt_port}")
            self.logger.error(f"认证信息: Username={self.product_key}, ClientID={self.device_name}")
            
            # 如果是认证错误，暂停重连
            if rc == 4:  # 用户名或密码错误
                self.logger.error("认证失败，请检查设备密钥是否正确")
                self.enabled = False
            else:
                self._schedule_reconnect()

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
        """断开连接回调函数"""
        self.connected = False
        if rc != 0:
            self.logger.warning(f"MQTT断开连接（返回码: {rc}）")
            self._schedule_reconnect()  # 异常断开时自动重连
        else:
            self.logger.info("MQTT连接正常关闭")
    
    def _schedule_reconnect(self):
        """计划重连（指数退避策略）"""
        if self.reconnect_delay < 60:
            self.reconnect_delay *= 2  # 重连延迟翻倍（最大60秒）
        self.logger.info(f"{self.reconnect_delay}秒后尝试重连...")
        time.sleep(self.reconnect_delay)
        if self.enabled and self.reconnect_count < self.max_reconnect:
            self.connect()

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

    def connect(self) -> bool:
        """连接到MQTT服务器"""
        if not self.enabled:
            self.logger.info(f"设备{self.device_id}已禁用，跳过连接")
            return False
            
        self._init_mqtt_client()
        try:
            self.logger.info(f"连接MQTT服务器: {self.mqtt_host}:{self.mqtt_port}")
            self.client.connect(self.mqtt_host, self.mqtt_port, keepalive=self.keepalive)
            self.client.loop_start()  # 启动网络循环线程
            
            # 等待连接成功（超时10秒）
            start_time = time.time()
            while not self.connected and (time.time() - start_time) < 10:
                time.sleep(0.1)
            
            return self.connected
        except Exception as e:
            self.logger.error(f"MQTT连接失败: {e}")
            return False

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
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
            self.connected = False
            self.logger.info("MQTT连接已断开")

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
