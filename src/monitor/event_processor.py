"""
事件处理器模块
"""

import logging
import time
from typing import Dict, Any, Callable, Optional
from datetime import datetime

from .models import JournalEntry
from src.notifier.wechat_notifier import WeChatNotifier

class EventProcessor:
    """事件处理器"""
    
    def __init__(self, notifier: WeChatNotifier, config):
        """
        初始化事件处理器
        
        Args:
            notifier: 通知器实例
            config: 配置对象
        """
        self.notifier = notifier
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # 事件处理器映射
        self.handlers = {
            'LoginSucc': self._handle_login_success,
            'LoginSucc2FA1': self._handle_login_2fa,
            'Logout': self._handle_logout,
            'FoundDisk': self._handle_found_disk,
            'APP_CRASH': self._handle_app_crash
        }
        
        self.logger.info("事件处理器初始化完成")
    
    def get_handler(self, event_type: str) -> Optional[Callable]:
        """
        获取事件处理器
        
        Args:
            event_type: 事件类型
            
        Returns:
            处理函数或None
        """
        return self.handlers.get(event_type)
    
    def _handle_login_success(self, event_data: Dict[str, Any], entry: JournalEntry):
        """处理登录成功事件"""
        user = event_data.get('user', '')
        ip = event_data.get('IP', '')
        via = event_data.get('via', '')
        
        self.logger.info(f"登录成功: {user}@{ip}")
        
        # 如果entry为None，使用默认值
        raw_log = getattr(entry, 'raw_data', '{}')
        timestamp = getattr(entry, 'timestamp', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        
        self.notifier.send_notification(
            event_type='LoginSucc',
            event_data=event_data,
            raw_log=raw_log,
            timestamp=timestamp
        )
    
    def _handle_login_2fa(self, event_data: Dict[str, Any], entry: JournalEntry):
        """处理二次验证登录事件"""
        user = event_data.get('user', '')
        ip = event_data.get('IP', '')
        via = event_data.get('via', '')
        
        self.logger.info(f"二次验证登录: {user}@{ip}")
        
        # 如果entry为None，使用默认值
        raw_log = getattr(entry, 'raw_data', '{}')
        timestamp = getattr(entry, 'timestamp', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        
        self.notifier.send_notification(
            event_type='LoginSucc2FA1',
            event_data=event_data,
            raw_log=raw_log,
            timestamp=timestamp
        )
    
    def _handle_logout(self, event_data: Dict[str, Any], entry: JournalEntry):
        """处理退出登录事件"""
        user = event_data.get('user', '')
        ip = event_data.get('IP', '')
        via = event_data.get('via', '')
        
        self.logger.info(f"退出登录: {user}@{ip}")
        
        # 如果entry为None，使用默认值
        raw_log = getattr(entry, 'raw_data', '{}')
        timestamp = getattr(entry, 'timestamp', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        
        self.notifier.send_notification(
            event_type='Logout',
            event_data=event_data,
            raw_log=raw_log,
            timestamp=timestamp
        )
    
    def _handle_found_disk(self, event_data: Dict[str, Any], entry: JournalEntry):
        """处理发现硬盘事件"""
        name = event_data.get('name', '')
        model = event_data.get('model', '')
        serial = event_data.get('serial', '')
        
        self.logger.info(f"发现硬盘: {name} ({model})")
        
        # 如果entry为None，使用默认值
        raw_log = getattr(entry, 'raw_data', '{}')
        timestamp = getattr(entry, 'timestamp', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        
        self.notifier.send_notification(
            event_type='FoundDisk',
            event_data=event_data,
            raw_log=raw_log,
            timestamp=timestamp
        )
    
    def _handle_app_crash(self, event_data: Dict[str, Any], entry: JournalEntry):
        """处理应用崩溃事件"""
        data = event_data.get('data', {})
        display_name = data.get('DISPLAY_NAME', data.get('APP_NAME', '未知应用'))
        timestamp = getattr(entry, 'timestamp', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        
        # 输出标准格式日志
        print(f"[错误] 应用: {display_name}, 崩溃异常退出, 时间: {timestamp}")
        
        self.logger.warning(f"应用崩溃: {display_name}")
        
        # 如果entry为None，使用默认值
        raw_log = getattr(entry, 'raw_data', '{}')
        
        self.notifier.send_notification(
            event_type='APP_CRASH',
            event_data=event_data,
            raw_log=raw_log,
            timestamp=timestamp
        )
    
    def _handle_generic_login(self, event_data: Dict[str, Any], entry: JournalEntry):
        """处理通用登录事件"""
        user = event_data.get('user', '')
        ip = event_data.get('IP', '')
        via = event_data.get('via', '')
        
        self.logger.info(f"通用登录成功: {user}@{ip}")
        
        # 如果entry为None，使用默认值
        raw_log = getattr(entry, 'raw_data', '{}')
        timestamp = getattr(entry, 'timestamp', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        
        self.notifier.send_notification(
            event_type='LoginSucc',
            event_data=event_data,
            raw_log=raw_log,
            timestamp=timestamp
        )
    
    def _handle_generic_logout(self, event_data: Dict[str, Any], entry: JournalEntry):
        """处理通用登出事件"""
        user = event_data.get('user', '')
        ip = event_data.get('IP', '')
        via = event_data.get('via', '')
        
        self.logger.info(f"通用登出: {user}@{ip}")
        
        # 如果entry为None，使用默认值
        raw_log = getattr(entry, 'raw_data', '{}')
        timestamp = getattr(entry, 'timestamp', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        
        self.notifier.send_notification(
            event_type='Logout',
            event_data=event_data,
            raw_log=raw_log,
            timestamp=timestamp
        )
    
    def process_event(self, event_type: str, event_data: Dict[str, Any], entry: JournalEntry):
        """
        处理事件（通用接口）
        
        Args:
            event_type: 事件类型
            event_data: 事件数据
            entry: 日志条目
        """
        handler = self.get_handler(event_type)
        if handler:
            try:
                handler(event_data, entry)
                return True
            except Exception as e:
                self.logger.error(f"处理事件失败: {e}")
                return False
        else:
            self.logger.warning(f"未知事件类型: {event_type}")
            return False