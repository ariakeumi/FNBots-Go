import hashlib
import json
import os
import re
import secrets
import socket
import sys
import threading
import time
from pathlib import Path

# 直接运行本文件时（python src/web/ui_app.py），把 src 加入 path 以便导入 notifier 等
if __name__ == "__main__":
    _repo = Path(__file__).resolve().parent.parent.parent
    _src = _repo / "src"
    if _src.exists() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from flask import Flask, jsonify, request, render_template_string

from notifier.multi_platform_notifier import MultiPlatformNotifier

# 配置页密码：会话空闲超时（秒），超时后需重新输入密码
SESSION_IDLE_SECONDS = 300
AUTH_COOKIE_NAME = "fnmb_session"
PBKDF2_ITERATIONS = 100000

# 内存会话：session_id -> {"last_activity": float}
_sessions = {}
_sessions_lock = threading.Lock()


def _hash_password(password: str, salt: bytes) -> str:
    """PBKDF2-HMAC-SHA256，返回 hex。"""
    h = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    return h.hex()


def _verify_password(password: str, salt_hex: str, stored_hash: str) -> bool:
    """验证密码是否与存储的 hash 一致。"""
    try:
        salt = bytes.fromhex(salt_hex)
        got = _hash_password(password, salt)
        return secrets.compare_digest(got, stored_hash)
    except Exception:
        return False


def _get_password_config(raw: dict) -> tuple:
    """返回 (salt_hex, hash_hex)，未设置则 (None, None)。"""
    salt = (raw.get("web_password_salt") or "").strip()
    h = (raw.get("web_password_hash") or "").strip()
    if salt and h:
        return (salt, h)
    return (None, None)


def _has_password_set() -> bool:
    raw = _load_raw_config()
    salt, h = _get_password_config(raw)
    return salt is not None and h is not None


def _create_session() -> str:
    sid = secrets.token_urlsafe(32)
    with _sessions_lock:
        _sessions[sid] = {"last_activity": time.time()}
    return sid


def _get_session_id_from_cookie() -> str:
    return (request.cookies.get(AUTH_COOKIE_NAME) or "").strip()


def _touch_session(session_id: str) -> bool:
    """若会话有效则更新 last_activity 并返回 True。"""
    if not session_id:
        return False
    with _sessions_lock:
        if session_id not in _sessions:
            return False
        last = _sessions[session_id]["last_activity"]
        if time.time() - last > SESSION_IDLE_SECONDS:
            del _sessions[session_id]
            return False
        _sessions[session_id]["last_activity"] = time.time()
        return True


def _is_authenticated() -> bool:
    return _touch_session(_get_session_id_from_cookie())


def _is_password_verification_enabled() -> bool:
    """是否开启密码验证（默认 True）。关闭后不删密码，但访问配置页无需验证。"""
    raw = _load_raw_config()
    return bool(raw.get("web_password_enabled", True))


def _get_base_dir() -> Path:
    """Docker 下用 /app，本地调试用项目根目录（含 config 的目录）。"""
    app_home = os.getenv("APP_HOME")
    if app_home:
        return Path(app_home)
    # 从 src/web/ui_app.py 向上到项目根
    candidate = Path(__file__).resolve().parent.parent.parent
    if (candidate / "config").exists():
        return candidate
    return Path("/app")


BASE_DIR = _get_base_dir()
CONFIG_FILE = BASE_DIR / "config" / "config.json"


def _title_prefix_from_dict(d: dict, key: str = "title_prefix") -> str:
    """从配置或请求体读取标题前缀：键不存在时默认「飞牛NAS」；键存在且为字符串时可留空。"""
    if key not in d:
        return "飞牛NAS"
    v = d[key]
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    return str(v).strip()


def _load_raw_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            # 如果配置损坏，回退到空配置，避免 UI 崩溃
            return {}
    return {}


def _save_raw_config(data: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _split_urls(raw: str):
    if not raw:
        return []
    return [u.strip() for u in str(raw).split("|") if u.strip()]


def _join_urls(urls):
    clean = [u.strip() for u in urls if u and u.strip()]
    return "|".join(clean)


# 事件分类（顺序即展示顺序）；不在此处的事件不会在 UI 中展示
EVENT_CATEGORIES = [
    ("login", "登录与认证", ["LoginSucc", "LoginSucc2FA1", "LoginFail", "Logout"]),
    ("ssh", "SSH", ["SSH_INVALID_USER", "SSH_AUTH_FAILED", "SSH_LOGIN_SUCCESS", "SSH_DISCONNECTED"]),
    ("security", "安全", [
        "FW_ENABLE", "FW_DISABLE", "SECURITY_PORTCHANGED",
    ]),
    ("hardware", "硬件与告警", ["CPU_USAGE_ALARM", "CPU_USAGE_RESTORED", "CPU_TEMPERATURE_ALARM"]),
    ("disk", "磁盘与存储", ["FoundDisk", "DiskWakeup", "DiskSpindown", "DISK_IO_ERR"]),
    ("ups", "UPS", ["UPS_ENABLE", "UPS_DISABLE", "UPS_ONBATT", "UPS_ONBATT_LOWBATT", "UPS_ONLINE"]),
    ("share_protocol", "共享协议", [
        "WEBDAV_ENABLED", "WEBDAV_DISABLED", "SAMBA_ENABLED", "SAMBA_DISABLED",
        "DLNA_ENABLED", "DLNA_DISABLED", "FTP_ENABLED", "FTP_DISABLED", "NFS_ENABLED", "NFS_DISABLED",
    ]),
    ("app_manage", "应用管理", [
        "APP_CRASH", "APP_UPDATE_FAILED",
        "APP_START_FAILED_LOCAL_APP_RUN_EXCEPTION",
        "APP_AUTO_START_FAILED_DOCKER_NOT_AVAILABLE",
        "APP_STARTED", "APP_STOPPED", "APP_UPDATED",
        "APP_INSTALLED", "APP_AUTO_STARTED", "APP_UNINSTALLED",
    ]),
    ("file_ops", "文件操作", [
        "ARCHIVING_SUCCESS", "DeleteFile", "MovetoTrashbin", "SHARE_EVENTID_DEL", "SHARE_EVENTID_PUT",
    ]),
    ("vm", "虚拟机", [
        "STATUS_RUNNING_VM", "SHUTDOWN_VM", "DESTROY_VM",
    ]),
]
# 不在 UI 中提供选择（内部使用的系统事件）
EVENT_IDS_HIDDEN_IN_UI = {"APP_START", "APP_STOP"}

# 应用生命周期事件（默认不勾选）
APP_LIFECYCLE_EVENTS = {
    "APP_STARTED",
    "APP_STOPPED",
    "APP_UPDATED",
    "APP_INSTALLED",
    "APP_AUTO_STARTED",
    "APP_UNINSTALLED",
}

# 后端认可的事件 ID（与 config.Config 校验一致，保存时只保留此集合内的项）
VALID_EVENT_IDS = frozenset({
    "LoginSucc", "LoginSucc2FA1", "LoginFail", "Logout", "FoundDisk",
    "SSH_INVALID_USER", "SSH_AUTH_FAILED", "SSH_LOGIN_SUCCESS", "SSH_DISCONNECTED",
    "APP_CRASH", "APP_UPDATE_FAILED", "APP_START_FAILED_LOCAL_APP_RUN_EXCEPTION",
    "APP_AUTO_START_FAILED_DOCKER_NOT_AVAILABLE",
    "APP_STARTED", "APP_STOPPED", "APP_UPDATED", "APP_INSTALLED", "APP_AUTO_STARTED", "APP_UNINSTALLED",
    "CPU_USAGE_ALARM", "CPU_USAGE_RESTORED", "CPU_TEMPERATURE_ALARM",
    "UPS_ONBATT", "UPS_ONBATT_LOWBATT", "UPS_ONLINE", "UPS_ENABLE", "UPS_DISABLE",
    "DiskWakeup", "DiskSpindown", "DISK_IO_ERR",
    "ARCHIVING_SUCCESS", "DeleteFile", "MovetoTrashbin", "SHARE_EVENTID_DEL", "SHARE_EVENTID_PUT",
    "WEBDAV_ENABLED", "WEBDAV_DISABLED", "SAMBA_ENABLED", "SAMBA_DISABLED",
    "DLNA_ENABLED", "DLNA_DISABLED", "FTP_ENABLED", "FTP_DISABLED", "NFS_ENABLED", "NFS_DISABLED",
    "FW_ENABLE", "FW_DISABLE", "SECURITY_PORTCHANGED",
    "SHUTDOWN_VM", "STATUS_RUNNING_VM", "DESTROY_VM",
})

# 默认勾选的事件（不含应用生命周期 6 项；应用启动/自启动失败、UPS 开启/关闭 默认不勾选）
DEFAULT_SELECTED_EVENTS = [
    "LoginSucc",
    "LoginSucc2FA1",
    "LoginFail",
    "Logout",
    "FoundDisk",
    "APP_CRASH",
    "APP_UPDATE_FAILED",
    "CPU_USAGE_ALARM",
    "CPU_USAGE_RESTORED",
    "CPU_TEMPERATURE_ALARM",
    "UPS_ONBATT",
    "UPS_ONBATT_LOWBATT",
    "UPS_ONLINE",
    "DiskWakeup",
    "DiskSpindown",
    "SSH_INVALID_USER",
    "SSH_AUTH_FAILED",
    "SSH_LOGIN_SUCCESS",
    "SSH_DISCONNECTED",
    "DISK_IO_ERR",
]

# 旧版默认勾选（含应用启动失败、自启动失败、UPS 开启/关闭），用于迁移：若当前配置等于此集合则改为新默认
OLD_DEFAULT_SELECTED_EVENTS_WITH_EXTRA = {
    "APP_START_FAILED_LOCAL_APP_RUN_EXCEPTION",
    "APP_AUTO_START_FAILED_DOCKER_NOT_AVAILABLE",
    "UPS_ENABLE",
    "UPS_DISABLE",
}


def create_app(on_config_saved=None) -> Flask:
    """创建 Flask 应用。on_config_saved: 保存配置成功后的回调（用于热加载，无需重启）。"""
    app = Flask(__name__)

    from notifier.multi_platform_notifier import MultiPlatformNotifier

    titles = MultiPlatformNotifier.EVENT_TITLES
    notes = MultiPlatformNotifier.EVENT_NOTES
    # 按分类构造事件列表，并排除 APP_START、APP_STOP
    events_by_category = []
    for cat_id, cat_name, event_ids in EVENT_CATEGORIES:
        events = []
        for key in event_ids:
            if key in EVENT_IDS_HIDDEN_IN_UI or key not in titles:
                continue
            # UI 里事件选择标题不展示“飞牛NAS”前缀：因为前缀已在下方“事件标题前缀”配置。
            raw_title = titles[key]
            display_title = raw_title.replace("飞牛NAS-", "").replace("飞牛NAS", "")
            display_title = re.sub(r"\s+", " ", display_title).strip()
            events.append({
                "id": key,
                "title": display_title,
                "note": notes.get(key, ""),
            })
        if events:
            events_by_category.append({"id": cat_id, "name": cat_name, "events": events})

    CHANNEL_OPTIONS = [
        {"id": "wechat", "name": "企业微信"},
        {"id": "dingtalk", "name": "钉钉"},
        {"id": "feishu", "name": "飞书"},
        {"id": "bark", "name": "Bark"},
        {"id": "pushplus", "name": "PushPlus"},
    ]

    PROTECTED_PATHS = {"/", "/history", "/api/config", "/api/save-config", "/api/test", "/api/push-stats"}
    PROTECTED_PREFIXES = ("/api/push-history",)

    @app.before_request
    def _require_auth():
        # 首页与 /history 的 GET 始终返回 HTML，由前端根据接口 401 跳转登录
        if request.path == "/":
            return None
        if request.path == "/history" and request.method == "GET":
            return None
        if request.path not in PROTECTED_PATHS and not request.path.startswith(PROTECTED_PREFIXES):
            return None
        if not _has_password_set():
            return None
        if not _is_password_verification_enabled():
            return None
        if _is_authenticated():
            return None
        return jsonify({"ok": False, "message": "未登录或会话已过期，请重新输入密码。"}), 401

    @app.get("/api/auth/status")
    def auth_status():
        """无需登录即可访问。返回是否需要设置密码、是否需要登录、是否已认证。"""
        has_pw = _has_password_set()
        verification_enabled = _is_password_verification_enabled()
        authenticated = _is_authenticated()
        need_setup = not has_pw
        need_login = has_pw and verification_enabled and not authenticated
        return jsonify({
            "ok": True,
            "need_setup": need_setup,
            "need_login": need_login,
            "authenticated": authenticated,
        })

    @app.post("/api/auth/set-password")
    def auth_set_password():
        """首次设置密码（两次输入须一致）。"""
        if _has_password_set():
            return jsonify({"ok": False, "message": "已设置过密码，请使用登录。"}), 400
        payload = request.get_json(force=True, silent=True) or {}
        p1 = (payload.get("password") or "").strip()
        p2 = (payload.get("password_confirm") or "").strip()
        if not p1:
            return jsonify({"ok": False, "message": "请输入密码。"}), 400
        if len(p1) < 6:
            return jsonify({"ok": False, "message": "密码长度至少 6 位。"}), 400
        if p1 != p2:
            return jsonify({"ok": False, "message": "两次输入的密码不一致。"}), 400
        salt = secrets.token_hex(16)
        stored_hash = _hash_password(p1, bytes.fromhex(salt))
        raw = _load_raw_config()
        raw["web_password_salt"] = salt
        raw["web_password_hash"] = stored_hash
        try:
            _save_raw_config(raw)
        except Exception as e:
            return jsonify({"ok": False, "message": f"保存失败：{e}"}), 500
        session_id = _create_session()
        resp = jsonify({"ok": True, "message": "密码设置成功。"})
        resp.set_cookie(
            AUTH_COOKIE_NAME,
            session_id,
            max_age=SESSION_IDLE_SECONDS,
            httponly=True,
            samesite="Lax",
            path="/",
        )
        return resp

    @app.post("/api/auth/login")
    def auth_login():
        """使用密码登录。"""
        if not _has_password_set():
            return jsonify({"ok": False, "message": "尚未设置密码。"}), 400
        payload = request.get_json(force=True, silent=True) or {}
        password = (payload.get("password") or "").strip()
        if not password:
            return jsonify({"ok": False, "message": "请输入密码。"}), 400
        raw = _load_raw_config()
        salt, stored_hash = _get_password_config(raw)
        if not _verify_password(password, salt, stored_hash):
            return jsonify({"ok": False, "message": "密码错误。"}), 401
        session_id = _create_session()
        resp = jsonify({"ok": True, "message": "登录成功。"})
        resp.set_cookie(
            AUTH_COOKIE_NAME,
            session_id,
            max_age=SESSION_IDLE_SECONDS,
            httponly=True,
            samesite="Lax",
            path="/",
        )
        return resp

    @app.get("/api/config")
    def get_config():
        raw = _load_raw_config()

        # 迁移：旧版默认多勾了「应用启动/自启动失败、UPS 开启/关闭」或「应用生命周期」时，改为新默认并回写
        raw_events = raw.get("monitor_events")
        if isinstance(raw_events, list):
            raw_set = set(raw_events)
            new_default_set = set(DEFAULT_SELECTED_EVENTS)
            # 仅当配置恰好为「旧版默认（含启动失败/UPS 开关）」时迁移为新默认；不迁移「全选」（= 新默认+生命周期+额外），否则会覆盖用户的全选
            old_default_with_extra = new_default_set | OLD_DEFAULT_SELECTED_EVENTS_WITH_EXTRA
            old_full_default = new_default_set | APP_LIFECYCLE_EVENTS
            if raw_set == old_default_with_extra:
                raw["monitor_events"] = DEFAULT_SELECTED_EVENTS
                _save_raw_config(raw)
                monitor_events = DEFAULT_SELECTED_EVENTS
            elif raw_set == old_full_default:
                filtered = [e for e in raw_events if e not in APP_LIFECYCLE_EVENTS]
                raw["monitor_events"] = filtered
                _save_raw_config(raw)
                monitor_events = filtered
            else:
                monitor_events = raw_events
        else:
            monitor_events = DEFAULT_SELECTED_EVENTS

        channels = []
        for ch_type, key in [
            ("wechat", "wechat_webhook_url"),
            ("dingtalk", "dingtalk_webhook_url"),
            ("feishu", "feishu_webhook_url"),
            ("bark", "bark_url"),
            ("pushplus", "pushplus_params"),
        ]:
            for url in _split_urls(raw.get(key, "")):
                # 过滤掉模板中的 ${WECHAT_WEBHOOK_URL} 这类占位符
                if url.startswith("${") and url.endswith("}"):
                    continue
                channels.append({"type": ch_type, "url": url})

        data = {
            "title": "FnMessageBots",
            "subtitle": "飞牛日志消息推送机器人",
            "version": "2.0.4",
            "events_by_category": events_by_category,
            "selected_events": monitor_events,
            "channels": channels,
            "title_prefix": _title_prefix_from_dict(raw),
            "log_retention_days": int(raw.get("log_retention_days", raw.get("max_log_age", 7))),
            "logger_poll_interval": int(raw.get("logger_poll_interval", 3)),
            "logger_db_path": raw.get(
                "logger_db_path", "/usr/trim/var/eventlogger_service/logger_data.db3"
            ),
            "dnd_enabled": bool(raw.get("dnd_enabled", False)),
            "dnd_start_time": (raw.get("dnd_start_time") or "22:00").strip(),
            "dnd_end_time": (raw.get("dnd_end_time") or "07:00").strip(),
            "web_password_enabled": bool(raw.get("web_password_enabled", True)),
            "channel_options": CHANNEL_OPTIONS,
        }
        return jsonify({"ok": True, "data": data})

    @app.post("/api/save-config")
    def save_config():
        payload = request.get_json(force=True, silent=True) or {}

        events = payload.get("events") or []
        # 只保留后端认可的事件 ID，避免写入非法值导致热加载或重启异常
        events = [e for e in events if e in VALID_EVENT_IDS]
        channels = payload.get("channels") or []
        log_retention_days = payload.get("log_retention_days", 7)
        logger_poll_interval = payload.get("logger_poll_interval", 3)
        logger_db_path = (payload.get("logger_db_path") or "").strip()
        dnd_enabled = bool(payload.get("dnd_enabled", False))
        dnd_start_time = (payload.get("dnd_start_time") or "22:00").strip()
        dnd_end_time = (payload.get("dnd_end_time") or "07:00").strip()
        web_password_enabled = bool(payload.get("web_password_enabled", True))
        title_prefix = _title_prefix_from_dict(payload)
        if title_prefix and len(title_prefix) > 20:
            return jsonify({"ok": False, "message": "标题前缀过长（最多 20 个字符）。"}), 400

        if dnd_enabled:
            if not dnd_start_time or not dnd_end_time:
                return jsonify({"ok": False, "message": "开启勿扰模式时请填写开始时间和结束时间。"}), 400
            if not re.match(r"^([01]?\d|2[0-3]):[0-5]\d$", dnd_start_time):
                return jsonify({"ok": False, "message": "勿扰开始时间格式不正确，请使用 HH:MM（如 22:00）。"}), 400
            if not re.match(r"^([01]?\d|2[0-3]):[0-5]\d$", dnd_end_time):
                return jsonify({"ok": False, "message": "勿扰结束时间格式不正确，请使用 HH:MM（如 07:00）。"}), 400

        # 不允许选择内部保留事件
        if EVENT_IDS_HIDDEN_IN_UI & set(events):
            return jsonify({"ok": False, "message": "包含不可选的事件类型，请刷新页面重试。"}), 400

        # 基本校验
        if not events:
            return jsonify({"ok": False, "message": "请至少选择一个事件类型。"}), 400

        if not channels:
            return jsonify({"ok": False, "message": "请至少配置一个推送渠道。"}), 400

        for ch in channels:
            ch_type = ch.get("type")
            url = (ch.get("url") or "").strip()
            if ch_type not in {"wechat", "dingtalk", "feishu", "bark", "pushplus"}:
                return jsonify({"ok": False, "message": "存在未知的推送渠道类型。"}), 400
            if not url:
                return jsonify({"ok": False, "message": "推送渠道地址不能为空。"}), 400
            if ch_type == "pushplus":
                try:
                    obj = json.loads(url)
                    if not isinstance(obj, dict) or "token" not in obj:
                        return jsonify({"ok": False, "message": "PushPlus 参数必须是包含 token 的 JSON 对象。"}), 400
                except json.JSONDecodeError as e:
                    return jsonify({"ok": False, "message": f"PushPlus 参数不是合法 JSON：{e}"}), 400
            elif not url.startswith("http"):
                return (
                    jsonify({"ok": False, "message": f"推送地址格式不正确：{url}"}),
                    400,
                )

        if log_retention_days is None:
            log_retention_days = 7
        if logger_poll_interval is None:
            logger_poll_interval = 3
        try:
            log_retention_days = int(log_retention_days)
            logger_poll_interval = int(logger_poll_interval)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "message": "日志缓存天数和轮询时间必须是整数。"}), 400

        if log_retention_days <= 0:
            return jsonify({"ok": False, "message": "日志缓存天数必须大于 0。"}), 400
        if logger_poll_interval <= 0:
            return jsonify({"ok": False, "message": "数据库轮询时间必须大于 0 秒。"}), 400
        if not logger_db_path:
            return jsonify({"ok": False, "message": "数据库地址不能为空。"}), 400

        # 归并渠道为每种类型一个以 '|' 分隔的字符串，兼容现有配置结构
        wechat_urls = []
        dingtalk_urls = []
        feishu_urls = []
        bark_urls = []
        pushplus_urls = []
        for ch in channels:
            ch_type = ch.get("type")
            url = (ch.get("url") or "").strip()
            if ch_type == "wechat":
                wechat_urls.append(url)
            elif ch_type == "dingtalk":
                dingtalk_urls.append(url)
            elif ch_type == "feishu":
                feishu_urls.append(url)
            elif ch_type == "bark":
                bark_urls.append(url)
            elif ch_type == "pushplus":
                pushplus_urls.append(url)

        raw = _load_raw_config()
        raw.update(
            {
                "wechat_webhook_url": _join_urls(wechat_urls),
                "dingtalk_webhook_url": _join_urls(dingtalk_urls),
                "feishu_webhook_url": _join_urls(feishu_urls),
                "bark_url": _join_urls(bark_urls),
                "pushplus_params": _join_urls(pushplus_urls),
                "monitor_events": events,
                "log_retention_days": log_retention_days,
                "logger_poll_interval": logger_poll_interval,
                "logger_db_path": logger_db_path,
                "dnd_enabled": dnd_enabled,
                "dnd_start_time": dnd_start_time,
                "dnd_end_time": dnd_end_time,
                "web_password_enabled": web_password_enabled,
                "title_prefix": title_prefix,
            }
        )

        try:
            _save_raw_config(raw)
        except Exception as e:
            return jsonify({"ok": False, "message": f"配置写入失败（{e}），请检查 config 目录是否可写。"}), 500

        if callable(on_config_saved):
            try:
                on_config_saved()
            except Exception as e:
                return jsonify({"ok": True, "message": f"配置已保存，但热加载失败（{e}），请重启容器后生效。"}), 200

        return jsonify({"ok": True, "message": "配置已保存，监控已热加载生效，无需重启容器。"})

    @app.post("/api/test")
    def test_push():
        try:
            payload = request.get_json(force=True, silent=True) or {}
            content = (payload.get("content") or "").strip()
            if not content:
                return jsonify({"ok": False, "message": "请输入要测试的内容。"}), 400

            raw = _load_raw_config()

            notifier = MultiPlatformNotifier(
                wechat_webhook_url=raw.get("wechat_webhook_url", ""),
                dingtalk_webhook_url=raw.get("dingtalk_webhook_url", ""),
                feishu_webhook_url=raw.get("feishu_webhook_url", ""),
                bark_url=raw.get("bark_url", ""),
                pushplus_params=raw.get("pushplus_params", ""),
                title_prefix=_title_prefix_from_dict(raw),
                dedup_window=int(raw.get("dedup_window", 300)),
                pool_size=int(raw.get("http_pool_size", 10)),
                retries=int(raw.get("http_retry_count", 3)),
                timeout=int(raw.get("http_timeout", 10)),
            )

            out = notifier.send_system_notification(
                "TEST_PUSH",
                content,
                {
                    "hostname": socket.gethostname(),
                    "version": "2.0.4",
                },
            )
            ok = out.get("success", False) if isinstance(out, dict) else bool(out)
            if ok:
                return jsonify({"ok": True, "message": "测试消息已发送，请检查各渠道是否收到。"})
            return jsonify({"ok": False, "message": "所有渠道发送失败，请检查配置。"}), 500
        except Exception as e:
            return jsonify({"ok": False, "message": f"测试发送异常：{e}"}), 500

    @app.get("/api/push-stats")
    def get_push_stats():
        """推送数据汇总：总条数/成功/失败，当日条数/成功/失败（基于 SQLite push_history）。"""
        try:
            from utils import push_history
            if not push_history.get_db_path():
                from utils import push_stats
                raw = _load_raw_config()
                push_stats.init(raw.get("cursor_dir", "./data/cursor"))
            return jsonify({
                "ok": True,
                "data": {
                    "total": push_history.get_total_counts(),
                    "today": push_history.get_today_counts(),
                },
            })
        except Exception:
            return jsonify({
                "ok": True,
                "data": {
                    "total": {"total": 0, "success": 0, "fail": 0},
                    "today": {"total": 0, "success": 0, "fail": 0},
                },
            })

    @app.get("/api/push-history")
    def get_push_history():
        """推送记录列表：分页，可选按成功/失败筛选。"""
        try:
            from utils import push_stats
            from utils import push_history
            if not push_history.get_db_path():
                raw = _load_raw_config()
                push_stats.init(raw.get("cursor_dir", "./data/cursor"))
            limit = min(100, max(1, request.args.get("limit", 50, type=int)))
            offset = max(0, request.args.get("offset", 0, type=int))
            success_param = request.args.get("success")
            success_filter = None
            if success_param is not None:
                if success_param in ("1", "true"):
                    success_filter = True
                elif success_param in ("0", "false"):
                    success_filter = False
            rows = push_history.get_records(limit=limit, offset=offset, success_filter=success_filter)
            return jsonify({"ok": True, "data": rows})
        except Exception as e:
            return jsonify({"ok": False, "message": str(e)}), 500

    @app.get("/api/push-history/<int:record_id>")
    def get_push_history_detail(record_id):
        """单条推送记录详情。"""
        try:
            from utils import push_stats
            from utils import push_history
            if not push_history.get_db_path():
                raw = _load_raw_config()
                push_stats.init(raw.get("cursor_dir", "./data/cursor"))
            row = push_history.get_record(record_id)
            if row is None:
                return jsonify({"ok": False, "message": "记录不存在"}), 404
            if row.get("detail"):
                try:
                    row = dict(row)
                    row["detail"] = json.loads(row["detail"]) if isinstance(row["detail"], str) else row["detail"]
                except Exception:
                    pass
            return jsonify({"ok": True, "data": row})
        except Exception as e:
            return jsonify({"ok": False, "message": str(e)}), 500

    @app.get("/history")
    def history_page():
        """推送记录二级页：列表 + 筛选 + 加载更多 + 查看详情。"""
        return render_template_string("""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <title>推送记录 - FnMessageBots</title>
  <style>
    body { margin: 0; padding: 24px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f3f4f6; color: #111827; }
    h1 { font-size: 20px; margin: 0 0 8px; }
    .page-hint { font-size: 13px; color: #6b7280; line-height: 1.5; margin: 0 0 16px; }
    .toolbar { margin-bottom: 12px; display: flex; gap: 8px; align-items: center; }
    .btn { padding: 6px 12px; font-size: 13px; border-radius: 6px; border: 1px solid #e5e7eb; background: #fff; cursor: pointer; color: #374151; text-decoration: none; }
    .btn:hover { background: #f3f4f6; }
    .filter-btn.active { background: #3b82f6; border-color: #3b82f6; color: #fff; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
    th, td { padding: 10px 12px; border-bottom: 1px solid #e5e7eb; text-align: left; }
    th { background: #f9fafb; font-weight: 600; }
    .result-ok { color: #16a34a; }
    .result-fail { color: #dc2626; }
    .summary { max-width: 320px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .empty { padding: 24px; text-align: center; color: #9ca3af; font-size: 13px; }
    .link { color: #3b82f6; cursor: pointer; }
    .link:hover { text-decoration: underline; }
    .more-wrap { margin-top: 12px; text-align: center; }
    .detail-wrap { margin-top: 20px; padding: 16px; background: #fff; border-radius: 8px; border: 1px solid #e5e7eb; }
    .detail-wrap h2 { font-size: 14px; margin: 0 0 8px; }
    pre { margin: 0; white-space: pre-wrap; word-break: break-all; font-size: 12px; background: #1f2937; color: #e5e7eb; padding: 12px; border-radius: 6px; }
  </style>
</head>
<body>
  <h1>推送记录</h1>
  <p class="page-hint">最多存储一万条数据，超过限制会自动删除。</p>
  <div class="toolbar">
    <a class="btn" href="/">返回配置页</a>
    <span>筛选：</span>
    <button class="btn filter-btn active" data-filter="">全部</button>
    <button class="btn filter-btn" data-filter="true">成功</button>
    <button class="btn filter-btn" data-filter="false">失败</button>
  </div>
  <table>
    <thead><tr><th style="width:160px;">时间</th><th style="width:120px;">事件类型</th><th style="width:60px;">结果</th><th>摘要</th><th>渠道返回结果</th></tr></thead>
    <tbody id="tbody"></tbody>
  </table>
  <div id="empty" class="empty" style="display:none;">暂无推送记录</div>
  <div class="more-wrap"><button id="btn-more" class="btn" style="display:none;">加载更多</button></div>
  <script>
  var fetchOpts = { credentials: "include" };
  var offset = 0;
  var pageSize = 30;
  var currentFilter = "";
  function loadList(reset) {
    if (reset) { offset = 0; document.getElementById("tbody").innerHTML = ""; }
    var params = "limit=" + pageSize + "&offset=" + offset;
    if (currentFilter !== "") params += "&success=" + currentFilter;
    fetch("/api/push-history?" + params, fetchOpts).then(function(r){
      if (r.status === 401) { window.location.href = "/"; return; }
      return r.json();
    }).then(function(json){
      if (!json || !json.ok || !Array.isArray(json.data)) return;
      var rows = json.data;
      var tbody = document.getElementById("tbody");
      var emptyEl = document.getElementById("empty");
      if (rows.length === 0 && offset === 0) { emptyEl.style.display = "block"; } else { emptyEl.style.display = "none"; }
      for (var i = 0; i < rows.length; i++) {
        var r = rows[i];
        var tr = document.createElement("tr");
        var td1 = document.createElement("td"); td1.textContent = r.created_at || ""; tr.appendChild(td1);
        var td2 = document.createElement("td"); td2.textContent = r.event_type || ""; tr.appendChild(td2);
        var td3 = document.createElement("td"); td3.textContent = r.success ? "成功" : "失败"; td3.className = r.success ? "result-ok" : "result-fail"; tr.appendChild(td3);
        var td4 = document.createElement("td"); td4.className = "summary"; td4.textContent = r.summary || "-"; td4.title = r.summary || ""; tr.appendChild(td4);
        var td5 = document.createElement("td"); td5.className = "summary";
        var channelText = "-";
        var channelTitle = "";
        if (r.detail) {
          try {
            var detail = typeof r.detail === "string" ? JSON.parse(r.detail) : r.detail;
            if (detail && Array.isArray(detail.channel_results) && detail.channel_results.length > 0) {
              var parts = [];
              var fullParts = [];
              detail.channel_results.forEach(function(c){
                var status = c.success ? "成功" : "失败";
                var extra = "";
                if (!c.success) {
                  if (c.response != null && typeof c.response === "object") {
                    extra = JSON.stringify(c.response);
                  } else if (typeof c.response === "string") {
                    extra = c.response;
                  }
                  if (!extra && c.error) extra = c.error;
                  if (!extra) extra = "无返回详情";
                }
                var extraShort = extra ? (extra.length > 45 ? extra.slice(0, 45) + "…" : extra) : "";
                var short = c.channel + ": " + status + (extraShort ? " (" + extraShort + ")" : "");
                parts.push(short);
                var fullExtra = extra ? " — " + extra : "";
                fullParts.push(c.channel + ": " + status + fullExtra);
              });
              channelText = parts.join("; ");
              channelTitle = fullParts.join(String.fromCharCode(10));
            }
          } catch (e) {
            channelText = "详情解析失败";
          }
        }
        td5.textContent = channelText;
        td5.title = channelTitle || channelText;
        tr.appendChild(td5);
        tbody.appendChild(tr);
      }
      offset += rows.length;
      document.getElementById("btn-more").style.display = rows.length >= pageSize ? "inline-block" : "none";
    }).catch(function(){});
  }
  document.querySelectorAll(".filter-btn").forEach(function(btn){
    btn.onclick = function(){
      document.querySelectorAll(".filter-btn").forEach(function(b){ b.classList.remove("active"); });
      this.classList.add("active");
      currentFilter = this.getAttribute("data-filter") || "";
      loadList(true);
    };
  });
  document.getElementById("btn-more").onclick = function(){ loadList(false); };
  loadList(true);
  </script>
</body>
</html>""")

    @app.get("/")
    def index():
        # 单页应用，使用简单的原生 JS
        return render_template_string(
            """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <title>FnMessageBots 配置</title>
  <style>
    * { box-sizing: border-box; }
    body {
      margin: 0;
      padding: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "Noto Sans", "PingFang SC", sans-serif;
      background: #eef3ff;
      color: #1f2933;
    }
    .page {
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 32px 16px;
    }
    .card {
      width: 100%;
      max-width: 960px;
      background: rgba(255,255,255,0.9);
      border-radius: 16px;
      box-shadow: 0 18px 40px rgba(15,23,42,0.18);
      padding: 32px 40px 40px;
      border: 1px solid rgba(148,163,184,0.32);
      backdrop-filter: blur(10px);
    }
    .header {
      text-align: center;
      margin-bottom: 28px;
    }
    .header-title {
      font-size: 28px;
      font-weight: 700;
      letter-spacing: 0.06em;
      color: #111827;
      margin-bottom: 6px;
    }
    .header-sub {
      font-size: 14px;
      color: #6b7280;
      margin-bottom: 4px;
    }
    .header-ver {
      font-size: 13px;
      color: #9ca3af;
    }
    .stats-section { margin-bottom: 16px; }
    .stats-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px 20px;
    }
    .stats-block {
      padding: 10px 14px;
      background: #fff;
      border-radius: 10px;
      border: 1px solid #e5e7eb;
    }
    .stats-label {
      font-size: 13px;
      font-weight: 600;
      color: #374151;
      margin-bottom: 6px;
    }
    .stats-row {
      display: flex;
      flex-wrap: wrap;
      gap: 12px 16px;
      font-size: 13px;
      color: #6b7280;
    }
    .stats-row .stats-total { color: #111827; }
    .stats-row .stats-ok { color: #059669; }
    .stats-row .stats-fail { color: #dc2626; }
    .section {
      border-radius: 12px;
      padding: 18px 20px 16px;
      background: #f9fafb;
      border: 1px solid #e5e7eb;
      margin-bottom: 16px;
    }
    .section-title {
      font-size: 15px;
      font-weight: 600;
      margin-bottom: 10px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      color: #111827;
    }
    .section-title span {
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .section-title small {
      font-weight: 400;
      font-size: 12px;
      color: #9ca3af;
    }
    .events-by-category { max-height: 420px; overflow: auto; padding-right: 4px; }
    .event-category { margin-bottom: 22px; }
    .event-category-title {
      font-size: 15px; font-weight: 650; color: #111827;
      margin-bottom: 8px; padding-bottom: 4px;
      border-bottom: 1px solid #e5e7eb;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .events-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
      gap: 10px 14px;
      padding-right: 4px;
    }
    .event-item {
      font-size: 13px;
      display: flex;
      align-items: flex-start;
      gap: 8px;
      color: #374151;
      padding: 10px 12px;
      border-radius: 8px;
      border: 1px solid #e5e7eb;
      background: #fafafa;
      transition: background 0.15s, border-color 0.15s;
    }
    .event-item:hover {
      background: #f3f4f6;
      border-color: #d1d5db;
    }
    .event-item input {
      margin-top: 3px;
      flex-shrink: 0;
    }
    .event-item span {
      line-height: 1.4;
    }
    .event-item .field-helper {
      margin-top: 4px;
      margin-bottom: 0;
    }
    .tag {
      display: inline-flex;
      align-items: center;
      padding: 2px 8px;
      border-radius: 999px;
      font-size: 11px;
      background: #e0f2fe;
      color: #0369a1;
      border: 1px solid #bae6fd;
    }
    .channels-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 8px;
    }
    .add-btn {
      border-radius: 999px;
      border: none;
      background: #2563eb;
      color: #fff;
      font-size: 12px;
      padding: 4px 10px;
      display: inline-flex;
      align-items: center;
      gap: 4px;
      cursor: pointer;
    }
    .add-btn span {
      font-size: 14px;
    }
    .add-btn:hover {
      background: #1d4ed8;
    }
    .channels-table {
      width: 100%;
      border-collapse: collapse;
    }
    .channels-table th,
    .channels-table td {
      padding: 6px 8px;
      font-size: 13px;
      text-align: left;
    }
    .channels-table thead th {
      color: #6b7280;
      font-weight: 500;
      border-bottom: 1px solid #e5e7eb;
    }
    .channels-table tbody tr:not(:last-child) td {
      border-bottom: 1px solid #f3f4f6;
    }
    select,
    input[type="text"],
    input[type="number"],
    textarea {
      width: 100%;
      padding: 7px 9px;
      border-radius: 8px;
      border: 1px solid #d1d5db;
      font-size: 13px;
      outline: none;
      transition: border-color 0.15s, box-shadow 0.15s, background-color 0.15s;
      background-color: #ffffff;
    }
    select:focus,
    input:focus,
    textarea:focus {
      border-color: #2563eb;
      box-shadow: 0 0 0 1px rgba(37,99,235,0.25);
    }
    textarea {
      resize: vertical;
      min-height: 70px;
    }
    .btn {
      min-width: 96px;
      border-radius: 999px;
      padding: 8px 20px;
      border: none;
      font-size: 14px;
      font-weight: 500;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      transition: background-color 0.15s, box-shadow 0.15s, transform 0.05s;
    }
    .btn-primary {
      background: linear-gradient(135deg,#2563eb,#1d4ed8);
      color: #fff;
      box-shadow: 0 12px 22px rgba(37,99,235,0.28);
    }
    .btn-primary:hover {
      background: linear-gradient(135deg,#1d4ed8,#1e40af);
      box-shadow: 0 14px 26px rgba(37,99,235,0.3);
      transform: translateY(-1px);
    }
    .btn-ghost {
      background: #fff;
      color: #111827;
      border: 1px solid #d1d5db;
    }
    .btn-ghost:hover {
      background: #f3f4f6;
    }
    .btn-danger {
      background: #fee2e2;
      color: #b91c1c;
      border-radius: 999px;
      border: none;
      padding: 4px 10px;
      font-size: 12px;
      cursor: pointer;
    }
    .btn-danger:hover {
      background: #fecaca;
    }
    .footer-actions {
      display: flex;
      justify-content: flex-end;
      gap: 10px;
      margin-top: 16px;
    }
    .system-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px 16px;
    }
    .field-label {
      font-size: 13px;
      color: #4b5563;
      margin-bottom: 4px;
    }
    .field-helper {
      font-size: 11px;
      color: #9ca3af;
      margin-top: 2px;
      /* 推送事件副标题：最多展示两行，超出打点省略 */
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }
    .test-section {
      margin-top: 20px;
    }
    .status-bar {
      margin-top: 10px;
      font-size: 12px;
      min-height: 18px;
    }
    .status-bar span {
      padding: 3px 10px;
      border-radius: 999px;
    }
    .status-ok span {
      background: #dcfce7;
      color: #166534;
    }
    .status-error span {
      background: #fee2e2;
      color: #b91c1c;
    }
    .toast-container {
      position: fixed;
      top: 20px;
      left: 50%;
      transform: translateX(-50%);
      z-index: 9999;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 8px;
      pointer-events: none;
    }
    .toast {
      padding: 12px 20px;
      border-radius: 10px;
      font-size: 14px;
      font-weight: 500;
      box-shadow: 0 10px 30px rgba(0,0,0,0.18);
      animation: toast-in 0.25s ease-out;
      pointer-events: auto;
    }
    .toast.toast-ok {
      background: #059669;
      color: #fff;
    }
    .toast.toast-error {
      background: #dc2626;
      color: #fff;
    }
    @keyframes toast-in {
      from {
        opacity: 0;
        transform: translateY(-12px);
      }
      to {
        opacity: 1;
        transform: translateY(0);
      }
    }
    @media (max-width: 768px) {
      .card {
        padding: 24px 18px 24px;
      }
      .system-grid {
        grid-template-columns: 1fr;
      }
      .stats-grid {
        grid-template-columns: 1fr;
      }
    }
    .auth-page {
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 32px 16px;
      background: #eef3ff;
      gap: 16px;
    }
    .auth-card {
      width: 100%;
      max-width: 420px;
      background: rgba(255,255,255,0.95);
      border-radius: 16px;
      box-shadow: 0 18px 40px rgba(15,23,42,0.18);
      padding: 32px 40px;
      border: 1px solid rgba(148,163,184,0.32);
    }
    .auth-title {
      font-size: 20px;
      font-weight: 600;
      color: #111827;
      margin-bottom: 8px;
      text-align: center;
    }
    .auth-sub {
      font-size: 13px;
      color: #6b7280;
      margin-bottom: 20px;
      text-align: center;
    }
    .auth-form .field-label { font-size: 13px; color: #4b5563; margin-bottom: 4px; }
    .auth-form .field-label + input { margin-bottom: 12px; }
    .auth-form .btn-block { width: 100%; margin-top: 16px; }
    .auth-msg {
      font-size: 13px;
      margin-top: 12px;
      min-height: 18px;
      text-align: center;
    }
    .auth-msg.error { color: #b91c1c; }
    .auth-msg.ok { color: #166534; }
    .auth-hint {
      font-size: 12px;
      color: #9ca3af;
      margin-top: 16px;
      text-align: center;
    }
    input[type="password"] {
      width: 100%;
      padding: 7px 9px;
      border-radius: 8px;
      border: 1px solid #d1d5db;
      font-size: 13px;
    }
  </style>
</head>
<body>
  <div id="auth-gate" class="auth-page" style="display:none;">
    <div class="auth-card">
      <div id="auth-set-password" style="display:none;">
        <div class="auth-title">设置访问密码</div>
        <div class="auth-sub">首次使用或已清除密码后，请设置新密码（至少 6 位）</div>
        <form class="auth-form" id="form-set-password">
          <div class="field-label">密码</div>
          <input type="password" id="set-pw-password" placeholder="请输入密码" autocomplete="new-password" />
          <div class="field-label">确认密码</div>
          <input type="password" id="set-pw-confirm" placeholder="请再次输入密码" autocomplete="new-password" />
          <button type="submit" class="btn btn-primary btn-block">确认设置</button>
        </form>
        <div id="auth-set-msg" class="auth-msg"></div>
      </div>
      <div id="auth-login" style="display:none;">
        <div class="auth-title">输入访问密码</div>
        <div class="auth-sub">会话有效期为 5 分钟，关闭页面后若未超时无需重新输入</div>
        <form class="auth-form" id="form-login">
          <div class="field-label">密码</div>
          <input type="password" id="login-password" placeholder="请输入密码" autocomplete="current-password" />
          <button type="submit" class="btn btn-primary btn-block">登录</button>
        </form>
        <div id="auth-login-msg" class="auth-msg"></div>
      </div>
    </div>
  </div>
  <div id="app-main" class="page" style="display:none;">
    <div class="card">
      <div class="header">
        <div class="header-title" id="app-title">FnMessageBots</div>
        <div class="header-sub" id="app-subtitle">飞牛日志消息推送机器人</div>
        <div class="header-ver" id="app-version">2.0.4</div>
      </div>

      <div class="section stats-section">
        <div class="channels-header">
          <div class="section-title">
            <span>推送数据汇总</span>
          </div>
          <button type="button" class="btn btn-ghost" onclick="window.location.href='/history'">查看推送记录</button>
        </div>
        <div class="stats-grid">
          <div class="stats-block">
            <div class="stats-label">总推送</div>
            <div class="stats-row">
              <span class="stats-total">共 <strong id="stat-total-total">0</strong> 条</span>
              <span class="stats-ok">成功 <strong id="stat-total-success">0</strong></span>
              <span class="stats-fail">失败 <strong id="stat-total-fail">0</strong></span>
            </div>
          </div>
          <div class="stats-block">
            <div class="stats-label">当日推送</div>
            <div class="stats-row">
              <span class="stats-total">共 <strong id="stat-today-total">0</strong> 条</span>
              <span class="stats-ok">成功 <strong id="stat-today-success">0</strong></span>
              <span class="stats-fail">失败 <strong id="stat-today-fail">0</strong></span>
            </div>
          </div>
        </div>
      </div>

      <div class="section">
        <div class="section-title">
          <span>事件选择 <small>请选择需要监控并推送的事件</small></span>
        </div>
        <div class="events-by-category" id="events-container"></div>
      </div>

      <div class="section">
        <div class="channels-header">
          <div class="section-title">
            <span>推送渠道 <small>支持为同一渠道配置多个 Webhook</small></span>
          </div>
          <button class="add-btn" type="button" id="add-channel-btn">
            <span>＋</span> 添加渠道
          </button>
        </div>
        <table class="channels-table">
          <thead>
          <tr>
            <th style="width: 120px;">渠道类型</th>
            <th>推送地址（Webhook / Bark URL）或 PushPlus 参数（JSON）</th>
            <th style="width: 64px; text-align: right;">操作</th>
          </tr>
          </thead>
          <tbody id="channels-body"></tbody>
        </table>
      </div>

      <div class="section">
        <div class="section-title">
          <span>系统设置 <small>影响日志缓存与数据库轮询行为</small></span>
        </div>
        <div>
          <div class="field-label" style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
            <input type="checkbox" id="input-web-password-enabled" />
            <span>开启密码验证</span>
          </div>
          <div class="field-helper">默认开启。关闭后无需输入密码即可访问配置页，本地密码仍保留，可随时重新开启。</div>
        </div>
        <div class="system-grid" style="margin-top: 16px; padding-top: 16px; border-top: 1px solid #e5e7eb;">
          <div>
            <div class="field-label">日志缓存天数 (day)</div>
            <input id="input-log-days" type="number" min="1" />
            <div class="field-helper">原始推送日志的保留时长。</div>
          </div>
          <div>
            <div class="field-label">数据库轮询时间 (s)</div>
            <input id="input-poll-interval" type="number" min="1" />
            <div class="field-helper">轮询日志数据库的间隔时间，过小会增加磁盘 IO。</div>
          </div>
          <div>
            <div class="field-label">数据库地址（不确定就不要修改）</div>
            <input id="input-db-path" type="text" />
            <div class="field-helper">默认：/usr/trim/var/eventlogger_service/logger_data.db3</div>
          </div>
          <div>
            <div class="field-label">事件标题前缀</div>
            <input id="input-title-prefix" type="text" placeholder="飞牛NAS" />
            <div class="field-helper">默认「飞牛NAS」；留空则标题仅为事件说明（如「🔐 登录成功通知」），不含「前缀-」。</div>
          </div>
        </div>
        <div class="dnd-section" style="margin-top: 16px; padding-top: 16px; border-top: 1px solid #e5e7eb;">
          <div class="field-label" style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
            <input type="checkbox" id="input-dnd-enabled" />
            <span>勿扰模式</span>
          </div>
          <div class="field-helper" style="margin-bottom: 10px;">开启后，在设定时段内不推送消息；结束后将本时段事件汇总为一条推送。</div>
          <div class="system-grid" style="grid-template-columns: 1fr 1fr;">
            <div>
              <div class="field-label">开始时间</div>
              <input id="input-dnd-start" type="time" value="22:00" />
              <div class="field-helper">如 22:00，该时刻起进入勿扰</div>
            </div>
            <div>
              <div class="field-label">结束时间</div>
              <input id="input-dnd-end" type="time" value="07:00" />
              <div class="field-helper">如 07:00，跨日则到次日该时刻结束</div>
            </div>
          </div>
        </div>
      </div>

      <div class="footer-actions">
        <button class="btn btn-primary" id="save-btn" type="button">保存配置</button>
      </div>

      <div class="section test-section">
        <div class="section-title">
          <span>测试推送 <small>保存成功后，可发送测试消息验证渠道是否配置正确</small></span>
        </div>
        <textarea id="test-content" placeholder="请输入要发送的测试内容，例如：这是一条 FnMessageBots 配置测试消息。"></textarea>
        <div class="footer-actions" style="margin-top: 10px;">
          <button class="btn btn-ghost" id="test-btn" type="button" disabled>发送测试</button>
        </div>
        <div class="status-bar" id="status-bar"></div>
      </div>
    </div>
  </div>
  <div id="toast-container" class="toast-container"></div>

  <script>
    const eventsContainer = document.getElementById("events-container");
    const channelsBody = document.getElementById("channels-body");
    const addChannelBtn = document.getElementById("add-channel-btn");
    const saveBtn = document.getElementById("save-btn");
    const testBtn = document.getElementById("test-btn");
    const statusBar = document.getElementById("status-bar");

    let channelOptions = [];
    const fetchOpts = { credentials: "include" };

    async function initAuth() {
      const res = await fetch("/api/auth/status", fetchOpts);
      const data = await res.json();
      const authGate = document.getElementById("auth-gate");
      const appMain = document.getElementById("app-main");
      // 已登录，或未开启密码验证（无需设置密码且无需登录）时直接进入配置页
      const canShowApp = data.authenticated || (!data.need_setup && !data.need_login);
      if (canShowApp) {
        authGate.style.display = "none";
        appMain.style.display = "flex";
        loadConfig();
        return;
      }
      authGate.style.display = "flex";
      appMain.style.display = "none";
      document.getElementById("auth-set-password").style.display = data.need_setup ? "block" : "none";
      document.getElementById("auth-login").style.display = data.need_login ? "block" : "none";
      document.getElementById("auth-set-msg").textContent = "";
      document.getElementById("auth-login-msg").textContent = "";
    }

    document.getElementById("form-set-password").addEventListener("submit", async function(e) {
      e.preventDefault();
      const msgEl = document.getElementById("auth-set-msg");
      const p1 = document.getElementById("set-pw-password").value.trim();
      const p2 = document.getElementById("set-pw-confirm").value.trim();
      msgEl.textContent = "";
      msgEl.className = "auth-msg";
      if (p1.length < 6) {
        msgEl.textContent = "密码长度至少 6 位";
        msgEl.className = "auth-msg error";
        return;
      }
      if (p1 !== p2) {
        msgEl.textContent = "两次输入的密码不一致";
        msgEl.className = "auth-msg error";
        return;
      }
      const res = await fetch("/api/auth/set-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ password: p1, password_confirm: p2 }),
      });
      const json = await res.json();
      if (json.ok) {
        msgEl.textContent = "设置成功，正在进入配置页…";
        msgEl.className = "auth-msg ok";
        initAuth();
      } else {
        msgEl.textContent = json.message || "设置失败";
        msgEl.className = "auth-msg error";
      }
    });

    document.getElementById("form-login").addEventListener("submit", async function(e) {
      e.preventDefault();
      const msgEl = document.getElementById("auth-login-msg");
      const password = document.getElementById("login-password").value.trim();
      msgEl.textContent = "";
      msgEl.className = "auth-msg";
      if (!password) {
        msgEl.textContent = "请输入密码";
        msgEl.className = "auth-msg error";
        return;
      }
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ password }),
      });
      const json = await res.json();
      if (json.ok) {
        msgEl.textContent = "登录成功，正在进入配置页…";
        msgEl.className = "auth-msg ok";
        initAuth();
      } else {
        msgEl.textContent = json.message || "登录失败";
        msgEl.className = "auth-msg error";
      }
    });

    function setStatus(ok, message) {
      statusBar.className = "status-bar " + (ok ? "status-ok" : "status-error");
      statusBar.innerHTML = message ? "<span>" + message + "</span>" : "";
    }

    function showToast(ok, message) {
      const container = document.getElementById("toast-container");
      const el = document.createElement("div");
      el.className = "toast " + (ok ? "toast-ok" : "toast-error");
      el.textContent = message || (ok ? "操作成功" : "操作失败");
      container.appendChild(el);
      setTimeout(() => {
        el.style.opacity = "0";
        el.style.transform = "translateY(-8px)";
        el.style.transition = "opacity 0.2s, transform 0.2s";
        setTimeout(() => el.remove(), 200);
      }, 3200);
    }

    const PUSHPLUS_PLACEHOLDER = '{"token":"你的token","title":"{title}","content":"消息内容","template":"html","channel":"wechat"}';

    function createChannelRow(chType, url) {
      const tr = document.createElement("tr");

      const tdType = document.createElement("td");
      const sel = document.createElement("select");
      for (const opt of channelOptions) {
        const o = document.createElement("option");
        o.value = opt.id;
        o.textContent = opt.name;
        if (opt.id === chType) o.selected = true;
        sel.appendChild(o);
      }
      tdType.appendChild(sel);

      const tdUrl = document.createElement("td");
      function setUrlWidget(isPushPlus, val) {
        tdUrl.innerHTML = "";
        if (isPushPlus) {
          const ta = document.createElement("textarea");
          ta.rows = 3;
          ta.placeholder = PUSHPLUS_PLACEHOLDER;
          ta.value = val || "";
          ta.style.minHeight = "60px";
          tdUrl.appendChild(ta);
        } else {
          const inp = document.createElement("input");
          inp.type = "text";
          inp.placeholder = "例如：https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...";
          inp.value = val || "";
          tdUrl.appendChild(inp);
        }
      }
      setUrlWidget(chType === "pushplus", url || "");

      sel.addEventListener("change", function() {
        const prev = tdUrl.querySelector("input[type=text], textarea");
        const prevVal = prev ? prev.value : "";
        setUrlWidget(sel.value === "pushplus", prevVal);
      });

      const tdOp = document.createElement("td");
      tdOp.style.textAlign = "right";
      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.className = "btn-danger";
      delBtn.textContent = "删除";
      delBtn.onclick = () => {
        channelsBody.removeChild(tr);
      };
      tdOp.appendChild(delBtn);

      tr.appendChild(tdType);
      tr.appendChild(tdUrl);
      tr.appendChild(tdOp);

      channelsBody.appendChild(tr);
    }

    async function loadConfig() {
      try {
        const res = await fetch("/api/config", fetchOpts);
        const json = await res.json();
        if (res.status === 401) {
          initAuth();
          return;
        }
        if (!json.ok) {
          setStatus(false, json.message || "加载配置失败");
          return;
        }
        const data = json.data;
        document.getElementById("app-title").textContent = data.title || "FnMessageBots";
        document.getElementById("app-subtitle").textContent = data.subtitle || "";
        document.getElementById("app-version").textContent = data.version || "";

        channelOptions = data.channel_options || [];

        // 按分类渲染事件
        eventsContainer.innerHTML = "";
        const selected = new Set(data.selected_events || []);
        const categories = data.events_by_category || [];
        for (const cat of categories) {
          const catBlock = document.createElement("div");
          catBlock.className = "event-category";

          // 分类标题 + 全选
          const catHeader = document.createElement("div");
          catHeader.className = "event-category-title";
          const catTitleSpan = document.createElement("span");
          catTitleSpan.textContent = cat.name || "";
          catHeader.appendChild(catTitleSpan);

          const catToggleLabel = document.createElement("label");
          catToggleLabel.style.fontSize = "13px";
          catToggleLabel.style.cursor = "pointer";
          catToggleLabel.style.flexShrink = "0";
          const catToggle = document.createElement("input");
          catToggle.type = "checkbox";
          catToggle.style.marginRight = "4px";
          catToggleLabel.appendChild(catToggle);
          const catToggleText = document.createElement("span");
          catToggleText.textContent = "全选";
          catToggleLabel.appendChild(catToggleText);
          catHeader.appendChild(catToggleLabel);

          catBlock.appendChild(catHeader);

          const grid = document.createElement("div");
          grid.className = "events-grid";

          function updateCatToggle() {
            const boxes = grid.querySelectorAll("input[type=checkbox]");
            if (!boxes.length) {
              catToggle.checked = false;
              return;
            }
            catToggle.checked = Array.from(boxes).every(b => b.checked);
          }

          for (const ev of cat.events || []) {
            const div = document.createElement("div");
            div.className = "event-item";
            const cb = document.createElement("input");
            cb.type = "checkbox";
            cb.value = ev.id;
            if (selected.has(ev.id)) cb.checked = true;

            cb.addEventListener("change", () => {
              updateCatToggle();
            });

            const label = document.createElement("div");
            const title = document.createElement("span");
            title.textContent = ev.title || ev.id;
            label.appendChild(title);
            if (ev.note) {
              const helper = document.createElement("div");
              helper.className = "field-helper";
              helper.textContent = ev.note;
              label.appendChild(helper);
            }
            div.appendChild(cb);
            div.appendChild(label);
            grid.appendChild(div);
          }

          // 分类全选/反选：用 change 事件，让复选框先自然切换，再根据其新状态同步子项
          catToggle.addEventListener("change", () => {
            const boxes = grid.querySelectorAll("input[type=checkbox]");
            const target = catToggle.checked;
            boxes.forEach(b => { b.checked = target; });
          });

          updateCatToggle();

          catBlock.appendChild(grid);
          eventsContainer.appendChild(catBlock);
        }

        // 渲染渠道
        channelsBody.innerHTML = "";
        if (data.channels && data.channels.length) {
          for (const ch of data.channels) {
            createChannelRow(ch.type || "wechat", ch.url || "");
          }
        } else {
          // 默认只展示一行企业微信，需要其他渠道可点击「添加渠道」
          createChannelRow("wechat", "");
        }

        document.getElementById("input-web-password-enabled").checked = data.web_password_enabled !== false;
        document.getElementById("input-log-days").value = data.log_retention_days || 7;
        document.getElementById("input-poll-interval").value = data.logger_poll_interval || 3;
        document.getElementById("input-db-path").value = data.logger_db_path || "";
        document.getElementById("input-title-prefix").value =
          typeof data.title_prefix === "string" ? data.title_prefix : "飞牛NAS";
        const dndEnabled = !!data.dnd_enabled;
        document.getElementById("input-dnd-enabled").checked = dndEnabled;
        document.getElementById("input-dnd-start").value = data.dnd_start_time || "22:00";
        document.getElementById("input-dnd-end").value = data.dnd_end_time || "07:00";
        document.getElementById("input-dnd-start").disabled = !dndEnabled;
        document.getElementById("input-dnd-end").disabled = !dndEnabled;
        document.getElementById("input-dnd-enabled").addEventListener("change", function() {
          const en = document.getElementById("input-dnd-enabled").checked;
          document.getElementById("input-dnd-start").disabled = !en;
          document.getElementById("input-dnd-end").disabled = !en;
        });

        setStatus(false, "");
        loadPushStats();
      } catch (e) {
        console.error(e);
        setStatus(false, "加载配置失败，请检查服务是否正常运行。");
      }
    }

    async function loadPushStats() {
      try {
        const res = await fetch("/api/push-stats", fetchOpts);
        const json = await res.json();
        if (!json.ok || !json.data) return;
        const t = json.data.total || {};
        const d = json.data.today || {};
        document.getElementById("stat-total-total").textContent = (t.total ?? 0);
        document.getElementById("stat-total-success").textContent = (t.success ?? 0);
        document.getElementById("stat-total-fail").textContent = (t.fail ?? 0);
        document.getElementById("stat-today-total").textContent = (d.total ?? 0);
        document.getElementById("stat-today-success").textContent = (d.success ?? 0);
        document.getElementById("stat-today-fail").textContent = (d.fail ?? 0);
      } catch (e) { /* ignore */ }
    }

    addChannelBtn.addEventListener("click", () => {
      const defaultType = channelOptions.length ? channelOptions[0].id : "wechat";
      createChannelRow(defaultType, "");
    });

    saveBtn.addEventListener("click", async () => {
      setStatus(false, "");
      const events = [];
      eventsContainer.querySelectorAll("input[type=checkbox]").forEach(cb => {
        if (cb.checked) events.push(cb.value);
      });

      const channels = [];
      channelsBody.querySelectorAll("tr").forEach(tr => {
        const sel = tr.querySelector("select");
        const inp = tr.querySelector("input[type=text]");
        const ta = tr.querySelector("textarea");
        const urlEl = inp || ta;
        if (!sel || !urlEl) return;
        const url = urlEl.value.trim();
        const type = sel.value;
        if (!url) return;
        channels.push({ type, url });
      });

      const payload = {
        events,
        channels,
        log_retention_days: document.getElementById("input-log-days").value,
        logger_poll_interval: document.getElementById("input-poll-interval").value,
        logger_db_path: document.getElementById("input-db-path").value,
        title_prefix: (document.getElementById("input-title-prefix").value || "").trim(),
        web_password_enabled: document.getElementById("input-web-password-enabled").checked,
        dnd_enabled: document.getElementById("input-dnd-enabled").checked,
        dnd_start_time: document.getElementById("input-dnd-start").value || "22:00",
        dnd_end_time: document.getElementById("input-dnd-end").value || "07:00",
      };

      try {
        const res = await fetch("/api/save-config", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify(payload),
        });
        const json = await res.json();
        if (res.ok && json.ok) {
          showToast(true, json.message || "配置已保存");
          testBtn.disabled = false;
          loadConfig();
        } else {
          showToast(false, json.message || "保存失败");
        }
      } catch (e) {
        console.error(e);
        showToast(false, "保存失败，请检查网络或稍后再试");
      }
    });

    testBtn.addEventListener("click", async () => {
      const content = document.getElementById("test-content").value.trim();
      if (!content) {
        showToast(false, "请输入测试内容");
        return;
      }
      setStatus(false, "正在发送测试消息...");
      try {
        const res = await fetch("/api/test", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({ content }),
        });
        const text = await res.text();
        let json = null;
        try { json = JSON.parse(text); } catch (e) { json = null; }
        if (res.ok && json.ok) {
          showToast(true, json.message || "测试消息已发送");
        } else {
          showToast(false, (json && json.message) ? json.message : ("测试发送失败：" + (text ? text.slice(0, 120) : "")));
        }
      } catch (e) {
        console.error(e);
        showToast(false, "测试发送失败，请稍后重试");
      }
      setStatus(false, "");
    });

    window.addEventListener("load", () => {
      initAuth();
      setInterval(loadPushStats, 30000);
    });
  </script>
</body>
</html>
            """
        )

    return app


def start_ui_server_in_background(on_config_saved=None):
    """在后台线程启动配置 UI 服务。on_config_saved: 保存配置成功后的回调（热加载用）。"""
    app = create_app(on_config_saved=on_config_saved)
    port = int(os.getenv("UI_PORT", "18080"))

    def _run():
        app.run(host="0.0.0.0", port=port, threaded=True)

    thread = threading.Thread(target=_run, name="FnMessageBots-UI", daemon=True)
    thread.start()
    return thread


if __name__ == "__main__":
    # 本地调试：只启动 UI，不启动监控（无需配置 Webhook 即可打开页面）
    repo_root = Path(__file__).resolve().parent.parent.parent
    os.chdir(repo_root)
    app = create_app()
    port = int(os.getenv("UI_PORT", "18080"))
    print(f"配置 UI: http://127.0.0.1:{port}")
    app.run(host="0.0.0.0", port=port, debug=True)

