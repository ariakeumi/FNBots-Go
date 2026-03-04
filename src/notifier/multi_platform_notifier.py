"""
多平台通知器
支持企业微信、钉钉和飞书的WebHook通知
"""

import time
import logging
import hashlib
import urllib.parse
import threading
from typing import Dict, Any, List
from dataclasses import dataclass
from datetime import datetime

from .connection_pool import ConnectionPool


@dataclass
class MultiPlatformMessage:
    """多平台消息"""
    
    title: str = ""
    content: str = ""
    
    def to_wechat_format(self) -> Dict[str, Any]:
        """转换为企业微信格式"""
        return {
            "msgtype": "text",
            "text": {
                "content": f"{self.title}\n{self.content}"
            }
        }
    
    def to_dingtalk_format(self) -> Dict[str, Any]:
        """转换为钉钉格式"""
        return {
            "msgtype": "text",
            "text": {
                "content": f"{self.title}\n{self.content}"
            }
        }
    
    def to_feishu_format(self) -> Dict[str, Any]:
        """转换为飞书格式"""
        return {
            "msg_type": "text",
            "content": {
                "text": f"{self.title}\n{self.content}"
            }
        }


class MultiPlatformNotifier:
    """多平台通知器"""
    
    # 事件标题映射
    EVENT_TITLES = {
        'LoginSucc': '🔐 飞牛NAS-登录成功通知',
        'LoginSucc2FA1': '🔐 飞牛NAS-二次验证登录',
        'LoginFail': '❌ 飞牛NAS-登录失败告警',
        'Logout': '👋 飞牛NAS-退出登录通知',
        'FoundDisk': '💾 飞牛NAS-发现新硬盘',
        'SSH_INVALID_USER': '⚠️ 飞牛NAS-SSH无效用户尝试',
        'SSH_AUTH_FAILED': '❌ 飞牛NAS-SSH认证失败',
        'SSH_LOGIN_SUCCESS': '🔐 飞牛NAS-SSH登录成功',
        'SSH_DISCONNECTED': '👋 飞牛NAS-SSH断开连接',
        'APP_CRASH': '💥 飞牛NAS-应用崩溃告警',
        'APP_UPDATE_FAILED': '💥 飞牛NAS-应用更新失败告警',
        'APP_START_FAILED_LOCAL_APP_RUN_EXCEPTION': '💥 飞牛NAS-应用启动失败告警',
        'APP_AUTO_START_FAILED_DOCKER_NOT_AVAILABLE': '💥 飞牛NAS-应用自启动失败告警',
        'CPU_USAGE_ALARM': '📊 飞牛NAS-CPU使用率告警',
        'CPU_USAGE_RESTORED': '✅ 飞牛NAS-CPU使用率恢复',
        'CPU_TEMPERATURE_ALARM': '🌡️ 飞牛NAS-CPU温度告警',
        'UPS_ONBATT': '⚠️ 飞牛NAS-UPS切换到电池供电模式',
        'UPS_ONBATT_LOWBATT': '🚨 飞牛NAS-UPS切换到电池供电模式',
        'UPS_ONLINE': '✅ 飞牛NAS-UPS切换到市电供电模式',
        'UPS_ENABLE': '🔌 飞牛NAS-开启UPS支持',
        'UPS_DISABLE': '🔌 飞牛NAS-关闭UPS支持',
        'DiskWakeup': '☀️ 飞牛NAS-磁盘唤醒通知',
        'DiskSpindown': '🌙 飞牛NAS-磁盘休眠通知',
        'APP_START': '🔔 飞牛NAS-监控启动通知',
        'APP_STOP': '🔕 飞牛NAS-监控关闭通知',
        # 数据库 log 表 eventId 直接对应（应用生命周期）
        'APP_STARTED': '✅ 飞牛NAS-应用已启动',
        'APP_STOPPED': '🛑 飞牛NAS-应用已停止',
        'APP_UPDATED': '🔄 飞牛NAS-应用已更新',
        'APP_INSTALLED': '📦 飞牛NAS-应用已安装',
        'APP_AUTO_STARTED': '▶️ 飞牛NAS-应用已自启动',
        'APP_UNINSTALLED': '🗑️ 飞牛NAS-应用已卸载',
        'DISK_IO_ERR': '⚠️ 飞牛NAS-磁盘IO错误告警',
        'TEST_PUSH': '🧪 飞牛NAS-测试推送',
        'DND_SUMMARY': '📋 飞牛NAS-勿扰时段汇总',
        # 可选事件（默认不推送）
        'ARCHIVING_SUCCESS': '📦 飞牛NAS-归档成功',
        'DeleteFile': '🗑️ 飞牛NAS-文件删除',
        'MovetoTrashbin': '🗑️ 飞牛NAS-移到回收站',
        'SHARE_EVENTID_DEL': '📤 飞牛NAS-共享删除',
        'SHARE_EVENTID_PUT': '📤 飞牛NAS-共享添加/更新',
        'WEBDAV_ENABLED': '🌐 飞牛NAS-WebDAV已启用',
        'WEBDAV_DISABLED': '🛑 飞牛NAS-WebDAV已关闭',
        'SAMBA_ENABLED': '📂 飞牛NAS-Samba已启用',
        'SAMBA_DISABLED': '🛑 飞牛NAS-Samba已关闭',
        'FW_ENABLE': '🔥 飞牛NAS-防火墙已开启',
        'FW_DISABLE': '🔥 飞牛NAS-防火墙已关闭',
        'SECURITY_PORTCHANGED': '🔒 飞牛NAS-安全/端口变更',
    }
    
    # Bark事件标题映射 - 用于Bark推送，标题统一为"飞牛NAS通知"
    BARK_EVENT_CONTENTS = {
        'LoginSucc': '用户{user}登录成功',
        'LoginSucc2FA1': '用户{user}登录触发二次校验',
        'LoginFail': '用户{user}登录失败，请检查是否有异常尝试。',
        'Logout': '用户{user}退出登录',
        'FoundDisk': '发现新硬盘{disk_info}',
        'SSH_INVALID_USER': '无效用户{user}尝试登录',
        'SSH_AUTH_FAILED': 'SSH认证失败{user_info}',
        'SSH_LOGIN_SUCCESS': 'SSH用户{user}登录成功',
        'SSH_DISCONNECTED': 'SSH连接已断开',
        'APP_CRASH': '应用{name}崩溃',
        'APP_UPDATE_FAILED': '应用{name}更新失败',
        'APP_START_FAILED_LOCAL_APP_RUN_EXCEPTION': '应用{name}启动失败',
        'APP_AUTO_START_FAILED_DOCKER_NOT_AVAILABLE': '应用{name}自启动失败(Docker不可用)',
        'CPU_USAGE_ALARM': 'CPU使用率超过{threshold}%',
        'CPU_USAGE_RESTORED': 'CPU使用率已恢复至阈值{threshold}%以下',
        'CPU_TEMPERATURE_ALARM': 'CPU温度超过{threshold}°C',
        'UPS_ONBATT': 'UPS提示：UPS切换到电池供电',
        'UPS_ONBATT_LOWBATT': 'UPS提示：UPS低电量自动关机',
        'UPS_ONLINE': 'UPS提示：UPS切换到市电供电',
        'UPS_ENABLE': '已开启UPS支持',
        'UPS_DISABLE': '已关闭UPS支持',
        'DiskWakeup': '磁盘被唤醒',
        'DiskSpindown': '磁盘进入休眠状态',
        'APP_START': '飞牛NAS通知启动',
        'APP_STOP': '飞牛NAS通知已停止',
        'APP_STARTED': '应用{name}已启动',
        'APP_STOPPED': '应用{name}已停止',
        'APP_UPDATED': '应用{name}已更新',
        'APP_INSTALLED': '应用{name}已安装',
        'APP_AUTO_STARTED': '应用{name}已自启动',
        'APP_UNINSTALLED': '应用{name}已卸载',
        'DISK_IO_ERR': '磁盘{dev}发生IO错误，错误次数{err_cnt}',
        'TEST_PUSH': '测试推送',
        'DND_SUMMARY': '勿扰时段事件汇总',
        'ARCHIVING_SUCCESS': '归档成功',
        'DeleteFile': '文件删除',
        'MovetoTrashbin': '移到回收站',
        'SHARE_EVENTID_DEL': '共享删除',
        'SHARE_EVENTID_PUT': '共享添加/更新',
        'WEBDAV_ENABLED': 'WebDAV已启用',
        'WEBDAV_DISABLED': 'WebDAV已关闭',
        'SAMBA_ENABLED': 'Samba已启用',
        'SAMBA_DISABLED': 'Samba已关闭',
        'FW_ENABLE': '防火墙已开启',
        'FW_DISABLE': '防火墙已关闭',
        'SECURITY_PORTCHANGED': '安全/端口变更',
    }
    
    # 事件备注
    EVENT_NOTES = {
        'LoginSucc': '💡 系统检测到用户登录成功，请确认是否为本人操作。',
        'LoginSucc2FA1': '⚠️ 用户已完成两步验证的第一步，等待二次验证。',
        'LoginFail': '⚠️ 系统检测到登录失败，请检查是否有异常尝试。',
        'Logout': '📝 用户已安全退出系统。',
        'FoundDisk': '💾 检测到新存储设备接入系统。',
        'SSH_INVALID_USER': '⚠️ 检测到无效用户登录尝试，请注意安全。',
        'SSH_AUTH_FAILED': '⚠️ SSH认证失败，请确认是否为合法用户。',
        'SSH_LOGIN_SUCCESS': '💡 SSH登录成功，请确认是否为本人操作。',
        'SSH_DISCONNECTED': '📝 SSH连接已断开。',
        'APP_CRASH': '❗ 应用程序异常退出，建议检查应用状态和日志。',
        'APP_UPDATE_FAILED': '❗ 应用程序更新失败，建议检查应用状态和日志。',
        'APP_START_FAILED_LOCAL_APP_RUN_EXCEPTION': '❗ 应用程序启动失败（本地运行异常），建议检查应用状态和日志。',
        'APP_AUTO_START_FAILED_DOCKER_NOT_AVAILABLE': '❗ 应用程序自启动失败（Docker 不可用），请检查 Docker 服务。',
        'CPU_USAGE_ALARM': '⚠️ CPU 使用率超过阈值，建议检查系统负载或关闭占用高的进程。',
        'CPU_USAGE_RESTORED': '✅ CPU 使用率已恢复至阈值以下，负载正常。',
        'CPU_TEMPERATURE_ALARM': '⚠️ CPU 温度超过阈值，请检查散热与机箱通风。',
        'UPS_ONBATT': '⚠️ UPS切换到电池供电模式，请注意电池电量。',
        'UPS_ONBATT_LOWBATT': '⚠️ UPS切换到电池供电模式，低电量自动关机，请尽快恢复市电供应。',
        'UPS_ONLINE': '✅ UPS切换到市电供电模式，电力供应恢复正常。',
        'UPS_ENABLE': '🔌 系统已开启 UPS 支持。',
        'UPS_DISABLE': '🔌 系统已关闭 UPS 支持。',
        'DiskWakeup': '🌙 磁盘已被唤醒。',
        'DiskSpindown': '🌙 磁盘已进入休眠状态。',
        'APP_START': '🚀 飞牛NAS日志监控服务已启动，开始监控系统事件。',
        'APP_STOP': '🛑 飞牛NAS日志监控服务已停止，暂停监控系统事件。',
        'APP_STARTED': '📱 应用已成功启动。',
        'APP_STOPPED': '🛑 应用已停止运行。',
        'APP_UPDATED': '🔄 应用已更新到新版本。',
        'APP_INSTALLED': '📦 新应用已安装。',
        'APP_AUTO_STARTED': '▶️ 应用已随系统自启动。',
        'APP_UNINSTALLED': '🗑️ 应用已卸载。',
        'DISK_IO_ERR': '⚠️ 磁盘发生IO错误，请检查硬盘健康与连接。',
        'TEST_PUSH': '🧪 Web 配置页发送的测试消息。',
        'ARCHIVING_SUCCESS': '📦 系统完成归档任务。',
        'DeleteFile': '🗑️ 文件已被删除。',
        'MovetoTrashbin': '🗑️ 文件已移至回收站。',
        'SHARE_EVENTID_DEL': '📤 共享已删除。',
        'SHARE_EVENTID_PUT': '📤 共享已添加或更新。',
        'WEBDAV_ENABLED': '🌐 WebDAV 服务已启用。',
        'WEBDAV_DISABLED': '🛑 WebDAV 服务已关闭。',
        'SAMBA_ENABLED': '📂 Samba 服务已启用。',
        'SAMBA_DISABLED': '🛑 Samba 服务已关闭。',
        'FW_ENABLE': '🔥 防火墙已开启。',
        'FW_DISABLE': '🔥 防火墙已关闭。',
        'SECURITY_PORTCHANGED': '🔒 安全或端口设置已变更。',
    }
    
    def __init__(self, 
                 wechat_webhook_url: str = "",
                 dingtalk_webhook_url: str = "",
                 feishu_webhook_url: str = "",
                 bark_url: str = "",
                 dedup_window: int = 300,
                 pool_size: int = 10,
                 retries: int = 3,
                 timeout: int = 10):
        """
        初始化通知器
        
        Args:
            wechat_webhook_url: 企业微信Webhook URL
            dingtalk_webhook_url: 钉钉Webhook URL
            feishu_webhook_url: 飞书Webhook URL
            bark_url: Bark推送URL
            dedup_window: 去重时间窗口（秒）
            pool_size: 连接池大小
            retries: 重试次数
            timeout: 超时时间
        """
        self.wechat_webhook_url = wechat_webhook_url
        self.dingtalk_webhook_url = dingtalk_webhook_url
        self.feishu_webhook_url = feishu_webhook_url
        self.bark_url = bark_url
        self.dedup_window = dedup_window
        
        # 连接池
        self.connection_pool = ConnectionPool(
            pool_size=pool_size,
            max_retries=retries,
            timeout=timeout
        )
        
        # 事件去重缓存
        self.sent_events = {}
        
        # 磁盘事件合并缓存 - 使用时间窗口缓存多个磁盘事件
        self.disk_wakeup_cache = {}  # {time_window: [event_data_list]}
        self.disk_spindown_cache = {}  # {time_window: [event_data_list]}
        self.merge_window = 5  # 5秒合并窗口

        # 线程控制
        self._stop_flag = False
        self._cache_lock = threading.Lock()  # 保护磁盘事件缓存的线程锁

        # 发送健康状态
        self._health_lock = threading.Lock()
        self.last_attempt_time = None
        self.last_success_time = None
        self.consecutive_failures = 0
        self.first_failure_time = None
        self.total_failures_since_success = 0

        # 合并事件定时发送线程
        self._start_merge_timer()
        
        # 日志
        self.logger = logging.getLogger(__name__)
        
        platforms = []
        if self.wechat_webhook_url:
            platforms.append('企业微信')
        if self.dingtalk_webhook_url:
            platforms.append('钉钉')
        if self.feishu_webhook_url:
            platforms.append('飞书')
        if self.bark_url:
            platforms.append('Bark')
        
        self.logger.info(f"多平台通知器初始化完成，支持平台: {', '.join(platforms) if platforms else '无'}, 去重窗口: {dedup_window}秒")

    def _record_send_result(self, success: bool):
        """记录发送结果用于健康监控"""
        now = time.time()
        with self._health_lock:
            self.last_attempt_time = now
            if success:
                self.last_success_time = now
                self.consecutive_failures = 0
                self.first_failure_time = None
                self.total_failures_since_success = 0
            else:
                if self.first_failure_time is None:
                    self.first_failure_time = now
                self.consecutive_failures += 1
                self.total_failures_since_success += 1

    def get_delivery_health(self) -> Dict[str, Any]:
        """获取通知发送健康状态"""
        with self._health_lock:
            return {
                'last_attempt_time': self.last_attempt_time,
                'last_success_time': self.last_success_time,
                'consecutive_failures': self.consecutive_failures,
                'first_failure_time': self.first_failure_time,
                'total_failures_since_success': self.total_failures_since_success,
                'active_platforms': {
                    'wechat': bool(self.wechat_webhook_url),
                    'dingtalk': bool(self.dingtalk_webhook_url),
                    'feishu': bool(self.feishu_webhook_url),
                    'bark': bool(self.bark_url)
                }
            }
    
    def _start_merge_timer(self):
        """启动合并事件定时处理线程"""
        self.timer_thread = threading.Thread(target=self._merge_timer_worker, daemon=True)
        self.timer_thread.start()
    
    def _merge_timer_worker(self):
        """合并事件定时处理工作线程"""
        while not self._stop_flag:
            try:
                # 检查并处理过期的合并事件
                current_time = time.time()
                current_window = int(current_time / self.merge_window)

                # 检查前一个窗口是否有待合并的事件
                prev_window = current_window - 1

                # 使用锁保护缓存访问
                with self._cache_lock:
                    # 处理待合并的磁盘唤醒事件
                    if prev_window in self.disk_wakeup_cache and self.disk_wakeup_cache[prev_window]:
                        self._send_merged_disk_event('DiskWakeup', self.disk_wakeup_cache[prev_window], prev_window)
                        del self.disk_wakeup_cache[prev_window]

                    # 处理待合并的磁盘休眠事件
                    if prev_window in self.disk_spindown_cache and self.disk_spindown_cache[prev_window]:
                        self._send_merged_disk_event('DiskSpindown', self.disk_spindown_cache[prev_window], prev_window)
                        del self.disk_spindown_cache[prev_window]

                    # 清理太久之前的缓存（超过2个窗口的）
                    too_old_window = current_window - 3
                    self.disk_wakeup_cache = {k: v for k, v in self.disk_wakeup_cache.items() if k > too_old_window}
                    self.disk_spindown_cache = {k: v for k, v in self.disk_spindown_cache.items() if k > too_old_window}

                # 使用短间隔睡眠以便快速响应停止信号
                for _ in range(10):
                    if self._stop_flag:
                        break
                    time.sleep(0.5)
            except Exception as e:
                self.logger.error(f"合并定时器工作线程出错: {e}", exc_info=True)
                if self._stop_flag:
                    break
    
    def _send_merged_disk_event(self, event_type: str, event_list: List[Dict], time_window: int = 0):
        """发送合并的磁盘事件。event_list 为磁盘信息列表，每项含 disk/model/serial 等字段。"""
        if not event_list:
            return
            
        # 创建合并事件数据
        merged_data = {
            'merged_disks': event_list,
            'count': len(event_list),
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        # 构建消息
        title = self.EVENT_TITLES.get(event_type, f"📋 飞牛NAS-系统事件: {event_type}")
        content = self._build_content(event_type, merged_data, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), '')
        message = MultiPlatformMessage(title=title, content=content)
        
        results = []
        
        # 发送到企业微信
        if self.wechat_webhook_url:
            wechat_result = self._send_to_wechat(message)
            results.append(wechat_result)
            self.logger.debug(f"合并事件-企业微信通知发送结果: {wechat_result}")
        
        # 发送到钉钉
        if self.dingtalk_webhook_url:
            dingtalk_result = self._send_to_dingtalk(message)
            results.append(dingtalk_result)
            self.logger.debug(f"合并事件-钉钉通知发送结果: {dingtalk_result}")
        
        # 发送到飞书
        if self.feishu_webhook_url:
            feishu_result = self._send_to_feishu(message)
            results.append(feishu_result)
            self.logger.debug(f"合并事件-飞书通知发送结果: {feishu_result}")
        
        # 发送到Bark
        if self.bark_url:
            bark_message = self._build_bark_message(event_type, merged_data, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), '')
            bark_result = self._send_to_bark(bark_message)
            results.append(bark_result)
            self.logger.debug(f"合并事件-Bark通知发送结果: {bark_result}")
        
        # 记录发送结果
        if results and any(results):
            self._record_send_result(True)
            self.logger.info(f"合并事件发送成功: {event_type}, 数量: {len(event_list)}")
        else:
            self._record_send_result(False)
            self.logger.warning(f"合并事件发送失败: {event_type}, 数量: {len(event_list)}")
    
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
            是否发送成功（任意一个平台成功即返回True）
        """
        # 特殊处理磁盘事件的合并
        if event_type in ['DiskWakeup', 'DiskSpindown']:
            # 若已是 event_processor 合并后的数据（含 merged_disks 列表），直接发送，避免被 notifier 再次“按条”合并导致内容丢失
            merged_disks = event_data.get('merged_disks') if isinstance(event_data.get('merged_disks'), list) else None
            if merged_disks:
                self._send_merged_disk_event(event_type, merged_disks, 0)
                return True
            return self._handle_disk_event(event_type, event_data, raw_log, timestamp)
        
        # 生成事件指纹（用于去重）
        event_fingerprint = self._generate_fingerprint(event_type, event_data)
        
        # 检查去重
        if self._is_duplicate(event_fingerprint):
            self.logger.debug(f"跳过重复事件: {event_type}")
            return False
        
        # 构建消息
        message = self._build_message(event_type, event_data, timestamp, raw_log)
        
        results = []
        
        # 发送到企业微信
        if self.wechat_webhook_url:
            wechat_result = self._send_to_wechat(message)
            results.append(wechat_result)
            self.logger.debug(f"企业微信通知发送结果: {wechat_result}")
        
        # 发送到钉钉
        if self.dingtalk_webhook_url:
            dingtalk_result = self._send_to_dingtalk(message)
            results.append(dingtalk_result)
            self.logger.debug(f"钉钉通知发送结果: {dingtalk_result}")
        
        # 发送到飞书
        if self.feishu_webhook_url:
            feishu_result = self._send_to_feishu(message)
            results.append(feishu_result)
            self.logger.debug(f"飞书通知发送结果: {feishu_result}")
        
        # 发送到Bark
        if self.bark_url:
            # 对于Bark，我们使用专门的格式，标题为“飞牛NAS通知”，内容为具体的事件
            bark_message = self._build_bark_message(event_type, event_data, timestamp, raw_log)
            bark_result = self._send_to_bark(bark_message)
            results.append(bark_result)
            self.logger.debug(f"Bark通知发送结果: {bark_result}")
        
        # 处理结果
        if results and any(results):  # 至少一个平台发送成功
            self.sent_events[event_fingerprint] = time.time()
            self._record_send_result(True)
            self.logger.info(f"通知发送成功: {event_type}")
            return True
        else:
            self._record_send_result(False)
            self.logger.warning(f"所有通知发送失败: {event_type}")
            return False
    
    def _handle_disk_event(self, event_type: str, event_data: Dict[str, Any], raw_log: str, timestamp: str) -> bool:
        """处理磁盘事件，将其添加到合并缓存中"""
        # 获取当前时间窗口
        current_time = time.time()
        current_window = int(current_time / self.merge_window)

        # 使用锁保护缓存访问，防止竞态条件
        with self._cache_lock:
            # 将事件数据添加到对应类型的缓存中
            if event_type == 'DiskWakeup':
                if current_window not in self.disk_wakeup_cache:
                    self.disk_wakeup_cache[current_window] = []
                self.disk_wakeup_cache[current_window].append(event_data.copy())  # 复制数据以避免后续修改影响
            elif event_type == 'DiskSpindown':
                if current_window not in self.disk_spindown_cache:
                    self.disk_spindown_cache[current_window] = []
                self.disk_spindown_cache[current_window].append(event_data.copy())

        # 返回True表示事件已加入合并队列
        self.logger.debug(f"磁盘事件已加入合并队列: {event_type} -> 窗口 {current_window}")
        return True
    
    def _iter_urls(self, raw: str):
        """将配置的URL拆分为列表，支持使用 '|' 分隔配置多个地址。"""
        if not raw:
            return []
        return [u.strip() for u in str(raw).split('|') if u.strip()]

    def _send_to_wechat(self, message: MultiPlatformMessage) -> bool:
        """发送到企业微信，支持同一渠道多个Webhook地址"""
        payload = message.to_wechat_format()
        urls = self._iter_urls(self.wechat_webhook_url)
        any_success = False
        for url in urls:
            result = self.connection_pool.post(url, payload)
            if result is not None:
                any_success = True
        return any_success
    
    def _send_to_dingtalk(self, message: MultiPlatformMessage) -> bool:
        """发送到钉钉，支持同一渠道多个Webhook地址"""
        payload = message.to_dingtalk_format()
        urls = self._iter_urls(self.dingtalk_webhook_url)
        any_success = False
        for url in urls:
            result = self.connection_pool.post(url, payload)
            if result is not None:
                any_success = True
        return any_success
    
    def _send_to_feishu(self, message: MultiPlatformMessage) -> bool:
        """发送到飞书，支持同一渠道多个Webhook地址"""
        payload = message.to_feishu_format()
        urls = self._iter_urls(self.feishu_webhook_url)
        any_success = False
        for url in urls:
            result = self.connection_pool.post(url, payload)
            if result is not None:
                any_success = True
        return any_success
    
    def _send_to_bark(self, message: MultiPlatformMessage) -> bool:
        """发送到Bark。支持占位符：{title}、{content}；若仅有 {content} 则把标题并入正文避免丢失。直连 URL 则拼接 /标题/内容。"""
        urls = self._iter_urls(self.bark_url)
        if not urls:
            return False

        encoded_title = urllib.parse.quote(message.title, safe='')
        encoded_content = urllib.parse.quote(message.content, safe='')
        encoded_title_and_content = urllib.parse.quote(message.title + '\n\n' + message.content, safe='')

        any_success = False
        for raw_url in urls:
            if '{title}' in raw_url and '{content}' in raw_url:
                bark_push_url = raw_url.replace('{title}', encoded_title).replace('{content}', encoded_content)
            elif '{content}' in raw_url:
                # 仅有 {content} 时无 {title}，把事件标题放进正文首行，避免推送看不到标题
                bark_push_url = raw_url.replace('{content}', encoded_title_and_content)
            else:
                bark_push_url = f"{raw_url.rstrip('/')}/{encoded_title}/{encoded_content}"
            result = self.connection_pool.get(bark_push_url)
            if result:
                any_success = True
        return any_success
    
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
        
        elif event_type == 'APP_UPDATE_FAILED':
            # 应用更新失败：按应用名和时间（5分钟）去重
            data = event_data.get('data', {})
            app_name = data.get('DISPLAY_NAME', data.get('APP_NAME', 'unknown'))
            minute_window = int(time.time() / 300)  # 5分钟窗口
            key = f"update_failed_{app_name}_{minute_window}"
        elif event_type in ['APP_START_FAILED_LOCAL_APP_RUN_EXCEPTION', 'APP_AUTO_START_FAILED_DOCKER_NOT_AVAILABLE']:
            data = event_data.get('data', {})
            app_name = data.get('DISPLAY_NAME', data.get('APP_NAME', 'unknown'))
            minute_window = int(time.time() / 300)
            key = f"{event_type}_{app_name}_{minute_window}"
        elif event_type in ['APP_STARTED', 'APP_STOPPED', 'APP_UPDATED', 'APP_INSTALLED', 'APP_AUTO_STARTED', 'APP_UNINSTALLED']:
            data = event_data.get('data', {})
            app_name = data.get('DISPLAY_NAME', data.get('APP_NAME', 'unknown'))
            minute_window = int(time.time() / 300)
            key = f"{event_type}_{app_name}_{minute_window}"
        elif event_type in ['CPU_USAGE_ALARM', 'CPU_USAGE_RESTORED', 'CPU_TEMPERATURE_ALARM']:
            minute_window = int(time.time() / 300)
            key = f"{event_type}_{minute_window}"
        
        elif event_type == 'UPS_ONBATT_LOWBATT':
            # UPS切换到电池供电：按时间（5分钟）去重
            minute_window = int(time.time() / 300)  # 5分钟窗口
            key = f"ups_battery_{minute_window}"
        
        elif event_type == 'UPS_ONLINE':
            # UPS切换到市电供电：按时间（5分钟）去重
            minute_window = int(time.time() / 300)  # 5分钟窗口
            key = f"ups_online_{minute_window}"
        elif event_type in ['UPS_ENABLE', 'UPS_DISABLE']:
            minute_window = int(time.time() / 300)
            key = f"{event_type}_{minute_window}"
        elif event_type in ['SSH_INVALID_USER', 'SSH_AUTH_FAILED', 'SSH_LOGIN_SUCCESS', 'SSH_DISCONNECTED']:
            # SSH事件：按用户/IP和时间（分钟）去重
            user = event_data.get('user', 'unknown')
            ip = event_data.get('IP', 'unknown')
            minute_window = int(time.time() / 60)
            key = f"{event_type}_{user}_{ip}_{minute_window}"
        elif event_type == 'DISK_IO_ERR':
            data = event_data.get('data', {})
            dev = data.get('DEV', data.get('dev', 'unknown'))
            minute_window = int(time.time() / 60)
            key = f"disk_io_err_{dev}_{minute_window}"
        elif event_type in {
            'ARCHIVING_SUCCESS', 'DeleteFile', 'MovetoTrashbin', 'SHARE_EVENTID_DEL', 'SHARE_EVENTID_PUT',
            'WEBDAV_ENABLED', 'WEBDAV_DISABLED', 'SAMBA_ENABLED', 'SAMBA_DISABLED',
            'FW_ENABLE', 'FW_DISABLE', 'SECURITY_PORTCHANGED',
        }:
            minute_window = int(time.time() / 60)
            key = f"{event_type}_{minute_window}"
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
                      timestamp: str, raw_log: str) -> MultiPlatformMessage:
        """构建多平台消息"""
        
        title = self.EVENT_TITLES.get(event_type, f"📋 飞牛NAS-系统事件: {event_type}")
        content = self._build_content(event_type, event_data, timestamp, raw_log)
        
        return MultiPlatformMessage(title=title, content=content)
    
    def _build_content(self, event_type: str, event_data: Dict[str, Any], 
                      timestamp: str, raw_log: str) -> str:
        """构建消息内容"""
        content = f"🕐 {timestamp}"
        
        # 根据事件类型添加特定字段
        if event_type in ['LoginSucc', 'LoginSucc2FA1', 'LoginFail', 'Logout']:
            content += '\n' + self._build_login_content(event_data)
        elif event_type in ['SSH_INVALID_USER', 'SSH_AUTH_FAILED', 'SSH_LOGIN_SUCCESS', 'SSH_DISCONNECTED']:
            content += '\n' + self._build_ssh_content(event_type, event_data)
        elif event_type == 'FoundDisk':
            content += '\n' + self._build_disk_content(event_data)
        elif event_type == 'APP_CRASH':
            content += '\n' + self._build_app_crash_content(event_data)
        elif event_type in ('APP_STARTED', 'APP_STOPPED', 'APP_UPDATED', 'APP_INSTALLED', 'APP_AUTO_STARTED', 'APP_UNINSTALLED'):
            content += '\n' + self._build_app_lifecycle_content(event_data)
        elif event_type == 'APP_UPDATE_FAILED':
            content += '\n' + self._build_app_update_failed_content(event_data)
        elif event_type == 'APP_START_FAILED_LOCAL_APP_RUN_EXCEPTION':
            content += '\n' + self._build_app_start_failed_content(event_data)
        elif event_type == 'APP_AUTO_START_FAILED_DOCKER_NOT_AVAILABLE':
            content += '\n' + self._build_app_auto_start_failed_content(event_data)
        elif event_type == 'CPU_USAGE_ALARM':
            content += '\n' + self._build_cpu_usage_alarm_content(event_data)
        elif event_type == 'CPU_USAGE_RESTORED':
            content += '\n' + self._build_cpu_usage_restored_content(event_data)
        elif event_type == 'CPU_TEMPERATURE_ALARM':
            content += '\n' + self._build_cpu_temperature_alarm_content(event_data)
        elif event_type == 'UPS_ONBATT':
            content += '\n' + self._build_ups_onbatt_content(event_data)
        elif event_type == 'UPS_ONBATT_LOWBATT':
            content += '\n' + self._build_ups_onbatt_lowbatt_content(event_data)
        elif event_type == 'UPS_ONLINE':
            content += '\n' + self._build_ups_online_content(event_data)
        elif event_type == 'UPS_ENABLE':
            content += '\n' + self._build_ups_enable_disable_content('UPS_ENABLE', event_data)
        elif event_type == 'UPS_DISABLE':
            content += '\n' + self._build_ups_enable_disable_content('UPS_DISABLE', event_data)
        elif event_type == 'DiskWakeup':
            # 所有磁盘唤醒事件都使用合并样式
            if 'merged_disks' in event_data:
                content += '\n' + self._build_merged_disk_wakeup_content(event_data)
            else:
                # 单个磁盘事件也转换为合并格式
                single_disk_as_merged = {
                    'merged_disks': [event_data],
                    'count': 1
                }
                content += '\n' + self._build_merged_disk_wakeup_content(single_disk_as_merged)
        elif event_type == 'DiskSpindown':
            # 所有磁盘休眠事件都使用合并样式
            if 'merged_disks' in event_data:
                content += '\n' + self._build_merged_disk_spindown_content(event_data)
            else:
                # 单个磁盘事件也转换为合并格式
                single_disk_as_merged = {
                    'merged_disks': [event_data],
                    'count': 1
                }
                content += '\n' + self._build_merged_disk_spindown_content(single_disk_as_merged)
        elif event_type == 'DISK_IO_ERR':
            content += '\n' + self._build_disk_io_err_content(event_data)
        elif event_type in {
            'ARCHIVING_SUCCESS', 'DeleteFile', 'MovetoTrashbin', 'SHARE_EVENTID_DEL', 'SHARE_EVENTID_PUT',
            'WEBDAV_ENABLED', 'WEBDAV_DISABLED', 'SAMBA_ENABLED', 'SAMBA_DISABLED',
            'FW_ENABLE', 'FW_DISABLE', 'SECURITY_PORTCHANGED',
        }:
            content += '\n' + self._build_simple_content(event_data)
        
        # 添加备注（去掉尾部多余换行，避免与备注之间出现空行）
        note = self.EVENT_NOTES.get(event_type, '')
        if note:
            content = content.rstrip('\n') + f"\n{note}"
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

    def _build_simple_content(self, event_data: Dict[str, Any]) -> str:
        """可选事件通用内容：展示操作用户、来源等（parameter 中 data.USER_NAME、from 等）。"""
        content = ""
        data = event_data.get('data', {}) or {}
        user = event_data.get('user') or data.get('USER_NAME', data.get('user', ''))
        if user:
            content += f"👤 操作用户: {user}\n"
        from_src = event_data.get('from', '')
        if from_src:
            content += f"📦 来源: {from_src}\n"
        for key in ('path', 'PATH', 'name', 'share_name', 'SHARE_NAME'):
            val = event_data.get(key) or data.get(key)
            if val:
                content += f"📁 {key}: {val}\n"
                break
        return content or "（无额外详情）"

    def _build_disk_io_err_content(self, event_data: Dict[str, Any]) -> str:
        """构建磁盘IO错误事件内容（data: DEV, SN, MODEL, ERR_CNT）"""
        content = ""
        data = event_data.get('data', {})
        dev = data.get('DEV', data.get('dev', ''))
        sn = data.get('SN', data.get('sn', ''))
        model = data.get('MODEL', data.get('model', ''))
        err_cnt = data.get('ERR_CNT', data.get('err_cnt', 0))
        if dev:
            content += f"📛 设备: {dev}\n"
        if model:
            content += f"🔧 型号: {model}\n"
        if sn:
            content += f"🔢 序列号: {sn}\n"
        content += f"⚠️ 错误次数: {err_cnt}\n"
        return content

    def _build_ssh_content(self, event_type: str, event_data: Dict[str, Any]) -> str:
        """构建SSH相关事件内容"""
        content = ""
        if event_type == 'SSH_INVALID_USER':
            user = event_data.get('user', '')
            ip = event_data.get('IP', '')
            port = event_data.get('port', '')
            content += f"👤 用户名: {user}\n"
            content += f"📍 IP地址: {ip}\n"
            if port:
                content += f"🔌 端口: {port}\n"
        elif event_type == 'SSH_AUTH_FAILED':
            user = event_data.get('user', '')
            ip = event_data.get('IP', '')
            port = event_data.get('port', '')
            reason = event_data.get('reason', '')
            if user:
                content += f"👤 用户名: {user}\n"
            if ip:
                content += f"📍 IP地址: {ip}\n"
            if port:
                content += f"🔌 端口: {port}\n"
            if reason:
                content += f"⚠️ 失败原因: {reason}\n"
        elif event_type == 'SSH_LOGIN_SUCCESS':
            user = event_data.get('user', '')
            ip = event_data.get('IP', '')
            port = event_data.get('port', '')
            content += f"👤 用户名: {user}\n"
            content += f"📍 IP地址: {ip}\n"
            if port:
                content += f"🔌 端口: {port}\n"
        elif event_type == 'SSH_DISCONNECTED':
            user = event_data.get('user', '')
            ip = event_data.get('IP', '')
            port = event_data.get('port', '')
            content += f"👤 用户名: {user}\n"
            content += f"📍 IP地址: {ip}\n"
            if port:
                content += f"🔌 端口: {port}\n"
        return content
    
    def _build_disk_wakeup_content(self, event_data: Dict[str, Any]) -> str:
        """构建单个磁盘唤醒事件内容"""
        content = ""
        
        if disk := event_data.get('disk', ''):
            content += f"📛 磁盘设备: {disk}\n"
        
        if model := event_data.get('model', ''):
            content += f"🔧 硬盘型号: {model}\n"
        
        if serial := event_data.get('serial', ''):
            content += f"🔢 序列号: {serial}\n"
        
        return content
    
    def _build_disk_spindown_content(self, event_data: Dict[str, Any]) -> str:
        """构建单个磁盘休眠事件内容"""
        content = ""
        
        if disk := event_data.get('disk', ''):
            content += f"📛 磁盘设备: {disk}\n"
        
        if model := event_data.get('model', ''):
            content += f"🔧 硬盘型号: {model}\n"
        
        if serial := event_data.get('serial', ''):
            content += f"🔢 序列号: {serial}\n"
        
        return content
    
    def _format_disk_fallback(self, disk_info: Dict[str, Any]) -> str:
        """当 disk/model/serial 都为空时，从 full_event_data 或 data 中拼一条可读摘要（支持飞牛顶层 template/user/model/serial）"""
        raw = disk_info.get('full_event_data') or disk_info.get('data')
        if not isinstance(raw, dict):
            return ""
        # 优先从 data 子段取，否则用顶层（飞牛格式：template, user, model, serial 在顶层）
        data = raw.get('data') if isinstance(raw.get('data'), dict) else raw
        parts = []
        for key in ('disk', 'device', 'path', 'name', 'DEVICE', 'DISK', 'deviceName', 'dev'):
            if key in data and data[key]:
                v = data[key]
                if isinstance(v, dict):
                    v = v.get('path') or v.get('device') or v.get('name') or str(v)[:80]
                parts.append(f"设备: {v}")
                break
        for key in ('model', 'MODEL', 'Model', 'modelName'):
            if key in data and data[key]:
                parts.append(f"型号: {data[key]}")
                break
        for key in ('serial', 'SERIAL', 'Serial', 'sn', 'SN', 'serialNumber'):
            if key in data and data[key]:
                parts.append(f"序列号: {data[key]}")
                break
        if parts:
            return " ".join(parts)
        # 无标准字段时，列出 data 中部分键值便于排查
        skip = {'raw', 'datetime', 'eventId', 'level', 'from', 'template', 'cat'}
        extra = [f"{k}: {v}" for k, v in list(data.items())[:5] if k not in skip and v]
        if extra:
            return "原始: " + ", ".join(extra)[:120]
        return ""

    def _build_merged_disk_wakeup_content(self, event_data: Dict[str, Any]) -> str:
        """构建合并磁盘唤醒事件内容"""
        content = ""
        
        merged_disks = event_data.get('merged_disks', [])
        for i, disk_info in enumerate(merged_disks, 1):
            content += f"磁盘 #{i}:\n"
            disk = disk_info.get('disk', '') or ''
            model = disk_info.get('model', '') or ''
            serial = disk_info.get('serial', '') or ''
            if not (disk or model or serial) and isinstance(disk_info.get('full_event_data'), dict):
                raw = disk_info['full_event_data']
                model = model or raw.get('model') or raw.get('MODEL') or raw.get('Model') or ''
                serial = serial or raw.get('serial') or raw.get('SERIAL') or raw.get('Serial') or raw.get('sn') or raw.get('SN') or ''
                disk = disk or raw.get('disk') or raw.get('device') or raw.get('dev') or ''
            if disk:
                content += f"  📛 磁盘设备: {disk}\n"
            if model:
                content += f"  🔧 硬盘型号: {model}\n"
            if serial:
                content += f"  🔢 序列号: {serial}\n"
            if not (disk or model or serial):
                fallback = self._format_disk_fallback(disk_info)
                if fallback:
                    content += f"  {fallback}\n"
                else:
                    content += "  （未解析到磁盘详情，请查看系统日志）\n"
            if i < len(merged_disks):
                content += "\n"
        
        return content
    
    def _build_merged_disk_spindown_content(self, event_data: Dict[str, Any]) -> str:
        """构建合并磁盘休眠事件内容"""
        content = ""
        
        merged_disks = event_data.get('merged_disks', [])
        for i, disk_info in enumerate(merged_disks, 1):
            content += f"磁盘 #{i}:\n"
            disk = disk_info.get('disk', '') or ''
            model = disk_info.get('model', '') or ''
            serial = disk_info.get('serial', '') or ''
            if not (disk or model or serial) and isinstance(disk_info.get('full_event_data'), dict):
                raw = disk_info['full_event_data']
                model = model or raw.get('model') or raw.get('MODEL') or raw.get('Model') or ''
                serial = serial or raw.get('serial') or raw.get('SERIAL') or raw.get('Serial') or raw.get('sn') or raw.get('SN') or ''
                disk = disk or raw.get('disk') or raw.get('device') or raw.get('dev') or ''
            if disk:
                content += f"  📛 磁盘设备: {disk}\n"
            if model:
                content += f"  🔧 硬盘型号: {model}\n"
            if serial:
                content += f"  🔢 序列号: {serial}\n"
            if not (disk or model or serial):
                fallback = self._format_disk_fallback(disk_info)
                if fallback:
                    content += f"  {fallback}\n"
                else:
                    content += "  （未解析到磁盘详情，请查看系统日志）\n"
            if i < len(merged_disks):
                content += "\n"
        
        return content
    
    def _build_app_lifecycle_content(self, event_data: Dict[str, Any]) -> str:
        """构建应用生命周期事件内容（APP_STARTED/STOPPED/UPDATED 等，与 APP_CRASH 同结构）"""
        return self._build_app_crash_content(event_data)

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
    
    def _build_app_update_failed_content(self, event_data: Dict[str, Any]) -> str:
        """构建应用更新失败事件内容"""
        content = ""
        data = event_data.get('data', {})
        
        if app_name := data.get('DISPLAY_NAME', data.get('APP_NAME', '')):
            content += f"📱 应用名称: {app_name}\n"
        
        if app_id := data.get('APP_ID', ''):
            content += f"🆔 应用ID: {app_id}\n"
        
        if from_src := event_data.get('from', ''):
            content += f"📦 来源模块: {from_src}\n"
        
        return content

    def _build_app_start_failed_content(self, event_data: Dict[str, Any]) -> str:
        """构建应用启动失败（本地运行异常）事件内容"""
        return self._build_app_crash_content(event_data)

    def _build_app_auto_start_failed_content(self, event_data: Dict[str, Any]) -> str:
        """构建应用自启动失败（Docker 不可用）事件内容"""
        content = self._build_app_crash_content(event_data)
        content += "⚠️ 原因: Docker 服务不可用\n"
        return content

    def _build_cpu_usage_alarm_content(self, event_data: Dict[str, Any]) -> str:
        """构建 CPU 使用率告警内容（parameter 格式: data.THRESHOLD）"""
        content = ""
        data = event_data.get('data', {})
        threshold = data.get('THRESHOLD', 0)
        content += f"📊 使用率阈值: {threshold}%\n"
        return content

    def _build_cpu_usage_restored_content(self, event_data: Dict[str, Any]) -> str:
        """构建 CPU 使用率恢复内容（parameter 格式: data.THRESHOLD）"""
        content = ""
        data = event_data.get('data', {})
        threshold = data.get('THRESHOLD', 0)
        content += f"✅ 使用率已恢复至阈值 {threshold}% 以下\n"
        return content

    def _build_cpu_temperature_alarm_content(self, event_data: Dict[str, Any]) -> str:
        """构建 CPU 温度告警内容"""
        content = ""
        data = event_data.get('data', {})
        threshold = data.get('THRESHOLD', 0)
        content += f"🌡️ 温度阈值: {threshold}°C\n"
        return content
    
    def _build_ups_onbatt_content(self, event_data: Dict[str, Any]) -> str:
        """构建UPS切换到电池供电事件内容"""
        content = ""
        
        content += f"🔋 UPS状态: 切换到电池供电\n"
        content += f"⚠️ 请注意电池电量\n"
        
        return content
    
    def _build_ups_onbatt_lowbatt_content(self, event_data: Dict[str, Any]) -> str:
        """构建UPS电池电量低警告事件内容"""
        content = ""
        
        content += f"🔋 UPS状态: 电池供电模式，电量低警告\n"
        content += f"🚨 电池电量不足，请尽快恢复市电供应\n"
        
        return content
    
    def _build_ups_online_content(self, event_data: Dict[str, Any]) -> str:
        """构建UPS切换到市电供电事件内容"""
        content = ""

        content += f"🔌 UPS状态: 切换到市电供电模式\n"
        content += f"✅ 电力供应恢复正常\n"

        return content

    def _build_ups_enable_disable_content(self, event_type: str, event_data: Dict[str, Any]) -> str:
        """构建开启/关闭 UPS 支持事件内容（parameter 含 data.USERNAME, from）"""
        content = ""
        data = event_data.get('data', {})
        if username := data.get('USERNAME', ''):
            content += f"👤 操作用户: {username}\n"
        if from_src := event_data.get('from', ''):
            content += f"📦 来源: {from_src}\n"
        return content
    
    def _build_system_content(self, event_type: str, event_data: Dict[str, Any], message: str) -> str:
        """构建系统事件消息内容"""
        content = f"{message}\n"
        
        # 添加简化的时间信息
        content += f"\n🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        return content
    
    def _build_bark_message(self, event_type: str, event_data: Dict[str, Any], 
                           timestamp: str, raw_log: str) -> MultiPlatformMessage:
        """构建Bark消息。标题通过 URL 单独传，正文不再重复包含标题，避免推送时标题显示两次。"""
        message = self._build_message(event_type, event_data, timestamp, raw_log)
        return MultiPlatformMessage(title=message.title, content=message.content)
    
    def send_system_notification(self, event_type: str, message: str, additional_info: Dict[str, Any] = None):
        """
        发送系统事件通知
        
        Args:
            event_type: 事件类型 ('APP_START', 'APP_STOP', 'APP_ERROR', 'DND_SUMMARY')
            message: 详细消息
            additional_info: 额外信息字典
            
        Returns:
            dict: {"success": bool, "success_count": int, "fail_count": int}
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
            return {"success": False, "success_count": 0, "fail_count": 0}
        
        # 构建消息
        title = self.EVENT_TITLES.get(event_type, f"📋 飞牛NAS-系统事件: {event_type}")
        content = self._build_system_content(event_type, event_data, message)
        multi_msg = MultiPlatformMessage(title=title, content=content)
        
        results = []
        
        # 发送到企业微信
        if self.wechat_webhook_url:
            wechat_result = self._send_to_wechat(multi_msg)
            results.append(wechat_result)
            self.logger.debug(f"企业微信系统通知发送结果: {wechat_result}")
        
        # 发送到钉钉
        if self.dingtalk_webhook_url:
            dingtalk_result = self._send_to_dingtalk(multi_msg)
            results.append(dingtalk_result)
            self.logger.debug(f"钉钉系统通知发送结果: {dingtalk_result}")
        
        # 发送到飞书
        if self.feishu_webhook_url:
            feishu_result = self._send_to_feishu(multi_msg)
            results.append(feishu_result)
            self.logger.debug(f"飞书系统通知发送结果: {feishu_result}")
        
        # 发送到Bark
        if self.bark_url:
            # 构建Bark系统消息
            bark_message = self._build_bark_message(event_type, event_data, '', '')
            bark_result = self._send_to_bark(bark_message)
            results.append(bark_result)
            self.logger.debug(f"Bark系统通知发送结果: {bark_result}")
        
        # 处理结果：返回是否成功及成功/失败渠道数（供勿扰汇总等展示）
        success_count = sum(1 for r in results if r)
        fail_count = len(results) - success_count
        any_ok = bool(results and success_count > 0)
        if any_ok:
            self.sent_events[event_fingerprint] = time.time()
            self._record_send_result(True)
            self.logger.info(f"系统事件通知发送成功: {event_type}")
        else:
            self._record_send_result(False)
            self.logger.warning(f"系统事件通知发送失败: {event_type}")
        return {"success": any_ok, "success_count": success_count, "fail_count": fail_count}
    
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
        elif event_type == 'TEST_PUSH':
            # 测试推送：每次发送独立，不去重
            key = f"TEST_PUSH_{time.time()}"
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
            'has_wechat_webhook': bool(self.wechat_webhook_url),
            'has_dingtalk_webhook': bool(self.dingtalk_webhook_url),
            'has_feishu_webhook': bool(self.feishu_webhook_url),
            'disk_wakeup_cache_size': len(self.disk_wakeup_cache),
            'disk_spindown_cache_size': len(self.disk_spindown_cache),
            'merge_window': self.merge_window,
            'wechat_webhook_url': self.wechat_webhook_url[:50] + '...' 
                if len(self.wechat_webhook_url) > 50 else self.wechat_webhook_url,
            'dingtalk_webhook_url': self.dingtalk_webhook_url[:50] + '...' 
                if len(self.dingtalk_webhook_url) > 50 else self.dingtalk_webhook_url,
            'feishu_webhook_url': self.feishu_webhook_url[:50] + '...' 
                if len(self.feishu_webhook_url) > 50 else self.feishu_webhook_url
        }
    
    def close(self):
        """关闭通知器"""
        self.logger.info("正在关闭多平台通知器...")

        # 设置停止标志
        self._stop_flag = True

        # 刷新所有待发送的磁盘事件
        self._flush_pending_disk_events()

        # 等待定时器线程结束
        if hasattr(self, 'timer_thread') and self.timer_thread.is_alive():
            self.timer_thread.join(timeout=10)

        # 关闭连接池
        self.connection_pool.close()

        # 清理缓存
        self.cleanup_cache()

        self.logger.info("多平台通知器已关闭")

    def _flush_pending_disk_events(self):
        """刷新所有待发送的磁盘事件"""
        try:
            with self._cache_lock:
                # 发送所有待发送的磁盘唤醒事件
                for time_window, event_list in self.disk_wakeup_cache.items():
                    if event_list:
                        self.logger.info(f"刷新待发送的磁盘唤醒事件: {len(event_list)} 个")
                        self._send_merged_disk_event('DiskWakeup', event_list, time_window)

                # 发送所有待发送的磁盘休眠事件
                for time_window, event_list in self.disk_spindown_cache.items():
                    if event_list:
                        self.logger.info(f"刷新待发送的磁盘休眠事件: {len(event_list)} 个")
                        self._send_merged_disk_event('DiskSpindown', event_list, time_window)

                # 清空缓存
                self.disk_wakeup_cache.clear()
                self.disk_spindown_cache.clear()
        except Exception as e:
            self.logger.error(f"刷新待发送事件时出错: {e}", exc_info=True)
