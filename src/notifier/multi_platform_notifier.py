"""
多平台通知器
支持企业微信、钉钉和飞书的WebHook通知
"""

import time
import logging
import hashlib
import urllib.parse
import threading
from typing import Dict, Any, Optional, List
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
                "content": f"{self.title}\n\n{self.content}"
            }
        }
    
    def to_dingtalk_format(self) -> Dict[str, Any]:
        """转换为钉钉格式"""
        return {
            "msgtype": "text",
            "text": {
                "content": f"{self.title}\n\n{self.content}"
            }
        }
    
    def to_feishu_format(self) -> Dict[str, Any]:
        """转换为飞书格式"""
        return {
            "msg_type": "text",
            "content": {
                "text": f"{self.title}\n\n{self.content}"
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
        'APP_CRASH': '💥 飞牛NAS-应用崩溃告警',
        'APP_UPDATE_FAILED': '💥 飞牛NAS-应用更新失败告警',
        'APP_START_FAILED_LOCAL_APP_RUN_EXCEPTION': '💥 飞牛NAS-应用启动失败告警',
        'APP_AUTO_START_FAILED_DOCKER_NOT_AVAILABLE': '💥 飞牛NAS-应用自启动失败告警',
        'CPU_USAGE_ALARM': '📊 飞牛NAS-CPU使用率告警',
        'CPU_TEMPERATURE_ALARM': '🌡️ 飞牛NAS-CPU温度告警',
        'UPS_ONBATT': '⚠️ 飞牛NAS-UPS切换到电池供电模式',
        'UPS_ONBATT_LOWBATT': '🚨 飞牛NAS-UPS切换到电池供电模式',
        'UPS_ONLINE': '✅ 飞牛NAS-UPS切换到市电供电模式',
        'DiskWakeup': '☀️ 飞牛NAS-磁盘唤醒通知',
        'DiskSpindown': '🌙 飞牛NAS-磁盘休眠通知',
        'APP_START': '🔔 飞牛NAS-监控启动通知',
        'APP_STOP': '🔕 飞牛NAS-监控关闭通知'
    }
    
    # Bark事件标题映射 - 用于Bark推送，标题统一为"飞牛NAS通知"
    BARK_EVENT_CONTENTS = {
        'LoginSucc': '用户{user}登录成功',
        'LoginSucc2FA1': '用户{user}登录触发二次校验',
        'LoginFail': '用户{user}登录失败，请检查是否有异常尝试。',
        'Logout': '用户{user}退出登录',
        'FoundDisk': '发现新硬盘{disk_info}',
        'APP_CRASH': '应用{name}崩溃',
        'APP_UPDATE_FAILED': '应用{name}更新失败',
        'APP_START_FAILED_LOCAL_APP_RUN_EXCEPTION': '应用{name}启动失败',
        'APP_AUTO_START_FAILED_DOCKER_NOT_AVAILABLE': '应用{name}自启动失败(Docker不可用)',
        'CPU_USAGE_ALARM': 'CPU使用率超过{threshold}%',
        'CPU_TEMPERATURE_ALARM': 'CPU温度超过{threshold}°C',
        'UPS_ONBATT': 'UPS提示：UPS切换到电池供电',
        'UPS_ONBATT_LOWBATT': 'UPS提示：UPS电池电量低警告',
        'UPS_ONLINE': 'UPS提示：UPS切换到市电供电',
        'DiskWakeup': '磁盘被唤醒',
        'DiskSpindown': '磁盘进入休眠状态',
        'APP_START': '飞牛NAS通知启动',
        'APP_STOP': '飞牛NAS通知已停止'
    }
    
    # 事件备注
    EVENT_NOTES = {
        'LoginSucc': '💡 系统检测到用户登录成功，请确认是否为本人操作。',
        'LoginSucc2FA1': '⚠️ 用户已完成两步验证的第一步，等待二次验证。',
        'LoginFail': '⚠️ 系统检测到登录失败，请检查是否有异常尝试。',
        'Logout': '📝 用户已安全退出系统。',
        'FoundDisk': '💾 检测到新存储设备接入系统。',
        'APP_CRASH': '❗ 应用程序异常退出，建议检查应用状态和日志。',
        'APP_UPDATE_FAILED': '❗ 应用程序更新失败，建议检查应用状态和日志。',
        'APP_START_FAILED_LOCAL_APP_RUN_EXCEPTION': '❗ 应用程序启动失败（本地运行异常），建议检查应用状态和日志。',
        'APP_AUTO_START_FAILED_DOCKER_NOT_AVAILABLE': '❗ 应用程序自启动失败（Docker 不可用），请检查 Docker 服务。',
        'CPU_USAGE_ALARM': '⚠️ CPU 使用率超过阈值，建议检查系统负载或关闭占用高的进程。',
        'CPU_TEMPERATURE_ALARM': '⚠️ CPU 温度超过阈值，请检查散热与机箱通风。',
        'UPS_ONBATT': '⚠️ UPS切换到电池供电模式，请注意电池电量。',
        'UPS_ONBATT_LOWBATT': '⚠️ UPS切换到电池供电模式，电池电量低，请尽快恢复市电供应。',
        'UPS_ONLINE': '✅ UPS切换到市电供电模式，电力供应恢复正常。',
        'DiskWakeup': '🌙 磁盘已被唤醒。',
        'DiskSpindown': '🌙 磁盘已进入休眠状态。',
        'APP_START': '🚀 飞牛NAS日志监控服务已启动，开始监控系统事件。',
        'APP_STOP': '🛑 飞牛NAS日志监控服务已停止，暂停监控系统事件。'
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
    
    def _start_merge_timer(self):
        """启动合并事件定时处理线程"""
        self.timer_thread = threading.Thread(target=self._merge_timer_worker, daemon=True)
        self.timer_thread.start()
    
    def _merge_timer_worker(self):
        """合并事件定时处理工作线程"""
        while True:
            try:
                # 检查并处理过期的合并事件
                current_time = time.time()
                current_window = int(current_time / self.merge_window)
                
                # 检查前一个窗口是否有待合并的事件
                prev_window = current_window - 1
                
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
                
                time.sleep(5)  # 每5秒检查一次
            except Exception as e:
                self.logger.error(f"合并定时器工作线程出错: {e}")
    
    def _send_merged_disk_event(self, event_type: str, event_list: List[Dict], time_window: int):
        """发送合并的磁盘事件"""
        if not event_list:
            return
            
        # 创建合并事件数据
        merged_data = {
            'merged_disks': event_list,
            'count': len(event_list),
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        # 构建消息
        title = self.EVENT_TITLES.get(event_type, f"📋 系统事件: {event_type}")
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
            self.logger.info(f"合并事件发送成功: {event_type}, 数量: {len(event_list)}")
        else:
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
            self.logger.info(f"通知发送成功: {event_type}")
            return True
        else:
            self.logger.warning(f"所有通知发送失败: {event_type}")
            return False
    
    def _handle_disk_event(self, event_type: str, event_data: Dict[str, Any], raw_log: str, timestamp: str) -> bool:
        """处理磁盘事件，将其添加到合并缓存中"""
        # 获取当前时间窗口
        current_time = time.time()
        current_window = int(current_time / self.merge_window)
        
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
    
    def _send_to_wechat(self, message: MultiPlatformMessage) -> bool:
        """发送到企业微信"""
        payload = message.to_wechat_format()
        result = self.connection_pool.post(self.wechat_webhook_url, payload)
        return result is not None
    
    def _send_to_dingtalk(self, message: MultiPlatformMessage) -> bool:
        """发送到钉钉"""
        payload = message.to_dingtalk_format()
        result = self.connection_pool.post(self.dingtalk_webhook_url, payload)
        return result is not None
    
    def _send_to_feishu(self, message: MultiPlatformMessage) -> bool:
        """发送到飞书"""
        payload = message.to_feishu_format()
        result = self.connection_pool.post(self.feishu_webhook_url, payload)
        return result is not None
    
    def _send_to_bark(self, message: MultiPlatformMessage) -> bool:
        """发送到Bark，支持 {content} 占位符或直连URL"""
        encoded_content = urllib.parse.quote(message.content, safe='')

        if '{content}' in self.bark_url:
            # 仅替换内容占位符，不改动用户参数，也不添加 title
            bark_push_url = self.bark_url.replace('{content}', encoded_content)
        else:
            # 直连URL：拼接 /飞牛NAS通知/内容
            encoded_title = urllib.parse.quote(message.title, safe='')
            bark_push_url = f"{self.bark_url.rstrip('/')}/{encoded_title}/{encoded_content}"
        
        result = self.connection_pool.get(bark_push_url)
        return result
    
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
        elif event_type in ['CPU_USAGE_ALARM', 'CPU_TEMPERATURE_ALARM']:
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
        
        title = self.EVENT_TITLES.get(event_type, f"📋 系统事件: {event_type}")
        content = self._build_content(event_type, event_data, timestamp, raw_log)
        
        return MultiPlatformMessage(title=title, content=content)
    
    def _build_content(self, event_type: str, event_data: Dict[str, Any], 
                      timestamp: str, raw_log: str) -> str:
        """构建消息内容"""
        content = f"🕐 {timestamp}"
        
        # 根据事件类型添加特定字段
        if event_type in ['LoginSucc', 'LoginSucc2FA1', 'LoginFail', 'Logout']:
            content += '\n' + self._build_login_content(event_data)
        elif event_type == 'FoundDisk':
            content += '\n' + self._build_disk_content(event_data)
        elif event_type == 'APP_CRASH':
            content += '\n' + self._build_app_crash_content(event_data)
        elif event_type == 'APP_UPDATE_FAILED':
            content += '\n' + self._build_app_update_failed_content(event_data)
        elif event_type == 'APP_START_FAILED_LOCAL_APP_RUN_EXCEPTION':
            content += '\n' + self._build_app_start_failed_content(event_data)
        elif event_type == 'APP_AUTO_START_FAILED_DOCKER_NOT_AVAILABLE':
            content += '\n' + self._build_app_auto_start_failed_content(event_data)
        elif event_type == 'CPU_USAGE_ALARM':
            content += '\n' + self._build_cpu_usage_alarm_content(event_data)
        elif event_type == 'CPU_TEMPERATURE_ALARM':
            content += '\n' + self._build_cpu_temperature_alarm_content(event_data)
        elif event_type == 'UPS_ONBATT':
            content += '\n' + self._build_ups_onbatt_content(event_data)
        elif event_type == 'UPS_ONBATT_LOWBATT':
            content += '\n' + self._build_ups_onbatt_lowbatt_content(event_data)
        elif event_type == 'UPS_ONLINE':
            content += '\n' + self._build_ups_online_content(event_data)
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
        
        # 添加备注
        note = self.EVENT_NOTES.get(event_type, '')
        # 统一格式：直接显示备注内容，不加前缀符号
        if note:
            content += f"\n{note}"
        
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
    
    def _build_merged_disk_wakeup_content(self, event_data: Dict[str, Any]) -> str:
        """构建合并磁盘唤醒事件内容"""
        content = ""
        
        merged_disks = event_data.get('merged_disks', [])
        for i, disk_info in enumerate(merged_disks, 1):
            content += f"磁盘 #{i}:\n"
            if disk := disk_info.get('disk', ''):
                content += f"  📛 磁盘设备: {disk}\n"
            if model := disk_info.get('model', ''):
                content += f"  🔧 硬盘型号: {model}\n"
            if serial := disk_info.get('serial', ''):
                content += f"  🔢 序列号: {serial}\n"
            if i < len(merged_disks):  # 只在不是最后一个磁盘时添加空行
                content += "\n"
        
        return content
    
    def _build_merged_disk_spindown_content(self, event_data: Dict[str, Any]) -> str:
        """构建合并磁盘休眠事件内容"""
        content = ""
        
        merged_disks = event_data.get('merged_disks', [])
        for i, disk_info in enumerate(merged_disks, 1):
            content += f"磁盘 #{i}:\n"
            if disk := disk_info.get('disk', ''):
                content += f"  📛 磁盘设备: {disk}\n"
            if model := disk_info.get('model', ''):
                content += f"  🔧 硬盘型号: {model}\n"
            if serial := disk_info.get('serial', ''):
                content += f"  🔢 序列号: {serial}\n"
            if i < len(merged_disks):  # 只在不是最后一个磁盘时添加空行
                content += "\n"
        
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
        """构建 CPU 使用率告警内容"""
        content = ""
        data = event_data.get('data', {})
        threshold = data.get('THRESHOLD', 0)
        content += f"📊 使用率阈值: {threshold}%\n"
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
    
    def _build_system_content(self, event_type: str, event_data: Dict[str, Any], message: str) -> str:
        """构建系统事件消息内容"""
        content = f"{message}\n"
        
        # 添加简化的时间信息
        content += f"\n🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        return content
    
    def _build_bark_message(self, event_type: str, event_data: Dict[str, Any], 
                           timestamp: str, raw_log: str) -> MultiPlatformMessage:
        """构建Bark消息，内容与其他渠道一致"""
        message = self._build_message(event_type, event_data, timestamp, raw_log)
        # Bark正文第一行包含标题
        merged_content = f"{message.title}\n\n{message.content}"
        return MultiPlatformMessage(title=message.title, content=merged_content)
    
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
        
        # 处理结果
        if results and any(results):  # 至少一个平台发送成功
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
        self.connection_pool.close()
        self.cleanup_cache()
        self.logger.info("多平台通知器已关闭")
