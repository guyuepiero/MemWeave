# -*- coding: utf-8 -*-
"""微文收纳 · 知识库 md 导出（B 方案：md + images/ 并排，相对路径引用图片）。

目标目录: 06_KNOWLEDGE/RAW/<公众号>/<日期>_<标题>/index.md + images/

- 正文: 从 index.html 提取 #js_content 容器 → html2text 转 md（保留图片相对路径）
- 清洗: 空标题行 / 行尾空格 / 连续空行 / 相邻图片拆行
- frontmatter: title / author / source / topic(多主题逗号分隔) / date / origin / album / link / appmsgid / biz
- 图片: 复制 images/ 目录，md 内相对路径引用（与 index.html 的 src 一致）

导出入口:
- export_one(article)  — 单篇（同步增量联动用）
- export_many(articles) — 批量（全量重建用）
"""
import re
import shutil
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup
import html2text

from .config import ARTICLES_DIR, EXPORT_DIR

_H = html2text.HTML2Text()
_H.body_width = 0
_H.ignore_images = False
_H.ignore_emphasis = False
_H.unicode_snob = True
_H.ignore_links = False
_H.protect_links = True


def _fmt_date(ts):
    if not ts:
        return ""
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d")
    except Exception:
        return ""


def _slug(s: str, max_len: int = 60) -> str:
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", s).strip(" .")
    return s[:max_len] or "untitled"


def _extract_body(html_path: Path) -> str:
    """从 index.html 提取 #js_content 正文容器的 HTML（去掉头部作者/来源/日期噪音）。"""
    html = html_path.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "lxml")
    node = soup.select_one("#js_content") or soup.select_one(".rich_media_content")
    if node is None:
        return html  # 兜底：无正文容器则退回全页
    return str(node)


def _clean_md(md: str) -> str:
    """压缩连续空行、行尾多余空格、清理空标题、图片连排拆行。"""
    md = re.sub(r"[ \t]+\n", "\n", md)
    md = re.sub(r"\n{3,}", "\n\n", md)
    md = re.sub(r"^\s*#+\s*$", "", md, flags=re.M)  # 空标题行（微信空 h 标签）
    md = re.sub(r"(\!\[[^\]]*\]\([^)]+\))(?=!\[)", r"\1\n", md)  # 相邻图片拆行
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()


def _build_md(article: dict, body_md: str) -> str:
    """拼 frontmatter + 标题 + 正文。topic 多主题逗号分隔，未打输出「无」。"""
    topics = article.get("topics") or []
    topic_str = ", ".join(t.get("name", "") for t in topics if t.get("name")) if topics else "无"
    album = article.get("album_name") or ""
    lines = [
        "---",
        f"title: {article.get('title','')}",
        f"author: {article.get('author','') or ''}",
        f"source: {article.get('source','')}",
        f"topic: {topic_str}",
        f"date: {_fmt_date(article.get('publish_time'))}",
        "origin: 微信公众号",
        f"album: {album}",
        f"link: {article.get('link','')}",
        f"appmsgid: {article.get('appmsgid','')}",
        f"biz: {article.get('biz','')}",
        "---",
        "",
        f"# {article.get('title','')}",
        "",
        body_md,
    ]
    return "\n".join(lines)


def export_one(article: dict, force: bool = False) -> dict:
    """导出单篇到 RAW。返回 {ok, md_path, images, error}。article 需含 get_article 全字段。

    force=False（默认）时做增量判断：目标 index.md 已存在且 appmsgid 一致 → 跳过
    （不重读、不重拷图片，全量重建/定期同步时省大量 IO）；冲突（目录被同名文章占用）
    → 自动追加 appmsgid 后缀分流。force=True 强制重写。
    """
    try:
        html_path = Path(article.get("html_path") or "")
        images_dir = Path(article.get("images_dir") or "")
        sub = _slug(article.get("source") or "unknown")
        title_slug = _slug(article.get("title", ""))
        title_dir = f"{_fmt_date(article.get('publish_time')) or '0000-00-00'}_{title_slug}"
        out_dir = EXPORT_DIR / sub / title_dir
        msgid = str(article.get("appmsgid") or "").strip()
        md_file = out_dir / "index.md"

        # 增量跳过：已导出且同一篇文章（appmsgid 相同）→ 直接返回，不重复 IO
        if not force and md_file.exists():
            head = md_file.read_text(encoding="utf-8", errors="ignore")[:400]
            m = re.search(r"^appmsgid:\s*(\S+)", head, re.M)
            if m and m.group(1) == msgid:
                return {"ok": True, "md_path": str(md_file), "images": 0, "skipped": True}
            # 冲突：目录被不同 appmsgid 的文章占用 → 追加后缀分流
            if msgid:
                out_dir = EXPORT_DIR / sub / f"{title_dir}_{msgid}"
                md_file = out_dir / "index.md"
        out_dir.mkdir(parents=True, exist_ok=True)

        if html_path.exists():
            body_html = _extract_body(html_path)
            body_md = _clean_md(_H.handle(body_html))
        else:
            body_md = (article.get("content_md") or "").strip()

        md_text = _build_md(article, body_md)
        md_file.write_text(md_text, encoding="utf-8")

        n_img = 0
        if images_dir.exists():
            img_target = out_dir / "images"
            if img_target.exists():
                shutil.rmtree(img_target)
            shutil.copytree(images_dir, img_target)
            n_img = len(list(img_target.iterdir()))

        return {"ok": True, "md_path": str(md_file), "images": n_img}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "md_path": ""}


def export_many(articles: list[dict]) -> dict:
    """批量导出。返回 {ok, count, failed}。"""
    ok = 0
    failed = []
    for a in articles:
        r = export_one(a)
        if r["ok"]:
            ok += 1
        else:
            failed.append({"id": a.get("id"), "error": r.get("error", "")})
    return {"ok": ok, "count": len(articles), "failed": failed}
