# 飞牛NAS日志监控系统

基于事件驱动的飞牛NAS系统日志监控工具，实时检测关键事件并通过企业微信机器人通知。

## 📋 监控事件

| 事件类型 | 说明 | 通知内容 |
|---------|------|----------|
| LoginSucc | 登录成功 | 用户、IP、时间、认证方式 |
| LoginSucc2FA1 | 二次验证登录 | 用户、IP、时间 |
| Logout | 退出登录 | 用户、IP、时间 |
| FoundDisk | 发现新硬盘 | 设备名、型号、序列号 |
| APP_CRASH | 应用崩溃 | 应用名、应用ID |

## 配置说明

| 参数 | 默认值 | 说明 |
|---------|--------|------|

| `WECHAT_WEBHOOK_URL` | 无 | 【必需】企业微信机器人 Webhook 地址 |
| `MONITOR_EVENTS` | `LoginSucc,LoginSucc2FA1,Logout,FoundDisk,APP_CRASH` | 【可选】监控事件类型，逗号分隔 |
| `LOG_LEVEL` | `INFO` | 【可选】日志级别 |
| `HTTP_POOL_SIZE` | `10` | 【可选】HTTP 连接池大小 |
| `HTTP_RETRY_COUNT` | `3` | 【可选】HTTP 请求重试次数 |
| `HTTP_TIMEOUT` | `10` | 【可选】HTTP 请求超时时间（秒） |
| `DEDUP_WINDOW` | `300` | 【可选】去重窗口时间（秒） |
| `HEARTBEAT_INTERVAL` | `30` | 【可选】心跳检测间隔（秒） |
| `FILE_CHECK_INTERVAL` | `60` | 【可选】文件检查间隔（秒） |
| `MAX_LOG_AGE` | `7` | 【可选】最大日志保存天数 |



## 1.0开发完成，基本功能实现