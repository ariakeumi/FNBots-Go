# 飞牛 NAS 日志监控机器人

监控飞牛 NAS 事件日志（数据库 `logger_data.db3` 的 `log` 表），并推送多平台通知。

## 功能特性

- **数据库轮询**：定时轮询 eventlogger 的 SQLite 数据库，仅处理启动后的新记录
- **多平台通知**：企业微信、钉钉、飞书、Bark、PushPlus
- **Web 配置页**：内置配置 UI（默认端口 `18080`），支持 Webhook、事件类型、勿扰、标题前缀、PushPlus 等；保存后热加载，一般无需重启
- **Web 访问控制**：可在页面中设置访问密码（`config.json` 内保存盐值与哈希）；支持关闭密码校验（`web_password_enabled`）
- **智能去重**：时间窗口去重（默认 300 秒）
- **磁盘事件合并**：同类型磁盘唤醒/休眠在时间窗口内合并推送
- **HTTP 连接池**：统一 HTTP 管理与重试
- **勿扰模式**：可设置时段内不推送，结束后汇总为一条消息
- **通知失败自愈**：连续失败达到阈值时可触发进程内重启通知链路（可通过环境变量关闭或调参）
- **Docker 部署**：支持 Docker Compose 一键部署，带健康检查
- **配置热加载**：通过 Web 保存 `config.json` 后自动生效；环境变量仍优先生效且不会被文件覆盖

### 支持的事件类型

以下为 `monitor_events` 中允许配置的 `eventId`（与数据库一致；旧配置里已移除的类型会在启动时被过滤）：

- **登录**：`LoginSucc`, `LoginSucc2FA1`, `LoginFail`, `Logout`
- **硬盘**：`FoundDisk`, `DiskWakeup`, `DiskSpindown`, `DISK_IO_ERR`
- **应用**：`APP_CRASH`, `APP_UPDATE_FAILED`, `APP_START_FAILED_LOCAL_APP_RUN_EXCEPTION`, `APP_AUTO_START_FAILED_DOCKER_NOT_AVAILABLE`, `APP_STARTED`, `APP_STOPPED`, `APP_UPDATED`, `APP_INSTALLED`, `APP_AUTO_STARTED`, `APP_UNINSTALLED`
- **系统**：`CPU_USAGE_ALARM`, `CPU_USAGE_RESTORED`, `CPU_TEMPERATURE_ALARM`
- **UPS**：`UPS_ONBATT`, `UPS_ONBATT_LOWBATT`, `UPS_ONLINE`, `UPS_ENABLE`, `UPS_DISABLE`
- **SSH**：`SSH_INVALID_USER`, `SSH_AUTH_FAILED`, `SSH_LOGIN_SUCCESS`, `SSH_DISCONNECTED`
- **文件与共享**：`ARCHIVING_SUCCESS`, `DeleteFile`, `MovetoTrashbin`, `SHARE_EVENTID_DEL`, `SHARE_EVENTID_PUT`
- **服务开关**：`WEBDAV_ENABLED` / `WEBDAV_DISABLED`, `SAMBA_ENABLED` / `SAMBA_DISABLED`, `DLNA_ENABLED` / `DLNA_DISABLED`, `FTP_ENABLED` / `FTP_DISABLED`, `NFS_ENABLED` / `NFS_DISABLED`
- **防火墙与安全**：`FW_ENABLE`, `FW_DISABLE`, `SECURITY_PORTCHANGED`
- **虚拟机**：`SHUTDOWN_VM`, `STATUS_RUNNING_VM`, `DESTROY_VM`

## 日志存储

- **触发推送的原始数据**写入 `./data/logs`（可配置 `log_dir`），按事件类型与日期分文件；保留天数由 `log_retention_days` 控制。
- **运行日志**：`./data/logs/monitor_YYYYMMDD.log`；应用运行日志保留天数由 `max_log_age` 控制。
- **游标**：`./data/cursor/db_poller_cursor.txt`，记录已处理到的 `log` 表 id。

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

### 1. [配置通知渠道](docs/notification-channels.md)

至少配置一个推送渠道；环境变量与 Web 配置页二选一即可（亦可混用）。各平台图文说明见 **[配置通知渠道](docs/notification-channels.md)**（内含企业微信、钉钉、飞书、Bark、PushPlus 的独立文档入口）。

未配置任何 Webhook / PushPlus 时进程仍可启动，仅提供 Web 配置页；配置完成后自动开始监控与推送。

### 2. 主要配置项（`config/config.json`）

| 项 | 说明 |
| --- | --- |
| `wechat_webhook_url` / `dingtalk_webhook_url` / `feishu_webhook_url` / `bark_url` | 各平台 Webhook 或 Bark URL |
| `pushplus_params` | PushPlus JSON（可多个，`\|` 分隔） |
| `title_prefix` | 推送标题前缀，留空则使用默认「飞牛NAS」 |
| `monitor_events` | 要监控的事件 ID 列表 |
| `log_level` | 日志级别 |
| `log_dir` / `cursor_dir` | 日志与游标目录 |
| `logger_db_path` | SQLite 数据库路径 |
| `logger_poll_interval` | 轮询间隔（秒） |
| `http_pool_size` / `http_retry_count` / `http_timeout` | HTTP 客户端参数 |
| `dedup_window` | 去重时间窗口（秒） |
| `log_retention_days` | 原始推送日志保留天数 |
| `max_log_age` | 应用运行日志 `monitor_*.log` 保留天数 |
| `dnd_enabled` / `dnd_start_time` / `dnd_end_time` | 勿扰开关与时段（HH:MM，可跨日） |
| `web_password_enabled` | 是否要求密码才能访问配置页（默认 true） |

首次在 Web 中设置密码后，会在同文件写入 `web_password_salt`、`web_password_hash`（请勿手工泄露）。

### 3. 常用环境变量

除上述 Webhook 外，还可通过环境变量覆盖（**已设置的环境变量不会被 `config.json` 覆盖**）：

- `LOGGER_DB_PATH`、`LOGGER_POLL_INTERVAL`
- `MONITOR_EVENTS`（逗号分隔）
- `LOG_LEVEL`、`HTTP_POOL_SIZE`、`HTTP_RETRY_COUNT`、`HTTP_TIMEOUT`、`DEDUP_WINDOW`
- `LOG_RETENTION_DAYS`、`MAX_LOG_AGE`
- `UI_PORT`：Web 端口（默认 `18080`）
- `LOGTIME_DISPLAY_OFFSET_SECONDS`：修正日志时间显示（默认 `28800`，即 +8 小时；若显示不准可调整）
- `NOTIFY_RESTART_ENABLED`、`NOTIFY_RESTART_CONSECUTIVE`、`NOTIFY_RESTART_WINDOW`、`NOTIFY_RESTART_COOLDOWN`：通知链路失败重启策略
- `APP_HOME`：自定义应用根目录（影响 `config.json` 解析路径，一般 Docker 内为 `/app`）

### 4. 数据库路径

- 默认：`/usr/trim/var/eventlogger_service/logger_data.db3`
- 覆盖：`LOGGER_DB_PATH=/path/to/logger_data.db3` 或在 `config.json` 中设置 `logger_db_path`
- Docker 需将该文件或所在目录以只读等方式挂载进容器（参见 `docker-compose.yml`）。

### 5. 启动

**依赖**：Python 3.9+（见 `pyproject.toml`）。本地可先安装依赖：`pip install -e .` 或 `pip install -r requirements.txt`（与镜像一致）。

```bash
# Docker Compose（推荐）
docker compose up -d
docker compose logs -f

# 本地（项目根目录）
PYTHONPATH=. LOGGER_DB_PATH=./logger_data.db3 WECHAT_WEBHOOK_URL=xxx python3 src/main.py
```

数据与配置建议持久化挂载：`./data/logs`、`./data/cursor`、`./config`。Compose 已映射 `18080:18080`，浏览器访问 `http://<本机IP>:18080` 打开 Web 配置页。

## 项目结构

```
├── src/
│   ├── monitor/          # 数据库轮询、事件处理、模型
│   ├── notifier/         # 多平台通知、连接池
│   ├── utils/            # 日志、存储、健康检查、推送统计
│   ├── web/              # Web 配置 UI（Flask）
│   ├── config.py
│   └── main.py
├── config/config.json    # 配置文件（可挂载，Web 可写）
├── data/logs             # 运行日志与推送存储
├── data/cursor           # 轮询游标等
├── tools/log_manager.py
├── docs/                 # 文档（notification-channels 与各推送渠道子页）
├── scripts/              # 辅助脚本（如推送历史种子数据等）
├── .github/workflows/    # Docker 多架构 manifest 合并
│   ├── docker-manifest.yml
│   └── merge-manifest.yml
├── Dockerfile
├── docker-compose.yml
├── deploy.sh             # 本地 compose 部署
├── healthcheck.sh        # 容器健康检查
├── publish-amd64.sh      # AMD64 镜像构建与推送
├── publish-arm64.sh      # ARM64 镜像构建与推送
└── pyproject.toml
```

## 故障排除

- **收不到通知**：检查 Webhook / PushPlus、网络与 `docker compose logs`。
- **时间不对**：调整 `LOGTIME_DISPLAY_OFFSET_SECONDS`（默认已为 +8 小时）。
- **重复通知**：调大 `dedup_window`（秒）。
- **Web 配置页打不开**：确认端口映射与防火墙；容器内可设 `UI_PORT` 并与 `ports` 一致。
- **忘记 Web 密码**：在可信环境下编辑 `config.json`，删除 `web_password_salt` 与 `web_password_hash` 后重启，再在页面重新设置密码（或暂时将 `web_password_enabled` 设为 `false`）。

##捐赠

创作不易，为了项目的稳定和可持续发展，欢迎搭建捐赠支持
<table>
  <tr>
    <td><img src="docs/images/wechat_pay.jpg" width="300" alt="图1说明" /></td>
    <td><img src="docs/images/ali_pay.jpg" width="300" alt="图2说明" /></td>
  </tr>
</table>


## 许可证

MIT License
