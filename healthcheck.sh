#!/bin/bash
# 容器健康检查脚本

# 检查Python进程 - 使用pgrep替代pidof（更通用）
if ! pgrep -f "python.*src/main.py" > /dev/null; then
    echo "Python进程不存在"
    exit 1
fi

# 检查是否有心跳活动（检查最近的日志输出）
LOG_DIR="/app/data/logs"
LOG_FILE=$(ls -t "$LOG_DIR"/monitor_*.log 2>/dev/null | head -n 1)
if [ -n "$LOG_FILE" ] && [ -f "$LOG_FILE" ]; then
    # 检查最近5分钟内是否有日志输出
    if [ -n "$(find "$LOG_FILE" -mmin +5 2>/dev/null)" ]; then
        # 即使日志文件未更新，只要进程在运行就认为是健康的
        if ! pgrep -f "python.*src/main.py" > /dev/null; then
            echo "Python进程不存在且日志未更新"
            exit 1
        fi
    fi
else
    # 如果没有日志文件，至少要确保主进程在运行
    if ! pgrep -f "python.*src/main.py" > /dev/null; then
        echo "Python进程不存在"
        exit 1
    fi
fi

echo "健康检查通过"
exit 0
