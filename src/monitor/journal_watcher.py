import os
import glob
import json
import signal
import time
import logging
import subprocess
import threading
import re
import shutil
import queue
import hashlib
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Callable, Optional, List, Any, Tuple

from .models import JournalEntry

class JournalWatcher:
    """Journal日志监视器"""
    
    def __init__(self, journal_paths: List[str] = None, cursor_dir: str = "/tmp/cursor",
                 eventlogger_log_path: Optional[str] = None, heartbeat_interval: int = 30):
        """
        初始化监视器

        Args:
            journal_paths: Journal目录路径列表
            cursor_dir: 游标文件目录
            eventlogger_log_path: eventlogger_service.log 路径
            heartbeat_interval: 心跳检测间隔（秒）
        """
        self.journal_paths = journal_paths or [
            "/var/log/journal",
            "/run/log/journal"
        ]
        self.cursor_dir = Path(cursor_dir)
        self.cursor_file = self.cursor_dir / "journal_cursor.txt"
        self.eventlogger_log_path = eventlogger_log_path

        # 事件处理器
        self.event_handlers: Dict[str, Callable] = {}

        # 运行状态
        self.running = False
        self.process: Optional[subprocess.Popen] = None
        self.stdout_thread: Optional[threading.Thread] = None
        self.log_mode: str = "unknown"  # file | journalctl | backup
        self.syslog_paths_used: List[str] = []
        self.line_queue = queue.Queue(maxsize=10000)
        self.file_followers: Dict[str, threading.Thread] = {}
        self.file_stop_event = threading.Event()
        self.cursor_locks: Dict[str, threading.Lock] = {}
        self.cursor_locks_lock = threading.Lock()
        self.cursor_save_failures: Dict[str, int] = defaultdict(int)

        # 心跳监控 - 使用配置的心跳间隔
        self.heartbeat_interval = heartbeat_interval
        self.last_heartbeat = time.time()
        self.heartbeat_thread: Optional[threading.Thread] = None

        # 日志源探测状态（用于判断是否有新日志）
        self.last_log_check_time = time.time()
        self.last_log_sizes: Dict[str, int] = {}  # 记录每个日志文件的大小
        
        # 统计信息
        self.stats = {
            'events_processed': 0,
            'entries_read': 0,
            'errors': 0,
            'start_time': datetime.now(),
            'dropped_lines': 0
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
        self.file_stop_event.clear()
        
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
        # 优先使用文件跟踪（syslog + eventlogger），两者逻辑保持一致
        self.file_stop_event.clear()
        if self._start_file_followers():
            self.log_mode = "file"
            self.logger.info("使用文件跟踪方式监控 syslog/eventlogger 日志")
            return

        # 无法跟踪文件时，退回到 journalctl
        if self._check_journalctl_available():
            self.log_mode = "journalctl"
            self.logger.info("使用journalctl方式监控日志")
            self._start_journalctl_process()
        else:
            self.log_mode = "backup"
            self.logger.warning("未找到合适的日志监控方式，启动备用进程保持运行")
            self._start_backup_process()
    
    def _check_journalctl_available(self) -> bool:
        """检查journalctl是否可用"""
        return shutil.which('journalctl') is not None
    
    def _start_file_followers(self) -> bool:
        """启动基于文件的日志跟踪"""
        file_targets = [
            '/var/log/syslog',
            '/var/log/messages',
            '/var/log/auth.log',
            '/var/log/daemon.log',
            '/var/log/kern.log',
            '/var/log/user.log',
            '/var/log/dmesg'
        ]

        if self.eventlogger_log_path:
            file_targets.append(self.eventlogger_log_path)

        # 去重并保持稳定顺序
        seen = set()
        unique_targets = []
        for path in file_targets:
            if not path:
                continue
            normalized = os.path.abspath(path)
            if normalized in seen:
                continue
            seen.add(normalized)
            unique_targets.append(normalized)

        if not unique_targets:
            return False

        started = False
        for path in unique_targets:
            if self._start_file_follower(path):
                started = True

        return started

    def _start_file_follower(self, path: str) -> bool:
        """为指定文件启动跟踪线程"""
        if path in self.file_followers:
            return True

        thread = threading.Thread(
            target=self._follow_file,
            args=(path,),
            name=f"FileFollower-{os.path.basename(path) or 'log'}",
            daemon=True
        )
        thread.start()
        self.file_followers[path] = thread
        if path not in self.syslog_paths_used:
            self.syslog_paths_used.append(path)

        if os.path.exists(path):
            self.logger.info(f"启动文件跟踪: {path}")
            try:
                self.last_log_sizes[path] = os.path.getsize(path)
            except OSError:
                self.last_log_sizes[path] = 0
        else:
            self.logger.info(f"启动文件跟踪: {path}（文件暂不存在，等待创建）")
            self.last_log_sizes[path] = 0
        return True

    def _follow_file(self, path: str):
        """持续读取文件新增内容"""
        cursor_inode, cursor_offset, _ = self._read_file_cursor(path)
        current_offset = cursor_offset or 0
        current_inode = cursor_inode
        skip_history = cursor_inode is None and cursor_offset == 0
        lines_since_save = 0
        last_save_time = time.time()
        save_interval_lines = 100
        save_interval_seconds = 5
        old_file_path: Optional[str] = None
        old_file_offset = 0
        retry_delay = 2.0

        while self.running and not self.file_stop_event.is_set():
            try:
                # 先读取轮转后的旧文件
                if old_file_path and os.path.exists(old_file_path):
                    self._drain_rotated_file(old_file_path, old_file_offset)
                    old_file_path = None
                    old_file_offset = 0
                    current_offset = 0
                    lines_since_save = 0
                    last_save_time = time.time()

                with open(path, 'r', encoding='utf-8', errors='replace') as logfile:
                    inode = os.fstat(logfile.fileno()).st_ino
                    mtime = os.path.getmtime(path)

                    if current_inode and current_inode != inode:
                        self.logger.info(f"检测到日志文件轮转: {path} (inode {current_inode} -> {inode})")
                        old_file_path = self._locate_rotated_file(path, current_inode)
                        if old_file_path:
                            self.logger.info(f"将继续读取轮转文件剩余内容: {old_file_path}")
                        else:
                            self.logger.warning(f"未找到轮转文件，可能丢失部分日志: {path}")
                        old_file_offset = current_offset
                        current_inode = inode
                        current_offset = 0
                        self._save_file_cursor(path, current_inode, current_offset, mtime)
                        lines_since_save = 0
                        last_save_time = time.time()
                        continue  # 先处理旧文件

                    current_inode = inode
                    if skip_history:
                        logfile.seek(0, os.SEEK_END)
                        current_offset = logfile.tell()
                        self._save_file_cursor(path, current_inode, current_offset, mtime)
                        skip_history = False
                        lines_since_save = 0
                        last_save_time = time.time()
                    else:
                        logfile.seek(current_offset)
                    retry_delay = 2.0  # 成功打开后重置退避

                    while self.running and not self.file_stop_event.is_set():
                        line = logfile.readline()
                        if not line:
                            if lines_since_save > 0:
                                self._save_file_cursor(path, current_inode, current_offset, mtime)
                                lines_since_save = 0
                                last_save_time = time.time()
                            if self.file_stop_event.wait(0.5):
                                return
                            continue

                        current_offset = logfile.tell()
                        lines_since_save += 1
                        now = time.time()
                        if (lines_since_save >= save_interval_lines or
                                now - last_save_time >= save_interval_seconds):
                            self._save_file_cursor(path, current_inode, current_offset, mtime)
                            lines_since_save = 0
                            last_save_time = now

                        self._publish_line(line)

                if lines_since_save > 0:
                    mtime = os.path.getmtime(path) if os.path.exists(path) else None
                    self._save_file_cursor(path, current_inode, current_offset, mtime)
                    lines_since_save = 0
                    last_save_time = time.time()

                if self.file_stop_event.wait(1.0):
                    break
            except FileNotFoundError:
                if self.file_stop_event.wait(min(retry_delay, 60.0)):
                    break
                retry_delay = min(retry_delay * 1.5, 60.0)
            except PermissionError:
                self.logger.warning(f"无权限读取日志文件: {path}")
                if self.file_stop_event.wait(5.0):
                    break
            except Exception as exc:
                self.logger.error(f"读取日志文件 {path} 时出错: {exc}", exc_info=True)
                if self.file_stop_event.wait(2.0):
                    break

    def _drain_rotated_file(self, old_path: str, start_offset: int):
        """读取轮转文件剩余内容，避免数据丢失"""
        try:
            with open(old_path, 'r', encoding='utf-8', errors='replace') as old_file:
                old_file.seek(start_offset)
                for line in old_file:
                    self._publish_line(line)
            self.logger.info(f"轮转文件读取完成: {old_path}")
        except Exception as exc:
            self.logger.warning(f"读取轮转文件失败 {old_path}: {exc}")

    def _locate_rotated_file(self, path: str, inode: int) -> Optional[str]:
        """尝试根据inode定位轮转文件"""
        directory = os.path.dirname(path)
        basename = os.path.basename(path)
        candidates = [
            f"{path}.{i}" for i in range(1, 6)
        ] + [
            os.path.join(directory, f"{basename}.{datetime.now().strftime('%Y%m%d')}"),
            os.path.join(directory, f"{basename}.{datetime.now().strftime('%Y%m%d-%H')}"),
        ]
        candidates.extend(glob.glob(f"{path}.*"))

        for candidate in candidates:
            try:
                if not os.path.exists(candidate):
                    continue
                if os.stat(candidate).st_ino == inode:
                    return candidate
            except OSError:
                continue
        return None

    def _file_cursor_path(self, path: str) -> Path:
        """根据文件路径生成唯一的游标文件"""
        safe_name = hashlib.md5(path.encode('utf-8')).hexdigest()
        return self.cursor_dir / f"file_{safe_name}.cursor"

    def _get_cursor_lock(self, path: str) -> threading.Lock:
        with self.cursor_locks_lock:
            if path not in self.cursor_locks:
                self.cursor_locks[path] = threading.Lock()
            return self.cursor_locks[path]

    def _read_file_cursor(self, path: str) -> Tuple[Optional[int], int, Optional[float]]:
        """读取文件游标信息"""
        cursor_file = self._file_cursor_path(path)
        if not cursor_file.exists():
            return None, 0, None
        lock = self._get_cursor_lock(path)
        with lock:
            try:
                data = json.loads(cursor_file.read_text())
                return data.get('inode'), data.get('offset', 0), data.get('mtime')
            except Exception:
                return None, 0, None

    def _save_file_cursor(self, path: str, inode: Optional[int], offset: int, mtime: Optional[float]):
        """保存文件游标"""
        if inode is None:
            return
        cursor_file = self._file_cursor_path(path)
        lock = self._get_cursor_lock(path)
        payload = json.dumps({'inode': inode, 'offset': offset, 'mtime': mtime})
        with lock:
            temp_file = cursor_file.with_suffix(cursor_file.suffix + '.tmp')
            try:
                temp_file.write_text(payload)
                temp_file.replace(cursor_file)
                if path in self.cursor_save_failures:
                    del self.cursor_save_failures[path]
            except Exception as exc:
                temp_file.unlink(missing_ok=True)
                self.cursor_save_failures[path] = self.cursor_save_failures.get(path, 0) + 1
                failure_count = self.cursor_save_failures[path]
                if failure_count == 1:
                    self.logger.warning(f"保存游标失败 {cursor_file}: {exc}")
                elif failure_count % 10 == 0:
                    self.logger.error(f"保存游标连续失败 {failure_count} 次: {cursor_file}")

    def _ensure_file_followers_alive(self):
        """确保文件跟踪线程保持运行"""
        if not self.file_followers:
            return
        for path, thread in list(self.file_followers.items()):
            if thread.is_alive():
                continue
            self.logger.warning(f"文件跟踪线程已停止: {path}，准备重启")
            del self.file_followers[path]
            self._start_file_follower(path)

    def _stop_file_followers(self):
        """停止所有文件跟踪线程"""
        self.file_stop_event.set()
        for path, thread in list(self.file_followers.items()):
            if thread.is_alive():
                thread.join(timeout=2)
        self.file_followers.clear()
    
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
            self._start_process_reader(self.process)
    
    def _start_process_reader(self, proc: subprocess.Popen):
        """启动stdout/stderr读取线程"""
        if not proc:
            return

        if proc.stdout:
            self.stdout_thread = threading.Thread(
                target=self._read_process_stdout,
                args=(proc,),
                name=f"JournalStdout-{proc.pid}",
                daemon=True
            )
            self.stdout_thread.start()

        if proc.stderr:
            threading.Thread(
                target=self._consume_stderr,
                args=(proc,),
                name=f"JournalStderr-{proc.pid}",
                daemon=True
            ).start()
    
    def _read_process_stdout(self, proc: subprocess.Popen):
        """持续读取journalctl输出"""
        try:
            while self.running and proc and proc.stdout:
                line = proc.stdout.readline()
                if not line:
                    if proc.poll() is not None:
                        break
                    time.sleep(0.1)
                    continue
                self._publish_line(line)
        except Exception as exc:
            self.logger.error(f"读取journalctl输出失败: {exc}")
    
    def _start_backup_process(self):
        """启动备用进程保持运行"""
        # 使用一个长时间运行的进程，但不会消耗太多CPU
        self.process = subprocess.Popen(['sleep', '86400'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.log_mode = "backup"
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
        """处理日志输出（统一从队列消费）"""
        while self.running:
            try:
                line = self.line_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if not line:
                continue

            try:
                self._process_line(line)
                self.stats['entries_read'] += 1
            except Exception as exc:
                self.logger.error(f"处理输出时出错: {exc}")
                self.stats['errors'] += 1

    def _publish_line(self, line: str):
        """将新日志行送入统一处理队列"""
        if not line:
            return

        clean_line = line.strip('\r\n')
        if not clean_line:
            return

        try:
            self.line_queue.put(clean_line, timeout=1)
            self.last_heartbeat = time.time()
        except queue.Full:
            self.stats['dropped_lines'] += 1
            self.logger.warning("日志处理队列已满，丢弃一条日志")

    def _consume_stderr(self, proc: subprocess.Popen):
        """消费子进程stderr，避免阻塞"""
        try:
            while self.running and proc and proc.stderr:
                line = proc.stderr.readline()
                if not line:
                    if proc.poll() is not None:
                        break
                    time.sleep(0.1)
                    continue
                msg = line.strip()
                if msg:
                    self.logger.debug(f"journalctl stderr: {msg}")
        except Exception:
            return
    
    def _process_line(self, line: str):
        """处理单行日志（支持JSON和普通文本）"""
        try:
            # 尝试解析为JSON
            data = json.loads(line)
            entry = JournalEntry.from_json(data, line)  # 传入原始行
            
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
                # 即使是非JSON日志，也更新心跳
                self.last_heartbeat = time.time()
        except json.JSONDecodeError:
            # 不是JSON格式，尝试解析为普通日志
            self._parse_generic_log_line(line)
            # 更新心跳，表示进程仍在工作
            self.last_heartbeat = time.time()
        except Exception as e:
            self.logger.error(f"处理日志行时出错: {e}")
            self.stats['errors'] += 1
    
    def _parse_generic_log_line(self, line: str):
        """解析通用日志行"""
        # 过滤掉不需要的特定日志
        if 'ShouldRestart failed' in line or 'container will not be restarted' in line:
            # 这些是Docker容器停止的正常日志，不需要处理
            return

        # SSH相关事件解析（优先处理，避免落入通用登录/登出）
        # 1) ssh服务启动
        if re.search(r'started\s+ssh\.service', line, re.IGNORECASE):
            handler = self.event_handlers.get('SSH_SERVICE_STARTED')
            if handler:
                event_data = {
                    'service': 'ssh',
                    'message': line,
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                try:
                    virtual_entry = JournalEntry(
                        cursor='',
                        timestamp=event_data['timestamp'],
                        hostname='unknown',
                        syslog_identifier='generic',
                        message=line,
                        priority=6,
                        pid=0,
                        raw_data=json.dumps({'message': line}, ensure_ascii=False),
                        original_line=line
                    )
                    handler(event_data, virtual_entry)
                    self.stats['events_processed'] += 1
                except Exception as e:
                    self.logger.error(f"处理SSH服务启动事件失败: {e}")
                    self.stats['errors'] += 1
                return

        # 1.1) ssh服务停止
        if re.search(r'ssh\.service:\s+deactivated successfully', line, re.IGNORECASE) or \
           re.search(r'stopped\s+ssh\.service', line, re.IGNORECASE):
            handler = self.event_handlers.get('SSH_SERVICE_STOPPED')
            if handler:
                event_data = {
                    'service': 'ssh',
                    'message': line,
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                try:
                    virtual_entry = JournalEntry(
                        cursor='',
                        timestamp=event_data['timestamp'],
                        hostname='unknown',
                        syslog_identifier='generic',
                        message=line,
                        priority=6,
                        pid=0,
                        raw_data=json.dumps({'message': line}, ensure_ascii=False),
                        original_line=line
                    )
                    handler(event_data, virtual_entry)
                    self.stats['events_processed'] += 1
                except Exception as e:
                    self.logger.error(f"处理SSH服务停止事件失败: {e}")
                    self.stats['errors'] += 1
                return

        # 2) ssh监听端口
        listen_match = re.search(r'Server listening on (.+?) port (\d+)\.', line, re.IGNORECASE)
        if listen_match:
            handler = self.event_handlers.get('SSH_LISTEN')
            if handler:
                event_data = {
                    'address': listen_match.group(1),
                    'port': listen_match.group(2),
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                try:
                    virtual_entry = JournalEntry(
                        cursor='',
                        timestamp=event_data['timestamp'],
                        hostname='unknown',
                        syslog_identifier='generic',
                        message=line,
                        priority=6,
                        pid=0,
                        raw_data=json.dumps({'message': line}, ensure_ascii=False),
                        original_line=line
                    )
                    handler(event_data, virtual_entry)
                    self.stats['events_processed'] += 1
                except Exception as e:
                    self.logger.error(f"处理SSH监听端口事件失败: {e}")
                    self.stats['errors'] += 1
                return

        # 3) 无效用户登录尝试
        invalid_user_match = re.search(r'Invalid user (\S+) from (\S+) port (\d+)', line, re.IGNORECASE)
        if invalid_user_match:
            handler = self.event_handlers.get('SSH_INVALID_USER')
            if handler:
                event_data = {
                    'user': invalid_user_match.group(1),
                    'IP': invalid_user_match.group(2),
                    'port': invalid_user_match.group(3),
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                try:
                    virtual_entry = JournalEntry(
                        cursor='',
                        timestamp=event_data['timestamp'],
                        hostname='unknown',
                        syslog_identifier='generic',
                        message=line,
                        priority=6,
                        pid=0,
                        raw_data=json.dumps({'message': line}, ensure_ascii=False),
                        original_line=line
                    )
                    handler(event_data, virtual_entry)
                    self.stats['events_processed'] += 1
                except Exception as e:
                    self.logger.error(f"处理SSH无效用户事件失败: {e}")
                    self.stats['errors'] += 1
                return

        # 4) 认证失败（pam_unix 或 Failed password）
        if re.search(r'pam_unix\(sshd:auth\): authentication failure', line, re.IGNORECASE):
            handler = self.event_handlers.get('SSH_AUTH_FAILED')
            if handler:
                rhost_match = re.search(r'rhost=([0-9a-fA-F\.:]+)', line)
                user_match = re.search(r'user=([^\s]+)', line, re.IGNORECASE)
                event_data = {
                    'reason': 'pam_auth_failure',
                    'user': user_match.group(1) if user_match else 'unknown',
                    'IP': rhost_match.group(1) if rhost_match else 'unknown',
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                try:
                    virtual_entry = JournalEntry(
                        cursor='',
                        timestamp=event_data['timestamp'],
                        hostname='unknown',
                        syslog_identifier='generic',
                        message=line,
                        priority=6,
                        pid=0,
                        raw_data=json.dumps({'message': line}, ensure_ascii=False),
                        original_line=line
                    )
                    handler(event_data, virtual_entry)
                    self.stats['events_processed'] += 1
                except Exception as e:
                    self.logger.error(f"处理SSH认证失败事件失败: {e}")
                    self.stats['errors'] += 1
                return

        failed_password_match = re.search(
            r'Failed password for (?:invalid user )?(\S+) from (\S+) port (\d+)',
            line,
            re.IGNORECASE
        )
        if failed_password_match:
            handler = self.event_handlers.get('SSH_AUTH_FAILED')
            if handler:
                event_data = {
                    'reason': 'failed_password',
                    'user': failed_password_match.group(1),
                    'IP': failed_password_match.group(2),
                    'port': failed_password_match.group(3),
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                try:
                    virtual_entry = JournalEntry(
                        cursor='',
                        timestamp=event_data['timestamp'],
                        hostname='unknown',
                        syslog_identifier='generic',
                        message=line,
                        priority=6,
                        pid=0,
                        raw_data=json.dumps({'message': line}, ensure_ascii=False),
                        original_line=line
                    )
                    handler(event_data, virtual_entry)
                    self.stats['events_processed'] += 1
                except Exception as e:
                    self.logger.error(f"处理SSH密码失败事件失败: {e}")
                    self.stats['errors'] += 1
                return

        # 5) 登录成功
        accepted_match = re.search(r'Accepted password for (\S+) from (\S+) port (\d+)', line, re.IGNORECASE)
        if accepted_match:
            handler = self.event_handlers.get('SSH_LOGIN_SUCCESS')
            if handler:
                event_data = {
                    'user': accepted_match.group(1),
                    'IP': accepted_match.group(2),
                    'port': accepted_match.group(3),
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                try:
                    virtual_entry = JournalEntry(
                        cursor='',
                        timestamp=event_data['timestamp'],
                        hostname='unknown',
                        syslog_identifier='generic',
                        message=line,
                        priority=6,
                        pid=0,
                        raw_data=json.dumps({'message': line}, ensure_ascii=False),
                        original_line=line
                    )
                    handler(event_data, virtual_entry)
                    self.stats['events_processed'] += 1
                except Exception as e:
                    self.logger.error(f"处理SSH登录成功事件失败: {e}")
                    self.stats['errors'] += 1
                return

        # 6) 会话开始
        session_open_match = re.search(r'session opened for user (\S+)', line, re.IGNORECASE)
        if session_open_match:
            handler = self.event_handlers.get('SSH_SESSION_OPENED')
            if handler:
                user = session_open_match.group(1)
                # 规范化用户名（去除 uid 信息）
                user = re.sub(r'\(uid=\d+\)$', '', user).strip()
                event_data = {
                    'user': user,
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                try:
                    virtual_entry = JournalEntry(
                        cursor='',
                        timestamp=event_data['timestamp'],
                        hostname='unknown',
                        syslog_identifier='generic',
                        message=line,
                        priority=6,
                        pid=0,
                        raw_data=json.dumps({'message': line}, ensure_ascii=False),
                        original_line=line
                    )
                    handler(event_data, virtual_entry)
                    self.stats['events_processed'] += 1
                except Exception as e:
                    self.logger.error(f"处理SSH会话开启事件失败: {e}")
                    self.stats['errors'] += 1
                return

        # 7) 断开连接
        disconnect_match = re.search(r'Disconnected from user (\S+) (\S+) port (\d+)', line, re.IGNORECASE)
        if disconnect_match:
            handler = self.event_handlers.get('SSH_DISCONNECTED')
            if handler:
                event_data = {
                    'user': disconnect_match.group(1),
                    'IP': disconnect_match.group(2),
                    'port': disconnect_match.group(3),
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                try:
                    virtual_entry = JournalEntry(
                        cursor='',
                        timestamp=event_data['timestamp'],
                        hostname='unknown',
                        syslog_identifier='generic',
                        message=line,
                        priority=6,
                        pid=0,
                        raw_data=json.dumps({'message': line}, ensure_ascii=False),
                        original_line=line
                    )
                    handler(event_data, virtual_entry)
                    self.stats['events_processed'] += 1
                except Exception as e:
                    self.logger.error(f"处理SSH断开连接事件失败: {e}")
                    self.stats['errors'] += 1
                return

        # 8) 会话关闭
        session_close_match = re.search(r'session closed for user (\S+)', line, re.IGNORECASE)
        if session_close_match:
            handler = self.event_handlers.get('SSH_SESSION_CLOSED')
            if handler:
                event_data = {
                    'user': session_close_match.group(1),
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                try:
                    virtual_entry = JournalEntry(
                        cursor='',
                        timestamp=event_data['timestamp'],
                        hostname='unknown',
                        syslog_identifier='generic',
                        message=line,
                        priority=6,
                        pid=0,
                        raw_data=json.dumps({'message': line}, ensure_ascii=False),
                        original_line=line
                    )
                    handler(event_data, virtual_entry)
                    self.stats['events_processed'] += 1
                except Exception as e:
                    self.logger.error(f"处理SSH会话关闭事件失败: {e}")
                    self.stats['errors'] += 1
                return
        
        # 检查是否为飞牛NAS的MAINEVENT或TRIMEVENT格式
        if self._parse_funan_events(line):
            # 如果是飞牛NAS事件格式，直接返回，不再做其他处理
            return
        
        # 这里可以根据需要添加对不同类型日志的解析
        self.logger.debug(f"解析通用日志行: {line[:100]}...")
        
        # 检测并处理常见的登录/登出事件（严格匹配）
        lower_line = line.lower()
        login_pattern = re.compile(
            r'(^|\s)sshd\[\d+\]:\s*accepted\s+',
            re.IGNORECASE
        )
        pam_open_pattern = re.compile(
            r'pam_unix\(.*\):\s*session opened',
            re.IGNORECASE
        )
        login_msg_pattern = re.compile(
            r'\blogin:\s+',
            re.IGNORECASE
        )
        if login_pattern.search(line) or pam_open_pattern.search(line) or login_msg_pattern.search(line):
            if 'LoginSucc' in self.event_handlers:
                # 提取用户和IP信息
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
                    # JournalEntry 已在模块顶部导入
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
        # 更精确的登出检测模式
        elif re.search(r'\bsession closed\b|\buser logged out\b|\blogout success\b', line, re.IGNORECASE):
            if 'Logout' in self.event_handlers:
                # 提取用户信息
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
                    # JournalEntry 已在模块顶部导入
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
            # 失败类日志噪声较大，不在控制台输出
            pass
    
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
                elif template == 'LoginFail':
                    user = event_data.get('user', '')
                    ip = event_data.get('IP', '')
                    via = event_data.get('via', '')
                    timestamp = entry.timestamp
                    print(f"[登录失败] 用户: {user}, IP: {ip}, 方式: {via}, 时间: {timestamp}")
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
                app_data = event_data.get('data', {})
                display_name = app_data.get('DISPLAY_NAME', app_data.get('APP_NAME', '未知应用'))
                timestamp = entry.timestamp
                print(f"[错误] 应用: {display_name}, 更新失败, 时间: {timestamp}")
                if 'APP_UPDATE_FAILED' in self.event_handlers:
                    try:
                        self.event_handlers['APP_UPDATE_FAILED'](event_data, entry)
                        self.stats['events_processed'] += 1
                    except Exception as e:
                        self.logger.error(f"处理APP_UPDATE_FAILED失败: {e}")
                        self.stats['errors'] += 1
            elif event_id == 'APP_START_FAILED_LOCAL_APP_RUN_EXCEPTION':
                app_data = event_data.get('data', {})
                display_name = app_data.get('DISPLAY_NAME', app_data.get('APP_NAME', '未知应用'))
                print(f"[错误] 应用: {display_name}, 启动失败(本地运行异常), 时间: {entry.timestamp}")
                if 'APP_START_FAILED_LOCAL_APP_RUN_EXCEPTION' in self.event_handlers:
                    try:
                        self.event_handlers['APP_START_FAILED_LOCAL_APP_RUN_EXCEPTION'](event_data, entry)
                        self.stats['events_processed'] += 1
                    except Exception as e:
                        self.logger.error(f"处理应用启动失败事件失败: {e}")
                        self.stats['errors'] += 1
            elif event_id == 'APP_AUTO_START_FAILED_DOCKER_NOT_AVAILABLE':
                app_data = event_data.get('data', {})
                display_name = app_data.get('DISPLAY_NAME', app_data.get('APP_NAME', '未知应用'))
                print(f"[错误] 应用: {display_name}, 自启动失败(Docker不可用), 时间: {entry.timestamp}")
                if 'APP_AUTO_START_FAILED_DOCKER_NOT_AVAILABLE' in self.event_handlers:
                    try:
                        self.event_handlers['APP_AUTO_START_FAILED_DOCKER_NOT_AVAILABLE'](event_data, entry)
                        self.stats['events_processed'] += 1
                    except Exception as e:
                        self.logger.error(f"处理应用自启动失败事件失败: {e}")
                        self.stats['errors'] += 1
            elif event_id == 'CPU_USAGE_ALARM':
                data = event_data.get('data', {})
                threshold = data.get('THRESHOLD', 0)
                print(f"[告警] CPU使用率超过 {threshold}%, 时间: {entry.timestamp}")
                if 'CPU_USAGE_ALARM' in self.event_handlers:
                    try:
                        self.event_handlers['CPU_USAGE_ALARM'](event_data, entry)
                        self.stats['events_processed'] += 1
                    except Exception as e:
                        self.logger.error(f"处理CPU使用率告警失败: {e}")
                        self.stats['errors'] += 1
            elif event_id == 'CPU_TEMPERATURE_ALARM':
                data = event_data.get('data', {})
                threshold = data.get('THRESHOLD', 0)
                print(f"[告警] CPU温度超过 {threshold}°C, 时间: {entry.timestamp}")
                if 'CPU_TEMPERATURE_ALARM' in self.event_handlers:
                    try:
                        self.event_handlers['CPU_TEMPERATURE_ALARM'](event_data, entry)
                        self.stats['events_processed'] += 1
                    except Exception as e:
                        self.logger.error(f"处理CPU温度告警失败: {e}")
                        self.stats['errors'] += 1
            elif event_id == 'UPS_ONBATT':
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                print(f"[警告] UPS启动，切换到电池供电, 时间: {timestamp}")
                
                # 创建一个虚拟的日志条目来包含完整的事件数据
                # 从原始日志行中提取主机名
                raw_line = entry.original_line or entry.message
                parts = raw_line.split(None, 3)  # 分割为最多4个部分：日期 时间 主机名 其余内容
                hostname = parts[2] if len(parts) >= 3 else 'unknown'
                virtual_entry = JournalEntry(
                    cursor='',
                    timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    hostname=hostname,
                    syslog_identifier='TRIMEVENT',
                    message=raw_line,
                    priority=6,
                    pid=0,
                    raw_data=json.dumps({'message': raw_line}, ensure_ascii=False),
                    original_line=raw_line
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
                # 从原始日志行中提取主机名
                raw_line = entry.original_line or entry.message
                parts = raw_line.split(None, 3)  # 分割为最多4个部分：日期 时间 主机名 其余内容
                hostname = parts[2] if len(parts) >= 3 else 'unknown'
                virtual_entry = JournalEntry(
                    cursor='',
                    timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    hostname=hostname,
                    syslog_identifier='TRIMEVENT',
                    message=raw_line,
                    priority=6,
                    pid=0,
                    raw_data=json.dumps({'message': raw_line}, ensure_ascii=False),
                    original_line=raw_line
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
        # json 已在模块顶部导入
        
        # 检查是否为MAINEVENT格式
        mainevent_match = re.search(r'MAINEVENT\[\d+\]:\s*MAINEVENT:(\{.*?\})', line)
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
                    elif template == 'LoginFail':
                        user = event_data.get('user', '')
                        ip = event_data.get('IP', '')
                        via = event_data.get('via', '')
                        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        print(f"[登录失败] 用户: {user}, IP: {ip}, 方式: {via}, 时间: {timestamp}")
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
        trimevent_match = re.search(r'TRIMEVENT\[\d+\]:\s*TRIMEVENT:(\{.*?\})', line)
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
                elif event_id == 'APP_START_FAILED_LOCAL_APP_RUN_EXCEPTION':
                    app_data = event_data.get('data', {})
                    display_name = app_data.get('DISPLAY_NAME', app_data.get('APP_NAME', '未知应用'))
                    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    print(f"[错误] 应用: {display_name}, 启动失败(本地运行异常), 时间: {timestamp}")
                    parts = line.split(None, 3)
                    hostname = parts[2] if len(parts) >= 3 else 'unknown'
                    virtual_entry = JournalEntry(
                        cursor='', timestamp=timestamp, hostname=hostname,
                        syslog_identifier='TRIMEVENT', message=line, priority=6, pid=0,
                        raw_data=json.dumps({'message': line}, ensure_ascii=False)
                    )
                    if 'APP_START_FAILED_LOCAL_APP_RUN_EXCEPTION' in self.event_handlers:
                        try:
                            self.event_handlers['APP_START_FAILED_LOCAL_APP_RUN_EXCEPTION'](event_data, virtual_entry)
                            self.stats['events_processed'] += 1
                            self.logger.info(f"检测到应用启动失败事件并发送通知: {display_name}")
                        except Exception as e:
                            self.logger.error(f"处理应用启动失败事件失败: {e}")
                            self.stats['errors'] += 1
                elif event_id == 'APP_AUTO_START_FAILED_DOCKER_NOT_AVAILABLE':
                    app_data = event_data.get('data', {})
                    display_name = app_data.get('DISPLAY_NAME', app_data.get('APP_NAME', '未知应用'))
                    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    print(f"[错误] 应用: {display_name}, 自启动失败(Docker不可用), 时间: {timestamp}")
                    parts = line.split(None, 3)
                    hostname = parts[2] if len(parts) >= 3 else 'unknown'
                    virtual_entry = JournalEntry(
                        cursor='', timestamp=timestamp, hostname=hostname,
                        syslog_identifier='TRIMEVENT', message=line, priority=6, pid=0,
                        raw_data=json.dumps({'message': line}, ensure_ascii=False)
                    )
                    if 'APP_AUTO_START_FAILED_DOCKER_NOT_AVAILABLE' in self.event_handlers:
                        try:
                            self.event_handlers['APP_AUTO_START_FAILED_DOCKER_NOT_AVAILABLE'](event_data, virtual_entry)
                            self.stats['events_processed'] += 1
                            self.logger.info(f"检测到应用自启动失败事件并发送通知: {display_name}")
                        except Exception as e:
                            self.logger.error(f"处理应用自启动失败事件失败: {e}")
                            self.stats['errors'] += 1
                elif event_id == 'CPU_USAGE_ALARM':
                    data = event_data.get('data', {})
                    threshold = data.get('THRESHOLD', 0)
                    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    print(f"[告警] CPU使用率超过 {threshold}%, 时间: {timestamp}")
                    parts = line.split(None, 3)
                    hostname = parts[2] if len(parts) >= 3 else 'unknown'
                    virtual_entry = JournalEntry(
                        cursor='', timestamp=timestamp, hostname=hostname,
                        syslog_identifier='TRIMEVENT', message=line, priority=6, pid=0,
                        raw_data=json.dumps({'message': line}, ensure_ascii=False)
                    )
                    if 'CPU_USAGE_ALARM' in self.event_handlers:
                        try:
                            self.event_handlers['CPU_USAGE_ALARM'](event_data, virtual_entry)
                            self.stats['events_processed'] += 1
                            self.logger.info("检测到CPU使用率告警并发送通知")
                        except Exception as e:
                            self.logger.error(f"处理CPU使用率告警失败: {e}")
                            self.stats['errors'] += 1
                elif event_id == 'CPU_TEMPERATURE_ALARM':
                    data = event_data.get('data', {})
                    threshold = data.get('THRESHOLD', 0)
                    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    print(f"[告警] CPU温度超过 {threshold}°C, 时间: {timestamp}")
                    parts = line.split(None, 3)
                    hostname = parts[2] if len(parts) >= 3 else 'unknown'
                    virtual_entry = JournalEntry(
                        cursor='', timestamp=timestamp, hostname=hostname,
                        syslog_identifier='TRIMEVENT', message=line, priority=6, pid=0,
                        raw_data=json.dumps({'message': line}, ensure_ascii=False)
                    )
                    if 'CPU_TEMPERATURE_ALARM' in self.event_handlers:
                        try:
                            self.event_handlers['CPU_TEMPERATURE_ALARM'](event_data, virtual_entry)
                            self.stats['events_processed'] += 1
                            self.logger.info("检测到CPU温度告警并发送通知")
                        except Exception as e:
                            self.logger.error(f"处理CPU温度告警失败: {e}")
                            self.stats['errors'] += 1
                elif event_id == 'UPS_ONBATT':
                    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    print(f"[警告] UPS启动，切换到电池供电, 时间: {timestamp}")
                    
                    # 创建一个虚拟的日志条目来包含完整的事件数据
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
        self.logger.info(f"心跳监控线程启动（间隔: {self.heartbeat_interval}秒）")

        while self.running:
            time.sleep(self.heartbeat_interval)

            idle_duration = time.time() - self.last_heartbeat
            threshold = self.heartbeat_interval * (3 if self.log_mode == "file" else 2)

            if idle_duration > threshold:
                if self.log_mode == "file":
                    self.logger.debug("心跳空闲，检查文件跟踪线程状态")
                    self._ensure_file_followers_alive()
                    self.last_heartbeat = time.time()
                    continue

                self.logger.warning(f"心跳超时（超过 {self.heartbeat_interval * 2} 秒未读到日志）")

                # 首先检查进程是否存活
                if self.process is None or self.process.poll() is not None:
                    self.logger.error("日志进程已退出或不存在，立即重启")
                    try:
                        self._restart_log_process()
                        self.last_heartbeat = time.time()
                    except Exception as e:
                        self.logger.error(f"重启失败: {e}")
                    continue

                # 进程存活但无输出，探测是否有新日志
                if self._probe_log_source_for_new_content():
                    self.logger.info("探测到新日志内容，更新心跳时间")
                    self.last_heartbeat = time.time()
                    continue

                # 探测失败，进程可能卡死，重启日志进程
                self.logger.error("日志探测失败（无新内容），进程可能卡死，重启日志进程")
                try:
                    self._restart_log_process()
                    self.last_heartbeat = time.time()
                except Exception as e:
                    self.logger.error(f"重启失败: {e}")

            # 定期输出统计信息（每小时）
            if self.stats['entries_read'] % 3600 == 0 and self.stats['entries_read'] > 0:
                self.logger.info(f"运行统计: {self.get_stats()}")
    
    def _restart_log_process(self):
        """重启日志进程"""
        self.logger.info("准备重启日志进程")

        if self.log_mode == "file":
            # 重启文件跟踪线程
            self._stop_file_followers()
            self.file_stop_event.clear()
            started = self._start_file_followers()
            if started:
                self.logger.info("文件跟踪线程已重启")
            else:
                self.logger.warning("无法重启文件跟踪线程，尝试切换到journalctl")
                self._start_log_process()
            self.last_heartbeat = time.time()
            return

        if self.process:
            try:
                self.logger.info(f"当前进程PID: {getattr(self.process, 'pid', 'Unknown')}")
                self.logger.info(f"进程状态: {getattr(self.process, 'poll', lambda: 'Unknown')()}")
                
                # 终止进程组
                if hasattr(self.process, 'poll') and self.process.poll() is None:
                    os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                    self.process.wait(timeout=5)
            except ProcessLookupError:
                self.logger.info("进程已经不存在")
            except Exception as e:
                self.logger.warning(f"优雅终止失败: {e}")
                try:
                    if hasattr(self.process, 'poll') and self.process.poll() is None:
                        os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                except Exception as e2:
                    self.logger.error(f"强制终止也失败: {e2}")
            
            self.process = None
        
        # 重新启动日志监控
        self._start_log_process()
        self.logger.info("日志进程已重启")

    def _probe_log_source_for_new_content(self) -> bool:
        """探测日志源是否有新内容（不是仅检查有内容）"""
        try:
            if self.log_mode == "file" and self.syslog_paths_used:
                has_new_content = False
                for path in self.syslog_paths_used:
                    try:
                        if not os.path.exists(path):
                            continue

                        current_size = os.path.getsize(path)
                        last_size = self.last_log_sizes.get(path, 0)

                        if current_size > last_size:
                            self.logger.info(f"检测到 {path} 有新内容（{last_size} -> {current_size} 字节）")
                            has_new_content = True
                        elif current_size < last_size:
                            self.logger.info(f"检测到 {path} 文件轮转（{last_size} -> {current_size} 字节）")
                            has_new_content = True

                        self.last_log_sizes[path] = current_size
                    except Exception as e:
                        self.logger.debug(f"探测 {path} 时出错: {e}")
                        continue
                return has_new_content

            if self.log_mode == "journalctl":
                # 使用 journalctl --since 检查是否有新日志
                since_time = datetime.fromtimestamp(self.last_log_check_time).strftime('%Y-%m-%d %H:%M:%S')
                result = subprocess.run(
                    ['journalctl', '--since', since_time, '-n', '1', '--no-pager'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                self.last_log_check_time = time.time()

                # 如果有输出且不为空，说明有新日志
                has_new = result.returncode == 0 and bool(result.stdout.strip())
                if has_new:
                    self.logger.info("journalctl 探测到新日志")
                return has_new

            return False
        except Exception as e:
            self.logger.error(f"探测日志源时出错: {e}")
            return False
    
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

        # 停止文件跟踪
        self._stop_file_followers()
        
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
                except ProcessLookupError:
                    self.logger.debug("进程已不存在，无需强制终止")
                except Exception as e:
                    self.logger.error(f"强制终止进程失败: {e}")
            except Exception as e:
                self.logger.error(f"停止进程失败: {e}")
        
        # 等待心跳线程
        if self.heartbeat_thread and self.heartbeat_thread.is_alive():
            self.heartbeat_thread.join(timeout=5)

        if self.stdout_thread and self.stdout_thread.is_alive():
            self.stdout_thread.join(timeout=5)
        
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
            'is_running': self.running,
            'queue_size': self.line_queue.qsize(),
            'active_file_followers': len([t for t in self.file_followers.values() if t.is_alive()]),
            'cursor_save_failures': sum(self.cursor_save_failures.values())
        }
    
    def is_running(self) -> bool:
        """检查是否在运行"""
        return self.running
