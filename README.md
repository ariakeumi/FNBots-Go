# 飞牛NAS日志监控机器人

飞牛NAS日志监控系统，用于监控飞牛NAS系统日志并发送多平台通知。

## 功能特性

- 监控飞牛NAS系统日志事件
- 支持多种事件类型：
  - 登录成功 (LoginSucc)
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
- 支持多平台通知：企业微信、钉钉、飞书、Bark
- 事件去重机制（默认300秒窗口）
- 磁盘事件智能合并功能
- HTTP连接池管理和重试机制
- 容器化部署支持

## 部署方式

### Docker Compose 部署（推荐）

```yaml
services:
  fn-message-bot:
    image: sunanang/fn-message-bots:latest
    container_name: fn-message-bot
    restart: unless-stopped
    network_mode: host
    privileged: true
    pid: host

    volumes:
      - /var/log/journal:/var/log/journal:ro
      - /run/log/journal:/run/log/journal:ro
      - /var/log/syslog:/var/log/syslog:ro
      - ./data/logs:/app/logs:rw
      - ./data/cursor:/tmp/cursor:rw
      - ./config:/app/config:ro

    environment:
      # 通知渠道配置（至少配置一个）
      - WECHAT_WEBHOOK_URL=${WECHAT_WEBHOOK_URL}
      - DINGTALK_WEBHOOK_URL=${DINGTALK_WEBHOOK_URL}
      - FEISHU_WEBHOOK_URL=${FEISHU_WEBHOOK_URL}
      - BARK_URL=${BARK_URL}
      
      # 监控配置
      - MONITOR_EVENTS=LoginSucc,LoginSucc2FA1,Logout,FoundDisk,APP_CRASH,APP_UPDATE_FAILED,UPS_ONBATT_LOWBATT,UPS_ONLINE,DiskWakeup,DiskSpindown
      - LOG_LEVEL=INFO
      - DEDUP_WINDOW=300
      
      # HTTP配置
      - HTTP_POOL_SIZE=10
      - HTTP_RETRY_COUNT=3
      - HTTP_TIMEOUT=10
      
      - TZ=Asia/Shanghai

    cap_add:
      - SYS_ADMIN
      - DAC_READ_SEARCH
      - SYS_PTRACE
      - AUDIT_READ
```

### 环境变量说明

| 变量名 | 说明 | 默认值 | 必需 |
|--------|------|--------|------|
| WECHAT_WEBHOOK_URL | 企业微信机器人Webhook地址 | 无 | 否 |
| DINGTALK_WEBHOOK_URL | 钉钉机器人Webhook地址 | 无 | 否 |
| FEISHU_WEBHOOK_URL | 飞书机器人Webhook地址 | 无 | 否 |
| BARK_URL | Bark推送URL | 无 | 否 |
| MONITOR_EVENTS | 监控事件类型列表 | 全部事件 | 否 |
| LOG_LEVEL | 日志级别 | INFO | 否 |
| DEDUP_WINDOW | 事件去重时间窗口(秒) | 300 | 否 |
| HTTP_POOL_SIZE | HTTP连接池大小 | 10 | 否 |
| HTTP_RETRY_COUNT | HTTP请求重试次数 | 3 | 否 |
| HTTP_TIMEOUT | HTTP请求超时时间(秒) | 10 | 否 |

> ⚠️ **注意**：至少需要配置一个通知渠道（WECHAT_WEBHOOK_URL、DINGTALK_WEBHOOK_URL、FEISHU_WEBHOOK_URL或BARK_URL）

## 配置文件

### config/config.json 示例

```json
{
  "wechat_webhook_url": "${WECHAT_WEBHOOK_URL}",
  "dingtalk_webhook_url": "${DINGTALK_WEBHOOK_URL}",
  "feishu_webhook_url": "${FEISHU_WEBHOOK_URL}",
  "bark_url": "${BARK_URL}",
  "monitor_events": [
    "LoginSucc",
    "LoginSucc2FA1", 
    "Logout",
    "FoundDisk",
    "APP_CRASH",
    "APP_UPDATE_FAILED",
    "APP_START_FAILED_LOCAL_APP_RUN_EXCEPTION",
    "APP_AUTO_START_FAILED_DOCKER_NOT_AVAILABLE",
    "CPU_USAGE_ALARM",
    "CPU_TEMPERATURE_ALARM",
    "UPS_ONBATT",
    "UPS_ONBATT_LOWBATT",
    "UPS_ONLINE",
    "DiskWakeup",
    "DiskSpindown"
  ],
  "log_level": "INFO",
  "http_pool_size": 10,
  "http_retry_count": 3,
  "http_timeout": 10,
  "dedup_window": 300,
  "journal_paths": [
    "/var/log/journal",
    "/run/log/journal"
  ],
  "cursor_dir": "./cursor",
  "heartbeat_interval": 30,
  "file_check_interval": 60,
  "max_log_age": 7
}
```

## 使用说明

### 1. 准备通知渠道
在相应平台创建群机器人并获取Webhook地址：
- **企业微信**：群聊 → 群机器人 → 添加机器人
- **钉钉**：群设置 → 智能群助手 → 添加机器人
- **飞书**：群设置 → 群机器人 → 添加机器人
- **Bark**：下载Bark应用获取推送URL

### 2. 配置环境变量
创建 `.env` 文件：
```bash
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
```bash
# 使用docker-compose启动
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```

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

## 架构支持

- ✅ AMD64 (x86_64)
- ✅ ARM64 (aarch64)
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
├── data/                  # 数据目录
│   ├── logs/              # 日志文件
│   └── cursor/            # 游标文件
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