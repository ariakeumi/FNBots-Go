"""
企业微信通知器
"""

import time
import logging
import hashlib
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime

from .connection_pool import ConnectionPool

@dataclass
class WechatMessage:
    """企业微信消息"""
    
    msgtype: str = "text"
    title: str = ""
    content: str = ""
    mentioned_list: List[str] = None
    mentioned_mobile_list: List[str] = None
    
    def __post_init__(self):
        if self.mentioned_list is None:
            self.mentioned_list = []
        if self.mentioned_mobile_list is None:
            self.mentioned_mobile_list = []
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为API请求格式"""
        # 使用文本格式发送消息
        message = {
            "msgtype": "text",
            "text": {
                "content": f"{self.title}\n\n{self.content}"
            }
        }
        
        # 添加@功能
        if self.mentioned_list:
            message["mentioned_list"] = self.mentioned_list
        if self.mentioned_mobile_list:
            message["mentioned_mobile_list"] = self.mentioned_mobile_list
        
        return message

class WeChatNotifier:
    """企业微信通知器"""
    
    # 事件标题映射
    EVENT_TITLES = {
        'LoginSucc': '🔐 登录成功通知',
        'LoginSucc2FA1': '🔐 二次验证登录',
        'Logout': '👋 退出登录通知',
        'FoundDisk': '💾 发现新硬盘',
        'APP_CRASH': '💥 应用崩溃告警',
        'APP_START': '🔔 监控启动通知',
        'APP_STOP': '🔕 监控关闭通知'
    }
    
    # 事件备注
    EVENT_NOTES = {
        'LoginSucc': '💡 系统检测到用户登录成功，请确认是否为本人操作。',
        'LoginSucc2FA1': '⚠️ 用户已完成两步验证的第一步，等待二次验证。',
        'Logout': '📝 用户已安全退出系统。',
        'FoundDisk': '💾 检测到新存储设备接入系统。',
        'APP_CRASH': '❗ 应用程序异常退出，建议检查应用状态和日志。',
        'APP_START': '🚀 飞牛NAS日志监控服务已启动，开始监控系统事件。',
        'APP_STOP': '🛑 飞牛NAS日志监控服务已停止，暂停监控系统事件。'
    }
    
    def __init__(self, 
                 webhook_url: str,
                 dedup_window: int = 300,
                 pool_size: int = 10,
                 retries: int = 3,
                 timeout: int = 10):
        """
        初始化通知器
        
        Args:
            webhook_url: Webhook URL
            dedup_window: 去重时间窗口（秒）
            pool_size: 连接池大小
            retries: 重试次数
            timeout: 超时时间
        """
        self.webhook_url = webhook_url
        self.dedup_window = dedup_window
        
        # 连接池
        self.connection_pool = ConnectionPool(
            pool_size=pool_size,
            max_retries=retries,
            timeout=timeout
        )
        
        # 事件去重缓存
        self.sent_events = {}
        
        # 日志
        self.logger = logging.getLogger(__name__)
        
        self.logger.info(f"企业微信通知器初始化完成，去重窗口: {dedup_window}秒")
    
    def send_notification(self, 
                         event_type: str,
                         event_data: Dict[str, Any],
                         raw_log: str,
                         timestamp: str) -> bool:
        """
        发送通知
        
        Args:
            event_type: 事件类型
            event_data: 事件数据
            raw_log: 原始日志
            timestamp: 时间戳
            
        Returns:
            是否发送成功
        """
        # 生成事件指纹（用于去重）
        event_fingerprint = self._generate_fingerprint(event_type, event_data)
        
        # 检查去重
        if self._is_duplicate(event_fingerprint):
            self.logger.debug(f"跳过重复事件: {event_type}")
            return False
        
        # 构建消息
        message = self._build_message(event_type, event_data, timestamp, raw_log)
        
        # 发送消息
        result = self.connection_pool.post(self.webhook_url, message.to_dict())
        
        # 处理结果
        if result:
            self.sent_events[event_fingerprint] = time.time()
            self.logger.info(f"通知发送成功: {event_type}")
            return True
        else:
            self.logger.warning(f"通知发送失败: {event_type}")
            return False
    
    def _generate_fingerprint(self, event_type: str, event_data: Dict[str, Any]) -> str:
        """生成事件指纹（用于去重）"""
        # 根据不同事件类型生成不同的指纹
        
        if event_type == 'FoundDisk':
            # 硬盘发现：按设备名和时间（小时）去重
            name = event_data.get('name', 'unknown')
            hour_window = int(time.time() / 3600)
            key = f"disk_{name}_{hour_window}"
        
        elif event_type == 'APP_CRASH':
            # 应用崩溃：按应用名和时间（5分钟）去重
            data = event_data.get('data', {})
            app_name = data.get('DISPLAY_NAME', data.get('APP_NAME', 'unknown'))
            minute_window = int(time.time() / 300)  # 5分钟窗口
            key = f"crash_{app_name}_{minute_window}"
        
        else:
            # 登录/退出：按用户、IP和时间（分钟）去重
            user = event_data.get('user', 'unknown')
            ip = event_data.get('IP', 'unknown')
            minute_window = int(time.time() / 60)
            key = f"{event_type}_{user}_{ip}_{minute_window}"
        
        # 使用MD5生成固定长度的指纹
        return hashlib.md5(key.encode()).hexdigest()
    
    def _is_duplicate(self, fingerprint: str) -> bool:
        """检查是否为重复事件"""
        if fingerprint in self.sent_events:
            last_time = self.sent_events[fingerprint]
            if time.time() - last_time < self.dedup_window:
                return True
            else:
                # 超过去重窗口，删除旧记录
                del self.sent_events[fingerprint]
        
        return False
    
    def _build_message(self, event_type: str, event_data: Dict[str, Any], 
                      timestamp: str, raw_log: str) -> WechatMessage:
        """构建企业微信消息"""
        
        title = self.EVENT_TITLES.get(event_type, f"📋 系统事件: {event_type}")
        content = self._build_content(event_type, event_data, timestamp, raw_log)
        
        return WechatMessage(title=title, content=content)
    
    def _build_content(self, event_type: str, event_data: Dict[str, Any], 
                      timestamp: str, raw_log: str) -> str:
        """构建消息内容"""
        content = f"🕐 {timestamp}\n"
        
        # 不显示事件类型行，适用于所有事件类型
        # if event_type != 'Logout':
        #     content += f"📝 {event_type}\n"
        
        # 根据事件类型添加特定字段
        if event_type in ['LoginSucc', 'LoginSucc2FA1', 'Logout']:
            content += self._build_login_content(event_data)
        elif event_type == 'FoundDisk':
            content += self._build_disk_content(event_data)
        elif event_type == 'APP_CRASH':
            content += self._build_app_crash_content(event_data)
        
        # 添加备注
        note = self.EVENT_NOTES.get(event_type, '')
        # 统一格式：直接显示备注内容，不加前缀符号
        content += f"{note}\n"
        
        return content
    
    def _build_login_content(self, event_data: Dict[str, Any]) -> str:
        """构建登录相关事件内容"""
        content = ""
        
        user = event_data.get('user', '')
        if user:
            content += f"👤 用户名: {user}\n"
        else:
            content += "👤 用户名: \n"
        
        ip = event_data.get('IP', '')
        if ip:
            content += f"📍 IP地址: {ip}\n"
        else:
            content += "📍 IP地址: \n"
        
        via = event_data.get('via', '')
        content += f"🔑 认证方式: {via}\n"
        
        return content
    
    def _build_disk_content(self, event_data: Dict[str, Any]) -> str:
        """构建硬盘发现事件内容"""
        content = ""
        
        if name := event_data.get('name', ''):
            content += f"📛 设备名称: {name}\n"
        
        if model := event_data.get('model', ''):
            content += f"🔧 硬盘型号: {model}\n"
        
        if serial := event_data.get('serial', ''):
            content += f"🔢 序列号: {serial}\n"
        
        return content
    
    def _build_app_crash_content(self, event_data: Dict[str, Any]) -> str:
        """构建应用崩溃事件内容"""
        content = ""
        data = event_data.get('data', {})
        
        if app_name := data.get('DISPLAY_NAME', data.get('APP_NAME', '')):
            content += f"📱 应用名称: {app_name}\n"
        
        if app_id := data.get('APP_ID', ''):
            content += f"🆔 应用ID: {app_id}\n"
        
        if from_src := event_data.get('from', ''):
            content += f"📦 来源模块: {from_src}\n"
        
        return content
    
    def _build_system_content(self, event_type: str, event_data: Dict[str, Any], message: str) -> str:
        """构建系统事件消息内容"""
        content = f"{message}\n"
        
        # 添加简化的时间信息
        content += f"\n🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        return content
    
    def send_system_notification(self, event_type: str, message: str, additional_info: Dict[str, Any] = None) -> bool:
        """
        发送系统事件通知
        
        Args:
            event_type: 事件类型 ('APP_START', 'APP_STOP', 'APP_ERROR')
            message: 详细消息
            additional_info: 额外信息字典
            
        Returns:
            是否发送成功
        """
        self.logger.info(f"准备发送系统事件通知: {event_type}")
        
        # 构建事件数据
        event_data = {
            'message': message,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'hostname': additional_info.get('hostname', '') if additional_info else '',
            'version': additional_info.get('version', '1.0') if additional_info else '1.0',
        }
        
        # 生成事件指纹
        event_fingerprint = self._generate_system_fingerprint(event_type, event_data)
        
        # 检查去重
        if self._is_duplicate(event_fingerprint):
            self.logger.debug(f"跳过重复系统事件: {event_type}")
            return False
        
        # 构建消息
        title = self.EVENT_TITLES.get(event_type, f"📋 系统事件: {event_type}")
        content = self._build_system_content(event_type, event_data, message)
        wechat_msg = WechatMessage(title=title, content=content)
        
        # 发送消息
        result = self.connection_pool.post(self.webhook_url, wechat_msg.to_dict())
        
        # 处理结果
        if result:
            self.sent_events[event_fingerprint] = time.time()
            self.logger.info(f"系统事件通知发送成功: {event_type}")
            return True
        else:
            self.logger.warning(f"系统事件通知发送失败: {event_type}")
            return False
    
    def _generate_system_fingerprint(self, event_type: str, event_data: Dict[str, Any]) -> str:
        """生成系统事件指纹（用于去重）"""
        # 根据事件类型生成不同的指纹
        if event_type == 'APP_START':
            # 启动事件：按小时去重
            hour_window = int(time.time() / 3600)
            key = f"{event_type}_{hour_window}"
        elif event_type == 'APP_STOP':
            # 停止事件：按分钟去重
            minute_window = int(time.time() / 60)
            key = f"{event_type}_{minute_window}"
        elif event_type == 'APP_ERROR':
            # 错误事件：按5分钟去重
            window = int(time.time() / 300)  # 5分钟窗口
            key = f"{event_type}_{window}"
        else:
            # 其他事件：按分钟去重
            minute_window = int(time.time() / 60)
            key = f"sys_{event_type}_{minute_window}"
        
        # 使用MD5生成固定长度的指纹
        return hashlib.md5(key.encode()).hexdigest()
    
    def cleanup_cache(self):
        """清理过期的缓存"""
        current_time = time.time()
        expired_keys = [
            key for key, ts in self.sent_events.items()
            if current_time - ts > self.dedup_window * 2
        ]
        
        for key in expired_keys:
            del self.sent_events[key]
        
        if expired_keys:
            self.logger.debug(f"清理了 {len(expired_keys)} 个过期缓存")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        pool_stats = self.connection_pool.get_stats()
        
        return {
            **pool_stats,
            'cache_size': len(self.sent_events),
            'dedup_window': self.dedup_window,
            'webhook_url': self.webhook_url[:50] + '...' 
                if len(self.webhook_url) > 50 else self.webhook_url
        }
    
    def close(self):
        """关闭通知器"""
        self.connection_pool.close()
        self.cleanup_cache()
        self.logger.info("企业微信通知器已关闭")