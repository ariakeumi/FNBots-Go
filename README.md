# 飞牛NAS日志监控机器人

监控飞牛NAS事件日志（数据库 `logger_data.db3` 的 log 表），并推送多平台通知。

## 功能特性

- 📊 **数据库轮询**：定时轮询 eventlogger 的 SQLite 数据库，仅处理启动后的新记录
- 🔔 **多平台通知**：企业微信、钉钉、飞书、Bark、PushPlus
- 🌐 **Web 配置页**：内置配置 UI（端口 18080），支持 Webhook、事件类型、勿扰等配置，保存后热加载无需重启
- 🔄 **智能去重**：时间窗口去重（默认 300 秒）
- 💾 **磁盘事件合并**：同类型磁盘唤醒/休眠在时间窗口内合并推送
- 📈 **HTTP 连接池**：统一 HTTP 管理与重试
- 🌙 **勿扰模式**：可设置时段内不推送，结束后汇总为一条消息
- 🐳 **Docker 部署**：支持 Docker Compose 一键部署，带健康检查
- 🔁 **配置热加载**：通过 Web 保存配置后自动生效，无需重启容器

### 支持的事件类型

- 登录：LoginSucc, LoginSucc2FA1, LoginFail, Logout
- 硬盘：FoundDisk, DiskWakeup, DiskSpindown, DISK_IO_ERR
- 应用：APP_CRASH, APP_UPDATE_FAILED, APP_START_FAILED_*, APP_AUTO_START_FAILED_*, APP_STARTED, APP_STOPPED, APP_UPDATED, APP_INSTALLED, APP_AUTO_STARTED, APP_UNINSTALLED
- 系统：CPU_USAGE_ALARM, CPU_USAGE_RESTORED, CPU_TEMPERATURE_ALARM
- UPS：UPS_ONBATT, UPS_ONBATT_LOWBATT, UPS_ONLINE, UPS_ENABLE, UPS_DISABLE
- SSH：SSH_INVALID_USER, SSH_AUTH_FAILED, SSH_LOGIN_SUCCESS, SSH_DISCONNECTED

## 日志存储

- **触发推送的原始数据**会写入 `./data/logs`（可配置 `log_dir`），按事件类型与日期分文件。
- **运行日志**：`./data/logs/monitor_YYYYMMDD.log`。
- **游标**：`./data/cursor/db_poller_cursor.txt`，用于记录已处理到的 log 表 id。

### 管理工具

```bash
# 需在项目根目录，或设置 PYTHONPATH
python tools/log_manager.py stats
python tools/log_manager.py recent --hours 24
python tools/log_manager.py type LoginSucc --limit 10
python tools/log_manager.py export ./logs.json --event-type APP_CRASH
python tools/log_manager.py cleanup 30
```

## 使用方法

### 1. 配置通知渠道

至少配置一个 Webhook，方式二选一：

- **环境变量**（可选）：`WECHAT_WEBHOOK_URL`、`DINGTALK_WEBHOOK_URL`、`FEISHU_WEBHOOK_URL`、`BARK_URL` 等
- **Web 配置页**（推荐）：启动后访问 `http://<本机IP>:端口`（或映射的端口），在页面中填写并保存，保存后自动生效

未配置 Webhook 时容器仍可启动，仅提供 Web 配置页，配置完成后自动开始监控。

### 2. 数据库路径

- 默认：`/usr/trim/var/eventlogger_service/logger_data.db3`
- 覆盖：`LOGGER_DB_PATH=/path/to/logger_data.db3`
- Docker 需挂载该路径（或所在目录）到容器内可读。

### 3. 启动

```bash
# Docker Compose（推荐）
docker compose up -d
docker compose logs -f

# 本地
PYTHONPATH=. LOGGER_DB_PATH=./logger_data.db3 WECHAT_WEBHOOK_URL=xxx python3 src/main.py
```

数据与配置目录建议挂载持久化：`./data/logs`、`./data/cursor`、`./config`。Compose 中已将 `18080:18080` 映射，访问 **http://&lt;本机IP&gt;:端口** 打开 Web 配置页。

## 项目结构

```
├── src/
│   ├── monitor/          # 数据库轮询、事件处理、模型
│   ├── notifier/         # 多平台通知、连接池
│   ├── utils/            # 日志、存储、健康检查
│   ├── web/              # Web 配置 UI（Flask）
│   ├── config.py
│   └── main.py
├── config/config.json    # 配置文件（可挂载，Web 可写）
├── data/logs             # 运行日志与推送存储
├── data/cursor           # 轮询游标
├── tools/log_manager.py
├── .github/workflows/    # Docker 多架构 manifest 合并
│   ├── docker-manifest.yml
│   └── merge-manifest.yml
├── Dockerfile
├── docker-compose.yml
├── deploy.sh             # 本地 compose 部署
├── healthcheck.sh        # 容器健康检查
├── publish-amd64.sh      # AMD64 镜像构建与推送
└── publish-arm64.sh      # ARM64 镜像构建与推送
```

## 故障排除

- **收不到通知**：检查 Webhook、网络与容器日志 `docker compose logs`。
- **时间不对**：可设置 `LOGTIME_DISPLAY_OFFSET_SECONDS=28800`（+8 小时）等偏移。
- **重复通知**：调整配置中的 `dedup_window`（秒）。
- **Web 配置页打不开**：确认端口映射（如 18080）与防火墙，或设置 `UI_PORT`。

## 许可证

MIT License
