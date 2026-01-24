"""HA Add-on主程序（动态设备管理+容错发现+长连接）"""
import logging
import time
import threading
import signal
import sys
from config_manager import ConfigManager
from device_discovery.ha_discovery import HADiscovery
from iot_push.iot_client import NeteaseIoTClient
from ntp_sync import sync_time_with_netease_ntp

# 全局日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("/data/gateway.log", encoding="utf-8")  # HA Add-on持久化日志
    ]
)
logger = logging.getLogger("163_gateway")

class GatewayManager:
    """网关核心管理器（支持动态设备、容错发现、自动恢复）"""
    def __init__(self):
        # 核心组件
        self.config_manager = ConfigManager()
        self.config = {}
        self.discovery = None
        self.iot_clients = {}  # {device_id: NeteaseIoTClient}
        
        # 运行状态控制
        self.running = False
        self.push_thread = None
        self.discovery_thread = None
        self.lock = threading.Lock()  # 线程安全锁
        
        # 注册信号处理（优雅退出）
        signal.signal(signal.SIGTERM, self._graceful_exit)
        signal.signal(signal.SIGINT, self._graceful_exit)

    def initialize(self) -> bool:
        """初始化网关（NTP校时→加载配置→初始化组件）"""
        # 1. 强制NTP校时（网易IoT必选）
        if not self._sync_ntp():
            logger.critical("NTP校时失败，程序无法启动")
            return False
        
        # 2. 加载配置（优先从HA Add-on读取，降级到本地缓存）
        self.config = self.config_manager.load_from_env()
        if not self.config:
            logger.critical("配置加载失败，程序无法启动")
            return False
        
        # 3. 初始化HA实体发现模块
        ha_headers = {
            "Authorization": f"Bearer {self.config['ha_token']}",
            "Content-Type": "application/json"
        }
        self.discovery = HADiscovery(self.config, ha_headers)
        
        # 4. 初始化所有启用设备的IoT客户端
        self._init_iot_clients()
        
        # 5. 标记运行状态
        self.running = True
        logger.info("=== 网关初始化完成 ===")
        return True

    def start(self):
        """启动网关核心线程"""
        if not self.running:
            logger.error("网关未完成初始化，启动失败")
            return
        
        # 启动数据推送线程（60秒/次）
        self.push_thread = threading.Thread(
            target=self._push_data_loop,
            name="DataPushThread",
            daemon=True
        )
        self.push_thread.start()
        
        # 启动设备发现重试线程（300秒/次）
        self.discovery_thread = threading.Thread(
            target=self._discovery_retry_loop,
            name="DiscoveryRetryThread",
            daemon=True
        )
        self.discovery_thread.start()
        
        logger.info("=== 网关已启动（推送间隔60秒，发现重试间隔300秒）===")
        
        # 主线程阻塞（保持程序运行）
        try:
            while self.running:
                time.sleep(1)
        except Exception as e:
            logger.error(f"主线程异常: {str(e)}")
        finally:
            self._graceful_exit()

    def _sync_ntp(self) -> bool:
        """NTP校时（最多重试3次）"""
        logger.info("=== 开始网易NTP服务器校时 ===")
        ntp_retry = 3
        for attempt in range(ntp_retry):
            if sync_time_with_netease_ntp(timeout=10):
                logger.info("=== NTP校时成功 ===")
                return True
            logger.warning(f"NTP校时第{attempt+1}次失败，5秒后重试")
            time.sleep(5)
        logger.error("=== NTP校时失败（已重试3次）===")
        return False

    def _init_iot_clients(self):
        """初始化IoT客户端（线程安全）"""
        with self.lock:
            # 获取所有启用的设备配置
            device_configs = self.config_manager.get_all_enabled_devices()
            mqtt_config = self.config["mqtt_config"]
            
            # 为每个设备创建IoT客户端
            for device_config in device_configs:
                device_id = device_config["device_id"]
                if device_id not in self.iot_clients:
                    # 创建客户端实例
                    client = NeteaseIoTClient(device_config, mqtt_config)
                    # 设置HA配置（用于命令同步）
                    client.set_ha_config({
                        "ha_url": self.config["ha_url"],
                        "ha_headers": {
                            "Authorization": f"Bearer {self.config['ha_token']}",
                            "Content-Type": "application/json"
                        }
                    })
                    # 保存客户端并建立连接
                    self.iot_clients[device_id] = client
                    client.connect()
                    logger.info(f"IoT客户端初始化完成: {device_id} (ProductKey: {device_config['product_key']})")

    def _push_data_loop(self):
        """数据推送循环（核心业务逻辑）"""
        while self.running:
            try:
                # 1. 获取当前已发现的所有设备
                discovered_devices = self.discovery.get_discovered_devices()
                logger.debug(f"推送循环 - 已发现设备数: {len(discovered_devices)}")
                
                # 2. 逐个设备处理（单个失败不影响其他）
                for device_id, device_info in discovered_devices.items():
                    try:
                        # 线程安全获取IoT客户端
                        with self.lock:
                            client = self.iot_clients.get(device_id)
                        
                        # 跳过禁用/未初始化的客户端
                        if not client or not client.enabled or not client.connected:
                            logger.debug(f"设备{device_id}跳过推送（禁用/未连接）")
                            continue
                        
                        # 3. 读取HA实体值（容错读取，单个实体失败不影响）
                        ha_data = {}
                        sensors = device_info.get("sensors", {})
                        for prop_name, entity_id in sensors.items():
                            value = self.discovery.read_entity_value_safe(entity_id)
                            if value is not None:
                                ha_data[prop_name] = value
                        
                        # 4. 推送数据（有有效数据才推送）
                        if ha_data:
                            client.push_property(ha_data)
                            logger.debug(f"设备{device_id}推送成功，字段数: {len(ha_data)}")
                        else:
                            logger.debug(f"设备{device_id}无有效数据可推送")
                    
                    except Exception as e:
                        # 单个设备推送失败，记录日志并继续处理下一个
                        logger.error(f"设备{device_id}推送异常（已跳过）: {str(e)}")
                        continue
                
                # 5. 等待推送间隔（固定60秒）
                time.sleep(self.config["report_interval"])
            
            except Exception as e:
                # 推送循环异常，记录并短暂等待后恢复
                logger.error(f"推送循环全局异常: {str(e)}", exc_info=True)
                time.sleep(10)

    def _discovery_retry_loop(self):
        """设备发现重试循环（自动恢复离线设备）"""
        while self.running:
            try:
                # 1. 获取所有启用的设备配置
                device_configs = self.config_manager.get_all_enabled_devices()
                retry_interval = self.config["discovery_retry_interval"]
                
                # 2. 重试发现失败的设备
                recovered_devices = self.discovery.retry_failed_devices(
                    device_configs,
                    retry_interval
                )
                
                # 3. 为恢复的设备初始化IoT客户端
                if recovered_devices:
                    with self.lock:
                        for device_id in recovered_devices.keys():
                            if device_id not in self.iot_clients:
                                # 重新获取设备配置
                                device_config = self.config_manager.get_device_triple(device_id)
                                if device_config:
                                    # 创建并启动IoT客户端
                                    client = NeteaseIoTClient(device_config, self.config["mqtt_config"])
                                    client.set_ha_config({
                                        "ha_url": self.config["ha_url"],
                                        "ha_headers": {
                                            "Authorization": f"Bearer {self.config['ha_token']}",
                                            "Content-Type": "application/json"
                                        }
                                    })
                                    self.iot_clients[device_id] = client
                                    client.connect()
                                    logger.info(f"设备{device_id}恢复上线，已加入推送队列")
                
                # 4. 全量重新发现（兜底，确保配置更新生效）
                if int(time.time()) % 3600 == 0:  # 每小时全量发现一次
                    self.discovery.discover_all_devices(device_configs)
                    logger.info("执行每小时全量设备发现，确保配置最新")
                
                # 5. 等待重试间隔（固定300秒）
                time.sleep(retry_interval)
            
            except Exception as e:
                logger.error(f"发现重试循环异常: {str(e)}", exc_info=True)
                time.sleep(60)

    def _graceful_exit(self, signum=None, frame=None):
        """优雅退出（关闭所有连接和线程）"""
        logger.info("=== 开始优雅退出网关 ===")
        self.running = False
        
        # 关闭所有IoT客户端连接
        with self.lock:
            for device_id, client in self.iot_clients.items():
                try:
                    client.disconnect()
                    logger.info(f"设备{device_id}IoT连接已关闭")
                except Exception as e:
                    logger.error(f"关闭设备{device_id}连接失败: {str(e)}")
        
        # 等待线程退出
        if self.push_thread and self.push_thread.is_alive():
            self.push_thread.join(timeout=10)
        if self.discovery_thread and self.discovery_thread.is_alive():
            self.discovery_thread.join(timeout=10)
        
        logger.info("=== 网关已优雅退出 ===")
        sys.exit(0)

# 入口函数
if __name__ == "__main__":
    # 创建网关实例
    gateway = GatewayManager()
    
    # 初始化并启动
    if gateway.initialize():
        gateway.start()
    else:
        logger.critical("网关初始化失败，程序退出")
        sys.exit(1)
