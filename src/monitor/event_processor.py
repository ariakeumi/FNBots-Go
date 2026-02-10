"""
事件处理器模块
"""

import logging
from typing import Dict, Any, Callable, Optional
from datetime import datetime
from threading import Timer

from .models import JournalEntry
from src.notifier.unified_notifier import UnifiedNotifier
from src.utils.log_storage import LogStorage

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

        # 初始化日志存储器
        log_retention_days = getattr(config, 'log_retention_days', 30)
        self.log_storage = LogStorage(
            storage_dir=getattr(config, 'log_dir', './data/logs'),
            days_to_keep=log_retention_days,
            enable_auto_cleanup=True
        )
        
        # 事件处理器映射
        self.handlers = {
            'LoginSucc': self._handle_login_success,
            'LoginSucc2FA1': self._handle_login_2fa,
            'LoginFail': self._handle_login_fail,
            'Logout': self._handle_logout,
            'FoundDisk': self._handle_found_disk,
            'SSH_SERVICE_STARTED': self._handle_ssh_service_started,
            'SSH_SERVICE_STOPPED': self._handle_ssh_service_stopped,
            'SSH_LISTEN': self._handle_ssh_listen,
            'SSH_INVALID_USER': self._handle_ssh_invalid_user,
            'SSH_AUTH_FAILED': self._handle_ssh_auth_failed,
            'SSH_LOGIN_SUCCESS': self._handle_ssh_login_success,
            'SSH_SESSION_OPENED': self._handle_ssh_session_opened,
            'SSH_DISCONNECTED': self._handle_ssh_disconnected,
            'SSH_SESSION_CLOSED': self._handle_ssh_session_closed,
            'APP_CRASH': self._handle_app_crash,
            'APP_UPDATE_FAILED': self._handle_app_update_failed,
            'APP_START_FAILED_LOCAL_APP_RUN_EXCEPTION': self._handle_app_start_failed_local,
            'APP_AUTO_START_FAILED_DOCKER_NOT_AVAILABLE': self._handle_app_auto_start_failed_docker,
            'CPU_USAGE_ALARM': self._handle_cpu_usage_alarm,
            'CPU_TEMPERATURE_ALARM': self._handle_cpu_temperature_alarm,
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

        # SSH认证失败去重（避免pam_unix与Failed password重复推送）
        self.ssh_auth_fail_cache = {}
        self.ssh_auth_fail_window = 5  # 秒
        self.ssh_auth_fail_cache_max = 10000
        
        # SSH事件合并（短窗口内合并相近事件）
        self.ssh_merge_window = 5  # 秒
        self.ssh_pending = {}
        
        self.logger.info("事件处理器初始化完成")

    def _send_ssh_notification(self, event_type: str, event_data: Dict[str, Any], entry: JournalEntry):
        """发送SSH相关通知并存储日志"""
        raw_log = getattr(entry, 'raw_data', '{}')
        timestamp = getattr(entry, 'timestamp', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        self.notifier.send_notification(
            event_type=event_type,
            event_data=event_data,
            raw_log=raw_log,
            timestamp=timestamp
        )
        self._store_notification_log(event_type, event_data, raw_log, entry)

    def _schedule_ssh_event(self, key: str, event_type: str, event_data: Dict[str, Any],
                            entry: JournalEntry, log_message: str):
        """短窗口延迟发送SSH事件，等待合并"""
        existing = self.ssh_pending.pop(key, None)
        if existing:
            existing.get('timer').cancel()

        def _flush():
            pending = self.ssh_pending.pop(key, None)
            if not pending:
                return
            self.logger.info(pending['log_message'])
            self._send_ssh_notification(pending['event_type'], pending['event_data'], pending['entry'])

        timer = Timer(self.ssh_merge_window, _flush)
        timer.daemon = True
        self.ssh_pending[key] = {
            'event_type': event_type,
            'event_data': event_data,
            'entry': entry,
            'log_message': log_message,
            'timer': timer
        }
        timer.start()
    
    def _store_notification_log(self, event_type: str, event_data: Dict[str, Any], 
                               raw_log: str, entry: JournalEntry, source: str = "journal"):
        """
        存储通知日志
        
        Args:
            event_type: 事件类型
            event_data: 事件数据
            raw_log: 原始日志
            entry: 日志条目对象
            source: 日志来源
        """
        try:
            # 优先使用真正的原始日志行，如果没有则使用传入的raw_log
            actual_raw_log = entry.original_line if entry.original_line else raw_log
            
            # 存储日志到数据库
            success = self.log_storage.store_log(
                event_type=event_type,
                raw_log=actual_raw_log,  # 使用真正的原始日志
                processed_data=event_data,
                source=source
            )
            
            if success:
                self.logger.debug(f"日志存储成功: {event_type}")
            else:
                self.logger.warning(f"日志存储失败: {event_type}")
                
        except Exception as e:
            self.logger.error(f"存储日志时发生错误: {e}")
    
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
        
        # 存储原始日志
        self._store_notification_log(
            event_type='LoginSucc',
            event_data=event_data,
            raw_log=raw_log,
            entry=entry,
            source='journal'
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

    def _handle_login_fail(self, event_data: Dict[str, Any], entry: JournalEntry):
        """处理登录失败事件"""
        user = event_data.get('user', '')
        ip = event_data.get('IP', '')
        via = event_data.get('via', '')
        
        self.logger.warning(f"登录失败: {user}@{ip}")
        
        raw_log = getattr(entry, 'raw_data', '{}')
        timestamp = getattr(entry, 'timestamp', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        
        self.notifier.send_notification(
            event_type='LoginFail',
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

    def _handle_ssh_service_started(self, event_data: Dict[str, Any], entry: JournalEntry):
        """处理SSH服务启动事件"""
        # 若近期有监听事件，优先合并为一条
        pending_listen = self.ssh_pending.pop('ssh_listen_group', None)
        if pending_listen:
            pending_listen['timer'].cancel()
            merged_data = dict(pending_listen['event_data'])
            merged_data['service_started'] = True
            self.logger.info("SSH服务启动(已合并监听)")
            self._send_ssh_notification('SSH_LISTEN', merged_data, pending_listen['entry'])
            return
        self._schedule_ssh_event(
            key='ssh_service_started',
            event_type='SSH_SERVICE_STARTED',
            event_data=event_data,
            entry=entry,
            log_message="SSH服务启动"
        )

    def _handle_ssh_listen(self, event_data: Dict[str, Any], entry: JournalEntry):
        """处理SSH监听端口事件"""
        pending_started = self.ssh_pending.pop('ssh_service_started', None)
        if pending_started:
            pending_started['timer'].cancel()
            # 等待合并窗口，把所有监听合成一条再发
            pending_listen = self.ssh_pending.pop('ssh_listen_group', None)
            listens = []
            if pending_listen:
                pending_listen['timer'].cancel()
                listens = list(pending_listen['event_data'].get('listens', []))
            listens.append(event_data)
            address = event_data.get('address', '')
            port = event_data.get('port', '')
            self._schedule_ssh_event(
                key='ssh_listen_group',
                event_type='SSH_LISTEN',
                event_data={'listens': listens, 'service_started': True},
                entry=entry,
                log_message=f"SSH服务启动+监听合并(聚合): {address}:{port}"
            )
            return

        # 合并多个监听事件为一条（IPv4/IPv6）
        pending_listen = self.ssh_pending.pop('ssh_listen_group', None)
        listens = []
        if pending_listen:
            pending_listen['timer'].cancel()
            listens = list(pending_listen['event_data'].get('listens', []))
        listens.append(event_data)
        # 去重并过滤空监听
        uniq_listens = []
        seen = set()
        for item in listens:
            addr = item.get('address', '')
            port = item.get('port', '')
            if not addr or not port:
                continue
            key = f"{addr}:{port}"
            if key in seen:
                continue
            seen.add(key)
            uniq_listens.append(item)
        address = event_data.get('address', '')
        port = event_data.get('port', '')
        self._schedule_ssh_event(
            key='ssh_listen_group',
            event_type='SSH_LISTEN',
            event_data={'listens': uniq_listens},
            entry=entry,
            log_message=f"SSH监听端口(合并): {address}:{port}"
        )

    def _handle_ssh_service_stopped(self, event_data: Dict[str, Any], entry: JournalEntry):
        """处理SSH服务停止事件"""
        # 短窗口合并 stop/deactivated 重复日志
        self._schedule_ssh_event(
            key='ssh_service_stopped',
            event_type='SSH_SERVICE_STOPPED',
            event_data=event_data,
            entry=entry,
            log_message="SSH服务停止"
        )

    def _handle_ssh_invalid_user(self, event_data: Dict[str, Any], entry: JournalEntry):
        """处理SSH无效用户尝试事件"""
        user = event_data.get('user', 'unknown')
        ip = event_data.get('IP', 'unknown')
        self.logger.warning(f"SSH无效用户尝试: {user}@{ip}")
        raw_log = getattr(entry, 'raw_data', '{}')
        timestamp = getattr(entry, 'timestamp', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        self.notifier.send_notification(
            event_type='SSH_INVALID_USER',
            event_data=event_data,
            raw_log=raw_log,
            timestamp=timestamp
        )
        self._store_notification_log('SSH_INVALID_USER', event_data, raw_log, entry)

    def _handle_ssh_auth_failed(self, event_data: Dict[str, Any], entry: JournalEntry):
        """处理SSH认证失败事件"""
        user = event_data.get('user', 'unknown')
        ip = event_data.get('IP', 'unknown')
        # 基于IP+user做短窗口去重，避免同一次尝试多条日志重复推送
        key = f"{ip or 'unknown'}|{user or 'unknown'}"
        now = datetime.now().timestamp()
        last_ts = self.ssh_auth_fail_cache.get(key)
        if last_ts and (now - last_ts) < self.ssh_auth_fail_window:
            self.logger.debug(f"SSH认证失败去重: {user}@{ip}")
            return
        self.ssh_auth_fail_cache[key] = now
        # 清理过期缓存，控制规模
        if len(self.ssh_auth_fail_cache) > self.ssh_auth_fail_cache_max:
            cutoff = now - (self.ssh_auth_fail_window * 2)
            self.ssh_auth_fail_cache = {
                k: ts for k, ts in self.ssh_auth_fail_cache.items()
                if ts >= cutoff
            }

        self.logger.warning(f"SSH认证失败: {user}@{ip}")
        raw_log = getattr(entry, 'raw_data', '{}')
        timestamp = getattr(entry, 'timestamp', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        self.notifier.send_notification(
            event_type='SSH_AUTH_FAILED',
            event_data=event_data,
            raw_log=raw_log,
            timestamp=timestamp
        )
        self._store_notification_log('SSH_AUTH_FAILED', event_data, raw_log, entry)

    def _handle_ssh_login_success(self, event_data: Dict[str, Any], entry: JournalEntry):
        """处理SSH登录成功事件"""
        user = event_data.get('user', 'unknown')
        ip = event_data.get('IP', 'unknown')
        key_suffix = user
        pending_open = self.ssh_pending.pop(f"ssh_session_opened:{key_suffix}", None)
        if pending_open:
            pending_open['timer'].cancel()
            merged_data = dict(event_data)
            merged_data['session_opened'] = True
            self.logger.info(f"SSH登录成功(已合并会话开启): {user}@{ip}")
            self._send_ssh_notification('SSH_LOGIN_SUCCESS', merged_data, entry)
            return
        self._schedule_ssh_event(
            key=f"ssh_login_success:{key_suffix}",
            event_type='SSH_LOGIN_SUCCESS',
            event_data=event_data,
            entry=entry,
            log_message=f"SSH登录成功: {user}@{ip}"
        )

    def _handle_ssh_session_opened(self, event_data: Dict[str, Any], entry: JournalEntry):
        """处理SSH会话开启事件"""
        user = event_data.get('user', 'unknown')
        key_suffix = user
        pending_login = self.ssh_pending.pop(f"ssh_login_success:{key_suffix}", None)
        if pending_login:
            pending_login['timer'].cancel()
            merged_data = dict(pending_login['event_data'])
            merged_data['session_opened'] = True
            login_user = merged_data.get('user', 'unknown')
            login_ip = merged_data.get('IP', 'unknown')
            self.logger.info(f"SSH登录成功(已合并会话开启): {login_user}@{login_ip}")
            self._send_ssh_notification('SSH_LOGIN_SUCCESS', merged_data, pending_login['entry'])
            return
        self._schedule_ssh_event(
            key=f"ssh_session_opened:{key_suffix}",
            event_type='SSH_SESSION_OPENED',
            event_data=event_data,
            entry=entry,
            log_message=f"SSH会话开启: {user}"
        )

    def _handle_ssh_disconnected(self, event_data: Dict[str, Any], entry: JournalEntry):
        """处理SSH断开连接事件"""
        user = event_data.get('user', 'unknown')
        ip = event_data.get('IP', 'unknown')
        key_suffix = user
        pending_closed = self.ssh_pending.pop(f"ssh_session_closed:{key_suffix}", None)
        if pending_closed:
            pending_closed['timer'].cancel()
            merged_data = dict(event_data)
            merged_data['session_closed'] = True
            self.logger.info(f"SSH断开连接(已合并会话关闭): {user}@{ip}")
            self._send_ssh_notification('SSH_DISCONNECTED', merged_data, entry)
            return
        self._schedule_ssh_event(
            key=f"ssh_disconnected:{key_suffix}",
            event_type='SSH_DISCONNECTED',
            event_data=event_data,
            entry=entry,
            log_message=f"SSH断开连接: {user}@{ip}"
        )

    def _handle_ssh_session_closed(self, event_data: Dict[str, Any], entry: JournalEntry):
        """处理SSH会话关闭事件"""
        user = event_data.get('user', 'unknown')
        key_suffix = user
        pending_disconnected = self.ssh_pending.pop(f"ssh_disconnected:{key_suffix}", None)
        if pending_disconnected:
            pending_disconnected['timer'].cancel()
            merged_data = dict(pending_disconnected['event_data'])
            merged_data['session_closed'] = True
            disc_user = merged_data.get('user', 'unknown')
            disc_ip = merged_data.get('IP', 'unknown')
            self.logger.info(f"SSH断开连接(已合并会话关闭): {disc_user}@{disc_ip}")
            self._send_ssh_notification('SSH_DISCONNECTED', merged_data, pending_disconnected['entry'])
            return
        self._schedule_ssh_event(
            key=f"ssh_session_closed:{key_suffix}",
            event_type='SSH_SESSION_CLOSED',
            event_data=event_data,
            entry=entry,
            log_message=f"SSH会话关闭: {user}"
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

    def _handle_app_start_failed_local(self, event_data: Dict[str, Any], entry: JournalEntry):
        """处理应用启动失败事件（本地运行异常）"""
        data = event_data.get('data', {})
        display_name = data.get('DISPLAY_NAME', data.get('APP_NAME', '未知应用'))
        timestamp = getattr(entry, 'timestamp', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        self.logger.warning(f"应用启动失败: {display_name}")
        raw_log = getattr(entry, 'raw_data', '{}')
        self.notifier.send_notification(
            event_type='APP_START_FAILED_LOCAL_APP_RUN_EXCEPTION',
            event_data=event_data,
            raw_log=raw_log,
            timestamp=timestamp
        )

    def _handle_app_auto_start_failed_docker(self, event_data: Dict[str, Any], entry: JournalEntry):
        """处理应用自启动失败事件（Docker 不可用）"""
        data = event_data.get('data', {})
        display_name = data.get('DISPLAY_NAME', data.get('APP_NAME', '未知应用'))
        timestamp = getattr(entry, 'timestamp', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        self.logger.warning(f"应用自启动失败(Docker不可用): {display_name}")
        raw_log = getattr(entry, 'raw_data', '{}')
        self.notifier.send_notification(
            event_type='APP_AUTO_START_FAILED_DOCKER_NOT_AVAILABLE',
            event_data=event_data,
            raw_log=raw_log,
            timestamp=timestamp
        )

    def _handle_cpu_usage_alarm(self, event_data: Dict[str, Any], entry: JournalEntry):
        """处理 CPU 使用率告警"""
        data = event_data.get('data', {})
        threshold = data.get('THRESHOLD', 0)
        timestamp = getattr(entry, 'timestamp', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        self.logger.warning(f"CPU使用率告警: 超过 {threshold}%")
        raw_log = getattr(entry, 'raw_data', '{}')
        self.notifier.send_notification(
            event_type='CPU_USAGE_ALARM',
            event_data=event_data,
            raw_log=raw_log,
            timestamp=timestamp
        )

    def _handle_cpu_temperature_alarm(self, event_data: Dict[str, Any], entry: JournalEntry):
        """处理 CPU 温度告警"""
        data = event_data.get('data', {})
        threshold = data.get('THRESHOLD', 0)
        timestamp = getattr(entry, 'timestamp', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        self.logger.warning(f"CPU温度告警: 超过 {threshold}°C")
        raw_log = getattr(entry, 'raw_data', '{}')
        self.notifier.send_notification(
            event_type='CPU_TEMPERATURE_ALARM',
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
        self._add_to_cache_and_schedule_send(
            self.disk_wakeup_cache, 
            'wakeup_timer', 
            event_data, 
            'DiskWakeup', 
            entry
        )
        
        # 存储原始日志用于后续分析
        raw_log = getattr(entry, 'raw_data', '{}')
        self._store_notification_log('DiskWakeup', event_data, raw_log, entry)

    def _handle_disk_spindown(self, event_data: Dict[str, Any], entry: JournalEntry):
        """处理磁盘休眠事件"""
        self._add_to_cache_and_schedule_send(
            self.disk_spindown_cache, 
            'spindown_timer', 
            event_data, 
            'DiskSpindown', 
            entry
        )
        
        # 存储原始日志用于后续分析
        raw_log = getattr(entry, 'raw_data', '{}')
        self._store_notification_log('DiskSpindown', event_data, raw_log, entry)

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
