#!/usr/bin/env python3
"""
向 push_history 表随机插入 5000 条推送记录（格式与正式写入一致），用于测试/展示。
在项目根目录执行：python scripts/seed_push_history.py
"""

import json
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# 保证可导入 src 下的 utils
_repo = Path(__file__).resolve().parent.parent
_src = _repo / "src"
if _src.exists() and str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

# 与 push_history 表结构一致的事件类型（取自 VALID_EVENT_IDS 子集）
EVENT_TYPES = [
    "LoginSucc", "LoginSucc2FA1", "LoginFail", "Logout", "FoundDisk",
    "SSH_INVALID_USER", "SSH_AUTH_FAILED", "SSH_LOGIN_SUCCESS", "SSH_DISCONNECTED",
    "APP_CRASH", "APP_UPDATE_FAILED", "APP_STARTED", "APP_STOPPED", "APP_UPDATED",
    "CPU_USAGE_ALARM", "CPU_USAGE_RESTORED", "CPU_TEMPERATURE_ALARM",
    "UPS_ONBATT", "UPS_ONBATT_LOWBATT", "UPS_ONLINE", "DiskWakeup", "DiskSpindown",
    "DISK_IO_ERR", "ARCHIVING_SUCCESS", "DeleteFile", "WEBDAV_ENABLED", "SAMBA_ENABLED",
]

# 与正式推送一致的渠道名（用于 channel_results）
CHANNELS = ["企业微信", "钉钉", "飞书", "Bark", "PushPlus"]

# 随机摘要/事件数据
USERS = ["admin", "user", "root", "test", "nas_user", "guest"]
IP_POOL = ["192.168.1.%d" % i for i in range(1, 255)] + ["10.0.0.%d" % i for i in range(1, 50)]
APP_NAMES = ["Docker", "Jellyfin", "Transmission", "HomeAssistant", "Node-Red", "qbittorrent", "Alist"]
MESSAGES = [
    "用户登录成功", "登录失败，密码错误", "SSH 认证成功", "磁盘唤醒", "磁盘休眠",
    "CPU 使用率告警", "UPS 进入电池模式", "应用已启动", "应用已停止", "文件已删除",
]


def random_created_at(days_back: int = 30):
    """生成过去 days_back 天内的随机时间，格式与 push_history 一致。"""
    tz = ZoneInfo("Asia/Shanghai")
    now = datetime.now(tz)
    start = now - timedelta(days=days_back)
    delta = (now - start).total_seconds()
    sec = random.uniform(0, delta)
    dt = start + timedelta(seconds=sec)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def random_summary(event_type: str) -> str:
    """生成与 _event_summary 风格一致的简短摘要。"""
    if random.random() < 0.6:
        user = random.choice(USERS)
        ip = random.choice(IP_POOL)
        return f"{user}@{ip}".strip()
    if random.random() < 0.5 and event_type in ("APP_CRASH", "APP_UPDATE_FAILED", "APP_STARTED", "APP_STOPPED"):
        return f"{event_type} {random.choice(APP_NAMES)}"
    if random.random() < 0.5:
        return random.choice(MESSAGES)[:50]
    return event_type


# 成功时模拟的接口返回体（各渠道风格）
RESPONSE_OK = [
    {"errcode": 0, "errmsg": "ok"},
    {"code": 0, "msg": "success"},
    {"StatusCode": 0, "StatusMessage": "success"},
    {"code": 0, "data": {"message_id": "mock-id"}},
]
# 失败时：模拟各渠道接口报错（既有 error 文案，也有 response 体，与真实存储一致）
# 企业微信
WECHAT_FAIL = [
    {"error": "errcode=40001: invalid credential", "response": {"errcode": 40001, "errmsg": "invalid credential"}},
    {"error": "errcode=41001: missing parameter", "response": {"errcode": 41001, "errmsg": "missing parameter"}},
    {"error": "请求超时", "response": None},
]
# 钉钉
DINGTALK_FAIL = [
    {"error": "code=310000: 机器人不存在", "response": {"errcode": 310000, "errmsg": "robot not exist"}},
    {"error": "code=310001: 签名不匹配", "response": {"errcode": 310001, "errmsg": "sign not match"}},
    {"error": "连接错误: Connection refused", "response": None},
]
# 飞书
FEISHU_FAIL = [
    {"error": "HTTP 400: 参数错误", "response": {"code": 99991668, "msg": "invalid param"}},
    {"error": "HTTP 401: 未授权", "response": {"code": 99991663, "msg": "unauthorized"}},
    {"error": "请求超时", "response": None},
]
# Bark
BARK_FAIL = [
    {"error": "HTTP 404", "response": None},
    {"error": "HTTP 500: Internal Server Error", "response": {"code": 500, "message": "server error"}},
]
# PushPlus
PUSHPLUS_FAIL = [
    {"error": "token无效", "response": {"code": 401, "msg": "token invalid"}},
    {"error": "超过发送频率限制", "response": {"code": 429, "msg": "rate limit"}},
    {"error": "参数 JSON 解析失败", "response": None},
]
CHANNEL_FAIL_MAP = {
    "企业微信": WECHAT_FAIL,
    "钉钉": DINGTALK_FAIL,
    "飞书": FEISHU_FAIL,
    "Bark": BARK_FAIL,
    "PushPlus": PUSHPLUS_FAIL,
}


def random_channel_results() -> tuple:
    """生成随机的渠道返回结果（含 response/error，模拟真实推送接口报错），返回 (channel_results, overall_success)。"""
    n = random.randint(1, len(CHANNELS))
    chosen = random.sample(CHANNELS, n)
    channel_results = []
    for c in chosen:
        success = random.choice([True, False])
        if success:
            channel_results.append({"channel": c, "success": True, "response": random.choice(RESPONSE_OK), "error": None})
        else:
            fail_options = CHANNEL_FAIL_MAP.get(c, [{"error": "请求失败", "response": None}])
            f = random.choice(fail_options)
            channel_results.append({
                "channel": c,
                "success": False,
                "response": f.get("response"),
                "error": f.get("error") or "请求失败",
            })
    overall = any(c["success"] for c in channel_results)
    return channel_results, overall


def random_detail(event_type: str, created_at: str, channel_results: list) -> dict:
    """生成与 add_record 写入格式一致的 detail 字典（含 channel_results）。"""
    event_data = {
        "user": random.choice(USERS) if random.random() < 0.7 else None,
        "IP": random.choice(IP_POOL) if random.random() < 0.6 else None,
        "name": random.choice(APP_NAMES) if "APP_" in event_type and random.random() < 0.5 else None,
        "message": random.choice(MESSAGES) if random.random() < 0.4 else None,
        "data": {},
    }
    if event_data["name"] or random.random() < 0.3:
        event_data["data"] = {"APP_NAME": event_data.get("name") or random.choice(APP_NAMES), "DISPLAY_NAME": None}
    event_data = {k: v for k, v in event_data.items() if v is not None}
    return {
        "event_type": event_type,
        "timestamp": created_at,
        "event_data": event_data,
        "channel_results": channel_results,
    }


def main():
    cursor_dir = "./data/cursor"
    config_path = _repo / "config" / "config.json"
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                cursor_dir = cfg.get("cursor_dir", cursor_dir)
        except Exception:
            pass

    from utils.push_history import init, bulk_insert, clear_all

    init(cursor_dir)
    clear_all()
    records = []
    for _ in range(5000):
        created_at = random_created_at()
        event_type = random.choice(EVENT_TYPES)
        channel_results, success = random_channel_results()
        summary = random_summary(event_type)
        detail = random_detail(event_type, created_at, channel_results)
        records.append({
            "created_at": created_at,
            "event_type": event_type,
            "success": success,
            "summary": summary,
            "detail": detail,
        })
    bulk_insert(records)
    print("已插入 5000 条推送记录到 push_history（cursor_dir=%s）" % cursor_dir)


if __name__ == "__main__":
    main()
