import os
import json
import signal
import time
import logging
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Callable, Optional, List, Any

from .models import JournalEntry

class JournalWatcher:
    """Journal日志监视器"""
    
    def __init__(self, journal_paths: List[str] = None, cursor_dir: str = "/tmp/cursor"):
        """
        初始化监视器
        
        Args:
            journal_paths: Journal目录路径列表
            cursor_dir: 游标文件目录
        """
        self.journal_paths = journal_paths or [
            "/var/log/journal",
            "/run/log/journal"
        ]
        self.cursor_dir = Path(cursor_dir)
        self.cursor_file = self.cursor_dir / "journal_cursor.txt"
        
        # 事件处理器
        self.event_handlers: Dict[str, Callable] = {}
        
        # 运行状态
        self.running = False
        self.process: Optional[subprocess.Popen] = None
        
        # 心跳监控
        self.heartbeat_interval = 30
        self.last_heartbeat = time.time()
        self.heartbeat_thread: Optional[threading.Thread] = None
        
        # 统计信息
        self.stats = {
            'events_processed': 0,
            'entries_read': 0,
            'errors': 0,
            'start_time': datetime.now()
        }
        
        # 设置日志
        self.logger = logging.getLogger(__name__)
        
        # 确保目录存在
        self.cursor_dir.mkdir(parents=True, exist_ok=True)
    
    def add_handler(self, event_type: str, handler: Callable):
        """
        添加事件处理器
        
        Args:
            event_type: 事件类型
            handler: 处理函数
        """
        self.event_handlers[event_type] = handler
        self.logger.info(f"注册事件处理器: {event_type}")
    
    def start(self):
        """启动日志监视"""
        if self.running:
            self.logger.warning("监视器已在运行")
            return
        
        self.running = True
        self.logger.info("启动Journal日志监视器")
        
        # 设置信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        try:
            # 启动日志监控进程（支持多种方式）
            self._start_log_process()
            
            # 启动心跳线程
            self.heartbeat_thread = threading.Thread(
                target=self._heartbeat_monitor,
                name="HeartbeatMonitor",
                daemon=True
            )
            self.heartbeat_thread.start()
            
            # 处理日志输出
            self._process_output()
            
            # 保持主线程运行
            while self.running:
                time.sleep(1)
                
        except Exception as e:
            self.logger.error(f"启动失败: {e}", exc_info=True)
            raise
        finally:
            self.stop()
    
    def _start_log_process(self):
        """启动日志进程（支持多种日志来源）"""
        # 检查系统支持的日志方式
        # 优先检查syslog方式，因为其更广泛兼容
        if self._check_syslog_available():
            self.logger.info("使用syslog方式监控日志")
            self._start_syslog_process()
        elif self._check_journalctl_available():
            self.logger.info("使用journalctl方式监控日志")
            self._start_journalctl_process()
        else:
            self.logger.warning("未找到合适的日志监控方式，启动备用进程保持运行")
            self._start_backup_process()
    
    def _check_journalctl_available(self) -> bool:
        """检查journalctl是否可用"""
        import shutil
        return shutil.which('journalctl') is not None
    
    def _check_syslog_available(self) -> bool:
        """检查syslog文件是否存在"""
        syslog_paths = ['/var/log/syslog', '/var/log/messages', '/var/log/auth.log']
        return any(os.path.exists(path) for path in syslog_paths)
    
    def _start_journalctl_process(self):
        """启动journalctl进程"""
        # 检查是否有访问日志目录的权限
        accessible_paths = []
        for path in self.journal_paths:
            try:
                if os.path.exists(path) and os.access(path, os.R_OK):
                    accessible_paths.append(path)
                    self.logger.info(f"日志路径可访问: {path}")
                else:
                    self.logger.warning(f"日志路径不可访问: {path}")
            except Exception as e:
                self.logger.warning(f"检查路径时出错 {path}: {e}")
        
        # 如果没有可访问的日志路径，使用系统默认
        if not accessible_paths:
            self.logger.warning("没有可访问的指定日志目录，使用系统默认journal")
            accessible_paths = []  # 使用系统默认路径
        
        # 读取上次游标
        cursor = self._read_cursor()
        
        # 构建命令
        cmd = self._build_journalctl_command(cursor, accessible_paths)
        
        self.logger.info(f"执行命令: {' '.join(cmd)}")
        
        try:
            # 尝试执行命令，但捕获权限错误
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True,
                preexec_fn=os.setsid  # 创建新进程组
            )
        except PermissionError:
            self.logger.error("权限不足，无法执行journalctl命令，使用备用进程维持运行")
            self._start_backup_process()
        except FileNotFoundError:
            self.logger.error("journalctl命令不存在，使用备用进程维持运行")
            self._start_backup_process()
        except Exception as e:
            self.logger.error(f"启动journalctl进程失败: {e}，使用备用进程维持运行")
            self._start_backup_process()
        
        if self.process and hasattr(self.process, 'pid'):
            self.logger.info(f"Journal进程启动，PID: {self.process.pid}")
    
    def _start_syslog_process(self):
        """启动syslog监控进程"""
        # 寻找可用的syslog文件
        syslog_paths = [
            '/var/log/syslog',      # Debian/Ubuntu 系统主要日志
            '/var/log/messages',    # RedHat/CentOS 系统主要日志
            '/var/log/auth.log',    # 认证相关日志
            '/var/log/daemon.log',  # 守护进程日志
            '/var/log/kern.log',    # 内核日志
            '/var/log/user.log',    # 用户级日志
            '/var/log/dmesg'        # 内核环形缓冲区日志
        ]
        available_paths = [path for path in syslog_paths if os.path.exists(path)]
        
        if not available_paths:
            self.logger.error("未找到可用的syslog文件，使用备用进程")
            self._start_backup_process()
            return
        
        # 使用tail -f监控最新的syslog文件
        cmd = ['tail', '-n', '0', '-f'] + available_paths
        
        self.logger.info(f"执行syslog命令: {' '.join(cmd)}")
        
        import subprocess
        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True,
                preexec_fn=os.setsid
            )
        except Exception as e:
            self.logger.error(f"启动syslog监控进程失败: {e}，使用备用进程维持运行")
            self._start_backup_process()
        
        if self.process and hasattr(self.process, 'pid'):
            self.logger.info(f"Syslog进程启动，PID: {self.process.pid}")
    
    def _start_backup_process(self):
        """启动备用进程保持运行"""
        import subprocess
        # 使用一个长时间运行的进程，但不会消耗太多CPU
        self.process = subprocess.Popen(['sleep', '86400'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.logger.info("启动备用进程保持运行")
    
    def _build_journalctl_command(self, cursor: str = None, paths: List[str] = None) -> List[str]:
        """构建journalctl命令"""
        cmd = [
            'journalctl',
            '-x',           # 显示扩展信息
            '-o', 'json',  # JSON格式输出
            '-f',          # 跟随模式（实时）
            '--no-tail',   # 不从历史开始
        ]
        
        # 添加游标
        if cursor:
            cmd.extend(['--after-cursor', cursor])
        else:
            # 如果没有游标，从当前时间开始
            cmd.extend(['--since', 'now'])
        
        # 添加journal目录 - 但首先检查目录中是否有实际的日志文件
        if paths:
            accessible_paths = []
            for path in paths:
                full_path = Path(path)
                if full_path.exists():
                    # 检查目录中是否有日志文件
                    if any(full_path.glob('*.journal*')):
                        accessible_paths.append(path)
                    else:
                        self.logger.info(f"日志目录 {path} 存在但没有日志文件")
                else:
                    self.logger.info(f"日志目录不存在: {path}")
            
            # 如果找到含日志文件的目录，添加到命令
            if accessible_paths:
                for path in accessible_paths:
                    cmd.extend(['--directory', path])
            else:
                self.logger.info("未找到含日志文件的目录，使用系统默认journal")
        else:
            self.logger.info("使用系统默认journal")
        
        return cmd
    
    def _process_output(self):
        """处理日志输出"""
        if not self.process or not self.process.stdout:
            self.logger.warning("没有有效的输出流，使用备用处理方式")
            # 如果没有输出流，保持进程运行而不崩溃
            while self.running:
                time.sleep(1)
            return
        
        buffer = ""
        while self.running and self.process.poll() is None:
            try:
                # 读取字符（非阻塞）
                char = self.process.stdout.read(1)
                if not char:
                    time.sleep(0.1)
                    continue
                
                buffer += char
                
                # 检查是否完成一个JSON对象或新的一行
                if '\n' in buffer:
                    lines = buffer.split('\n')
                    buffer = lines[-1]  # 保留最后一行未完成的部分
                    for line in lines[:-1]:  # 处理完成的行
                        if line.strip():
                            # 尝试解析JSON，如果不是JSON则按普通日志处理
                            self._process_line(line.strip())
                    
                    self.stats['entries_read'] += 1
                    
            except Exception as e:
                self.logger.error(f"处理输出时出错: {e}")
                self.stats['errors'] += 1
                time.sleep(1)
    
    def _process_line(self, line: str):
        """处理单行日志（支持JSON和普通文本）"""
        try:
            # 尝试解析为JSON
            data = json.loads(line)
            entry = JournalEntry.from_json(data)
            
            if entry:
                # 更新心跳
                self.last_heartbeat = time.time()
                
                # 保存游标
                if entry.cursor:
                    self._save_cursor(entry.cursor)
                
                # 处理日志条目
                self._handle_journal_entry(entry)
            else:
                # 如果不是期望的JSON格式，尝试解析普通日志
                self._parse_generic_log_line(line)
        except json.JSONDecodeError:
            # 不是JSON格式，尝试解析为普通日志
            self._parse_generic_log_line(line)
        except Exception as e:
            self.logger.error(f"处理日志行时出错: {e}")
            self.stats['errors'] += 1
    
    def _parse_generic_log_line(self, line: str):
        """解析通用日志行"""
        # 过滤掉不需要的特定日志
        if 'ShouldRestart failed' in line or 'container will not be restarted' in line:
            # 这些是Docker容器停止的正常日志，不需要处理
            return
        
        # 检查是否为飞牛NAS的MAINEVENT或TRIMEVENT格式
        if self._parse_funan_events(line):
            # 如果是飞牛NAS事件格式，直接返回，不再做其他处理
            return
        
        # 这里可以根据需要添加对不同类型日志的解析
        self.logger.debug(f"解析通用日志行: {line[:100]}...")
        
        # 检测并处理常见的登录/登出事件
        lower_line = line.lower()
        if 'login' in lower_line or 'logged in' in lower_line or 'session opened' in lower_line:
            if 'LoginSucc' in self.event_handlers:
                # 提取用户和IP信息
                import re
                user_match = re.search(r'(?:user|for)\s+(\w+)', line, re.IGNORECASE)
                user = user_match.group(1) if user_match else 'unknown'
                ip_match = re.search(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b', line)
                ip = ip_match.group() if ip_match else 'unknown'
                
                event_data = {
                    'user': user,
                    'IP': ip,
                    'via': 'unknown',
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                
                try:
                    # 创建一个虚拟的日志条目
                    from .models import JournalEntry
                    import json
                    virtual_entry = JournalEntry(
                        cursor='',
                        timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        hostname='unknown',
                        syslog_identifier='generic',
                        message=line,
                        priority=6,
                        pid=0,
                        raw_data=json.dumps({'message': line}, ensure_ascii=False)
                    )
                    self.event_handlers['LoginSucc'](event_data, virtual_entry)
                    self.stats['events_processed'] += 1
                    self.logger.info(f"检测到登录事件并发送通知: {user}@{ip}")
                except Exception as e:
                    self.logger.error(f"处理登录事件失败: {e}")
                    self.stats['errors'] += 1
        elif 'logout' in lower_line or 'logged out' in lower_line or 'session closed' in lower_line:
            if 'Logout' in self.event_handlers:
                # 提取用户信息
                import re
                user_match = re.search(r'(?:user|for)\s+(\w+)', line, re.IGNORECASE)
                user = user_match.group(1) if user_match else 'unknown'
                ip_match = re.search(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b', line)
                ip = ip_match.group() if ip_match else 'unknown'
                
                event_data = {
                    'user': user,
                    'IP': ip,
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                
                try:
                    # 创建一个虚拟的日志条目
                    from .models import JournalEntry
                    import json
                    virtual_entry = JournalEntry(
                        cursor="",
                        timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        hostname='unknown',
                        syslog_identifier='generic',
                        message=line,
                        priority=6,
                        pid=0,
                        raw_data=json.dumps({'message': line}, ensure_ascii=False)
                    )
                    self.event_handlers['Logout'](event_data, virtual_entry)
                    self.stats['events_processed'] += 1
                    self.logger.info(f"检测到登出事件并发送通知: {user}@{ip}")
                except Exception as e:
                    self.logger.error(f"处理登出事件失败: {e}")
                    self.stats['errors'] += 1
        elif 'accepted' in lower_line:
            self.logger.info(f"检测到接受连接: {line}")
        elif 'failed' in lower_line or 'failure' in lower_line:
            self.logger.info(f"检测到失败事件: {line}")
    
    def _handle_journal_entry(self, entry: JournalEntry):
        """处理日志条目"""
        # 检查是否为监控的事件类型
        if entry.syslog_identifier not in ['MAINEVENT', 'TRIMEVENT']:
            return
        
        # 提取事件数据
        event_data = entry.extract_event_data()
        if not event_data:
            return
        
        event_type = event_data.pop('_event_type', None)
        
        # MAINEVENT事件
        if event_type == 'MAINEVENT':
            template = event_data.get('template')
            if template:
                self.logger.debug(f"处理MAINEVENT: {template}")
                # 根据模板输出特定格式的日志
                if template == 'LoginSucc':
                    user = event_data.get('user', '')
                    ip = event_data.get('IP', '')
                    via = event_data.get('via', '')
                    timestamp = entry.timestamp
                    print(f"[登录成功] 用户: {user}, IP: {ip}, 方式: {via}, 时间: {timestamp}")
                elif template == 'LoginSucc2FA1':
                    user = event_data.get('user', '')
                    ip = event_data.get('IP', '')
                    via = event_data.get('via', '')
                    timestamp = entry.timestamp
                    print(f"[登录二次校验] 用户: {user}, IP: {ip}, 方式: {via}, 时间: {timestamp}")
                elif template == 'Logout':
                    user = event_data.get('user', '')
                    ip = event_data.get('IP', '')
                    via = event_data.get('via', '')
                    timestamp = entry.timestamp
                    print(f"[退出登录] 用户: {user}, IP: {ip}, 方式: {via}, 时间: {timestamp}")
                elif template == 'FoundDisk':
                    name = event_data.get('name', '')
                    model = event_data.get('model', '')
                    serial = event_data.get('serial', '')
                    timestamp = entry.timestamp
                    print(f"[发现硬盘] 设备名: {name}, 型号: {model}, 序列号: {serial}, 时间: {timestamp}")
                
                # 如果有对应的事件处理器，也调用它
                if template in self.event_handlers:
                    try:
                        self.event_handlers[template](event_data, entry)
                        self.stats['events_processed'] += 1
                    except Exception as e:
                        self.logger.error(f"处理事件失败: {e}")
                        self.stats['errors'] += 1
        
        # TRIMEVENT事件
        elif event_type == 'TRIMEVENT':
            event_id = event_data.get('eventId')
            if event_id == 'APP_CRASH':
                self.logger.debug("处理APP_CRASH事件")
                # 输出APP崩溃格式的日志
                app_data = event_data.get('data', {})
                display_name = app_data.get('DISPLAY_NAME', app_data.get('APP_NAME', '未知应用'))
                timestamp = entry.timestamp
                print(f"[错误] 应用: {display_name}, 崩溃异常退出, 时间: {timestamp}")
                
                # 如果有APP_CRASH处理器，也调用它
                if 'APP_CRASH' in self.event_handlers:
                    try:
                        self.event_handlers['APP_CRASH'](event_data, entry)
                        self.stats['events_processed'] += 1
                    except Exception as e:
                        self.logger.error(f"处理APP_CRASH失败: {e}")
                        self.stats['errors'] += 1
            elif event_id == 'APP_UPDATE_FAILED':
                self.logger.debug("处理APP_UPDATE_FAILED事件")
                # 输出APP更新失败格式的日志
                app_data = event_data.get('data', {})
                display_name = app_data.get('DISPLAY_NAME', app_data.get('APP_NAME', '未知应用'))
                timestamp = entry.timestamp
                print(f"[错误] 应用: {display_name}, 更新失败, 时间: {timestamp}")
                
                # 如果有APP_UPDATE_FAILED处理器，也调用它
                if 'APP_UPDATE_FAILED' in self.event_handlers:
                    try:
                        self.event_handlers['APP_UPDATE_FAILED'](event_data, entry)
                        self.stats['events_processed'] += 1
                    except Exception as e:
                        self.logger.error(f"处理APP_UPDATE_FAILED失败: {e}")
                        self.stats['errors'] += 1
            elif event_id == 'UPS_ONBATT':
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                print(f"[警告] UPS启动，切换到电池供电, 时间: {timestamp}")
                
                # 创建一个虚拟的日志条目来包含完整的事件数据
                from .models import JournalEntry
                # 从原始日志行中提取主机名
                parts = line.split(None, 3)  # 分割为最多4个部分：日期 时间 主机名 其余内容
                hostname = parts[2] if len(parts) >= 3 else 'unknown'
                virtual_entry = JournalEntry(
                    cursor='',
                    timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    hostname=hostname,
                    syslog_identifier='TRIMEVENT',
                    message=line,
                    priority=6,
                    pid=0,
                    raw_data=json.dumps({'message': line}, ensure_ascii=False)
                )
                
                # 如果有UPS_ONBATT处理器，也调用它
                if 'UPS_ONBATT' in self.event_handlers:
                    try:
                        self.event_handlers['UPS_ONBATT'](event_data, virtual_entry)
                        self.stats['events_processed'] += 1
                        self.logger.info("检测到UPS切换到电池供电事件并发送通知")
                    except Exception as e:
                        self.logger.error(f"处理UPS切换到电池供电事件失败: {e}")
                        self.stats['errors'] += 1
            elif event_id == 'UPS_ONBATT_LOWBATT':
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                print(f"[警告] UPS电池电量低警告, 时间: {timestamp}")
                
                # 创建一个虚拟的日志条目来包含完整的事件数据
                from .models import JournalEntry
                # 从原始日志行中提取主机名
                parts = line.split(None, 3)  # 分割为最多4个部分：日期 时间 主机名 其余内容
                hostname = parts[2] if len(parts) >= 3 else 'unknown'
                virtual_entry = JournalEntry(
                    cursor='',
                    timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    hostname=hostname,
                    syslog_identifier='TRIMEVENT',
                    message=line,
                    priority=6,
                    pid=0,
                    raw_data=json.dumps({'message': line}, ensure_ascii=False)
                )
                
                # 如果有UPS_ONBATT_LOWBATT处理器，也调用它
                if 'UPS_ONBATT_LOWBATT' in self.event_handlers:
                    try:
                        self.event_handlers['UPS_ONBATT_LOWBATT'](event_data, virtual_entry)
                        self.stats['events_processed'] += 1
                        self.logger.info("检测到UPS电池电量低警告事件并发送通知")
                    except Exception as e:
                        self.logger.error(f"处理UPS电池电量低警告事件失败: {e}")
                        self.stats['errors'] += 1
            elif event_id == 'UPS_ONLINE':
                self.logger.debug("处理UPS_ONLINE事件")
                # 输出UPS切换到市电供电格式的日志
                timestamp = entry.timestamp
                print(f"[通知] UPS启动，切换到市电供电模式, 时间: {timestamp}")
                
                # 如果有UPS_ONLINE处理器，也调用它
                if 'UPS_ONLINE' in self.event_handlers:
                    try:
                        self.event_handlers['UPS_ONLINE'](event_data, entry)
                        self.stats['events_processed'] += 1
                        self.logger.info("检测到UPS切换到市电供电模式事件并发送通知")
                    except Exception as e:
                        self.logger.error(f"处理UPS切换到市电供电模式事件失败: {e}")
                        self.stats['errors'] += 1
    
    def _parse_funan_events(self, line: str) -> bool:
        """解析飞牛NAS的MAINEVENT和TRIMEVENT格式"""
        import re
        import json
        
        # 检查是否为MAINEVENT格式
        mainevent_match = re.search(r'MAINEVENT\[\d+\]:\s*MAINEVENT:(\{.*?\})(?=\s|$)', line)
        if mainevent_match:
            try:
                event_json = mainevent_match.group(1)
                event_data = json.loads(event_json)
                event_data['_event_type'] = 'MAINEVENT'
                template = event_data.get('template')
                
                if template:
                    # 根据模板输出特定格式的日志
                    if template == 'LoginSucc':
                        user = event_data.get('user', '')
                        ip = event_data.get('IP', '')
                        via = event_data.get('via', '')
                        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        print(f"[登录成功] 用户: {user}, IP: {ip}, 方式: {via}, 时间: {timestamp}")
                    elif template == 'LoginSucc2FA1':
                        user = event_data.get('user', '')
                        ip = event_data.get('IP', '')
                        via = event_data.get('via', '')
                        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        print(f"[登录二次校验] 用户: {user}, IP: {ip}, 方式: {via}, 时间: {timestamp}")
                    elif template == 'Logout':
                        user = event_data.get('user', '')
                        ip = event_data.get('IP', '')
                        via = event_data.get('via', '')
                        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        print(f"[退出登录] 用户: {user}, IP: {ip}, 方式: {via}, 时间: {timestamp}")
                    elif template == 'FoundDisk':
                        name = event_data.get('name', '')
                        model = event_data.get('model', '')
                        serial = event_data.get('serial', '')
                        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        print(f"[发现硬盘] 设备名: {name}, 型号: {model}, 序列号: {serial}, 时间: {timestamp}")
                    elif template == 'DiskWakeup':
                        disk = event_data.get('disk', '')
                        model = event_data.get('model', '')
                        serial = event_data.get('serial', '')
                        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        print(f"[磁盘唤醒] 磁盘: {disk}, 型号: {model}, 序列号: {serial}, 时间: {timestamp}")
                    elif template == 'DiskSpindown':
                        disk = event_data.get('disk', '')
                        model = event_data.get('model', '')
                        serial = event_data.get('serial', '')
                        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        print(f"[磁盘休眠] 磁盘: {disk}, 型号: {model}, 序列号: {serial}, 时间: {timestamp}")
                    
                    # 创建一个虚拟的日志条目来包含完整的事件数据
                    from .models import JournalEntry
                    # 从原始日志行中提取主机名
                    parts = line.split(None, 3)  # 分割为最多4个部分：日期 时间 主机名 其余内容
                    hostname = parts[2] if len(parts) >= 3 else 'unknown'
                    virtual_entry = JournalEntry(
                        cursor='',
                        timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        hostname=hostname,
                        syslog_identifier='MAINEVENT',
                        message=line,
                        priority=6,
                        pid=0,
                        raw_data=json.dumps({'message': line}, ensure_ascii=False)
                    )
                    
                    # 如果有对应的事件处理器，也调用它
                    if template in self.event_handlers:
                        try:
                            self.event_handlers[template](event_data, virtual_entry)
                            self.stats['events_processed'] += 1
                            self.logger.info(f"检测到飞牛事件并发送通知: {template} - {event_data.get('user', 'unknown')}@{event_data.get('IP', 'unknown')}")
                        except Exception as e:
                            self.logger.error(f"处理飞牛事件失败: {e}")
                            self.stats['errors'] += 1
                    
                return True  # 表示这是一个飞牛NAS事件，已处理
            except json.JSONDecodeError:
                pass
        
        # 检查是否为TRIMEVENT格式
        trimevent_match = re.search(r'TRIMEVENT\[\d+\]:\s*TRIMEVENT:(\{.*?\})(?=\s|$)', line)
        if trimevent_match:
            try:
                event_json = trimevent_match.group(1)
                event_data = json.loads(event_json)
                event_data['_event_type'] = 'TRIMEVENT'
                event_id = event_data.get('eventId')
                
                if event_id == 'APP_CRASH':
                    app_data = event_data.get('data', {})
                    display_name = app_data.get('DISPLAY_NAME', app_data.get('APP_NAME', '未知应用'))
                    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    print(f"[错误] 应用: {display_name}, 崩溃异常退出, 时间: {timestamp}")
                    
                    # 创建一个虚拟的日志条目来包含完整的事件数据
                    from .models import JournalEntry
                    # 从原始日志行中提取主机名
                    parts = line.split(None, 3)  # 分割为最多4个部分：日期 时间 主机名 其余内容
                    hostname = parts[2] if len(parts) >= 3 else 'unknown'
                    virtual_entry = JournalEntry(
                        cursor='',
                        timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        hostname=hostname,
                        syslog_identifier='TRIMEVENT',
                        message=line,
                        priority=6,
                        pid=0,
                        raw_data=json.dumps({'message': line}, ensure_ascii=False)
                    )
                    
                    # 如果有APP_CRASH处理器，也调用它
                    if 'APP_CRASH' in self.event_handlers:
                        try:
                            self.event_handlers['APP_CRASH'](event_data, virtual_entry)
                            self.stats['events_processed'] += 1
                            self.logger.info(f"检测到APP崩溃事件并发送通知: {display_name}")
                        except Exception as e:
                            self.logger.error(f"处理APP崩溃事件失败: {e}")
                            self.stats['errors'] += 1
                elif event_id == 'APP_UPDATE_FAILED':
                    app_data = event_data.get('data', {})
                    display_name = app_data.get('DISPLAY_NAME', app_data.get('APP_NAME', '未知应用'))
                    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    print(f"[错误] 应用: {display_name}, 更新失败, 时间: {timestamp}")
                    
                    # 创建一个虚拟的日志条目来包含完整的事件数据
                    from .models import JournalEntry
                    # 从原始日志行中提取主机名
                    parts = line.split(None, 3)  # 分割为最多4个部分：日期 时间 主机名 其余内容
                    hostname = parts[2] if len(parts) >= 3 else 'unknown'
                    virtual_entry = JournalEntry(
                        cursor='',
                        timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        hostname=hostname,
                        syslog_identifier='TRIMEVENT',
                        message=line,
                        priority=6,
                        pid=0,
                        raw_data=json.dumps({'message': line}, ensure_ascii=False)
                    )
                    
                    # 如果有APP_UPDATE_FAILED处理器，也调用它
                    if 'APP_UPDATE_FAILED' in self.event_handlers:
                        try:
                            self.event_handlers['APP_UPDATE_FAILED'](event_data, virtual_entry)
                            self.stats['events_processed'] += 1
                            self.logger.info(f"检测到APP更新失败事件并发送通知: {display_name}")
                        except Exception as e:
                            self.logger.error(f"处理APP更新失败事件失败: {e}")
                            self.stats['errors'] += 1
                elif event_id == 'UPS_ONBATT':
                    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    print(f"[警告] UPS启动，切换到电池供电, 时间: {timestamp}")
                    
                    # 创建一个虚拟的日志条目来包含完整的事件数据
                    from .models import JournalEntry
                    # 从原始日志行中提取主机名
                    parts = line.split(None, 3)  # 分割为最多4个部分：日期 时间 主机名 其余内容
                    hostname = parts[2] if len(parts) >= 3 else 'unknown'
                    virtual_entry = JournalEntry(
                        cursor='',
                        timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        hostname=hostname,
                        syslog_identifier='TRIMEVENT',
                        message=line,
                        priority=6,
                        pid=0,
                        raw_data=json.dumps({'message': line}, ensure_ascii=False)
                    )
                    
                    # 如果有UPS_ONBATT处理器，也调用它
                    if 'UPS_ONBATT' in self.event_handlers:
                        try:
                            self.event_handlers['UPS_ONBATT'](event_data, virtual_entry)
                            self.stats['events_processed'] += 1
                            self.logger.info("检测到UPS切换到电池供电事件并发送通知")
                        except Exception as e:
                            self.logger.error(f"处理UPS切换到电池供电事件失败: {e}")
                            self.stats['errors'] += 1
                elif event_id == 'UPS_ONBATT_LOWBATT':
                    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    print(f"[警告] UPS电池电量低警告, 时间: {timestamp}")
                    
                    # 创建一个虚拟的日志条目来包含完整的事件数据
                    from .models import JournalEntry
                    # 从原始日志行中提取主机名
                    parts = line.split(None, 3)  # 分割为最多4个部分：日期 时间 主机名 其余内容
                    hostname = parts[2] if len(parts) >= 3 else 'unknown'
                    virtual_entry = JournalEntry(
                        cursor='',
                        timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        hostname=hostname,
                        syslog_identifier='TRIMEVENT',
                        message=line,
                        priority=6,
                        pid=0,
                        raw_data=json.dumps({'message': line}, ensure_ascii=False)
                    )
                    
                    # 如果有UPS_ONBATT_LOWBATT处理器，也调用它
                    if 'UPS_ONBATT_LOWBATT' in self.event_handlers:
                        try:
                            self.event_handlers['UPS_ONBATT_LOWBATT'](event_data, virtual_entry)
                            self.stats['events_processed'] += 1
                            self.logger.info("检测到UPS电池电量低警告事件并发送通知")
                        except Exception as e:
                            self.logger.error(f"处理UPS电池电量低警告事件失败: {e}")
                            self.stats['errors'] += 1
                elif event_id == 'UPS_ONLINE':
                    self.logger.debug("处理UPS_ONLINE事件")
                    # 输出UPS切换到市电供电格式的日志
                    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    print(f"[通知] UPS启动，切换到市电供电模式, 时间: {timestamp}")
                    
                    # 创建一个虚拟的日志条目来包含完整的事件数据
                    from .models import JournalEntry
                    # 从原始日志行中提取主机名
                    parts = line.split(None, 3)  # 分割为最多4个部分：日期 时间 主机名 其余内容
                    hostname = parts[2] if len(parts) >= 3 else 'unknown'
                    virtual_entry = JournalEntry(
                        cursor='',
                        timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        hostname=hostname,
                        syslog_identifier='TRIMEVENT',
                        message=line,
                        priority=6,
                        pid=0,
                        raw_data=json.dumps({'message': line}, ensure_ascii=False)
                    )
                    
                    # 如果有UPS_ONLINE处理器，也调用它
                    if 'UPS_ONLINE' in self.event_handlers:
                        try:
                            self.event_handlers['UPS_ONLINE'](event_data, virtual_entry)
                            self.stats['events_processed'] += 1
                            self.logger.info("检测到UPS切换到市电供电模式事件并发送通知")
                        except Exception as e:
                            self.logger.error(f"处理UPS切换到市电供电模式事件失败: {e}")
                            self.stats['errors'] += 1
                
                return True  # 表示这是一个飞牛NAS事件，已处理
            except json.JSONDecodeError:
                pass
        
        return False  # 不是飞牛NAS事件格式
    
    def _heartbeat_monitor(self):
        """心跳监控线程"""
        self.logger.info("心跳监控线程启动")
        
        while self.running:
            time.sleep(self.heartbeat_interval)
            
            # 检查心跳
            if time.time() - self.last_heartbeat > self.heartbeat_interval * 2:
                self.logger.warning("心跳超时，可能日志进程异常")
                
                # 检查进程状态
                if self.process and self.process.poll() is not None:
                    self.logger.error("日志进程已退出，尝试重启...")
                    try:
                        self._restart_log_process()
                    except Exception as e:
                        self.logger.error(f"重启失败: {e}")
                else:
                    # 即使没有日志输出，也更新心跳时间以避免频繁重启
                    self.logger.info("日志进程仍在运行，更新心跳时间")
                    self.last_heartbeat = time.time()
            
            # 定期输出统计信息（每小时）
            if self.stats['entries_read'] % 3600 == 0 and self.stats['entries_read'] > 0:
                self.logger.info(f"运行统计: {self.get_stats()}")
    
    def _restart_log_process(self):
        """重启日志进程"""
        if self.process:
            try:
                # 终止进程组
                if hasattr(self.process, 'poll') and self.process.poll() is not None:
                    os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                    self.process.wait(timeout=5)
            except ProcessLookupError:
                # 进程已经不存在
                pass
            except Exception:
                try:
                    if hasattr(self.process, 'poll') and self.process.poll() is not None:
                        os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                except:
                    pass
            
            self.process = None
        
        # 重新启动日志监控
        self._start_log_process()
        self.logger.info("日志进程已重启")
    
    def _read_cursor(self) -> Optional[str]:
        """读取保存的游标"""
        try:
            if self.cursor_file.exists():
                cursor = self.cursor_file.read_text().strip()
                if cursor:
                    self.logger.info(f"从游标恢复: {cursor[:50]}...")
                    return cursor
        except Exception as e:
            self.logger.error(f"读取游标失败: {e}")
        
        self.logger.info("未找到有效游标，从最新日志开始")
        return None
    
    def _save_cursor(self, cursor: str):
        """保存游标"""
        try:
            self.cursor_file.write_text(cursor)
        except Exception as e:
            self.logger.error(f"保存游标失败: {e}")
    
    def _signal_handler(self, signum, frame):
        """信号处理器"""
        self.logger.info(f"收到信号 {signum}，正在停止...")
        self.stop()
    
    def stop(self):
        """停止监视器"""
        if not self.running:
            return
        
        self.running = False
        self.logger.info("停止Journal监视器")
        
        # 终止进程
        if self.process:
            try:
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                self.process.wait(timeout=5)
                self.logger.info("日志进程已停止")
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                    self.logger.warning("强制终止日志进程")
                except:
                    pass
            except Exception as e:
                self.logger.error(f"停止进程失败: {e}")
        
        # 等待心跳线程
        if self.heartbeat_thread and self.heartbeat_thread.is_alive():
            self.heartbeat_thread.join(timeout=5)
        
        self.logger.info("Journal监视器已停止")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取运行统计"""
        current_time = datetime.now()
        runtime = (current_time - self.stats['start_time']).total_seconds()
        
        return {
            **self.stats,
            'runtime_seconds': runtime,
            'runtime_human': str(current_time - self.stats['start_time']),
            'event_handlers': len(self.event_handlers),
            'is_running': self.running
        }
    
    def is_running(self) -> bool:
        """检查是否在运行"""
        return self.running