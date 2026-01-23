"""
数据模型定义
"""

import json
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Dict, Any, Optional
import re

@dataclass
class JournalEntry:
    """Journal日志条目"""
    
    cursor: str
    timestamp: str
    hostname: str
    syslog_identifier: str
    message: str
    priority: int
    pid: int
    raw_data: str
    
    @classmethod
    def from_json(cls, json_data: Dict[str, Any]) -> Optional['JournalEntry']:
        """从JSON数据创建日志条目"""
        try:
            # 解析时间戳
            ts = json_data.get('__REALTIME_TIMESTAMP')
            if ts:
                try:
                    # 尝试区分秒级时间戳和微秒级时间戳
                    ts_float = float(ts)
                    # 如果时间戳大于1e10，则认为是微秒级时间戳（2001年之后的时间会超过1e10毫秒）
                    if ts_float > 1e10:
                        # 微秒转秒
                        ts_float = ts_float / 1000000
                    dt = datetime.fromtimestamp(ts_float)
                    timestamp = dt.strftime("%Y-%m-%d %H:%M:%S")
                except (ValueError, TypeError):
                    timestamp = str(ts)
            else:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            return cls(
                cursor=json_data.get('__CURSOR', ''),
                timestamp=timestamp,
                hostname=json_data.get('_HOSTNAME', 'unknown'),
                syslog_identifier=json_data.get('SYSLOG_IDENTIFIER', 'unknown'),
                message=json_data.get('MESSAGE', ''),
                priority=int(json_data.get('PRIORITY', 6)),
                pid=int(json_data.get('_PID', 0)),
                raw_data=json.dumps(json_data, ensure_ascii=False)
            )
        except Exception as e:
            return None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)
    
    def extract_event_data(self) -> Optional[Dict[str, Any]]:
        """从消息中提取事件数据"""
        # 匹配 MAINEVENT 格式: MAINEVENT[1593]: MAINEVENT:{...}
        mainevent_match = re.search(r'MAINEVENT\[\d+\]:\s*MAINEVENT:(\{.*?\})(?=\s|$)', self.message)
        if mainevent_match:
            try:
                event_json = mainevent_match.group(1)
                event_data = json.loads(event_json)
                event_data['_event_type'] = 'MAINEVENT'
                return event_data
            except json.JSONDecodeError:
                pass
        
        # 匹配 TRIMEVENT 格式: TRIMEVENT[2543]: TRIMEVENT:{...}
        trimevent_match = re.search(r'TRIMEVENT\[\d+\]:\s*TRIMEVENT:(\{.*?\})(?=\s|$)', self.message)
        if trimevent_match:
            try:
                event_json = trimevent_match.group(1)
                event_data = json.loads(event_json)
                event_data['_event_type'] = 'TRIMEVENT'
                return event_data
            except json.JSONDecodeError:
                pass
        
        # 备用：匹配不带方括号的格式
        patterns = {
            'MAINEVENT': re.compile(r'MAINEVENT:\s*(\{.*?\})(?=\s|$)'),
            'TRIMEVENT': re.compile(r'TRIMEVENT:\s*(\{.*?\})(?=\s|$)')
        }
        
        for event_type, pattern in patterns.items():
            match = pattern.search(self.message)
            if match:
                try:
                    event_json = match.group(1)
                    event_data = json.loads(event_json)
                    event_data['_event_type'] = event_type
                    return event_data
                except json.JSONDecodeError:
                    continue
        
        # 尝试从其他格式中提取数据
        return self._extract_additional_formats()
    
    def _extract_additional_formats(self) -> Optional[Dict[str, Any]]:
        """从其他日志格式中提取数据"""
        import re
        message_lower = self.message.lower()
        
        # 尝试检测登录事件
        if any(keyword in message_lower for keyword in ['login', 'logged in', 'session opened']):
            # 尝试从消息中提取用户信息
            user_match = re.search(r'(?:user|for)\s+(\w+)', self.message, re.IGNORECASE)
            ip_match = re.search(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b', self.message)
            
            return {
                'user': user_match.group(1) if user_match else 'unknown',
                'IP': ip_match.group() if ip_match else 'unknown',
                'via': 'unknown',
                '_event_type': 'GENERIC_LOGIN'
            }
        
        # 尝试检测登出事件
        elif any(keyword in message_lower for keyword in ['logout', 'logged out', 'session closed']):
            user_match = re.search(r'(?:user|for)\s+(\w+)', self.message, re.IGNORECASE)
            ip_match = re.search(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b', self.message)
            
            return {
                'user': user_match.group(1) if user_match else 'unknown',
                'IP': ip_match.group() if ip_match else 'unknown',
                '_event_type': 'GENERIC_LOGOUT'
            }
        
        return None

@dataclass
class MonitorEvent:
    """监控事件"""
    
    event_type: str  # LoginSucc, FoundDisk, APP_CRASH等
    event_data: Dict[str, Any]
    journal_entry: JournalEntry
    timestamp: str
    
    @property
    def description(self) -> str:
        """事件描述"""
        descriptions = {
            'LoginSucc': '登录成功',
            'LoginSucc2FA1': '二次验证登录',
            'Logout': '退出登录',
            'FoundDisk': '发现新硬盘',
            'APP_CRASH': '应用崩溃'
        }
        return descriptions.get(self.event_type, self.event_type)
    
    def to_notification_data(self) -> Dict[str, Any]:
        """转换为通知数据"""
        base = {
            'event_type': self.event_type,
            'description': self.description,
            'timestamp': self.timestamp,
            'hostname': self.journal_entry.hostname
        }
        
        # 根据不同事件类型添加特定字段
        if self.event_type in ['LoginSucc', 'LoginSucc2FA1', 'Logout']:
            base.update({
                'user': self.event_data.get('user', ''),
                'ip': self.event_data.get('IP', ''),
                'via': self.event_data.get('via', ''),
                'uid': self.event_data.get('uid', '')
            })
        elif self.event_type == 'FoundDisk':
            base.update({
                'disk_name': self.event_data.get('name', ''),
                'model': self.event_data.get('model', ''),
                'serial': self.event_data.get('serial', '')
            })
        elif self.event_type == 'APP_CRASH':
            data = self.event_data.get('data', {})
            base.update({
                'app_name': data.get('DISPLAY_NAME', data.get('APP_NAME', '')),
                'app_id': data.get('APP_ID', ''),
                'from': self.event_data.get('from', '')
            })
        
        return base