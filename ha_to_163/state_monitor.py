"""HA实体状态变化监听器"""
import logging
import time
import threading
import json
import requests
from typing import Dict, Set, Callable
from datetime import datetime

logger = logging.getLogger("state_monitor")

class HAStateMonitor:
    """Home Assistant实体状态变化监听器"""
    
    def __init__(self, ha_config: Dict, device_configs: list):
        self.ha_url = ha_config["ha_url"]
        self.ha_headers = ha_config["ha_headers"]
        self.device_configs = device_configs
        
        # 状态监控
        self.monitored_entities: Set[str] = set()
        self.last_states: Dict[str, any] = {}
        self.change_callbacks: list[Callable] = []
        
        # 运行状态
        self.running = False
        self.monitor_thread = None
        self.check_interval = 5  # 每5秒检查一次状态变化
        
        # 防抖机制
        self.last_push_time = 0
        self.push_cooldown = 3  # 3秒内不重复推送
        
        logger.info(f"状态监听器初始化完成，检查间隔: {self.check_interval}秒")
        
    def add_monitored_entities(self, entity_ids: Set[str]):
        """添加需要监控的实体"""
        before_count = len(self.monitored_entities)
        self.monitored_entities.update(entity_ids)
        after_count = len(self.monitored_entities)
        logger.info(f"添加监控实体: {after_count - before_count}个，总计: {after_count}个")
        
    def remove_monitored_entities(self, entity_ids: Set[str]):
        """移除监控实体"""
        self.monitored_entities.difference_update(entity_ids)
        # 清理对应的缓存状态
        for entity_id in entity_ids:
            self.last_states.pop(entity_id, None)
        logger.info(f"移除监控实体: {len(entity_ids)}个")
        
    def register_change_callback(self, callback: Callable[[str, any, any], None]):
        """注册状态变化回调函数
        
        Args:
            callback: 回调函数，参数为(entity_id, old_value, new_value)
        """
        self.change_callbacks.append(callback)
        logger.info(f"注册状态变化回调，当前回调数: {len(self.change_callbacks)}")
        
    def start(self):
        """启动状态监听"""
        if self.running:
            logger.warning("状态监听器已在运行")
            return
            
        self.running = True
        
        # 初始化当前状态
        self._initialize_states()
        
        # 启动监听线程
        self.monitor_thread = threading.Thread(
            target=self._monitor_loop,
            name="StateMonitorThread",
            daemon=True
        )
        self.monitor_thread.start()
        
        logger.info("✅ 状态监听器已启动")
        
    def stop(self):
        """停止状态监听"""
        if not self.running:
            return
            
        self.running = False
        
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=10)
            
        logger.info("❌ 状态监听器已停止")
        
    def _initialize_states(self):
        """初始化所有监控实体的当前状态"""
        if not self.monitored_entities:
            return
            
        logger.info(f"正在初始化 {len(self.monitored_entities)} 个实体的状态...")
        
        for entity_id in self.monitored_entities:
            try:
                current_state = self._get_entity_state(entity_id)
                if current_state is not None:
                    self.last_states[entity_id] = current_state
                    logger.debug(f"初始化状态: {entity_id} = {current_state}")
            except Exception as e:
                logger.error(f"初始化实体{entity_id}状态失败: {e}")
                
        logger.info(f"✅ 状态初始化完成，成功: {len(self.last_states)}个")
        
    def _monitor_loop(self):
        """状态监听主循环"""
        logger.info("状态监听主循环已启动")
        
        while self.running:
            try:
                # 检查所有监控实体的状态变化
                changes = self._check_state_changes()
                
                if changes:
                    # 防抖：避免频繁推送
                    current_time = time.time()
                    if current_time - self.last_push_time >= self.push_cooldown:
                        logger.info(f"🔔 检测到状态变化: {len(changes)}个实体")
                        
                        # 调用所有注册的回调函数
                        for entity_id, old_value, new_value in changes:
                            logger.info(f"  📝 {entity_id}: {old_value} → {new_value}")
                            
                            for callback in self.change_callbacks:
                                try:
                                    callback(entity_id, old_value, new_value)
                                except Exception as e:
                                    logger.error(f"回调函数执行失败: {e}")
                                    
                        self.last_push_time = current_time
                    else:
                        logger.debug(f"防抖跳过推送，剩余冷却时间: {self.push_cooldown - (current_time - self.last_push_time):.1f}秒")
                
                # 等待下次检查
                time.sleep(self.check_interval)
                
            except Exception as e:
                logger.error(f"状态监听循环异常: {e}")
                time.sleep(self.check_interval)
                
        logger.info("状态监听主循环已退出")
        
    def _check_state_changes(self) -> list:
        """检查状态变化
        
        Returns:
            list: 变化列表，每项为(entity_id, old_value, new_value)
        """
        changes = []
        
        for entity_id in self.monitored_entities:
            try:
                current_state = self._get_entity_state(entity_id)
                last_state = self.last_states.get(entity_id)
                
                # 检查是否有变化
                if current_state != last_state:
                    changes.append((entity_id, last_state, current_state))
                    self.last_states[entity_id] = current_state
                    
            except Exception as e:
                logger.error(f"检查实体{entity_id}状态失败: {e}")
                continue
                
        return changes
        
    def _get_entity_state(self, entity_id: str):
        """获取实体的当前状态值"""
        try:
            ha_api_url = self.ha_url if self.ha_url.endswith("/") else f"{self.ha_url}/"
            resp = requests.get(
                f"{ha_api_url}api/states/{entity_id}",
                headers=self.ha_headers,
                timeout=5,
                verify=False
            )
            
            if resp.status_code == 200:
                state_data = resp.json()
                return state_data.get("state")
            else:
                logger.warning(f"获取实体{entity_id}状态失败，状态码: {resp.status_code}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"请求实体{entity_id}状态失败: {e}")
            return None
        except Exception as e:
            logger.error(f"获取实体{entity_id}状态异常: {e}")
            return None
            
    def get_current_states(self) -> Dict[str, any]:
        """获取所有监控实体的当前状态"""
        return self.last_states.copy()
        
    def force_check_all(self) -> Dict[str, any]:
        """强制检查所有实体状态并返回最新状态"""
        latest_states = {}
        
        for entity_id in self.monitored_entities:
            try:
                current_state = self._get_entity_state(entity_id)
                if current_state is not None:
                    latest_states[entity_id] = current_state
                    self.last_states[entity_id] = current_state
            except Exception as e:
                logger.error(f"强制检查实体{entity_id}失败: {e}")
                
        logger.info(f"强制检查完成，获取到 {len(latest_states)} 个实体状态")
        return latest_states
