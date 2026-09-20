#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
哔哩哔哩大会员线下点映会 - GitHub Actions 监控脚本
通过环境变量 BARK_SERVER 和 BARK_KEY 进行安全推送，避免明文泄露。
"""

import os
import sys
import json
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone, timedelta

BILI_API = "https://api.bilibili.com/x/vip/web/vip_center/offlinemeeting"
DEFAULT_BARK_SERVER = "https://bark.guoyingwei.top"
BARK_USER_AGENT = "bili-dyh-monitor/1.0"
STATE_FILE = "state.json"
DATA_FILE = "data.json"

def get_beijing_time(ts=None):
    tz = timezone(timedelta(hours=8))
    dt = datetime.fromtimestamp(ts, tz=tz) if ts else datetime.now(tz=tz)
    return dt.strftime("%Y-%m-%d %H:%M")

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"读取状态文件失败: {e}", file=sys.stderr)
    return {"notified_ids": []}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def send_bark(title, body, url="https://b23.tv/O1cUFKs"):
    server = os.environ.get("BARK_SERVER", DEFAULT_BARK_SERVER).rstrip("/")
    key = os.environ.get("BARK_KEY")
    if not key:
        print("Bark 推送失败: 未设置 BARK_KEY 环境变量", file=sys.stderr)
        return False

    endpoint = f"{server}/{key}"
    payload = {
        "title": title,
        "body": body,
        "url": url,
        "group": "bili-dyh",
        "icon": "https://www.bilibili.com/favicon.ico",
        "badge": 1,
        "sound": "calypso"
    }

    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": BARK_USER_AGENT,
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw_body = resp.read().decode("utf-8")
            try:
                result = json.loads(raw_body)
            except ValueError:
                raise ValueError(f"HTTP {resp.status}, 响应不是 JSON: {raw_body[:512]}")
            if resp.status != 200 or not isinstance(result, dict) or result.get("code") != 200:
                raise ValueError(f"HTTP {resp.status}, Bark 未确认成功: {raw_body[:512]}")
            print(f"Bark 推送成功: HTTP {resp.status}, code=200")
            return True
    except urllib.error.HTTPError as e:
        try:
            detail = e.read(2048).decode("utf-8", errors="replace")
        except Exception:
            detail = "无法读取错误响应"
        ray = e.headers.get("CF-Ray", "") if e.headers else ""
        error = f"HTTP {e.code}, CF-Ray={ray or '无'}, 响应: {detail}"
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
    for secret in (urllib.parse.quote(key, safe=""), urllib.parse.quote_plus(key), key):
        error = error.replace(secret, "[REDACTED]")
    print(f"Bark 推送失败: {error}", file=sys.stderr)
    return False

def main():
    print(f"开始检查 B站大会员点映会活动 [{get_beijing_time()}]...")
    req_url = f"{BILI_API}?t={int(time.time() * 1000)}"
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
        "Referer": "https://www.bilibili.com/blackboard/era/kXP06cmqKtYULNL1.html"
    }

    req = urllib.request.Request(req_url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            res_data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"请求 B站 API 失败: {e}", file=sys.stderr)
        sys.exit(1)

    if res_data.get("code") != 0:
        print(f"B站 API 业务异常: {res_data}", file=sys.stderr)
        sys.exit(1)

    om = res_data.get("data", {}).get("offline_meeting", {})
    ongoing = om.get("enroll_detail", {}).get("items") or []
    upcoming = om.get("activity_preview_detail", {}).get("items") or []
    history = om.get("history_detail", {}).get("items") or []

    state = load_state()
    notified_set = set(str(i) for i in state.get("notified_ids", []))
    new_notified = []
    failed_ids = []

    print(f"当前状态: 正在进行 {len(ongoing)} 个, 活动预告 {len(upcoming)} 个, 历史活动 {len(history)} 个")

    for item in ongoing:
        item_id = str(item.get("id"))
        if item_id not in notified_set:
            title = f"🎬 B站大会员点映会开抢：{item.get('title')}"
            type_name = item.get("type_name") or "线下点映"
            city = item.get("city") or "全国"
            start_str = get_beijing_time(item.get("start_time")) if item.get("start_time") else ""
            end_str = get_beijing_time(item.get("end_time")) if item.get("end_time") else ""
            date_str = get_beijing_time(item.get("date")) if item.get("date") else ""
            register_link = item.get("register_info_share_link")
            detail_link = item.get("link")
            target_url = register_link or detail_link or "https://b23.tv/O1cUFKs"

            body = f"🏷️ 类型：{type_name}\n📍 城市：{city}\n⏰ 报名：{start_str} ~ {end_str}"
            if date_str:
                body += f"\n🎟️ 放映：{date_str}"
            body += "\n👉 点击此通知直达【报名页】立即抢票！"
            if detail_link and detail_link != target_url:
                body += f"\n📖 活动详情：{detail_link}"

            if send_bark(title, body, target_url):
                notified_set.add(item_id)
                new_notified.append(item_id)
            else:
                failed_ids.append(item_id)

    state["notified_ids"] = sorted(notified_set)
    state["last_checked"] = get_beijing_time()
    save_state(state)

    # 生成前端数据文件 data.json
    output_data = {
        "updated_at": get_beijing_time(),
        "ongoing_count": len(ongoing),
        "upcoming_count": len(upcoming),
        "history_count": len(history),
        "ongoing": ongoing,
        "upcoming": upcoming,
        "history": history
    }
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(f"检查完毕: 本次新增提醒 {len(new_notified)} 个，已更新 {DATA_FILE}")
    if failed_ids:
        print(f"推送失败的活动 ID: {', '.join(failed_ids)}；保留待下次重试", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
