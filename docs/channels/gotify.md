# Gotify

[← 返回通知渠道总览](../notification-channels.md)

项目支持通过 Gotify HTTP API 推送通知。

## 配置方式

在 Web 配置页新增一条 `Gotify` 渠道，或在 `config/config.json` 中填写：

```json
{
  "gotify_url": "http://127.0.0.1:8008/message?token=你的应用Token"
}
```

也可以通过环境变量：

```bash
GOTIFY_URL=http://127.0.0.1:8008/message?token=你的应用Token
```

如果需要同时推送到多个 Gotify 应用，可使用 `|` 分隔多个地址：

```json
{
  "gotify_url": "http://127.0.0.1:8008/message?token=tokenA|http://127.0.0.1:8008/message?token=tokenB"
}
```

## 地址格式

请填写 Gotify 消息接口完整地址，格式通常为：

```text
http://你的Gotify地址/message?token=应用Token
```

应用 Token 可在 Gotify Web 界面的应用设置中获取。更多说明见 Gotify 官方文档：

- [Gotify Push message examples](https://gotify.net/docs/more-pushmsg)
