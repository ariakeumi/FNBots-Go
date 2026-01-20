# 飞牛NAS日志监控系统

基于事件驱动的飞牛NAS系统日志监控工具，实时检测关键事件并通过企业微信机器人通知。

## ✨ 功能特性

- 🔍 **实时监控**：使用journalctl游标机制，非轮询方式
- 🚨 **事件检测**：监控登录、磁盘发现、应用崩溃等关键事件
- 📱 **微信通知**：通过企业微信机器人发送即时通知
- 🐳 **容器化部署**：支持Docker一键部署
- 🔧 **连接池优化**：HTTP连接复用，提升性能
- 💾 **游标持久化**：重启后从上次位置继续监控
- 🩺 **健康检查**：自动监控和恢复

## 📋 监控事件

| 事件类型 | 说明 | 通知内容 |
|---------|------|----------|
| LoginSucc | 登录成功 | 用户、IP、时间、认证方式 |
| LoginSucc2FA1 | 二次验证登录 | 用户、IP、时间 |
| Logout | 退出登录 | 用户、IP、时间 |
| FoundDisk | 发现新硬盘 | 设备名、型号、序列号 |
| APP_CRASH | 应用崩溃 | 应用名、应用ID |

## 🚀 快速开始

### 1. 克隆项目
```bash
mkdir -p /data/docker/fn-log-monitor
cd /data/docker/fn-log-monitor
```

### 2. 配置环境
```bash
# 复制环境变量模板
cp .env .env

# 编辑.env文件，配置企业微信Webhook
nano .env
```

### 3. 启动服务
```bash
docker-compose up -d
```

### 4. 查看日志
```bash
docker-compose logs -f
```

## ⚙️ 配置说明

### 必需配置
- `WECHAT_WEBHOOK_URL`: 企业微信机器人Webhook地址

### 可选配置
- `MONITOR_EVENTS`: 监控的事件类型，逗号分隔
- `LOG_LEVEL`: 日志级别 (DEBUG/INFO/WARNING/ERROR)
- `HTTP_POOL_SIZE`: HTTP连接池大小
- `DEDUP_WINDOW`: 事件去重时间窗口（秒）

## 🔧 故障排除

### 常见问题

1. **权限问题**
```bash
# 检查journalctl权限
docker exec fn-log-monitor sudo -n journalctl --version
```

2. **Webhook配置错误**
```bash
# 测试Webhook
docker exec fn-log-monitor python -c "
import os, requests
url = os.getenv('WECHAT_WEBHOOK_URL')
print('Webhook配置:', '已设置' if url else '未设置')
"
```

3. **查看详细日志**
```bash
# 查看容器日志
docker-compose logs --tail=100

# 查看应用日志
docker exec fn-log-monitor tail -f /app/logs/monitor.log
```

### 调试模式
```bash
# 以调试模式运行
docker-compose down
LOG_LEVEL=DEBUG docker-compose up
```

## 📊 监控统计

查看运行统计：
```bash
docker exec fn-log-monitor python -c "
from src.monitor.journal_watcher import JournalWatcher
watcher = JournalWatcher()
print('处理事件数:', watcher.get_stats())
"
```

## 🔄 更新维护

### 更新代码
```bash
# 停止服务
docker-compose down

# 拉取最新代码
git pull

# 重新构建
docker-compose build --no-cache
docker-compose up -d
```

### 清理旧数据
```bash
# 清理旧日志（保留7天）
find ./data/logs -name "*.log" -mtime +7 -delete

# 清理游标文件
rm -f ./data/cursor/journal_cursor.txt
```

## 📄 许可证

MIT License

## 🤝 贡献

欢迎提交Issue和Pull Request！# FNMessageBots
