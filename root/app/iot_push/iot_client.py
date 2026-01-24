"""网易IoT MQTT客户端（适配HA Add-on + 长连接）"""
import json
import logging
import time
from typing import Dict, Any
import paho.mqtt.client as mqtt
from iot_model.config import (
    PRODUCT_KEY, TOPIC_CONFIG, FIELD_MAPPING, RESPONSE_CODE, VALUE_MEANING
)
import requests

class NeteaseIoTClient:
    """IoT客户端（长连接版）"""
    def __init__(self, device_name: str, mqtt_config: Dict):
        self.device_name = device_name
        self.mqtt_host = mqtt_config.get("host")
        self.mqtt_port = mqtt_config.get("port")
        self.mqtt_username = mqtt_config.get("username")
        self.mqtt_password = mqtt_config.get("password")
        self.keepalive = mqtt_config.get("keepalive", 60)  # 长连接心跳间隔
        
        # MQTT客户端配置（长连接优化）
        self.client = mqtt.Client(
            client_id=f"{PRODUCT_KEY}_{device_name}",
            clean_session=False,  # 禁用clean session，保持长连接
            protocol=mqtt.MQTTv311
        )
        self.client.username_pw_set(self.mqtt_username, self.mqtt_password)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect
        self.client.on_publish = self._on_publish  # 新增发布回调
        self.client.on_subscribe = self._on_subscribe  # 新增订阅回调
        
        # 长连接状态监控
        self.connected = False
        self.last_heartbeat = 0
        self.reconnect_count = 0
        self.max_reconnect = 10  # 最大重连次数
        
        # 日志
        self.logger = logging.getLogger(f"iot_client_{device_name}")
        
        # Topic替换
        self.topic_control = TOPIC_CONFIG["control"].replace("$(deviceName)", device_name)
        self.topic_control_reply = TOPIC_CONFIG["control_reply"].replace("$(deviceName)", device_name)
        self.topic_property_post = TOPIC_CONFIG["property_post"].replace("$(deviceName)", device_name)
        
        # HA配置
        self.ha_config = {}

    def set_ha_config(self, ha_config: Dict):
        """设置HA配置"""
        self.ha_config = ha_config

    def _on_connect(self, client, userdata, flags, rc):
        """连接回调（长连接优化）"""
        if rc == 0:
            self.connected = True
            self.last_heartbeat = time.time()
            self.reconnect_count = 0
            self.logger.info(f"IoT长连接成功: {self.device_name} (MQTT keepalive: {self.keepalive}秒)")
            
            # 重新订阅命令Topic（确保长连接订阅不丢失）
            self.client.subscribe(self.topic_control, qos=1)
            self.logger.info(f"重新订阅命令Topic: {self.topic_control}")
        else:
            self.connected = False
            self.reconnect_count += 1
            self.logger.error(f"IoT连接失败，错误码{rc}，已重连{self.reconnect_count}/{self.max_reconnect}次")
            
            # 超过最大重连次数则停止
            if self.reconnect_count >= self.max_reconnect:
                self.logger.critical(f"达到最大重连次数({self.max_reconnect})，停止重连")

    def _on_message(self, client, userdata, msg):
        """消息回调（处理平台命令）"""
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            self.logger.info(f"收到平台命令: {payload}")
            
            # 解析命令
            cmd_id = payload.get("id")
            params = payload.get("params", {})
            
            # 响应数据
            reply = {
                "id": cmd_id,
                "code": RESPONSE_CODE["success"],
                "data": {}
            }
            
            # 处理命令
            commands = []
            for ha_field, config in FIELD_MAPPING.items():
                iot_field = config["iot_field"]
                if iot_field in params:
                    value = params[iot_field]
                    # 范围校验
                    if not (config["range"][0] <= value <= config["range"][1]):
                        self.logger.error(f"参数{iot_field}超出范围: {value}")
                        reply["code"] = RESPONSE_CODE["failed"]
                        continue
                    commands.append({
                        "ha_field": ha_field,
                        "value": value,
                        "iot_field": iot_field
                    })
                    reply["data"][iot_field] = value
            
            # 发送响应
            self._publish(reply, self.topic_control_reply)
            
            # 同步到HA
            self._sync_to_ha(commands)
        
        except Exception as e:
            self.logger.error(f"处理命令失败: {str(e)}", exc_info=True)
            error_reply = {
                "id": str(int(time.time()*1000)),
                "code": RESPONSE_CODE["failed"],
                "data": {}
            }
            self._publish(error_reply, self.topic_control_reply)

    def _on_disconnect(self, client, userdata, rc):
        """断开回调（长连接重连逻辑）"""
        self.connected = False
        self.logger.warning(f"IoT长连接断开，错误码{rc}")
        
        # 非主动断开则重连
        if rc != 0 and self.reconnect_count < self.max_reconnect:
            self.logger.info(f"{5}秒后尝试重连...")
            time.sleep(5)
            self.reconnect()

    def _on_publish(self, client, userdata, mid):
        """发布回调（更新心跳时间）"""
        self.last_heartbeat = time.time()
        self.logger.debug(f"消息发布成功，Mid: {mid}，更新心跳时间")

    def _on_subscribe(self, client, userdata, mid, granted_qos):
        """订阅回调"""
        self.logger.debug(f"Topic订阅成功，Mid: {mid}，QoS: {granted_qos}")

    def _publish(self, data: Dict, topic: str):
        """发布消息（长连接安全发布）"""
        if not self.connected:
            self.logger.warning("未连接到IoT平台，跳过消息发布")
            return
        
        try:
            payload = json.dumps(data, ensure_ascii=False)
            # 阻塞发布（确保消息发送成功）
            result = self.client.publish(topic, payload, qos=1, retain=False)
            result.wait_for_publish()
            
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                self.logger.error(f"消息发布失败，错误码: {result.rc}")
            else:
                self.logger.debug(f"推送消息: {topic} → {payload}")
        except Exception as e:
            self.logger.error(f"推送失败: {str(e)}")

    def _sync_to_ha(self, commands: list):
        """同步平台命令到HA"""
        ha_url = self.ha_config.get("ha_url")
        ha_headers = self.ha_config.get("ha_headers")
        prefix = self.ha_config.get("ha_entity_prefix")
        
        if not ha_url or not ha_headers:
            self.logger.error("HA配置未设置，无法同步命令")
            return
        
        ha_api_url = ha_url if ha_url.endswith("/") else f"{ha_url}/"
        
        for cmd in commands:
            try:
                # 构建实体ID
                entity_id = None
                if cmd["ha_field"] == "all_switch":
                    entity_id = f"switch.{prefix}_on_p_2_1"
                elif cmd["ha_field"].startswith("jack_"):
                    jack_num = cmd["ha_field"].split("_")[1]
                    p_num = 6 + int(jack_num)
                    entity_id = f"switch.{prefix}_on_p_{p_num}_1"
                elif cmd["ha_field"] == "default_power_on_state":
                    entity_id = f"select.{prefix}_default_power_on_state_p_2_2"
                
                if not entity_id:
                    continue
                
                # 转换状态
                ha_state = "on" if cmd["value"] == 1 else "off"
                if cmd["ha_field"] == "default_power_on_state":
                    state_map = {0: "off", 1: "on", 2: "memory"}
                    ha_state = state_map.get(cmd["value"], "off")
                
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

    def _validate_value(self, ha_field: str, value: Any) -> Any:
        """校验并转换值"""
        if ha_field not in FIELD_MAPPING:
            return None
        
        config = FIELD_MAPPING[ha_field]
        try:
            # 类型转换
            if config["type"] == "int":
                val = int(value)
            elif config["type"] == "float":
                val = float(value)
            else:
                val = value
            
            # 范围校验
            if not (config["range"][0] <= val <= config["range"][1]):
                self.logger.warning(f"值{val}超出范围，使用默认值{config['default']}")
                val = config["default"]
            
            return val
        except (ValueError, TypeError):
            self.logger.warning(f"值转换失败，使用默认值{config['default']}")
            return config["default"]

    def connect(self):
        """连接MQTT（长连接版）"""
        try:
            # 启用自动重连
            self.client.auto_reconnect = True
            self.client.connect(self.mqtt_host, self.mqtt_port, self.keepalive)
            # 启动后台循环（保持长连接）
            self.client.loop_start()
            
            # 等待连接成功
            for _ in range(10):  # 延长等待时间到10秒
                if self.connected:
                    break
                time.sleep(1)
            
            if not self.connected:
                self.logger.error("MQTT长连接超时")
        except Exception as e:
            self.logger.error(f"MQTT长连接失败: {str(e)}")
            self.reconnect()

    def reconnect(self):
        """重连（长连接优化）"""
        if self.reconnect_count >= self.max_reconnect:
            self.logger.error("达到最大重连次数，停止重连")
            return
        
        self.logger.info(f"尝试第{self.reconnect_count+1}次重连...")
        try:
            self.client.reconnect()
        except Exception as e:
            self.logger.error(f"重连失败: {str(e)}")
            time.sleep(5)
            self.reconnect()

    def disconnect(self):
        """断开连接（优雅关闭长连接）"""
        self.client.loop_stop()
        self.client.disconnect()
        self.connected = False
        self.logger.info("IoT长连接已优雅关闭")

    def push_property(self, ha_data: Dict):
        """推送属性数据（60秒一次）"""
        if not self.connected:
            self.logger.warning("MQTT未连接，尝试重连")
            self.reconnect()
            if not self.connected:
                return
        
        # 构建上报数据
        payload = {
            "id": str(int(time.time()*1000)),  # 使用NTP校时后的时间戳
            "params": {}
        }
        
        # 转换字段
        for ha_field, value in ha_data.items():
            val = self._validate_value(ha_field, value)
            if val is None:
                continue
            payload["params"][FIELD_MAPPING[ha_field]["iot_field"]] = val
        
        # 推送（长连接安全发布）
        self._publish(payload, self.topic_property_post)
        self.logger.info(f"属性上报成功（60秒间隔）: {payload}")
