# Cursor MCP 配置说明

当前 `mcp.json` 已配置以下 MCP 服务器（需已安装 Node.js，首次使用会自动拉取）：

| 名称 | 用途 |
|------|------|
| **google-search** | 实时联网检索，打破模型时效限制 |
| **playwright** | 自动化浏览器（agent-browser），点击、抓取、模拟操作 |
| **sequential-thinking** | 深度逻辑推理，多步推导与自纠 |
| **postgres** | 智能数据库（需改连接串） |
| **filesystem** | 全量文件管理（当前指向本项目目录） |
| **slack** | Slack 群聊/消息代回复（需在 Cursor 里点「连接」授权） |
| **git** | Git 自动化（commit/diff/branch 等，需安装 uv） |

---

## 你需要手动改的两项

1. **postgres**：若不用 PostgreSQL，可删掉该段；若用，把连接串改成你的库：
   - `"postgresql://用户:密码@host:端口/库名"`
2. **filesystem**：若希望允许访问其他目录，把路径改成你要开放的目录（可多写几个 `args` 里的路径）。

---

## Slack 与 Git 使用说明

- **Slack**：保存配置后，在 Cursor 的 **Settings → MCP** 里找到 Slack，点击 **Connect** 完成 Slack 工作区授权。需工作区管理员已批准 MCP 集成。
- **Git**：依赖 [uv](https://docs.astral.sh/uv/)（`curl -LsSf https://astral.sh/uv/install.sh | sh` 或 `brew install uv`）。未装 uv 时 Git MCP 会启动失败，可暂时删掉 `mcp.json` 里的 `git` 段，或改用 Docker：`"command": "docker", "args": ["run", "--rm", "-i", "-v", "/path/to/repos:/repos", "mcp/git"]`。

---

## 其他文章中提到的 MCP（需单独安装）

以下需用 **Cursor 设置 → Features → MCP → Add New MCP Server** 或自行改 `mcp.json` 添加：

- **ios-simulator**：移动端模拟器控制，多来自 Appium 等，可搜 [Cursor Directory - Appium](https://cursor.directory/mcp) 或 [modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers)。
- **Docker**：可用 `uvx mcp-server-docker`（需先装 [uv](https://docs.astral.sh/uv/)），或 Docker 方式见 [ckreiling/mcp-server-docker](https://github.com/ckreiling/mcp-server-docker)。
- **Security（CVE 扫描）**：如 [BoostSecurity](https://github.com/boost-community/boost-mcp) 等，按其仓库说明配置。
- **frontend-design / karen-reviewer / context7 / doc-puller / unit-test-gen**：多为 Cursor Rules 或独立工具，不在标准 MCP 列表，需按文章给出的链接或仓库单独安装。

---

## 使用方式

- 保存 `mcp.json` 后，在 Cursor 中 **重新加载 MCP**（或重启 Cursor）。
- 在 **Composer（Agent）** 里即可使用上述工具；普通聊天窗口不一定可见 MCP 工具。
