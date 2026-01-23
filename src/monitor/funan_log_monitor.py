#!/usr/bin/env python3
"""
飞牛NAS系统日志监控脚本

此脚本监控飞牛NAS系统日志，检测特定事件并输出通知信息
"""

import subprocess
import json
import re
import sys
import time
from datetime import datetime


def parse_log_line(line):
    """
    解析日志行，提取所需信息
    """
    # 检测 MAINEVENT 类型日志
    mainevent_match = re.search(r'MAINEVENT:(\{.*\})', line)
    if mainevent_match:
        try:
            event_data = json.loads(mainevent_match.group(1))
            template = event_data.get('template')
            
            if template == 'LoginSucc':
                # 登录成功
                user = event_data.get('user', '未知用户')
                ip = event_data.get('IP', '未知IP')
                via = event_data.get('via', '未知方式')
                timestamp = extract_timestamp(line)
                
                print(f"[登录成功] 用户: {user}, IP: {ip}, 方式: {via}, 时间: {timestamp}")
                return True
                
            elif template == 'LoginSucc2FA1':
                # 登录二次校验
                user = event_data.get('user', '未知用户')
                ip = event_data.get('IP', '未知IP')
                via = event_data.get('via', '未知方式')
                timestamp = extract_timestamp(line)
                
                print(f"[登录二次校验] 用户: {user}, IP: {ip}, 方式: {via}, 时间: {timestamp}")
                return True
                
            elif template == 'Logout':
                # 退出成功
                user = event_data.get('user', '未知用户')
                ip = event_data.get('IP', '未知IP')
                via = event_data.get('via', '未知方式')
                timestamp = extract_timestamp(line)
                
                print(f"[退出登录] 用户: {user}, IP: {ip}, 方式: {via}, 时间: {timestamp}")
                return True
                
            elif template == 'FoundDisk':
                # 发现磁盘
                name = event_data.get('name', '未知设备')
                model = event_data.get('model', '未知型号')
                serial = event_data.get('serial', '未知序列号')
                timestamp = extract_timestamp(line)
                
                print(f"[发现硬盘] 设备名: {name}, 型号: {model}, 序列号: {serial}, 时间: {timestamp}")
                return True
                
        except json.JSONDecodeError:
            pass  # 如果JSON解析失败，继续处理下一行
    
    # 检测 TRIMEVENT 类型日志
    trimevent_match = re.search(r'TRIMEVENT:(\{.*\})', line)
    if trimevent_match:
        try:
            event_data = json.loads(trimevent_match.group(1))
            event_id = event_data.get('eventId')
            
            if event_id == 'APP_CRASH':
                # APP崩溃
                app_data = event_data.get('data', {})
                display_name = app_data.get('DISPLAY_NAME', app_data.get('APP_NAME', '未知应用'))
                timestamp = extract_timestamp(line)
                
                print(f"[错误] 应用: {display_name}, 崩溃异常退出, 时间: {timestamp}")
                return True
                
        except json.JSONDecodeError:
            pass  # 如果JSON解析失败，继续处理下一行
    
    return False


def extract_timestamp(log_line):
    """
    从日志行中提取时间戳
    """
    # 匹配日期时间格式，如: Jan 11 22:58:21
    date_match = re.match(r'^(\w+\s+\d+\s+\d+:\d+:\d+)', log_line)
    if date_match:
        return date_match.group(1)
    
    # 如果没有匹配到，返回当前时间
    return datetime.now().strftime('%b %d %H:%M:%S')


def monitor_logs():
    """
    监控系统日志
    """
    print("开始监控飞牛NAS系统日志...")
    print("监控的事件类型:")
    print("  - 登录成功 (LoginSucc)")
    print("  - 登录二次校验 (LoginSucc2FA1)")
    print("  - 退出登录 (Logout)")
    print("  - 发现硬盘 (FoundDisk)")
    print("  - 应用崩溃 (APP_CRASH)")
    print("=" * 60)
    
    try:
        # 启动 journalctl 命令
        process = subprocess.Popen(
            ['journalctl', '-x', '-o', 'json', '-f'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        
        # 逐行读取日志
        for line in iter(process.stdout.readline, ''):
            if line.strip():
                # 尝试解析为JSON
                try:
                    json_data = json.loads(line.strip())
                    # 获取 MESSAGE 字段
                    message = json_data.get('MESSAGE', '')
                    if message:
                        parse_log_line(message)
                except json.JSONDecodeError:
                    # 如果不是JSON格式，直接解析整行
                    parse_log_line(line.strip())
        
        process.wait()
        
    except KeyboardInterrupt:
        print("\\n监控已停止")
    except FileNotFoundError:
        print("错误: 未找到 journalctl 命令，请确保在 Linux 系统上运行")
    except Exception as e:
        print(f"监控过程中发生错误: {e}")


def test_parsing():
    """
    测试日志解析功能
    """
    print("测试日志解析功能...")
    
    # 测试用例
    test_cases = [
        'Jan 11 22:58:21 LandoNas MAINEVENT[1593]: MAINEVENT:{"cat":3,"template":"LoginSucc","user":"胖头鱼","IP":"192.168.1.10","via":"(via token)","uid":1002}',
        'Jan 11 22:58:21 LandoNas MAINEVENT[1593]: MAINEVENT:{"cat":3,"template":"LoginSucc2FA1","user":"胖头鱼","IP":"192.168.1.10","via":"(via token)","uid":1002}',
        'Jan 11 22:58:21 LandoNas MAINEVENT[1593]: MAINEVENT:{"cat":3,"template":"Logout","user":"胖头鱼","IP":"192.168.1.10","via":"(via token)","uid":1002}',
        'Jan 09 09:49:03 LandoNas MAINEVENT[1593]: MAINEVENT:{"cat":1,"template":"FoundDisk","name":"nvme0n1","model":"SAMSUNG MZVLB256HAHQ-00000","serial":"S444NG0KB00345"}',
        'Jan 09 10:13:49 LandoNas TRIMEVENT[2543]: TRIMEVENT:{"data":{"APP_GROUP":"","APP_ID":57,"APP_NAME":"metube","APP_USERNAME":"","DISPLAY_NAME":"MeTube","INSTALL_VOLUME_ID":0,"META_VOLUME_ID":0,"PORT_USAGE":0},"datetime":1767924829,"eventId":"APP_CRASH","from":"trim.app-center","level":1}'
    ]
    
    for case in test_cases:
        print(f"\\n测试: {case[:50]}...")
        parse_log_line(case)
    
    print("\\n测试完成")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        test_parsing()
    else:
        monitor_logs()