import sys
import signal
import socket
import os
from datetime import datetime

from src.config import Config
from src.utils.logger import setup_logging
from src.monitor.journal_watcher import JournalWatcher
from src.monitor.event_processor import EventProcessor
from src.notifier.wechat_notifier import WeChatNotifier

class Application:
    """主应用程序"""
    
    def __init__(self):
        """初始化应用"""
        self.config = None
        self.notifier = None
        self.event_processor = None
        self.journal_watcher = None
        self.running = False

        
    def _print_banner(self):
        """打印启动横幅"""
        banner = f"""
        启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        监控模式: 实时事件驱动 (支持journalctl和syslog)
        通知方式: 企业微信机器人

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
            setup_logging(self.config)
            print("日志设置完成")
            
            # 打印横幅
            self._print_banner()
            
            # 显示配置信息
            print(f"监控事件: {', '.join(self.config.monitor_events)}")
            print(f"日志级别: {self.config.log_level}")
            print(f"连接池大小: {self.config.http_pool_size}")
            print("-" * 60)
            
            # 初始化通知器
            print("正在初始化通知器...")
            self.notifier = WeChatNotifier(
                webhook_url=self.config.wechat_webhook_url,
                dedup_window=self.config.dedup_window,
                pool_size=self.config.http_pool_size,
                retries=self.config.http_retry_count,
                timeout=self.config.http_timeout
            )
            print("通知器初始化完成")
            
            # 初始化事件处理器
            print("正在初始化事件处理器...")
            self.event_processor = EventProcessor(self.notifier, self.config)
            print("事件处理器初始化完成")
            
            # 初始化日志监视器
            print("正在初始化日志监视器...")
            self.journal_watcher = JournalWatcher(
                journal_paths=self.config.journal_paths,
                cursor_dir=self.config.cursor_dir
            )
            print("日志监视器初始化完成")
            
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
            print(f"初始化失败: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()  # 添加详细错误追踪
            return False
    
    def run(self):
        """运行主程序"""
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
            print("正在发送启动通知...")
            result = self.notifier.send_system_notification(
                'APP_START',
                '飞牛NAS日志监控系统已启动，开始监控系统事件',
                {'hostname': socket.gethostname(), 'version': '1.0'}
            )
            print(f"启动通知发送结果: {result}")
        
        # 设置信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        try:
            # 启动日志监视
            self.journal_watcher.start()
            
        except KeyboardInterrupt:
            print("\n用户中断监控")
        except Exception as e:
            print(f"运行异常: {e}", file=sys.stderr)
            # 发送异常通知
            if self.notifier:
                self.notifier.send_system_notification(
                    'APP_ERROR',
                    f'应用运行时发生异常: {str(e)}',
                    {'hostname': socket.gethostname(), 'version': '1.0'}
                )
        finally:
            self.shutdown()
    
    def _signal_handler(self, signum, frame):
        """信号处理器"""
        print(f"\n收到停止信号 {signum}，正在关闭...")
        self.running = False
        if self.journal_watcher:
            self.journal_watcher.stop()
    
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