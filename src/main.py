
import sys
import signal
import socket
import os
import traceback
from datetime import datetime

# 添加src目录到Python路径，解决模块导入问题
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from utils.logger import setup_logging
from monitor.journal_watcher import JournalWatcher
from monitor.event_processor import EventProcessor
from notifier.unified_notifier import UnifiedNotifier

class Application:
    """主应用程序"""
    
    def __init__(self):
        """初始化应用"""
        self.config = None
        self.notifier = None
        self.event_processor = None
        self.journal_watcher = None
        self.logger = None
        self.running = False

        
    def _print_banner(self):
        """打印启动横幅"""
        banner = f"""
        启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        监控模式: 实时事件驱动 (支持journalctl和syslog)
        通知方式: 企业微信/钉钉/飞书机器人/Bark

        """
        print(banner)
    
    def initialize(self) -> bool:
        """初始化应用组件"""
        try:
            print("开始初始化应用组件...")
            
            # 加载配置
            self.config = Config()
            print(f"配置加载完成: {self.config.wechat_webhook_url[:50]}...")
            
            # 设置日志
            self.logger = setup_logging(self.config)
            print("日志设置完成")
            
            # 打印横幅
            self._print_banner()
            
            # 显示配置信息
            print(f"监控事件: {', '.join(self.config.monitor_events)}")
            print(f"日志级别: {self.config.log_level}")
            print(f"去重窗口: {self.config.dedup_window}秒")
            print(f"连接池大小: {self.config.http_pool_size}")
            
            # 检查Webhook配置
            if self.config.wechat_webhook_url:
                print(f"企业微信Webhook: 已配置")
            if self.config.dingtalk_webhook_url:
                print(f"钉钉Webhook: 已配置")
            if self.config.feishu_webhook_url:
                print(f"飞书Webhook: 已配置")
            
            if not any([self.config.wechat_webhook_url, self.config.dingtalk_webhook_url, self.config.feishu_webhook_url]):
                print("警告: 未配置任何Webhook URL，通知功能将不可用")
            
            # 初始化通知器 - 现在支持多平台
            print("初始化多平台通知器...")
            self.notifier = UnifiedNotifier(self.config)
            print("多平台通知器初始化完成")
            
            # 初始化事件处理器
            print("正在初始化事件处理器...")
            self.event_processor = EventProcessor(self.notifier, self.config)
            print("事件处理器初始化完成")
            
            # 初始化日志监视器
            print("正在初始化日志监视器...")
            self.journal_watcher = JournalWatcher(
                journal_paths=self.config.journal_paths,
                cursor_dir=self.config.cursor_dir,
                eventlogger_log_path=self.config.eventlogger_log_path,
                heartbeat_interval=self.config.heartbeat_interval
            )
            print(f"日志监视器初始化完成（心跳间隔: {self.config.heartbeat_interval}秒）")
            
            # 注册事件处理器
            print("开始注册事件处理器...")
            for event_type in self.config.monitor_events:
                handler = self.event_processor.get_handler(event_type)
                if handler:
                    self.journal_watcher.add_handler(event_type, handler)
                    print(f"✓ 注册事件处理器: {event_type}")
                else:
                    print(f"✗ 未知事件类型: {event_type}")
            
            print(f"\n初始化完成，开始监控...")
            return True
        except Exception as e:
            print(f"初始化失败: {e}")
            traceback.print_exc()
            return False
    
    def _signal_handler(self, signum, frame):
        """信号处理器"""
        print(f"\n接收到信号 {signum}，准备关闭应用...")
        self.running = False
        # 不立即关闭，让应用正常关闭流程
    
    def run(self):
        """运行应用"""
        try:
            if not self.initialize():
                # 发送启动失败通知
                if self.notifier:
                    self.notifier.send_system_notification(
                        'APP_ERROR',
                        '应用初始化失败: 未知错误',
                        {'hostname': socket.gethostname(), 'version': '1.0'}
                    )
                sys.exit(1)
            
            self.running = True
            
            # 发送启动通知
            if self.notifier:
                self.notifier.send_system_notification(
                    'APP_START',
                    '飞牛NAS日志监控系统已启动，开始监控系统事件',
                    {'hostname': socket.gethostname(), 'version': '1.0'}
                )
            
            # 设置信号处理
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)
            
            # 启动监视器
            if self.journal_watcher:
                print("启动日志监视器...")
                self.journal_watcher.start()
            else:
                print("无法启动日志监视器")
            
        except KeyboardInterrupt:
            print("\\n接收到中断信号...")
        except Exception as e:
            print(f"运行时错误: {e}")
            traceback.print_exc()
        finally:
            self.shutdown()
    
    def shutdown(self):
        """关闭应用"""
        print("\n正在关闭应用...")

        # 发送停止通知
        if self.notifier:
            self.notifier.send_system_notification(
                'APP_STOP',
                '飞牛NAS日志监控系统已停止，监控服务暂停',
                {'hostname': socket.gethostname(), 'version': '1.0'}
            )

        # 停止监视器
        if self.journal_watcher:
            self.journal_watcher.stop()

        # 停止运行日志清理线程
        if self.logger and hasattr(self.logger, 'cleanup_stop_flag'):
            print("正在停止运行日志清理线程...")
            self.logger.cleanup_stop_flag.set()

        # 停止原始推送日志清理线程
        if self.event_processor and hasattr(self.event_processor, 'log_storage'):
            print("正在停止原始推送日志清理线程...")
            self.event_processor.log_storage.stop_cleanup_thread()

        # 关闭通知器
        if self.notifier:
            stats = self.notifier.get_stats()
            print("\n运行统计:")
            print(f"  发送请求: {stats.get('request_count', 0)}")
            print(f"  成功通知: {stats.get('success_count', 0)}")
            print(f"  失败通知: {stats.get('error_count', 0)}")

            # success_rate 在连接池中已经是格式化的字符串（例如 "0.0%"）
            success_rate = stats.get('success_rate', '0.0%')
            print(f"  成功率: {success_rate}")

            self.notifier.close()

        print(f"应用已关闭 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


def main():
    """主函数"""
    app = Application()
    app.run()

if __name__ == "__main__":
    main()
