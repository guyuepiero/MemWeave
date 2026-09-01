"""微文收纳 · 共享业务逻辑（REST / WS / 同步引擎 共用）"""
import json

import httpx

from . import db, exporters, parser, storage
from .config import REFERER, UA


def build_meta(payload: dict) -> tuple[dict, str, str]:
    """从扩展/同步引擎载荷解析文章元数据，返回 (meta, content_html, full_html)。"""
    full_html = payload.get("html", "")
    parsed = parser.parse_article(full_html, url=payload.get("url", ""))
    meta = {k: (payload.get(k) or parsed.get(k) or "") for k in
            ("biz", "appmsgid", "title", "author", "link", "cover", "source", "digest")}
    meta["idx"] = payload.get("idx") or parsed["idx"]
    meta["publish_time"] = payload.get("publish_time") or parsed["publish_time"]
    meta["album_id"] = payload.get("album_id") or ""
    meta["topic_id"] = payload.get("topic_id")
    meta["is_paid"] = payload.get("is_paid") if payload.get("is_paid") is not None else parsed.get("is_paid", 0)
    content_html = parsed["content_html"] or full_html
    return meta, content_html, full_html


def save_article(meta: dict, content_html: str, full_html: str) -> dict:
    """落盘 + 入库 + 自动写默认属性。返回 {ok, id, created, title, biz}"""
    if not meta.get("biz"):
        return {"ok": False, "error": "未能解析出公众号 __biz"}
    db.upsert_account(meta["biz"], meta.get("source", ""))
    files = storage.save_article_files(
        meta["biz"], meta["appmsgid"], full_html, content_html,
        title=meta.get("title", ""), idx=meta.get("idx") or 0,
        author=meta.get("author", ""), source=meta.get("source", ""),
        publish_time=meta.get("publish_time"),
    )
    meta["html_path"] = files["html_path"]
    meta["images_dir"] = files["images_dir"]
    meta["content_md"] = exporters.md_from_html(content_html)
    meta["attrs_json"] = json.dumps(
        {
            "author": meta.get("author", ""),
            "publish_time": meta.get("publish_time"),
            "link": meta.get("link", ""),
            "source": meta.get("source", ""),
        },
        ensure_ascii=False,
    )
    article_id, created = db.upsert_article(meta)
    # 增量联动：入库成功后自动导出知识库 md（RAW/<公众号>/），知识库持续更新
    try:
        from . import md_knowledge
        article = db.get_article(article_id)
        if article:
            md_knowledge.export_one(article)
    except Exception as e:  # noqa: BLE001
        print(f"[md_knowledge] 增量导出失败 #{article_id}: {e}")
    return {"ok": True, "id": article_id, "created": created, "title": meta.get("title", ""), "biz": meta.get("biz", "")}


def sync_article_payload(payload: dict) -> dict:
    meta, content_html, full_html = build_meta(payload)
    return save_article(meta, content_html, full_html)


def _cookie_dict(session: dict | None) -> dict:
    c = (session or {}).get("cookie") or ""
    return {p.split("=", 1)[0]: p.split("=", 1)[1] for p in c.split(";") if "=" in p}


def session_headers(session: dict | None) -> dict:
    return {"Referer": REFERER, "User-Agent": (session or {}).get("ua") or UA}


async def fetch_article_page(link: str, session: dict | None = None) -> str:
    """抓取单篇文章页面（公开页；尽量带浏览器会话 cookie 提高成功率）。"""
    async with httpx.AsyncClient(
        timeout=20,
        headers=session_headers(session),
        cookies=_cookie_dict(session),
        follow_redirects=True,
    ) as client:
        r = await client.get(link)
        r.raise_for_status()
        return r.text
