"""
日志配置模块
"""

import logging
import sys
import os
import glob
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import threading
import time

def setup_logging(config) -> logging.Logger:
    """
    设置日志配置
    
    Args:
        config: 配置对象
        
    Returns:
        根日志记录器
    """
    # 创建日志格式
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # 获取根日志记录器
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, config.log_level))
    
    # 清除现有处理器
    logger.handlers.clear()
    
    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(getattr(logging, config.log_level))
    logger.addHandler(console_handler)
    
    # 文件处理器
    # 确保使用项目根目录下的logs目录
    project_root = Path(__file__).parent.parent
    log_file = project_root / "logs" / f"monitor_{datetime.now().strftime('%Y%m%d')}.log"
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)
    file_handler.setLevel(getattr(logging, config.log_level))
    logger.addHandler(file_handler)
    
    # 设置第三方库日志级别
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('requests').setLevel(logging.WARNING)
    
    # 启动日志清理线程
    start_log_cleanup_thread(config)
    
    return logger

def cleanup_old_logs(log_dir: str, max_age_days: int = 7):
    """
    清理旧的日志文件
    
    Args:
        log_dir: 日志目录
        max_age_days: 保留日志的最大天数
    """
    log_path = Path(log_dir)
    if not log_path.exists():
        return
    
    cutoff_date = datetime.now() - timedelta(days=max_age_days)
    
    # 查找所有匹配的日志文件
    log_files = list(log_path.glob("monitor_*.log"))
    
    for log_file in log_files:
        try:
            # 从文件名提取日期 (monitor_YYYYMMDD.log)
            filename = log_file.name
            if filename.startswith("monitor_") and filename.endswith(".log"):
                date_str = filename.replace("monitor_", "").replace(".log", "")
                if len(date_str) == 8:  # YYYYMMDD
                    file_date = datetime.strptime(date_str, "%Y%m%d")
                    if file_date < cutoff_date:
                        log_file.unlink()  # 删除文件
                        print(f"已删除旧日志文件: {log_file}")
        except (ValueError, OSError) as e:
            print(f"处理日志文件时出错 {log_file}: {e}")

def start_log_cleanup_thread(config):
    """
    启动日志清理线程
    
    Args:
        config: 配置对象
    """
    def cleanup_loop():
        while True:
            try:
                cleanup_old_logs(config.log_dir, config.max_log_age)
                # 每24小时运行一次清理
                time.sleep(24 * 3600)
            except Exception as e:
                print(f"日志清理线程出错: {e}")
                # 即使出错也继续运行
                time.sleep(3600)  # 一小时后再试
    
    # 启动后台清理线程
    cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True)
    cleanup_thread.start()

def get_logger(name: str) -> logging.Logger:
    """
    获取指定名称的日志记录器
    
    Args:
        name: 记录器名称
        
    Returns:
        日志记录器实例
    """
    return logging.getLogger(name)