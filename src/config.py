"""
配置管理模块
"""

import os
import json
from typing import List, Dict, Any
from dataclasses import dataclass, field
from pathlib import Path

@dataclass
class Config:
    """应用配置"""
    
    # Webhook配置
    wechat_webhook_url: str = ""  # 企业微信Webhook URL
    dingtalk_webhook_url: str = ""  # 钉钉Webhook URL
    feishu_webhook_url: str = ""   # 飞书Webhook URL
    bark_url: str = ""  # Bark推送URL
    
    # 监控配置
    monitor_events: List[str] = field(default_factory=lambda: [
        "LoginSucc", "LoginSucc2FA1", "LoginFail", "Logout", "FoundDisk", "APP_CRASH",
        "APP_UPDATE_FAILED", "APP_START_FAILED_LOCAL_APP_RUN_EXCEPTION",
        "APP_AUTO_START_FAILED_DOCKER_NOT_AVAILABLE", "CPU_USAGE_ALARM",
        "CPU_TEMPERATURE_ALARM", "UPS_ONBATT", "UPS_ONBATT_LOWBATT", "UPS_ONLINE",
        "DiskWakeup", "DiskSpindown",
        "SSH_SERVICE_STARTED", "SSH_SERVICE_STOPPED", "SSH_LISTEN", "SSH_INVALID_USER", "SSH_AUTH_FAILED",
        "SSH_LOGIN_SUCCESS", "SSH_SESSION_OPENED", "SSH_DISCONNECTED", "SSH_SESSION_CLOSED"
    ])
    
    # 日志配置
    log_level: str = "INFO"
    log_dir: str = "./data/logs"
    log_retention_days: int = 30  # 原始推送日志保留天数
    
    # 连接池配置
    http_pool_size: int = 10
    http_retry_count: int = 3
    http_timeout: int = 10
    dedup_window: int = 300
    
    # 系统路径配置
    journal_paths: List[str] = field(default_factory=lambda: [
        "./test_logs/journal",  # 用于测试
        "/var/log/journal",
        "/run/log/journal"
    ])
    cursor_dir: str = "./data/cursor"  # 统一使用data目录下的cursor
    eventlogger_log_path: str = "/usr/trim/logs/eventlogger_service.log"
    
    # 高级配置
    heartbeat_interval: int = 180  #3分钟
    file_check_interval: int = 240 #4分钟
    max_log_age: int = 7
    notification_restart_enabled: bool = True
    notification_restart_consecutive_failures: int = 10
    notification_restart_window: int = 1800  # 30分钟
    notification_restart_cooldown: int = 3600  # 1小时
    

    
    def __post_init__(self):
        """初始化后处理"""
        # 记录哪些配置项是从环境变量设置的
        self._env_set_keys = set()
        # 首先从环境变量加载配置
        self._load_from_env()
        # 然后从配置文件加载，但仅当配置项未从环境变量设置时才覆盖
        self._load_from_file_skip_if_set()
        self._validate()
        self._ensure_directories()
    
    def _load_from_file_skip_if_set(self):
        """从配置文件加载（可选），但跳过已从环境变量设置的配置项"""
        config_file = Path('/app/config/config.json')
        if config_file.exists():
            try:
                with open(config_file, 'r') as f:
                    data = json.load(f)

                # 覆盖配置 - 仅当配置项未从环境变量设置时才使用配置文件的值
                for key, value in data.items():
                    if hasattr(self, key):
                        # 如果这个配置项已经从环境变量设置过，跳过
                        if key in self._env_set_keys:
                            continue

                        # 如果值是字符串且包含环境变量占位符，则进行替换
                        if isinstance(value, str) and value.startswith('${') and value.endswith('}'):
                            env_var_name = value[2:-1]  # 提取变量名
                            env_value = os.getenv(env_var_name, '')  # 获取环境变量值，不存在则为空字符串
                            setattr(self, key, env_value)
                        else:
                            setattr(self, key, value)
            except Exception as e:
                print(f"警告: 配置文件读取失败 - {e}")
    
    def _load_from_env(self):
        """从环境变量加载配置"""
        # 端口配置（保留此行以兼容旧版本，但不实际使用）
        # port = os.getenv('PORT')  # 未使用，保留会造成误导

        # Webhook URLs
        if wechat_webhook := os.getenv('WECHAT_WEBHOOK_URL'):
            self.wechat_webhook_url = wechat_webhook
            self._env_set_keys.add('wechat_webhook_url')
        elif webhook := os.getenv('WEBHOOK_URL'):  # 兼容旧的环境变量名
            self.wechat_webhook_url = webhook
            self._env_set_keys.add('wechat_webhook_url')

        if dingtalk_webhook := os.getenv('DINGTALK_WEBHOOK_URL'):
            self.dingtalk_webhook_url = dingtalk_webhook
            self._env_set_keys.add('dingtalk_webhook_url')

        if feishu_webhook := os.getenv('FEISHU_WEBHOOK_URL'):
            self.feishu_webhook_url = feishu_webhook
            self._env_set_keys.add('feishu_webhook_url')

        if bark_url := os.getenv('BARK_URL'):
            self.bark_url = bark_url
            self._env_set_keys.add('bark_url')

        # 监控事件
        if events := os.getenv('MONITOR_EVENTS'):
            self.monitor_events = [e.strip() for e in events.split(',')]
            self._env_set_keys.add('monitor_events')

        # 日志级别
        if log_level := os.getenv('LOG_LEVEL'):
            self.log_level = log_level.upper()
            self._env_set_keys.add('log_level')


        # HTTP配置
        if pool_size := os.getenv('HTTP_POOL_SIZE'):
            self.http_pool_size = int(pool_size)
            self._env_set_keys.add('http_pool_size')

        if retry_count := os.getenv('HTTP_RETRY_COUNT'):
            self.http_retry_count = int(retry_count)
            self._env_set_keys.add('http_retry_count')

        if timeout := os.getenv('HTTP_TIMEOUT'):
            self.http_timeout = int(timeout)
            self._env_set_keys.add('http_timeout')

        if dedup_window := os.getenv('DEDUP_WINDOW'):
            self.dedup_window = int(dedup_window)
            self._env_set_keys.add('dedup_window')

        # 高级配置
        if heartbeat := os.getenv('HEARTBEAT_INTERVAL'):
            self.heartbeat_interval = int(heartbeat)
            self._env_set_keys.add('heartbeat_interval')

        if file_check := os.getenv('FILE_CHECK_INTERVAL'):
            self.file_check_interval = int(file_check)
            self._env_set_keys.add('file_check_interval')

        if max_age := os.getenv('MAX_LOG_AGE'):
            self.max_log_age = int(max_age)
            self._env_set_keys.add('max_log_age')

        if log_retention := os.getenv('LOG_RETENTION_DAYS'):
            self.log_retention_days = int(log_retention)
            self._env_set_keys.add('log_retention_days')

        if notify_restart_enabled := os.getenv('NOTIFY_RESTART_ENABLED'):
            self.notification_restart_enabled = notify_restart_enabled.lower() in ['1', 'true', 'yes', 'on']
            self._env_set_keys.add('notification_restart_enabled')

        if notify_restart_failures := os.getenv('NOTIFY_RESTART_CONSECUTIVE'):
            self.notification_restart_consecutive_failures = int(notify_restart_failures)
            self._env_set_keys.add('notification_restart_consecutive_failures')

        if notify_restart_window := os.getenv('NOTIFY_RESTART_WINDOW'):
            self.notification_restart_window = int(notify_restart_window)
            self._env_set_keys.add('notification_restart_window')

        if notify_restart_cooldown := os.getenv('NOTIFY_RESTART_COOLDOWN'):
            self.notification_restart_cooldown = int(notify_restart_cooldown)
            self._env_set_keys.add('notification_restart_cooldown')

    
    def _validate(self):
        """验证配置"""
        # 至少需要配置一个Webhook URL
        if not self.wechat_webhook_url and not self.dingtalk_webhook_url and not self.feishu_webhook_url and not self.bark_url:
            raise ValueError("必须配置至少一个WebHook URL (WECHAT_WEBHOOK_URL, DINGTALK_WEBHOOK_URL, FEISHU_WEBHOOK_URL 或 BARK_URL)")
        
        if self.wechat_webhook_url and not self.wechat_webhook_url.startswith('http'):
            raise ValueError("WECHAT_WEBHOOK_URL 必须是有效的URL")
        
        if self.dingtalk_webhook_url and not self.dingtalk_webhook_url.startswith('http'):
            raise ValueError("DINGTALK_WEBHOOK_URL 必须是有效的URL")
        
        if self.feishu_webhook_url and not self.feishu_webhook_url.startswith('http'):
            raise ValueError("FEISHU_WEBHOOK_URL 必须是有效的URL")
        
        if self.bark_url and not self.bark_url.startswith('http'):
            raise ValueError("BARK_URL 必须是有效的URL")
        
        if not self.monitor_events:
            raise ValueError("必须配置至少一个监控事件")
        
        # 验证事件类型
        valid_events = {"LoginSucc", "LoginSucc2FA1", "LoginFail", "Logout", "FoundDisk", "APP_CRASH",
                        "APP_UPDATE_FAILED", "APP_START_FAILED_LOCAL_APP_RUN_EXCEPTION",
                        "APP_AUTO_START_FAILED_DOCKER_NOT_AVAILABLE", "CPU_USAGE_ALARM",
                        "CPU_TEMPERATURE_ALARM", "UPS_ONBATT", "UPS_ONBATT_LOWBATT", "UPS_ONLINE",
                        "DiskWakeup", "DiskSpindown",
                        "SSH_SERVICE_STARTED", "SSH_SERVICE_STOPPED", "SSH_LISTEN", "SSH_INVALID_USER", "SSH_AUTH_FAILED",
                        "SSH_LOGIN_SUCCESS", "SSH_SESSION_OPENED", "SSH_DISCONNECTED", "SSH_SESSION_CLOSED"}
        for event in self.monitor_events:
            if event not in valid_events:
                raise ValueError(f"未知事件类型: {event}")
        

    
    def _ensure_directories(self):
        """确保目录存在"""
        Path(self.log_dir).mkdir(parents=True, exist_ok=True)
        Path(self.cursor_dir).mkdir(parents=True, exist_ok=True)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'monitor_events': self.monitor_events,
            'log_level': self.log_level,
            'http_pool_size': self.http_pool_size,
            'dedup_window': self.dedup_window,
            'wechat_webhook_url': self.wechat_webhook_url[:50] + '...' 
                if len(self.wechat_webhook_url) > 50 else self.wechat_webhook_url
        }
