"""设备发现基类"""
import logging
from typing import Dict

class BaseDiscovery:
    """设备发现基类"""
    def __init__(self, config: Dict, logger_name: str = None):
        self.config = config
        self.logger = logging.getLogger(logger_name or __name__)
        self.devices = []
