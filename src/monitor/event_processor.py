tong"""
事件处理器模块
"""

import logging
import time
from typing import Dict, Any, Callable, Optional
from datetime import datetime
from threading import Timer

from .models import JournalEntry
from src.notifier.unified_notifier import UnifiedNotifier

class EventProcessor:
    """事件处理器"""
    
    def __init__(self, notifier: UnifiedNotifier, config):
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
            'APP_CRASH': self._handle_app_crash,
            'APP_UPDATE_FAILED': self._handle_app_update_failed,
            'UPS_ONBATT': self._handle_ups_onbatt,
            'UPS_ONBATT_LOWBATT': self._handle_ups_onbatt_lowbatt,
            'UPS_ONLINE': self._handle_ups_online,
            'DiskWakeup': self._handle_disk_wakeup,
            'DiskSpindown': self._handle_disk_spindown
        }
        
        # 磁盘事件合并缓存
        self.disk_wakeup_cache = []
        self.disk_spindown_cache = []
        self.merge_window = 30  # 30秒合并窗口
        self.wakeup_timer = None
        self.spindown_timer = None
        
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
    
    def _handle_app_update_failed(self, event_data: Dict[str, Any], entry: JournalEntry):
        """处理应用更新失败事件"""
        data = event_data.get('data', {})
        display_name = data.get('DISPLAY_NAME', data.get('APP_NAME', '未知应用'))
        timestamp = getattr(entry, 'timestamp', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        
        # 输出标准格式日志
        print(f"[错误] 应用: {display_name}, 更新失败, 时间: {timestamp}")
        
        self.logger.warning(f"应用更新失败: {display_name}")
        
        # 如果entry为None，使用默认值
        raw_log = getattr(entry, 'raw_data', '{}')
        
        self.notifier.send_notification(
            event_type='APP_UPDATE_FAILED',
            event_data=event_data,
            raw_log=raw_log,
            timestamp=timestamp
        )
    
    def _handle_ups_onbatt(self, event_data: Dict[str, Any], entry: JournalEntry):
        """处理UPS切换到电池供电事件"""
        timestamp = getattr(entry, 'timestamp', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        
        # 输出标准格式日志
        print(f"[警告] UPS启动，切换到电池供电, 时间: {timestamp}")
        
        self.logger.warning("UPS启动，切换到电池供电")
        
        # 如果entry为None，使用默认值
        raw_log = getattr(entry, 'raw_data', '{}')
        
        self.notifier.send_notification(
            event_type='UPS_ONBATT',
            event_data=event_data,
            raw_log=raw_log,
            timestamp=timestamp
        )
    
    def _handle_ups_onbatt_lowbatt(self, event_data: Dict[str, Any], entry: JournalEntry):
        """处理UPS切换到电池供电且电池电量低事件"""
        timestamp = getattr(entry, 'timestamp', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        
        # 输出标准格式日志
        print(f"[严重警告] UPS启动，切换到电池供电，电池电量低警告, 时间: {timestamp}")
        
        self.logger.warning("UPS启动，切换到电池供电，电池电量低警告")
        
        # 如果entry为None，使用默认值
        raw_log = getattr(entry, 'raw_data', '{}')
        
        self.notifier.send_notification(
            event_type='UPS_ONBATT_LOWBATT',
            event_data=event_data,
            raw_log=raw_log,
            timestamp=timestamp
        )
    
    def _handle_ups_online(self, event_data: Dict[str, Any], entry: JournalEntry):
        """处理UPS切换到市电供电事件"""
        timestamp = getattr(entry, 'timestamp', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        
        # 输出标准格式日志
        print(f"[通知] UPS启动，切换到市电供电模式, 时间: {timestamp}")
        
        self.logger.info("UPS启动，切换到市电供电模式")
        
        # 如果entry为None，使用默认值
        raw_log = getattr(entry, 'raw_data', '{}')
        
        self.notifier.send_notification(
            event_type='UPS_ONLINE',
            event_data=event_data,
            raw_log=raw_log,
            timestamp=timestamp
        )
    
    def _add_to_cache_and_schedule_send(self, cache_list, timer_attr, event_data, event_type, entry):
        """将事件添加到缓存并安排发送"""
        # 添加事件到缓存
        timestamp = getattr(entry, 'timestamp', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        event_entry = {
            'disk': event_data.get('disk', ''),
            'model': event_data.get('model', ''),
            'serial': event_data.get('serial', ''),
            'timestamp': timestamp,
            'raw_log': getattr(entry, 'raw_data', '{}'),
            'full_event_data': event_data
        }
        
        cache_list.append(event_entry)
        
        # 输出标准格式日志
        event_desc = "磁盘唤醒" if event_type == 'DiskWakeup' else "磁盘休眠"
        print(f"[{event_desc}] 磁盘: {event_entry['disk']}, 型号: {event_entry['model']}, 序列号: {event_entry['serial']}, 时间: {timestamp}")
        
        # 取消之前的定时器
        old_timer = getattr(self, timer_attr, None)
        if old_timer and old_timer.is_alive():
            old_timer.cancel()
        
        # 设置新的定时器，延迟发送合并事件
        new_timer = Timer(self.merge_window, lambda: self._send_merged_events(cache_list, event_type))
        new_timer.start()
        setattr(self, timer_attr, new_timer)
    
    def _handle_disk_wakeup(self, event_data: Dict[str, Any], entry: JournalEntry):
        """处理磁盘唤醒事件"""
        disk = event_data.get('disk', '')
        model = event_data.get('model', '')
        serial = event_data.get('serial', '')
        
        self.logger.info(f"磁盘唤醒: {disk} ({model})")
        
        # 添加到缓存并安排发送
        self._add_to_cache_and_schedule_send(
            self.disk_wakeup_cache, 
            'wakeup_timer', 
            event_data, 
            'DiskWakeup', 
            entry
        )
    
    def _handle_disk_spindown(self, event_data: Dict[str, Any], entry: JournalEntry):
        """处理磁盘休眠事件"""
        disk = event_data.get('disk', '')
        model = event_data.get('model', '')
        serial = event_data.get('serial', '')
        
        self.logger.info(f"磁盘休眠: {disk} ({model})")
        
        # 添加到缓存并安排发送
        self._add_to_cache_and_schedule_send(
            self.disk_spindown_cache, 
            'spindown_timer', 
            event_data, 
            'DiskSpindown', 
            entry
        )
    
    def _send_merged_events(self, cache_list, event_type):
        """发送合并的磁盘事件"""
        if not cache_list:
            return
        
        # 创建合并的事件数据
        merged_data = {
            'merged_disks': cache_list,
            'count': len(cache_list),
            'event_type': event_type
        }
        
        # 获取最新的时间戳作为事件时间
        latest_timestamp = cache_list[-1]['timestamp']
        
        # 输出合并的日志
        event_desc = "磁盘唤醒" if event_type == 'DiskWakeup' else "磁盘休眠"
        print(f"[{event_desc}合并] 共 {len(cache_list)} 个磁盘事件:")
        for event in cache_list:
            print(f"  - 磁盘: {event['disk']}, 型号: {event['model']}, 序列号: {event['serial']}")
        
        # 发送通知
        self.notifier.send_notification(
            event_type=event_type,
            event_data=merged_data,
            raw_log=str(cache_list),
            timestamp=latest_timestamp
        )
        
        # 清空缓存
        cache_list.clear()
    
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