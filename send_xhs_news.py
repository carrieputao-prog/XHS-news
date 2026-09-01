import base64
import hashlib
import hmac
import json
import os
import re
import sys
import time
import urllib.parse
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx


GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
DINGTALK_WEBHOOK = os.environ["DINGTALK_WEBHOOK"]
DINGTALK_SECRET = os.environ["DINGTALK_SECRET"]
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_REPO = "carrieputao-prog/grape-data"

BEIJING_TZ = timezone(timedelta(hours=8))
GENERIC_TERMS = {
    "AI",
    "人工智能",
    "AIGC",
    "ChatGPT",
    "小红书",
    "教程",
    "工具",
    "爆款",
    "热门",
    "笔记",
}


def beijing_now() -> datetime:
    return datetime.now(BEIJING_TZ)


def github_headers() -> dict[str, str]:
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }


def get_github_file(path: str) -> tuple[Any | None, str | None]:
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    resp = httpx.get(url, headers=github_headers(), timeout=30)
    if resp.status_code == 404:
        return None, None
    resp.raise_for_status()
    payload = resp.json()
    content = base64.b64decode(payload["content"]).decode("utf-8")
    return json.loads(content), payload["sha"]


def put_github_file(path: str, content: str, message: str, sha: str | None = None) -> None:
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    payload = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
    }
    if sha:
        payload["sha"] = sha
    resp = httpx.put(url, headers=github_headers(), json=payload, timeout=30)
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"GitHub write failed: {resp.status_code} {resp.text}")


def generate_daily_hot_trends() -> dict[str, Any]:
    today = beijing_now().strftime("%Y年%m月%d日")
    window_end = beijing_now()
    window_start = window_end - timedelta(hours=24)

    prompt = f"""你是小红书AI内容选题分析员。请联网检索北京时间最近24小时内，小红书及相关数据/媒体渠道中与AI、AIGC、AI工具、AI应用、AI教程、AI办公、AI绘画、AI视频、AI编程、AI副业、AI学习相关的热门内容。

时间窗口：{window_start:%Y-%m-%d %H:%M} 至 {window_end:%Y-%m-%d %H:%M}。

任务：
1. 输出热门话题Top 5。
2. 输出低粉爆文Top 5。
3. 输出5-10个AI相关标签词或新兴词。

筛选规则：
- 10条内容尽量覆盖不同话题，同一工具、事件、教程角度不要重复。
- 热门话题必须有热度证据，优先多个笔记、多个账号或新红/热点雷达等榜单共同指向的话题。
- 低粉爆文优先粉丝数低于1万；数据不足可放宽到5万以内，但必须有粉丝数和赞藏评。
- 互动粉丝比 = (点赞 + 收藏 + 评论) / 粉丝数。
- 来源优先小红书、新红、热点雷达，可参考国内媒体，但必须和小红书传播有关。
- 无法确认发布时间时，热度证据中标注“时间待核验”。

只返回JSON，不要Markdown。"""

    response = httpx.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
        params={"key": GEMINI_API_KEY},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": daily_schema(),
            },
        },
        timeout=120,
    )
    response.raise_for_status()
    raw = response.json()["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(strip_json_fence(raw))


def daily_schema() -> dict[str, Any]:
    topic = {
        "type": "OBJECT",
        "properties": {
            "topic": {"type": "STRING"},
            "evidence": {"type": "STRING"},
            "representative_note": {"type": "STRING"},
            "reason": {"type": "STRING"},
            "source": {"type": "STRING"},
            "tags": {"type": "ARRAY", "items": {"type": "STRING"}},
        },
        "required": ["topic", "evidence", "representative_note", "reason", "source", "tags"],
    }
    hit = {
        "type": "OBJECT",
        "properties": {
            "title": {"type": "STRING"},
            "followers": {"type": "STRING"},
            "engagement": {"type": "STRING"},
            "engagement_follower_ratio": {"type": "STRING"},
            "reason": {"type": "STRING"},
            "source": {"type": "STRING"},
            "tags": {"type": "ARRAY", "items": {"type": "STRING"}},
        },
        "required": [
            "title",
            "followers",
            "engagement",
            "engagement_follower_ratio",
            "reason",
            "source",
            "tags",
        ],
    }
    return {
        "type": "OBJECT",
        "properties": {
            "hot_topics": {"type": "ARRAY", "items": topic},
            "low_follower_hits": {"type": "ARRAY", "items": hit},
            "ai_terms": {"type": "ARRAY", "items": {"type": "STRING"}},
        },
        "required": ["hot_topics", "low_follower_hits", "ai_terms"],
    }


def render_daily_markdown(data: dict[str, Any], date_text: str) -> str:
    lines = [
        f"🍇 小红书 AI 热点追踪 · {date_text}",
        "",
        "## 热门话题 Top 5",
        "",
    ]
    for index, item in enumerate(data.get("hot_topics", [])[:5], 1):
        lines.extend(
            [
                f"{index}. 话题：{item.get('topic', '')}",
                f"   热度证据：{item.get('evidence', '')}",
                f"   代表笔记：{item.get('representative_note', '')}",
                f"   推荐理由：{item.get('reason', '')}",
                f"   来源：{item.get('source', '')}",
                f"   标签词：{'、'.join(item.get('tags', []))}",
                "",
            ]
        )

    lines.extend(["## 低粉爆文 Top 5", ""])
    for index, item in enumerate(data.get("low_follower_hits", [])[:5], 1):
        lines.extend(
            [
                f"{index}. 标题：{item.get('title', '')}",
                f"   粉丝数：{item.get('followers', '')}",
                f"   赞藏评：{item.get('engagement', '')}",
                f"   互动粉丝比：{item.get('engagement_follower_ratio', '')}",
                f"   爆发原因：{item.get('reason', '')}",
                f"   来源：{item.get('source', '')}",
                f"   标签词：{'、'.join(item.get('tags', []))}",
                "",
            ]
        )

    terms = [term for term in data.get("ai_terms", []) if term]
    if terms:
        lines.extend(["## 今日 AI 相关词", " | ".join(terms[:10])])
    return "\n".join(lines).strip()


def save_daily_data(data: dict[str, Any], date_str: str) -> None:
    path = f"xhs-hot-trends/{date_str}.json"
    existing, sha = get_github_file(path)
    content = json.dumps(
        {
            "date": date_str,
            "hot_topics": data.get("hot_topics", [])[:5],
            "low_follower_hits": data.get("low_follower_hits", [])[:5],
            "ai_terms": data.get("ai_terms", [])[:10],
        },
        ensure_ascii=False,
        indent=2,
    )
    put_github_file(path, content, f"📌 XHS AI热点追踪 {date_str}", sha)


def collect_weekly_terms(end_date: datetime) -> tuple[list[str], str, str]:
    dates = [end_date - timedelta(days=offset) for offset in range(6, -1, -1)]
    all_terms: list[str] = []
    for day in dates:
        date_str = day.strftime("%Y-%m-%d")
        data, _ = get_github_file(f"xhs-hot-trends/{date_str}.json")
        if not data:
            continue
        all_terms.extend(data.get("ai_terms", []))
        for topic in data.get("hot_topics", []):
            all_terms.extend(topic.get("tags", []))
        for hit in data.get("low_follower_hits", []):
            all_terms.extend(hit.get("tags", []))

    normalized = [normalize_term(term) for term in all_terms]
    filtered = [term for term in normalized if term and term not in GENERIC_TERMS]
    counts = Counter(filtered)
    candidates = [term for term, _ in counts.most_common(30)]
    return candidates, dates[0].strftime("%Y-%m-%d"), dates[-1].strftime("%Y-%m-%d")


def normalize_term(term: str) -> str:
    return re.sub(r"\s+", " ", str(term)).strip()


def generate_weekly_candidates(terms: list[str], week_start: str, week_end: str) -> list[dict[str, str]]:
    if not terms:
        return []

    prompt = f"""以下是本周小红书AI热点追踪中出现的候选词，已按频次和热度粗排：
{chr(10).join(f"- {term}" for term in terms[:30])}

请筛选3-10个AI相关的新兴工具、概念、玩法、方法论或内容标签。
排除泛词：AI、人工智能、AIGC、ChatGPT、小红书、教程、工具、爆款。
source统一使用：Agent-小红书热点-{week_start}-{week_end}

只返回JSON。"""

    response = httpx.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
        params={"key": GEMINI_API_KEY},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": weekly_schema(),
            },
        },
        timeout=60,
    )
    response.raise_for_status()
    raw = response.json()["candidates"][0]["content"]["parts"][0]["text"]
    result = json.loads(strip_json_fence(raw))
    return result.get("candidates", [])


def weekly_schema() -> dict[str, Any]:
    return {
        "type": "OBJECT",
        "properties": {
            "candidates": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "term": {"type": "STRING"},
                        "brief": {"type": "STRING"},
                        "source": {"type": "STRING"},
                    },
                    "required": ["term", "brief", "source"],
                },
            }
        },
        "required": ["candidates"],
    }


def save_pending_topics(candidates: list[dict[str, str]], date_str: str) -> None:
    if not candidates:
        print("本周没有发现新词候选")
        return

    path = "pending_topics.json"
    existing, sha = get_github_file(path)
    if not existing:
        existing = {"last_updated": date_str, "pending": []}

    pending = existing.setdefault("pending", [])
    existing_terms = {item.get("term") for item in pending}
    next_id = 200 + len(pending)
    added = []
    for item in candidates:
        term = item.get("term", "").strip()
        if not term or term in existing_terms:
            continue
        pending.append(
            {
                "id": next_id,
                "term": term,
                "brief": item.get("brief", "").strip(),
                "source": item.get("source", f"Agent-小红书热点-{date_str}"),
                "added_date": date_str,
                "status": "pending",
            }
        )
        added.append(term)
        existing_terms.add(term)
        next_id += 1

    if not added:
        print("候选词已在待审核池中，跳过")
        return

    existing["last_updated"] = date_str
    content = json.dumps(existing, ensure_ascii=False, indent=2)
    put_github_file(path, content, f"🔍 XHS热点发现新词候选 {date_str}", sha)
    print(f"✅ 新词候选已写入 grape-data/pending_topics.json：{added}")


def strip_json_fence(raw: str) -> str:
    text = raw.strip()
    text = text.removeprefix("```json").removeprefix("```").strip()
    if text.endswith("```"):
        text = text[:-3].strip()
    return text


def dingtalk_sign() -> tuple[str, str]:
    timestamp = str(round(time.time() * 1000))
    string_to_sign = f"{timestamp}\n{DINGTALK_SECRET}"
    digest = hmac.new(
        DINGTALK_SECRET.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    return timestamp, urllib.parse.quote_plus(base64.b64encode(digest))


def send_to_dingtalk(content: str) -> None:
    timestamp, sign = dingtalk_sign()
    url = f"{DINGTALK_WEBHOOK}&timestamp={timestamp}&sign={sign}"
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": "🍇 小红书 AI 热点追踪",
            "text": content,
        },
    }
    resp = httpx.post(url, json=payload, timeout=30)
    result = resp.json()
    if result.get("errcode") != 0:
        raise RuntimeError(f"钉钉推送失败: {result}")
    print("✅ 热点追踪推送成功")


def run_daily() -> None:
    now = beijing_now()
    date_str = now.strftime("%Y-%m-%d")
    date_text = now.strftime("%Y年%m月%d日")
    data = generate_daily_hot_trends()
    markdown = render_daily_markdown(data, date_text)
    send_to_dingtalk(markdown)
    save_daily_data(data, date_str)
    print(f"✅ 今日结构化数据已保存：xhs-hot-trends/{date_str}.json")


def run_weekly() -> None:
    now = beijing_now()
    date_str = now.strftime("%Y-%m-%d")
    terms, week_start, week_end = collect_weekly_terms(now)
    candidates = generate_weekly_candidates(terms, week_start, week_end)
    save_pending_topics(candidates, date_str)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "daily"
    if mode == "daily":
        run_daily()
    elif mode == "weekly":
        run_weekly()
    else:
        raise SystemExit("Usage: python send_xhs_news.py [daily|weekly]")
