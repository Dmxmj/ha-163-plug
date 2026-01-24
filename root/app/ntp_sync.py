"""NTP校时模块（对接ntp.n.netease.com）"""
import logging
import socket
import struct
import time

# NTP服务器配置
NTP_SERVER = "ntp.n.netease.com"
NTP_PORT = 123
NTP_PACKET_FORMAT = "!12I"
NTP_DELTA = 2208988800  # 1970-01-01 00:00:00 UTC 到 1900-01-01 00:00:00 UTC 的秒数

logger = logging.getLogger("ntp_sync")

def sync_time_with_netease_ntp(timeout: int = 10) -> bool:
    """
    与网易NTP服务器校时
    :param timeout: 超时时间（秒）
    :return: 校时是否成功
    """
    try:
        # 创建UDP套接字
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        client_socket.settimeout(timeout)
        
        # 构建NTP请求包（版本4，客户端模式）
        ntp_packet = bytearray(48)
        ntp_packet[0] = 0x1B  # 00 011 011 → LI=0, VN=3, Mode=3 (客户端)
        
        # 发送请求
        logger.info(f"连接网易NTP服务器: {NTP_SERVER}:{NTP_PORT}")
        client_socket.sendto(ntp_packet, (NTP_SERVER, NTP_PORT))
        
        # 接收响应
        data, _ = client_socket.recvfrom(48)
        client_socket.close()
        
        # 解析NTP响应
        unpacked_data = struct.unpack(NTP_PACKET_FORMAT, data)
        ntp_time = unpacked_data[10] + float(unpacked_data[11]) / 2**32
        ntp_timestamp = ntp_time - NTP_DELTA  # 转换为Unix时间戳
        
        # 获取本地时间
        local_timestamp = time.time()
        time_diff = abs(ntp_timestamp - local_timestamp)
        
        logger.info(f"NTP校时完成 - 服务器时间: {time.ctime(ntp_timestamp)}, 本地时间: {time.ctime(local_timestamp)}, 差值: {time_diff:.3f}秒")
        
        # 差值超过1秒则记录警告（容器内一般不允许修改系统时间，仅校验）
        if time_diff > 1:
            logger.warning(f"本地时间与NTP服务器偏差超过1秒（{time_diff:.3f}秒），可能影响IoT连接")
        
        return True
    
    except socket.timeout:
        logger.error(f"NTP校时超时（{timeout}秒）")
        return False
    except Exception as e:
        logger.error(f"NTP校时失败: {str(e)}", exc_info=True)
        return False
