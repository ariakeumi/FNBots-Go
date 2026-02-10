"""
统一通知器
根据配置决定使用企业微信webhook、钉钉或飞书进行消息推送
"""

import logging
from typing import Dict, Any
from dataclasses import dataclass

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
        
        # 根据配置初始化多平台通知器
        self.multi_platform_notifier = MultiPlatformNotifier(
            wechat_webhook_url=config.wechat_webhook_url,
            dingtalk_webhook_url=config.dingtalk_webhook_url,
            feishu_webhook_url=config.feishu_webhook_url,
            bark_url=config.bark_url,
            dedup_window=config.dedup_window,
            pool_size=config.http_pool_size,
            retries=config.http_retry_count,
            timeout=config.http_timeout
        )
        self.logger.info("多平台通知器已初始化")
    
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
        # 通过多平台通知器发送
        success = self.multi_platform_notifier.send_notification(
            event_type, event_data, raw_log, timestamp
        )
        
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
        # 通过多平台通知器发送系统通知
        success = self.multi_platform_notifier.send_system_notification(
            event_type, message, additional_info
        )
        
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
    
    def close(self):
        """关闭通知器"""
        if self.multi_platform_notifier:
            self.multi_platform_notifier.close()
        
        self.logger.info("统一通知器已关闭")
