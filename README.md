# 飞牛NAS日志监控机器人

飞牛NAS日志监控系统，用于监控飞牛NAS系统日志并发送企业微信、钉钉或飞书通知。

## 功能特性

- 监控飞牛NAS系统日志事件
- 支持多种事件类型：
  - 登录成功 (LoginSucc)
  - 登录二次校验 (LoginSucc2FA1)
  - 退出登录 (Logout)
  - 发现硬盘 (FoundDisk)
  - 应用崩溃 (APP_CRASH)
  - 应用更新失败 (APP_UPDATE_FAILED)
  - UPS切换到电池供电 (UPS_ONBATT)
  - UPS低电量预警 (UPS_ONBATT_LOWBATT)
  - UPS切换到市电供电 (UPS_ONLINE)
  - 磁盘唤醒 (DiskWakeup)
  - 磁盘休眠 (DiskSpindown)
- 支持企业微信、钉钉、飞书机器人通知
- 事件去重机制
- 磁盘事件合并功能

## 部署方式

### Docker Compose 部署

```yaml
services:
  fn-message-bot:
    image: sunanang/fn-message-bots:latest  # 使用预构建镜像
    container_name: fn-message-bot
    restart: unless-stopped
    network_mode: host
    privileged: true
    pid: host

    # 挂载系统日志目录（关键配置）
    volumes:
      # journal二进制日志（如果存在）
      - /var/log/journal:/var/log/journal:ro
      - /run/log/journal:/run/log/journal:ro
      # 文本日志（可选）
      - /var/log/syslog:/var/log/syslog:ro
      # 应用数据目录
      - ./data/logs:/app/logs:rw
      - ./data/cursor:/tmp/cursor:rw
      # 配置文件目录
      - ./config:/app/config:ro

    # 环境变量配置
    environment:
      # 企业微信Webhook URL (可选)
      - WECHAT_WEBHOOK_URL=${WECHAT_WEBHOOK_URL}
      # 钉钉Webhook URL (可选)
      - DINGTALK_WEBHOOK_URL=${DINGTALK_WEBHOOK_URL}
      # 飞书Webhook URL (可选)
      - FEISHU_WEBHOOK_URL=${FEISHU_WEBHOOK_URL}
      # Bark推送URL (可选)
      - BARK_URL=${BARK_URL}
      - TZ=Asia/Shanghai

    cap_add:
      - SYS_ADMIN
      - DAC_READ_SEARCH
      - SYS_PTRACE
      - AUDIT_READ
      - AUDIT_READ
```

### 环境变量说明

- `WEBHOOK_URL`: 企业微信机器人的Webhook地址（可选）
- `DINGTALK_WEBHOOK_URL`: 钉钉机器人的Webhook地址（可选）
- `FEISHU_WEBHOOK_URL`: 飞书机器人的Webhook地址（可选）
- `BARK_URL`: Bark推送URL（可选）
- `MONITOR_EVENTS`: 要监控的事件类型列表，逗号分隔（可选）
- `LOG_LEVEL`: 日志级别，可选值：DEBUG, INFO, WARNING, ERROR（默认INFO）
- `DEDUP_WINDOW`: 事件去重时间窗口（秒）（默认300）
- `HTTP_POOL_SIZE`: HTTP连接池大小（默认10）
- `HTTP_RETRY_COUNT`: HTTP请求重试次数（默认3）
- `HTTP_TIMEOUT`: HTTP请求超时时间（秒）（默认10）

## 使用说明

1. 在企业微信、钉钉或飞书中创建群机器人，获取Webhook地址
2. 配置环境变量 `WEBHOOK_URL`（企业微信）、`DINGTALK_WEBHOOK_URL`（钉钉）或`FEISHU_WEBHOOK_URL`（飞书）
3. 启动容器，系统将自动监控飞牛NAS日志并发送通知

## 通知示例

- 登录成功：`🔐 登录成功通知`
- 登录二次校验：`🔐 二次验证登录`
- 退出登录：`👋 退出登录通知`
- 发现硬盘：`💾 发现新硬盘`
- 应用崩溃：`💥 应用崩溃告警`
- 应用更新失败：`💥 应用更新失败告警`
- UPS切换到电池供电：`🔋 UPS电池供电告警`
- UPS切换到市电供电：`🔌 UPS市电供电通知`
- 磁盘唤醒：`🔐 磁盘唤醒事件`
- 磁盘休眠：`🔒 磁盘休眠事件`

## 架构支持

支持 AMD64 和 ARM64 架构。

## 许可证

MIT License