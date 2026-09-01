"""微文收纳 · 存量 index.html 重建脚本

背景：2026-08-04 发现两条同步路径产物不一致 ——
  - 正常路径：index.html = 骨架 + 仅 #js_content 正文（无标题/作者头部）
  - 异常路径（38 篇，parser 提取失败时回退整页）：整页 HTML 被塞进骨架（双重 <html>）

本脚本把全部文章的 index.html 原地重建为统一格式：
  art-head（标题/作者/公众号/发布时间） + #page-content（正文）

用法：在 WeChatVaultServer 目录下运行
  .venv/Scripts/python.exe tools/rebuild_index.py [--ids 1,2,3] [--dry-run]
"""
import argparse
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import parser, storage  # noqa: E402

import httpx  # noqa: E402

BASE = Path(__file__).resolve().parent.parent.parent.parent
DB_PATH = os.environ.get("WEICHAT_VAULT_DB") or str(
    BASE / "DATA" / "db" / "wechat_vault.db"
)


def _extract_page_content(old_html: str) -> str:
    """从旧 index.html 的 #page-content 提取正文。
    兼容两种情况：正常正文 / 嵌套整页（html/body 包装）。"""
    m = re.search(r'<div id="page-content">(.*?)</div>\s*</body>', old_html, re.S)
    if not m:
        return ""
    raw = m.group(1)
    # 嵌套整页：page-content 内还有 <html> → 取其中 body 的全部子元素
    inner = re.search(r"<html.*?<body[^>]*>(.*?)</body>\s*</html>", raw, re.S)
    if inner:
        return inner.group(1)
    return raw


def rebuild_inplace(row: dict, dry: bool = False) -> str:
    """原地重建一篇 index.html，返回状态说明。目录路径不变。"""
    hp = row.get("html_path") or ""
    if not hp or not os.path.exists(hp):
        return f"SKIP id={row['id']}: html_path 不存在"
    d = Path(hp).parent
    src = d / "source.html"
    if not src.exists():
        return f"SKIP id={row['id']}: 无 source.html"
    with open(src, encoding="utf-8", errors="ignore") as f:
        full_html = f.read()
    parsed = parser.parse_article(full_html, url="")
    content_html = parsed.get("content_html") or ""

    # 兜底 1：parser 提取失败 → 用旧 index.html 的正文（保留已本地化图片）
    if not content_html:
        with open(hp, encoding="utf-8", errors="ignore") as f:
            old = f.read()
        content_html = _extract_page_content(old)
    # 兜底 2：仍然为空（如风控验证页）→ 跳过，不破坏原文件
    if not content_html or "verify.html" in full_html:
        return f"SKIP id={row['id']}: 无正文（source 疑似验证页/残缺页）"

    images_dir = d / "images"
    css_dir = d / "css"
    images_dir.mkdir(exist_ok=True)
    css_dir.mkdir(exist_ok=True)

    localized = storage.localize_images(content_html, images_dir)
    localized = storage._force_js_content_visible(localized)
    try:
        with httpx.Client(
            timeout=15, headers=storage._fetch_headers(), follow_redirects=True
        ) as client:
            styles = storage.collect_styles(full_html, css_dir, client)
    except Exception:  # noqa: BLE001
        styles = storage._FALLBACK_CSS

    safe_title = (re.sub(r"[<>&\"']", "", row.get("title") or "") or "文章").strip()
    head_meta_parts = []
    for label, val in (("作者", row.get("author") or ""), ("公众号", row.get("source") or "")):
        if val:
            head_meta_parts.append(
                f'<span class="art-meta-item"><span class="art-meta-label">{label}</span>'
                f'<span class="art-meta-val">{re.sub(r"[<>&\"\']", "", val)}</span></span>'
            )
    pt = row.get("publish_time")
    if pt:
        try:
            dt = datetime.fromtimestamp(int(pt), tz=timezone.utc)
            head_meta_parts.append(
                f'<span class="art-meta-item"><span class="art-meta-label">发布于</span>'
                f'<span class="art-meta-val">{dt.strftime("%Y-%m-%d")}</span></span>'
            )
        except Exception:  # noqa: BLE001
            pass
    head_meta = "".join(head_meta_parts) or ""
    art_head = (
        f'<div class="art-head"><h1 class="art-title">{safe_title}</h1>'
        + (f'<div class="art-meta">{head_meta}</div>' if head_meta else "")
        + "</div>"
    )
    index_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{safe_title}</title>
<style>
{styles}
.art-head{{max-width:677px;margin:0 auto;padding:28px 16px 8px}}
.art-title{{margin:0 0 12px;font-size:22px;line-height:1.4;color:#1a1a1a;font-weight:700;word-break:break-word}}
.art-meta{{font-size:13px;color:#999;display:flex;flex-wrap:wrap;gap:6px 16px}}
.art-meta-label{{color:#bbb;margin-right:4px}}
#page-content{{max-width:677px;margin:0 auto;padding:8px 16px 40px}}
</style>
</head>
<body>
{art_head}
<div id="page-content">{localized}</div>
</body>
</html>
"""
    if dry:
        return f"DRY id={row['id']}: 将重建 {d.name}"
    storage._write_text_robust(d / "index.html", index_html)
    return f"OK   id={row['id']}: 重建 {d.name}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default="", help="只处理指定 id（逗号分隔）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    if args.ids:
        ids = [int(x) for x in args.ids.split(",") if x.strip()]
        ph = ",".join("?" * len(ids))
        rows = conn.execute(
            f"SELECT id, title, author, source, publish_time, html_path FROM articles WHERE id IN ({ph})",
            ids,
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, title, author, source, publish_time, html_path FROM articles WHERE html_path IS NOT NULL"
        ).fetchall()
    conn.close()

    ok = skip = 0
    for row in rows:
        msg = rebuild_inplace(dict(row), dry=args.dry_run)
        if msg.startswith("OK"):
            ok += 1
        else:
            skip += 1
        print(msg)
    print(f"\n完成：重建 {ok} 篇，跳过 {skip} 篇" + ("（dry-run，未写入）" if args.dry_run else ""))


if __name__ == "__main__":
    main()
