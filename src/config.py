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
    wechat_webhook_url: str = ""
    
    # 监控配置
    monitor_events: List[str] = field(default_factory=lambda: [
        "LoginSucc", "LoginSucc2FA1", "Logout", "FoundDisk", "APP_CRASH"
    ])
    
    # 日志配置
    log_level: str = "INFO"
    log_dir: str = "/app/logs"
    
    # 连接池配置
    http_pool_size: int = 10
    http_retry_count: int = 3
    http_timeout: int = 10
    dedup_window: int = 300
    
    # 系统路径配置
    journal_paths: List[str] = field(default_factory=lambda: [
        "/var/log/journal",
        "/run/log/journal"
    ])
    cursor_dir: str = "/tmp/cursor"
    
    # 高级配置
    heartbeat_interval: int = 30
    file_check_interval: int = 60
    max_log_age: int = 7
    

    
    def __post_init__(self):
        """初始化后处理"""
        self._load_from_env()
        self._load_from_file()
        self._validate()
        self._ensure_directories()
    
    def _load_from_env(self):
        """从环境变量加载配置"""
        # 端口配置（保留此行以兼容旧版本，但不实际使用）
        port = os.getenv('PORT')
        
        # Webhook URL
        if webhook := os.getenv('WECHAT_WEBHOOK_URL'):
            self.wechat_webhook_url = webhook
        
        # 监控事件
        if events := os.getenv('MONITOR_EVENTS'):
            self.monitor_events = [e.strip() for e in events.split(',')]
        
        # 日志级别
        if log_level := os.getenv('LOG_LEVEL'):
            self.log_level = log_level.upper()
        
        # HTTP配置
        if pool_size := os.getenv('HTTP_POOL_SIZE'):
            self.http_pool_size = int(pool_size)
        
        if retry_count := os.getenv('HTTP_RETRY_COUNT'):
            self.http_retry_count = int(retry_count)
        
        if timeout := os.getenv('HTTP_TIMEOUT'):
            self.http_timeout = int(timeout)
        
        if dedup_window := os.getenv('DEDUP_WINDOW'):
            self.dedup_window = int(dedup_window)
        
        # 高级配置
        if heartbeat := os.getenv('HEARTBEAT_INTERVAL'):
            self.heartbeat_interval = int(heartbeat)
        
        if file_check := os.getenv('FILE_CHECK_INTERVAL'):
            self.file_check_interval = int(file_check)
        
        if max_age := os.getenv('MAX_LOG_AGE'):
            self.max_log_age = int(max_age)
    
    def _load_from_file(self):
        """从配置文件加载（可选）"""
        config_file = Path('/app/config/config.json')
        if config_file.exists():
            try:
                with open(config_file, 'r') as f:
                    data = json.load(f)
                
                # 覆盖配置
                for key, value in data.items():
                    if hasattr(self, key):
                        setattr(self, key, value)
            except Exception as e:
                print(f"警告: 配置文件读取失败 - {e}")
    
    def _validate(self):
        """验证配置"""
        if not self.wechat_webhook_url:
            raise ValueError("必须配置 WECHAT_WEBHOOK_URL")
        
        if not self.wechat_webhook_url.startswith('http'):
            raise ValueError("WECHAT_WEBHOOK_URL 必须是有效的URL")
        
        if not self.monitor_events:
            raise ValueError("必须配置至少一个监控事件")
        
        # 验证事件类型
        valid_events = {"LoginSucc", "LoginSucc2FA1", "Logout", "FoundDisk", "APP_CRASH"}
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
            'webhook_url': self.wechat_webhook_url[:50] + '...' 
                if len(self.wechat_webhook_url) > 50 else self.wechat_webhook_url
        }