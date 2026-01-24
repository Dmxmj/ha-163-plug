# HA-163-Plug：网易IoT米家插座网关集成

[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2023.1+-%23049cdb.svg)](https://www.home-assistant.io/)

Home Assistant 集成插件，用于对接网易IoT平台，实现米家智能插座的远程控制、数据采集与推送，支持多设备管理、自动故障恢复、NTP校时等核心功能。

## 🌟 核心功能
- ✅ 网易NTP强制校时（满足IoT平台时间同步要求）
- ✅ 多设备三元组（ProductKey/DeviceName/DeviceSecret）可视化配置
- ✅ MQTT长连接保持，断开自动重连
- ✅ 容错性实体发现（单个设备离线不影响其他设备）
- ✅ 自动重试发现离线设备，恢复后自动加入推送
- ✅ 60秒固定频次数据推送，300秒重试发现间隔
- ✅ 优雅退出机制，保障连接安全关闭
- ✅ 日志持久化，便于问题排查

## 📋 前置要求
1. Home Assistant 版本 ≥ 2023.1
2. 网易IoT平台账号及设备三元组信息
3. 米家智能插座已接入Home Assistant
4. 网络可访问 `ntp.n.netease.com` 和网易IoT MQTT服务器

## 🚀 安装方法
### 方法1：手动安装（推荐）
1. 下载本仓库代码，解压后将 `163-gateway` 目录复制到HA的 `/config/addons` 目录
2. 重启Home Assistant
3. 在HA界面进入「设置」→「加载项」→「添加加载项仓库」，添加本仓库地址
4. 找到「163 Gateway」加载项，点击「安装」

### 方法2：HACS安装（待适配）
1. 确保已安装HACS
2. 添加自定义仓库：`https://github.com/Dmxmj/ha-163-plug`
3. 在HACS中搜索「163 Gateway」并安装
4. 重启Home Assistant

## ⚙️ 配置说明
### 基础配置（UI界面）
安装完成后，进入加载项配置页面，修改以下核心参数：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `ha_url` | Home Assistant API地址 | `http://supervisor/core/api` |
| `ha_token` | HA长期访问令牌（设置→个人资料→长期令牌） | 空 |
| `gateway_triple` | 网关三元组 | `{"product_key": "", "device_name": "", "device_secret": ""}` |
| `devices_triple` | 设备三元组列表 | 示例配置见下文 |
| `mqtt_host` | 网易IoT MQTT服务器地址 | `device.iot.163.com` |
| `mqtt_port` | MQTT端口 | `1883` |
| `report_interval` | 数据推送间隔（秒） | `60`（固定，修改无效） |
| `discovery_retry_interval` | 设备发现重试间隔（秒） | `300` |
| `retry_attempts` | API重试次数 | `5` |
| `retry_delay` | API重试延迟（秒） | `3` |

### 设备三元组配置示例
```json
[
  {
    "device_id": "mi_socket_001",
    "product_key": "your_product_key",
    "device_name": "your_device_name",
    "device_secret": "your_device_secret",
    "entity_prefix": "iot_cn_2004109533_pw6u1",
    "enabled": true
  },
  {
    "device_id": "mi_socket_002",
    "product_key": "another_product_key",
    "device_name": "another_device_name",
    "device_secret": "another_device_secret",
    "entity_prefix": "iot_cn_2004109533_pw6u2",
    "enabled": true
  }
]
