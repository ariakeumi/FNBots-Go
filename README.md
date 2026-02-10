# 飞牛NAS日志监控机器人

飞牛NAS日志监控系统，用于监控飞牛NAS系统日志并发送多平台通知。

## 功能特性

- 📊 **实时日志监控**：持续监控飞牛NAS系统日志事件
- 🔔 **多平台通知**：支持企业微信、钉钉、飞书、Bark等主流通知平台
- 🔄 **智能去重**：基于时间窗口的事件去重机制（默认300秒）
- 💾 **磁盘事件合并**：智能合并相同类型的磁盘事件
- 🛡️ **安全权限管理**：最小化权限设计，提升系统安全性
- 📈 **HTTP连接池**：高效的HTTP连接管理和重试机制
- 🐳 **容器化部署**：支持Docker和Docker Compose一键部署
- 📋 **丰富事件类型**：支持多种系统事件监控：
  - 登录成功 (LoginSucc)
  - 登录失败 (LoginFail)
  - 登录二次校验 (LoginSucc2FA1)
  - 退出登录 (Logout)
  - 发现硬盘 (FoundDisk)
  - 应用崩溃 (APP_CRASH)
  - 应用更新失败 (APP_UPDATE_FAILED)
  - 应用启动失败 (APP_START_FAILED_LOCAL_APP_RUN_EXCEPTION)
  - 应用自启动失败 (APP_AUTO_START_FAILED_DOCKER_NOT_AVAILABLE)
  - CPU使用率告警 (CPU_USAGE_ALARM)
  - CPU温度告警 (CPU_TEMPERATURE_ALARM)
  - UPS切换到电池供电 (UPS_ONBATT)
  - UPS低电量预警 (UPS_ONBATT_LOWBATT)
  - UPS切换到市电供电 (UPS_ONLINE)
  - 磁盘唤醒 (DiskWakeup)
  - 磁盘休眠 (DiskSpindown)
  - SSH服务启动 (SSH_SERVICE_STARTED)
  - SSH服务停止 (SSH_SERVICE_STOPPED)
  - SSH监听端口 (SSH_LISTEN)
  - SSH无效用户尝试 (SSH_INVALID_USER)
  - SSH认证失败 (SSH_AUTH_FAILED)
  - SSH登录成功 (SSH_LOGIN_SUCCESS)
  - SSH会话开启 (SSH_SESSION_OPENED)
  - SSH断开连接 (SSH_DISCONNECTED)
  - SSH会话关闭 (SSH_SESSION_CLOSED)
- 🗃️ **日志存储分析**：自动存储触发通知的原始系统日志，支持后续问题分析和审计
- 🩺 **稳定心跳监控**：syslog 与 eventlogger 采用统一游标式文件跟踪，长时间空闲也不会误判重启

## 新增功能：日志存储与分析

### 功能特点
- **自动存储**：当检测到需要推送的消息时，自动将原始系统日志存储到.log文件
- **完整信息**：存储包括事件类型、时间戳、原始日志内容、处理后的数据等完整信息
- **灵活查询**：支持按事件类型、时间范围等多种方式查询存储的日志
- **数据导出**：支持将日志导出为JSON格式，便于进一步分析
- **定期清理**：支持自动清理过期日志文件，节省存储空间

### 存储结构
日志以JSON格式存储在.log文件中，每个事件类型每天生成一个独立的日志文件：
```
logs/
├── LoginSucc_2026-02-04.log
├── APP_CRASH_2026-02-04.log
└── FoundDisk_2026-02-04.log

每行包含一个JSON对象：
{
    "event_type": "LoginSucc",
    "timestamp": "2026-02-04 22:32:40",
    "raw_log": "原始日志内容",
    "processed_data": {"user": "admin", "IP": "192.168.1.100"},
    "notification_sent": true,
    "stored_at": "2026-02-04 22:32:40",
    "source": "journal"
}
```

### 存储位置
- **默认路径**：`./logs/`
- **文件命名**：`{事件类型}_{日期}.log`（如：LoginSucc_2026-02-04.log）
- **可配置**：通过配置文件或环境变量 `LOG_STORAGE_DIR` 修改存储目录

### 管理工具
提供 `tools/log_manager.py` 脚本用于管理存储的日志：

```
# 查看存储统计信息
python tools/log_manager.py stats

# 查看最近24小时的日志
python tools/log_manager.py recent --hours 24

# 按事件类型查询日志
python tools/log_manager.py type LoginSucc --limit 10

# 导出日志到文件
python tools/log_manager.py export ./logs.json --event-type APP_CRASH

# 清理30天前的旧日志
python tools/log_manager.py cleanup 30
```

### 配置选项
在配置文件中可以设置日志存储目录和保留天数：
```
{
  "log_storage_dir": "./stored_logs",
  "log_retention_days": 30
}
```

或通过环境变量：
```bash
export LOG_STORAGE_DIR="/path/to/storage"
export LOG_RETENTION_DAYS=30
```

**自动清理**：系统会在启动时自动清理超过保留天数的旧日志文件，并每24小时执行一次定期清理

## 使用方法

### 1. 准备通知渠道
在相应平台创建群机器人并获取Webhook地址：
- **企业微信**：群聊 → 群机器人 → 添加机器人
- **钉钉**：群设置 → 智能群助手 → 添加机器人
- **飞书**：群设置 → 群机器人 → 添加机器人
- **Bark**：下载Bark应用获取推送URL

### 2. 配置环境变量
通过系统环境变量或 Docker/Compose 传入，例如：
```
# 至少配置一个通知渠道
WECHAT_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=your-key
# DINGTALK_WEBHOOK_URL=https://oapi.dingtalk.com/robot/send?access_token=your-token
# FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/your-hook
# BARK_URL=https://api.day.app/your-key

# 其他可选配置
MONITOR_EVENTS=LoginSucc,Logout,FoundDisk,APP_CRASH
LOG_LEVEL=INFO
```

### 3. 启动服务
```
# 使用docker-compose启动
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```
> ⚠️ **数据持久化说明**：监控游标和原始日志默认写入 `./data` 目录，请在 Docker/Compose 中将该目录挂载到宿主机持久化存储（例如 `./data:/app/data`），避免容器重启后重复消费日志。

## 通知示例

### 企业微信/钉钉/飞书推送格式
```
🔐 飞牛NAS-登录成功通知
🕐 2024-01-01 12:00:00
👤 用户名: admin
📍 IP地址: 192.168.1.100
🔑 认证方式: SSH
💡 系统检测到用户登录成功，请确认是否为本人操作。
```

### Bark推送格式
```
标题: 飞牛NAS通知
内容: 用户admin登录成功
```

### 磁盘事件推送
- **磁盘唤醒**：`磁盘唤醒: /dev/sda, /dev/sdb`
- **磁盘休眠**：`磁盘休眠: /dev/sda`
- **发现硬盘**：`发现新硬盘: /dev/sdc`

## 系统要求

### 硬件要求
- CPU: 1核心以上
- 内存: 256MB以上
- 存储: 100MB可用空间

### 系统兼容性
- ✅ 飞牛NAS系统
- ✅ Ubuntu 20.04+
- ✅ Debian 10+
- ✅ CentOS 7+
- ✅ 其他支持systemd的Linux发行版

### 架构支持
- ✅ AMD64 (x86_64)
- ✅ ARM64 (aarch64)
- ✅ ARMv7
- ✅ 支持主流Linux发行版

## 项目结构

```
FNMessageBots/
├── src/                    # 源代码目录
│   ├── monitor/           # 日志监控模块
│   ├── notifier/          # 通知推送模块
│   ├── utils/             # 工具模块
│   ├── config.py          # 配置管理
│   └── main.py            # 主程序入口
├── config/                # 配置文件目录
│   └── config.json        # 主配置文件
├── logs/                  # 日志文件目录（统一存储）
│   ├── monitor_*.log      # 应用程序运行日志
│   ├── LoginSucc_*.log    # 登录成功事件日志
│   └── 其他事件类型日志文件
├── cursor/                # 游标文件目录
├── tools/                 # 管理工具目录
│   └── log_manager.py     # 日志管理工具
├── Dockerfile             # Docker构建文件
├── docker-compose.yml     # Docker编排文件
├── requirements.txt       # Python依赖
└── README.md              # 项目说明文档
```

## 故障排除

### 常见问题

1. **无法发送通知**
   - 检查Webhook URL是否正确
   - 确认网络连接正常
   - 查看容器日志：`docker-compose logs`

2. **无法读取日志**
   - 确认挂载了正确的日志目录
   - 检查文件权限
   - 验证journalctl命令可用性

3. **重复通知问题**
   - 调整DEDUP_WINDOW参数
   - 检查事件去重配置

### 日志查看
```bash
# 查看实时日志
docker-compose logs -f

# 查看最近100行日志
docker-compose logs --tail=100

# 查看特定服务日志
docker-compose logs fn-message-bot
```

## 开发指南

### 本地开发环境
```bash
# 安装依赖
pip install -r requirements.txt

# 运行测试
python test_notifications.py

# 启动开发服务
python src/main.py
```

### 代码结构说明
- `src/monitor/`: 日志监控和事件处理
- `src/notifier/`: 多平台通知推送
- `src/utils/`: 辅助工具和日志管理
- `src/config.py`: 配置加载和验证

## 更新日志

### v1.1.0
- 新增Bark推送支持
- 优化磁盘事件推送格式
- 改进权限配置安全性
- 修复事件去重机制

### v1.0.0
- 支持多平台通知（企业微信/钉钉/飞书）
- 实现事件去重和合并功能
- 添加容器化部署支持
- 重构代码架构

## 许可证

MIT License

## 联系方式

如有问题或建议，请提交Issue或联系维护者。
