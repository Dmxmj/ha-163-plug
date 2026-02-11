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
        self.use_ssl = mqtt_config.get("use_ssl", False)  # 添加SSL选项
        
        # 状态管理
        self.connected = False
        self.last_heartbeat = 0
        self.last_time_sync = 0
        self.reconnect_count = 0
        self.max_reconnect = 10
        self.enabled = device_config.get("enabled", True)
        self.reconnect_delay = 1
        
        # 自动重启机制
        self.failed_reconnect_count = 0  # 累计失败重连次数
        self.max_failed_reconnects = 10  # 最大失败重连次数，超过则重启程序
        self.restart_callback = None  # 程序重启回调函数
        
        # 状态缓存和同步管理
        self.cached_states = {}  # 缓存最后的实体状态
        self.pending_states = {}  # 待推送的状态变化
        self.last_sync_time = 0  # 上次同步时间
        self.sync_on_reconnect = True  # 重连时是否同步状态
        self.subscribed_topics = set()  # 已订阅的主题集合
        
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
        
    def _generate_mqtt_password(self) -> str:
        """生成MQTT连接密码（基于HMAC-SHA256的动态令牌）"""
        try:
            # 每5分钟同步一次时间
            if time.time() - self.last_time_sync > 300:
                self._sync_time()
            
            timestamp = int(time.time())
            counter = timestamp // 300  # 每5分钟更新一次计数器
            self.logger.info(f"密码生成参数 - 时间戳: {timestamp}, counter: {counter}, device_secret: {self.device_secret}")
            
            counter_bytes = str(counter).encode('utf-8')
            secret_bytes = self.device_secret.encode('utf-8')
            hmac_obj = hmac.new(secret_bytes, counter_bytes, hashlib.sha256)
            # 修复：使用正确的方式 - 获取二进制摘要前10字节，然后转hex大写
            token = hmac_obj.digest()[:10].hex().upper()
            password = f"v1:{token}"
            self.logger.info(f"生成的MQTT密码: {password}")
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
            
            # 订阅网关自己的控制主题
            client.subscribe(self.topic_control, qos=1)
            self.subscribed_topics.add(self.topic_control)
            self.logger.info(f"订阅网关控制Topic: {self.topic_control}")
            
            # ✅ 关键修复：如果是网关设备，订阅所有子设备的控制主题
            if hasattr(self, 'subdevice_configs') and self.subdevice_configs:
                for subdevice_config in self.subdevice_configs:
                    subdevice_pk = subdevice_config.get("product_key")
                    subdevice_dn = subdevice_config.get("device_name")
                    if subdevice_pk and subdevice_dn:
                        # 订阅子设备控制主题
                        subdevice_control_topic = f"sys/{subdevice_pk}/{subdevice_dn}/service/CommonService"
                        client.subscribe(subdevice_control_topic, qos=1)
                        self.subscribed_topics.add(subdevice_control_topic)
                        self.logger.info(f"✅ 订阅子设备控制Topic: {subdevice_control_topic}")
                        
                        # 订阅子设备属性设置主题（备用）
                        subdevice_property_set_topic = f"sys/{subdevice_pk}/{subdevice_dn}/thing/service/property/set"
                        client.subscribe(subdevice_property_set_topic, qos=1)
                        self.subscribed_topics.add(subdevice_property_set_topic)
                        self.logger.info(f"✅ 订阅子设备属性设置Topic: {subdevice_property_set_topic}")
            else:
                self.logger.warning("❌ 网关未配置子设备信息，无法订阅子设备控制主题")
            
            # 重连后同步状态（首次连接跳过）
            if self.sync_on_reconnect and (self.reconnect_count > 0 or self.cached_states or self.pending_states):
                self._sync_all_states_on_reconnect()
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
        """消息回调 - 处理云端下发的控制指令"""
        try:
            topic = msg.topic
            payload = json.loads(msg.payload.decode("utf-8"))
            self.logger.info(f"收到控制指令: {topic} -> {payload}")
            
            cmd_id = payload.get("id")
            params = payload.get("params", {})
            
            # 提取子设备信息（从Topic中解析）
            # Topic格式: sys/{product_key}/{device_name}/service/CommonService
            topic_parts = topic.split("/")
            if len(topic_parts) >= 5 and topic_parts[0] == "sys":
                subdevice_product_key = topic_parts[1]
                subdevice_device_name = topic_parts[2]
                
                # 查找对应的子设备配置
                target_device_config = None
                if hasattr(self, 'subdevice_configs') and self.subdevice_configs:
                    for device_config in self.subdevice_configs:
                        if (device_config.get("product_key") == subdevice_product_key and 
                            device_config.get("device_name") == subdevice_device_name):
                            target_device_config = device_config
                            break
                
                if target_device_config:
                    device_id = target_device_config.get("device_id", "未知设备")
                    entity_prefix = target_device_config.get("entity_prefix", "未知前缀")
                    
                    # 同步控制指令到HA
                    success = self._sync_to_ha_with_prefix(params, entity_prefix)
                    
                    # 构造回复消息
                    if success:
                        reply = {"id": cmd_id, "code": RESPONSE_CODE["success"], "data": params}
                        self.logger.info(f"设备{device_id}控制指令执行成功")
                    else:
                        reply = {"id": cmd_id, "code": RESPONSE_CODE["failed"], "data": {}}
                        self.logger.error(f"设备{device_id}控制指令执行失败")
                    
                    # 发送回复到对应的子设备回复主题
                    reply_topic = f"sys/{subdevice_product_key}/{subdevice_device_name}/service/CommonService_reply"
                    success_reply = self._publish(reply, reply_topic)
                    
                else:
                    self.logger.warning(f"未找到设备配置: {subdevice_product_key}/{subdevice_device_name}")
                    
                    # 发送失败回复
                    error_reply = {"id": cmd_id, "code": RESPONSE_CODE["param_error"], "data": {}}
                    reply_topic = f"sys/{subdevice_product_key}/{subdevice_device_name}/service/CommonService_reply"
                    self._publish(error_reply, reply_topic)
            else:
                self.logger.warning(f"无法解析控制指令Topic: {topic}")
                
        except Exception as e:
            self.logger.error(f"处理控制指令失败: {str(e)}")
            try:
                # 尽力发送错误回复
                error_reply = {
                    "id": payload.get("id", str(int(time.time()*1000))),
                    "code": RESPONSE_CODE["failed"], 
                    "data": {}
                }
                # 如果能解析到子设备信息，就发送到对应主题
                if topic and "sys/" in topic:
                    parts = topic.split("/")
                    if len(parts) >= 3:
                        error_topic = f"sys/{parts[1]}/{parts[2]}/service/CommonService_reply"
                        self._publish(error_reply, error_topic)
            except:
                pass

    def _on_disconnect(self, client, userdata, rc):
        """断开连接回调函数"""
        self.connected = False
        if rc != 0:
            self.logger.warning(f"MQTT断开连接（返回码: {rc}）")
            self._schedule_reconnect()  # 异常断开时自动重连
        else:
            self.logger.info("MQTT连接正常关闭")
    
    def _schedule_reconnect(self):
        """计划重连（非阻塞方式，增加自动重启机制）"""
        if self.reconnect_count >= self.max_reconnect or not self.enabled:
            self.failed_reconnect_count += 1
            self.logger.error(f"达到最大重连次数或已禁用，累计失败次数: {self.failed_reconnect_count}/{self.max_failed_reconnects}")
            
            # 检查是否需要自动重启程序
            if self.failed_reconnect_count >= self.max_failed_reconnects:
                self.logger.critical(f"MQTT重连失败次数达到 {self.max_failed_reconnects} 次，触发程序自动重启")
                if self.restart_callback:
                    self.restart_callback()
                else:
                    self.logger.error("未设置重启回调函数，无法自动重启程序")
            return
            
        if self.reconnect_delay < 60:
            self.reconnect_delay = min(self.reconnect_delay * 2, 60)  # 重连延迟翻倍，最大60秒
        
        self.logger.info(f"将在 {self.reconnect_delay} 秒后尝试重连（第{self.reconnect_count}次）")
        
        # 使用非阻塞方式延迟重连（将在后台线程中处理）
        import threading
        def delayed_reconnect():
            time.sleep(self.reconnect_delay)
            if self.enabled and self.reconnect_count < self.max_reconnect:
                self.logger.info("开始重连...")
                # 关键：每次重连都完全重新初始化，避免状态污染
                try:
                    if self.client:
                        self.client.loop_stop()
                        self.client.disconnect()
                        self.client = None
                    
                    success = self.connect()  # 完全重新连接
                    if success:
                        # 重连成功，重置失败计数器
                        self.failed_reconnect_count = 0
                        self.logger.info("✅ MQTT重连成功，重置失败计数器")
                    else:
                        self.failed_reconnect_count += 1
                        self.logger.warning(f"MQTT重连失败，累计失败次数: {self.failed_reconnect_count}")
                        
                except Exception as e:
                    self.failed_reconnect_count += 1
                    self.logger.error(f"重连异常: {e}，累计失败次数: {self.failed_reconnect_count}")
        
        reconnect_thread = threading.Thread(target=delayed_reconnect, daemon=True)
        reconnect_thread.start()

    def _on_publish(self, client, userdata, mid):
        """发布回调"""
        self.last_heartbeat = time.time()
        self.logger.debug(f"消息发布成功，Mid: {mid}")

    def _on_subscribe(self, client, userdata, mid, granted_qos):
        """订阅回调"""
        self.logger.debug(f"订阅成功，Mid: {mid}，QoS: {granted_qos}")

    def _on_log(self, client, userdata, level, buf):
        """MQTT日志回调（用于调试）"""
        if level == mqtt.MQTT_LOG_ERR:
            self.logger.error(f"MQTT错误: {buf}")
        elif level == mqtt.MQTT_LOG_WARNING:
            self.logger.warning(f"MQTT警告: {buf}")
        elif level == mqtt.MQTT_LOG_INFO:
            self.logger.info(f"MQTT信息: {buf}")
        else:
            self.logger.debug(f"MQTT调试: {buf}")

    def _publish(self, data: Dict, topic: str) -> bool:
        """安全发布消息"""
        if not self.connected or not self.enabled:
            self.logger.warning(f"MQTT连接不可用或设备已禁用，跳过发布")
            return False
        
        try:
            payload = json.dumps(data, ensure_ascii=False)
            self.logger.info(f"发送数据到{topic}: {payload}")
            
            # 检查MQTT客户端状态
            if not self.client:
                self.logger.error("MQTT客户端未初始化")
                return False
            
            # 发布消息
            result = self.client.publish(topic, payload, qos=1)
            
            # 等待发布确认
            try:
                result.wait_for_publish(timeout=10)
            except Exception as wait_e:
                self.logger.error(f"发布超时: {wait_e}")
                return False
            
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                # 详细的错误码说明
                error_meanings = {
                    1: "内存不足", 2: "协议错误", 3: "输入参数无效",
                    4: "客户端未连接", 5: "连接被拒绝", 6: "消息未找到",
                    7: "连接丢失", 8: "TLS错误", 9: "负载过大",
                    10: "不支持", 11: "认证错误", 12: "ACL拒绝",
                    13: "未知错误", 14: "系统错误", 15: "队列大小错误"
                }
                error_msg = error_meanings.get(result.rc, f"未知错误码: {result.rc}")
                self.logger.error(f"发布失败: {error_msg}")
                return False
            else:
                self.logger.info(f"发布成功")
                return True
        except Exception as e:
            self.logger.error(f"发布异常: {str(e)}")
            return False

    def _sync_to_ha(self, params: Dict):
        """同步命令到HA"""
        return self._sync_to_ha_with_prefix(params, self.entity_prefix)

    def _sync_to_ha_with_prefix(self, params: Dict, entity_prefix: str) -> bool:
        """同步控制指令到HA（支持指定entity_prefix）"""
        ha_url = self.ha_config.get("ha_url")
        ha_headers = self.ha_config.get("ha_headers")
        if not ha_url or not ha_headers:
            self.logger.error("HA配置不完整，无法同步控制指令")
            return False
        
        success_count = 0
        total_count = len(params)
        
        try:
            ha_api_url = ha_url if ha_url.endswith("/") else f"{ha_url}/"
            
            for param, value in params.items():
                try:
                    # 映射参数到实体ID（使用指定的entity_prefix）
                    entity_id = self._map_param_to_entity_with_prefix(param, entity_prefix)
                    if not entity_id:
                        self.logger.warning(f"参数{param}无法映射到HA实体")
                        continue
                    
                    # 转换IoT值到HA状态
                    if param in ["state0", "state1", "state2", "state3", "state4", "state5", "state6"]:
                        # 开关类型
                        ha_state = "on" if value == 1 else "off"
                        service = "switch.turn_on" if value == 1 else "switch.turn_off"
                        service_data = {"entity_id": entity_id}
                    elif param == "default":
                        # 默认状态选择器 (智能插座上电状态)
                        state_map = {0: "上电关闭", 1: "上电打开", 2: "断电记忆"}
                        ha_state = state_map.get(value, "上电关闭")
                        service = "select.select_option"
                        service_data = {"entity_id": entity_id, "option": ha_state}
                    else:
                        # 传感器类型（只读，跳过）
                        self.logger.debug(f"跳过只读参数{param}")
                        continue
                    
                    self.logger.info(f"🎯 同步控制指令: {param}={value} → {entity_id}={ha_state}")
                    
                    # 先验证实体是否存在
                    # 处理HA Add-on环境中的URL构建
                    if ha_api_url.endswith("/api/") or ha_api_url.endswith("/api"):
                        entity_check_url = f"{ha_api_url.rstrip('/')}/states/{entity_id}"
                    else:
                        entity_check_url = f"{ha_api_url}api/states/{entity_id}"
                    
                    entity_check_resp = requests.get(
                        entity_check_url,
                        headers=ha_headers,
                        timeout=5,
                        verify=False
                    )
                    
                    if entity_check_resp.status_code != 200:
                        self.logger.error(f"❌ 实体{entity_id}不存在或不可访问，状态码: {entity_check_resp.status_code}")
                        continue
                    
                    # 调用HA服务API（比直接设置state更可靠）
                    domain, service_name = service.split('.', 1)
                    
                    # 处理HA Add-on环境中的服务URL构建
                    if ha_api_url.endswith("/api/") or ha_api_url.endswith("/api"):
                        service_url = f"{ha_api_url.rstrip('/')}/services/{domain}/{service_name}"
                    else:
                        service_url = f"{ha_api_url}api/services/{domain}/{service_name}"
                    
                    self.logger.debug(f"🔧 调用HA服务: {service_url}")
                    self.logger.debug(f"🔧 请求数据: {service_data}")
                    
                    service_resp = requests.post(
                        service_url,
                        headers=ha_headers,
                        json=service_data,
                        timeout=10,
                        verify=False
                    )
                    
                    if service_resp.status_code == 200:
                        self.logger.info(f"✅ 控制指令执行成功: {entity_id} → {ha_state}")
                        success_count += 1
                    else:
                        self.logger.error(f"❌ 控制指令执行失败: {entity_id}, 状态码: {service_resp.status_code}")
                        self.logger.error(f"响应内容: {service_resp.text}")
                        
                        # 尝试通过states API直接设置（作为备用方案）
                        self.logger.info(f"🔄 尝试通过states API设置: {entity_id}")
                        
                        # 处理HA Add-on环境中的states API URL构建
                        if ha_api_url.endswith("/api/") or ha_api_url.endswith("/api"):
                            states_url = f"{ha_api_url.rstrip('/')}/states/{entity_id}"
                        else:
                            states_url = f"{ha_api_url}api/states/{entity_id}"
                        
                        states_resp = requests.post(
                            states_url,
                            headers=ha_headers,
                            json={"state": ha_state},
                            timeout=10,
                            verify=False
                        )
                        
                        if states_resp.status_code in [200, 201]:
                            self.logger.warning(f"⚠️ 通过states API更新显示状态: {entity_id} → {ha_state} (设备可能未实际响应)")
                            # 注意：states API只更新显示状态，不算控制成功
                        else:
                            self.logger.error(f"❌ states API也失败: {entity_id}, 状态码: {states_resp.status_code}")
                        
                except Exception as e:
                    self.logger.error(f"处理参数{param}时出错: {e}")
                    continue
            
            self.logger.info(f"控制指令同步完成: {success_count}/{total_count} 成功")
            return success_count == total_count
            
        except Exception as e:
            self.logger.error(f"同步控制指令到HA失败: {e}")
            return False

    def _map_param_to_entity(self, param: str) -> Optional[str]:
        """映射IoT参数到HA实体ID"""
        return self._map_param_to_entity_with_prefix(param, self.entity_prefix)

    def _map_param_to_entity_with_prefix(self, param: str, entity_prefix: str) -> Optional[str]:
        """映射IoT参数到HA实体ID（优先使用发现阶段的缓存数据）"""
        
        # 1. 首先尝试从发现模块的缓存中查找
        if self.discovery:
            discovered_devices = self.discovery.get_discovered_devices()
            for device_id, device_info in discovered_devices.items():
                # 检查是否是目标设备（通过entity_prefix匹配）
                device_prefix = device_info.get('config', {}).get('entity_prefix', '')
                if device_prefix == entity_prefix:
                    # 从sensors映射中查找对应的实体
                    sensors = device_info.get('sensors', {})
                    if param in sensors:
                        entity_id = sensors[param]
                        self.logger.info(f"✅ 从发现缓存获取实体: {param} → {entity_id}")
                        return entity_id
        
        # 2. 如果缓存中没有，则使用动态查询（兜底方案）
        self.logger.warning(f"缓存中未找到{param}，尝试动态查询...")
        
        # 参数到实体特征后缀的映射（基于发现时的规律）
        param_to_suffix = {
            "state0": "on_p_2_1",
            "state1": "on_p_7_1", 
            "state2": "on_p_8_1",
            "state3": "on_p_9_1", 
            "state4": "on_p_10_1",
            "state5": "on_p_11_1",
            "state6": "on_p_12_1",
            "default": "default_power_on_state_p_2_2"
        }
        
        param_to_domain = {
            "state0": "switch", "state1": "switch", "state2": "switch",
            "state3": "switch", "state4": "switch", "state5": "switch", 
            "state6": "switch", "default": "select"
        }
        
        suffix = param_to_suffix.get(param)
        domain = param_to_domain.get(param)
        if not suffix or not domain:
            self.logger.warning(f"参数{param}不支持控制")
            return None
        
        # 动态查询HA实体
        ha_url = self.ha_config.get("ha_url")
        ha_headers = self.ha_config.get("ha_headers")
        if not ha_url or not ha_headers:
            self.logger.error("HA配置不完整，无法查询实体")
            return None
        
        try:
            # 查询HA中的所有实体
            # 处理HA Add-on环境中的URL构建
            if ha_url.endswith("/api") or ha_url.endswith("/api/"):
                states_list_url = f"{ha_url.rstrip('/')}/states"
            else:
                states_list_url = f"{ha_url}/api/states"
            
            resp = requests.get(
                states_list_url,
                headers=ha_headers,
                timeout=10,
                verify=False
            )
            if resp.status_code != 200:
                self.logger.error(f"查询HA实体失败，状态码: {resp.status_code}")
                self.logger.error(f"响应内容: {resp.text}")
                return None

            entities = resp.json()
            # 精确匹配：同时满足domain、entity_prefix、suffix
            for entity in entities:
                entity_id = entity["entity_id"]
                if (entity_id.startswith(f"{domain}.") and 
                    entity_prefix in entity_id and 
                    entity_id.endswith(suffix)):
                    self.logger.info(f"✅ 动态查询匹配: {param} → {entity_id}")
                    return entity_id
            
            # 如果精确匹配失败，使用硬编码兜底
            fallback_entity = f"{domain}.{entity_prefix}_{suffix}"
            self.logger.warning(f"⚠️ 动态查询失败，使用兜底映射: {param} → {fallback_entity}")
            return fallback_entity

        except Exception as e:
            self.logger.error(f"动态查询实体异常: {e}")
            # 异常情况下的硬编码兜底
            fallback_entity = f"{param_to_domain[param]}.{entity_prefix}_{param_to_suffix[param]}"
            return fallback_entity

    def _init_mqtt_client(self):
        """初始化MQTT客户端，设置认证信息和回调函数"""
        try:
            client_id = self.device_name
            username = self.product_key
            password = self._generate_mqtt_password()
            
            # 每次重新创建客户端实例（避免重连时的状态问题）
            if self.client:
                try:
                    self.client.loop_stop()
                    self.client.disconnect()
                except:
                    pass
            
            self.client = mqtt.Client(client_id=client_id, clean_session=True, protocol=mqtt.MQTTv311)
            self.client.username_pw_set(username=username, password=password)
            
            if self.use_ssl:
                self.client.tls_set()
                self.logger.info("已启用SSL加密连接")
            
            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect
            self.client.on_message = self._on_message
            self.client.on_publish = self._on_publish
            self.client.on_subscribe = self._on_subscribe
            self.client.on_log = self._on_log
            
            self.logger.info(f"MQTT客户端初始化完成 - ClientID: {client_id}, Username: {username}")
            self.logger.info(f"当前密码: {password}")
        except Exception as e:
            self.logger.error(f"MQTT客户端初始化失败: {e}")
            raise

    def connect(self) -> bool:
        """连接到MQTT服务器"""
        if not self.enabled:
            self.logger.info(f"设备{self.device_id}已禁用，跳过连接")
            return False
            
        self._init_mqtt_client()
        try:
            # 根据SSL配置选择端口 - 参考工作代码的逻辑
            port = 8883 if self.use_ssl else self.mqtt_port
            self.logger.info(f"连接MQTT服务器: {self.mqtt_host}:{port} (SSL: {self.use_ssl})")
            self.client.connect(self.mqtt_host, port, keepalive=60)
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
        """推送属性数据（支持断线时缓存状态）"""
        # 缓存最新的HA实体状态
        self._cache_states(ha_data)
        
        if not self.connected or not self.enabled:
            # 如果未连接，将状态加入待推送队列
            self.pending_states.update(ha_data)
            self.logger.warning(f"MQTT未连接，状态已加入待推送队列: {ha_data}")
            return
        
        payload = {
            "id": str(int(time.time()*1000)),
            "params": self._convert_ha_data(ha_data)
        }
        self._publish(payload, self.topic_property_post)
        self.logger.info(f"属性推送成功: {payload}")

    def _convert_ha_data(self, ha_data: Dict) -> Dict:
        """转换HA数据为IoT格式（直接使用IoT原生参数名，避免双重转换）"""
        converted = {}
        for iot_key, value in ha_data.items():
            if value is not None:
                # 值类型转换
                if iot_key in ["state0", "state1", "state2", "state3", "state4", "state5", "state6"]:
                    # 开关类型：确保为整数 0 或 1
                    converted[iot_key] = 1 if value in [1, "1", "on", True, "True"] else 0
                elif iot_key == "default":
                    # 默认状态选择器：反向映射（HA中文选项 → 网易云数值）
                    reverse_state_map = {"上电关闭": 0, "上电打开": 1, "断电记忆": 2}
                    if isinstance(value, str):
                        converted[iot_key] = reverse_state_map.get(value, 0)
                    else:
                        # 如果是数字，直接使用
                        converted[iot_key] = int(value) if isinstance(value, (int, float)) else 0
                elif iot_key in ["active_power", "current", "voltage", "energy"]:
                    # 传感器数值：确保为浮点数
                    try:
                        converted[iot_key] = float(value)
                    except (ValueError, TypeError):
                        self.logger.warning(f"无法转换{iot_key}的值{value}为浮点数")
                        continue
                else:
                    # 其他属性直接保留
                    converted[iot_key] = value
        
        self.logger.debug(f"数据转换: {ha_data} -> {converted}")
        return converted

    def push_subdevice_property(self, device_config: Dict[str, any], ha_data: Dict):
        """推送子设备属性数据（按照网易IoT物模型规范）"""
        if not self.connected or not self.enabled or not ha_data or not device_config:
            self.logger.warning(f"无法推送子设备数据: connected={self.connected}, enabled={self.enabled}")
            return False
        
        try:
            # 获取子设备信息
            subdevice_product_key = device_config.get("product_key")
            subdevice_device_name = device_config.get("device_name") 
            subdevice_id = device_config.get("device_id")
            
            if not subdevice_product_key or not subdevice_device_name:
                self.logger.error(f"子设备{subdevice_id}配置不完整")
                return False
            
            # 转换HA数据为IoT格式
            converted_data = self._convert_ha_data(ha_data)
            if not converted_data:
                self.logger.warning(f"子设备{subdevice_id}无有效数据可推送")
                return False
            
            # 构造属性上报消息（按照物模型规范）
            payload = {
                "id": str(int(time.time() * 1000)),
                "params": converted_data
            }
            
            # 使用正确的属性上报Topic：sys/ProductKey/DeviceName/event/property/post
            topic = f"sys/{subdevice_product_key}/{subdevice_device_name}/event/property/post"
            success = self._publish(payload, topic)
            
            if success:
                self.logger.info(f"✅ 子设备{subdevice_id}属性数据推送成功: {converted_data}")
                self.logger.info(f"推送Topic: {topic}")
                return True
            else:
                self.logger.error(f"❌ 子设备{subdevice_id}属性数据推送失败")
                return False
                
        except Exception as e:
            self.logger.error(f"推送子设备{device_config.get('device_id')}属性数据异常: {e}")
            return False

    def _cache_states(self, ha_data: Dict):
        """缓存HA实体状态"""
        try:
            self.cached_states.update(ha_data)
            self.last_sync_time = time.time()
            self.logger.debug(f"状态已缓存: {ha_data}")
        except Exception as e:
            self.logger.error(f"缓存状态失败: {e}")

    def _sync_all_states_on_reconnect(self):
        """重连后同步所有状态"""
        try:
            # 合并缓存状态和待推送状态
            all_states = {**self.cached_states, **self.pending_states}
            
            if not all_states:
                self.logger.info("重连后无状态需要同步")
                return
            
            self.logger.info(f"重连后同步状态: {len(all_states)} 个实体")
            
            # 推送所有状态
            if all_states:
                payload = {
                    "id": str(int(time.time()*1000)),
                    "params": self._convert_ha_data(all_states)
                }
                self._publish(payload, self.topic_property_post)
                self.logger.info(f"重连后状态同步完成: {payload}")
                
                # 清空待推送队列
                self.pending_states.clear()
            
        except Exception as e:
            self.logger.error(f"重连后状态同步失败: {e}")

    def _fetch_current_ha_states(self) -> Dict:
        """从HA API获取当前所有相关实体的状态"""
        ha_url = self.ha_config.get("ha_url")
        ha_headers = self.ha_config.get("ha_headers")
        
        if not ha_url or not ha_headers:
            self.logger.warning("HA配置不完整，无法获取当前状态")
            return {}
        
        try:
            ha_api_url = ha_url if ha_url.endswith("/") else f"{ha_url}/"
            current_states = {}
            
            # 定义需要同步的实体映射
            entity_map = {
                f"switch.{self.entity_prefix}_on_p_2_1": "all_switch",
                f"switch.{self.entity_prefix}_on_p_7_1": "jack_1", 
                f"switch.{self.entity_prefix}_on_p_8_1": "jack_2",
                f"switch.{self.entity_prefix}_on_p_9_1": "jack_3",
                f"switch.{self.entity_prefix}_on_p_10_1": "jack_4",
                f"switch.{self.entity_prefix}_on_p_11_1": "jack_5",
                f"switch.{self.entity_prefix}_on_p_12_1": "jack_6",
                f"select.{self.entity_prefix}_default_power_on_state_p_2_2": "default_power_on_state",
                f"sensor.{self.entity_prefix}_electric_power_p_2_6": "electric_power",
                f"sensor.{self.entity_prefix}_electric_current_p_2_7": "electric_current",
                f"sensor.{self.entity_prefix}_voltage_p_2_8": "voltage",
                f"sensor.{self.entity_prefix}_power_consumption_p_2_9": "power_consumption"
            }
            
            # 获取每个实体的状态
            for entity_id, ha_key in entity_map.items():
                try:
                    resp = requests.get(
                        f"{ha_api_url}states/{entity_id}",
                        headers=ha_headers,
                        timeout=5,
                        verify=False
                    )
                    if resp.status_code == 200:
                        state_data = resp.json()
                        state_value = state_data.get("state")
                        
                        # 转换状态值
                        if ha_key in ["all_switch", "jack_1", "jack_2", "jack_3", "jack_4", "jack_5", "jack_6"]:
                            current_states[ha_key] = 1 if state_value == "on" else 0
                        elif ha_key == "default_power_on_state":
                            # 智能插座上电状态：中文选项映射
                            state_map = {"上电关闭": 0, "上电打开": 1, "断电记忆": 2}
                            current_states[ha_key] = state_map.get(state_value, 0)
                        else:
                            # 数值类型传感器
                            try:
                                current_states[ha_key] = float(state_value)
                            except (ValueError, TypeError):
                                self.logger.warning(f"实体 {entity_id} 状态值无法转换为数值: {state_value}")
                                
                except requests.exceptions.RequestException as e:
                    self.logger.warning(f"获取实体 {entity_id} 状态失败: {e}")
                except Exception as e:
                    self.logger.error(f"处理实体 {entity_id} 状态时出错: {e}")
            
            self.logger.info(f"从HA获取到 {len(current_states)} 个实体状态")
            return current_states
            
        except Exception as e:
            self.logger.error(f"获取HA当前状态失败: {e}")
            return {}

    def force_sync_all_states(self):
        """强制同步所有当前状态（用于手动触发）"""
        if not self.connected or not self.enabled:
            self.logger.warning("MQTT未连接，无法强制同步状态")
            return False
        
        try:
            # 获取当前HA状态
            current_states = self._fetch_current_ha_states()
            if not current_states:
                self.logger.warning("无法获取到当前HA状态，强制同步取消")
                return False
            
            # 缓存并推送状态
            self._cache_states(current_states)
            
            payload = {
                "id": str(int(time.time()*1000)),
                "params": self._convert_ha_data(current_states)
            }
            self._publish(payload, self.topic_property_post)
            self.logger.info(f"强制同步状态完成: {len(current_states)} 个实体")
            return True
            
        except Exception as e:
            self.logger.error(f"强制同步状态失败: {e}")
            return False

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
