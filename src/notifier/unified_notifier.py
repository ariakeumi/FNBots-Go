"""
统一通知器
根据配置决定使用企业微信webhook、钉钉或飞书进行消息推送
支持勿扰模式：时段内缓冲事件，结束后汇总为一条推送
"""

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Any, List
from zoneinfo import ZoneInfo

from .multi_platform_notifier import MultiPlatformNotifier


@dataclass
class NotificationResult:
    """通知发送结果"""
    success: bool
    method: str  # 'wechat', 'dingtalk', 'feishu', 'multiple', 'none'
    details: Dict[str, Any] = None


class UnifiedNotifier:
    """统一通知器，支持多平台推送"""
    
    def __init__(self, config):
        """
        初始化统一通知器
        
        Args:
            config: 配置对象
        """
        self.config = config
        self.logger = logging.getLogger(__name__)
        # 勿扰模式缓冲：{event_type, timestamp, event_data}
        self._dnd_buffer: List[Dict[str, Any]] = []

        # 根据配置初始化多平台通知器
        self.multi_platform_notifier = MultiPlatformNotifier(
            wechat_webhook_url=config.wechat_webhook_url,
            dingtalk_webhook_url=config.dingtalk_webhook_url,
            feishu_webhook_url=config.feishu_webhook_url,
            bark_url=config.bark_url,
            pushplus_params=config.pushplus_params,
            dedup_window=config.dedup_window,
            pool_size=config.http_pool_size,
            retries=config.http_retry_count,
            timeout=config.http_timeout
        )
        self.logger.info("多平台通知器已初始化")

    def reload_config(self):
        """按当前 self.config 重新创建多平台通知器（保存配置后热加载用）。"""
        old = self.multi_platform_notifier
        self.multi_platform_notifier = MultiPlatformNotifier(
            wechat_webhook_url=self.config.wechat_webhook_url,
            dingtalk_webhook_url=self.config.dingtalk_webhook_url,
            feishu_webhook_url=self.config.feishu_webhook_url,
            bark_url=self.config.bark_url,
            pushplus_params=self.config.pushplus_params,
            dedup_window=self.config.dedup_window,
            pool_size=self.config.http_pool_size,
            retries=self.config.http_retry_count,
            timeout=self.config.http_timeout,
        )
        if old:
            try:
                old.close()
            except Exception as e:
                self.logger.warning("关闭旧通知器失败: %s", e)
        self.logger.info("多平台通知器已热加载配置")

    def _dnd_minutes_since_midnight(self, time_str: str) -> int:
        """将 HH:MM 转为当日 0 点起的分钟数。"""
        try:
            parts = time_str.strip().split(":")
            h, m = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
            return max(0, min(24 * 60 - 1, h * 60 + m))
        except (ValueError, IndexError):
            return 0

    def _in_dnd_window(self) -> bool:
        """当前时间是否在勿扰时段内（使用 Asia/Shanghai）。"""
        enabled = getattr(self.config, "dnd_enabled", False)
        if not enabled:
            return False
        start_s = getattr(self.config, "dnd_start_time", "22:00") or "22:00"
        end_s = getattr(self.config, "dnd_end_time", "07:00") or "07:00"
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        current = now.hour * 60 + now.minute
        start_m = self._dnd_minutes_since_midnight(start_s)
        end_m = self._dnd_minutes_since_midnight(end_s)
        if end_m <= start_m:
            return current >= start_m or current < end_m
        return start_m <= current < end_m

    def _build_dnd_summary_and_clear(self) -> str:
        """将缓冲按事件类型统计，生成汇总文案并清空缓冲。"""
        if not self._dnd_buffer:
            return ""
        start_s = getattr(self.config, "dnd_start_time", "22:00") or "22:00"
        end_s = getattr(self.config, "dnd_end_time", "07:00") or "07:00"
        by_type = defaultdict(int)
        for item in self._dnd_buffer:
            by_type[item.get("event_type", "unknown")] += 1
        buf_count = len(self._dnd_buffer)
        self._dnd_buffer.clear()
        titles = MultiPlatformNotifier.EVENT_TITLES
        lines = [f"【勿扰时段汇总】{start_s} - {end_s}"]
        for event_type in sorted(by_type.keys()):
            count = by_type[event_type]
            label = titles.get(event_type, event_type)
            if "飞牛NAS-" in label:
                label = label.split("飞牛NAS-", 1)[-1].strip()
            lines.append(f"· {label} {count} 次")
        self.logger.info("勿扰结束，发送汇总消息（共 %s 条事件）", buf_count)
        return "\n".join(lines)

    def flush_dnd_buffer_if_needed(self) -> None:
        """若当前不在勿扰时段且缓冲非空，则汇总为一条消息推送并清空缓冲；再发一条推送结果（成功/失败渠道数）。"""
        if self._in_dnd_window():
            return
        if not self._dnd_buffer:
            return
        summary = self._build_dnd_summary_and_clear()
        if not summary:
            return
        try:
            out = self.multi_platform_notifier.send_system_notification(
                "DND_SUMMARY",
                summary,
                {"hostname": "", "version": ""},
            )
            success = out.get("success", False) if isinstance(out, dict) else bool(out)
            sc = out.get("success_count", 0) if isinstance(out, dict) else 0
            fc = out.get("fail_count", 0) if isinstance(out, dict) else 0
            try:
                from utils.push_stats import record as record_push
                record_push(success)
            except Exception:
                pass
            # 再发一条短消息：勿扰汇总推送结果（成功/失败渠道数）
            result_msg = f"本次汇总推送：成功 {sc} 个渠道，失败 {fc} 个渠道"
            self.multi_platform_notifier.send_system_notification(
                "DND_SUMMARY",
                result_msg,
                {"hostname": "", "version": ""},
            )
        except Exception as e:
            self.logger.warning("勿扰汇总推送失败: %s", e)

    def send_notification(self, 
                         event_type: str,
                         event_data: Dict[str, Any],
                         raw_log: str,
                         timestamp: str) -> NotificationResult:
        """
        发送通知
        
        Args:
            event_type: 事件类型
            event_data: 事件数据
            raw_log: 原始日志
            timestamp: 时间戳
            
        Returns:
            通知发送结果
        """
        if self._in_dnd_window():
            self._dnd_buffer.append({
                "event_type": event_type,
                "timestamp": timestamp,
                "event_data": event_data,
            })
            return NotificationResult(
                success=True,
                method="dnd_buffered",
                details={"event_type": event_type, "buffered": True},
            )
        # 通过多平台通知器发送
        success = self.multi_platform_notifier.send_notification(
            event_type, event_data, raw_log, timestamp
        )
        try:
            from utils.push_stats import record as record_push
            record_push(success)
        except Exception:
            pass
        # 确定实际使用的方法（检查哪些平台真正发送了）
        active_platforms = []
        if self.config.wechat_webhook_url:
            active_platforms.append('wechat')
        if self.config.dingtalk_webhook_url:
            active_platforms.append('dingtalk')
        if self.config.feishu_webhook_url:
            active_platforms.append('feishu')
        if self.config.bark_url:
            active_platforms.append('bark')
        if self.config.pushplus_params:
            active_platforms.append('pushplus')
        
        if len(active_platforms) == 0:
            method = 'none'
        elif len(active_platforms) == 1:
            method = active_platforms[0]
        else:
            method = 'multiple'
        
        return NotificationResult(
            success=success,
            method=method,
            details={
                'platforms': active_platforms,
                'event_type': event_type
            }
        )
    
    def send_system_notification(self, 
                                event_type: str, 
                                message: str, 
                                additional_info: Dict[str, Any] = None) -> NotificationResult:
        """
        发送系统事件通知
        
        Args:
            event_type: 事件类型
            message: 消息内容
            additional_info: 额外信息
            
        Returns:
            通知发送结果
        """
        if self._in_dnd_window():
            return NotificationResult(
                success=True,
                method="dnd_skipped",
                details={"event_type": event_type, "message": message[:50]},
            )
        # 通过多平台通知器发送系统通知（返回 dict: success, success_count, fail_count）
        out = self.multi_platform_notifier.send_system_notification(
            event_type, message, additional_info
        )
        success = out.get("success", False) if isinstance(out, dict) else bool(out)
        try:
            from utils.push_stats import record as record_push
            record_push(success)
        except Exception:
            pass
        
        # 确定实际使用的方法（检查哪些平台真正发送了）
        active_platforms = []
        if self.config.wechat_webhook_url:
            active_platforms.append('wechat')
        if self.config.dingtalk_webhook_url:
            active_platforms.append('dingtalk')
        if self.config.feishu_webhook_url:
            active_platforms.append('feishu')
        if self.config.bark_url:
            active_platforms.append('bark')
        if self.config.pushplus_params:
            active_platforms.append('pushplus')
        
        if len(active_platforms) == 0:
            method = 'none'
        elif len(active_platforms) == 1:
            method = active_platforms[0]
        else:
            method = 'multiple'
        
        return NotificationResult(
            success=success,
            method=method,
            details={
                'platforms': active_platforms,
                'event_type': event_type,
                'message': message
            }
        )
    
    def cleanup_cache(self):
        """清理缓存"""
        if self.multi_platform_notifier:
            self.multi_platform_notifier.cleanup_cache()
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        stats = {
            'has_multi_platform_notifier': self.multi_platform_notifier is not None
        }
        
        if self.multi_platform_notifier:
            stats['multi_platform_notifier'] = self.multi_platform_notifier.get_stats()
        
        return stats

    def get_delivery_health(self) -> Dict[str, Any]:
        """获取通知发送健康状态"""
        if self.multi_platform_notifier:
            return self.multi_platform_notifier.get_delivery_health()
        return {
            'last_attempt_time': None,
            'last_success_time': None,
            'consecutive_failures': 0,
            'first_failure_time': None,
            'total_failures_since_success': 0,
            'active_platforms': {
                'wechat': False,
                'dingtalk': False,
                'feishu': False,
                'bark': False,
                'pushplus': False,
            }
        }
    
    def close(self):
        """关闭通知器"""
        if self.multi_platform_notifier:
            self.multi_platform_notifier.close()
        
        self.logger.info("统一通知器已关闭")
