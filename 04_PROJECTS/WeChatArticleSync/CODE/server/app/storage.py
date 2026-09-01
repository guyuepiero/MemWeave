"""微文收纳 · 文章文件落盘：图片本地化 + 样式收集（100% 还原）"""
import hashlib
import re
import time
from datetime import datetime
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from .config import ARTICLES_DIR, REFERER, UA

_IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

# 兜底样式：外部样式表全部下载失败时，仍保证可读的排版
_FALLBACK_CSS = """
body{margin:0;padding:0;font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;font-size:16px;line-height:1.75;color:#3f3f3f}
#page-content{max-width:677px;margin:0 auto;padding:24px 16px}
img{max-width:100%;height:auto!important}
section{word-break:break-word}
blockquote{border-left:4px solid #eee;margin:1em 0;padding:0 1em;color:#888}
"""


def _write_text_robust(path: Path, text: str) -> Path:
    """写入文本；遇到文件被外部进程锁定（如文件监视器/OneDrive）时重试，
    仍失败则写时间戳变体文件，保证同步永不因锁失败。返回实际写入路径。"""
    for _ in range(5):
        try:
            path.write_text(text, encoding="utf-8")
            return path
        except PermissionError:
            time.sleep(0.3)
    alt = path.with_name(f"{path.stem}_{datetime.now().strftime('%H%M%S')}{path.suffix}")
    alt.write_text(text, encoding="utf-8")
    return alt


def _fetch_headers() -> dict:
    return {"Referer": REFERER, "User-Agent": UA}


def localize_images(content_html: str, images_dir: Path) -> str:
    """下载 mmbiz.qpic.cn 图片到 images_dir，改写 img src 为相对路径。

    失败时保留原始 data-src/src，保证正文不丢图。
    """
    soup = BeautifulSoup(content_html, "html.parser")
    imgs = soup.find_all("img")
    if not imgs:
        return content_html

    with httpx.Client(timeout=15, headers=_fetch_headers(), follow_redirects=True) as client:
        for img in imgs:
            src = img.get("src") or img.get("data-src")
            if not src or not src.startswith(("http://", "https://")):
                continue
            ext = Path(src.split("?")[0]).suffix.lower()
            if ext not in _IMG_EXT:
                ext = ".jpg"
            name = hashlib.md5(src.encode()).hexdigest()[:16] + ext
            dest = images_dir / name
            if not dest.exists():
                try:
                    r = client.get(src)
                    r.raise_for_status()
                    dest.write_bytes(r.content)
                except Exception:
                    continue
            img["src"] = f"images/{name}"
            if img.has_attr("data-src"):
                del img["data-src"]
            img["data-local"] = "1"
    return str(soup)


# 外部样式表内存缓存（URL -> 内容）：微信多篇文章共用同一批 res.wx.qq.com 样式，
# 进程内只下载一次即可；不落盘，避免产生 css/ 死文件（样式已内联进 index.html）。
_CSS_CACHE: dict[str, bytes] = {}


def collect_styles(full_html: str, css_dir: Path, client: httpx.Client) -> str:
    """收集页面样式：<head> 内联 <style> + 下载外部样式表，返回可内联的 CSS 文本。
    css_dir 参数保留仅为兼容旧调用（不再落盘，外部样式只进内存缓存）。"""
    soup = BeautifulSoup(full_html, "html.parser")
    parts = []

    # 1. 内联 style 块
    for st in soup.find_all("style"):
        text = st.get_text()
        if text.strip():
            parts.append(text)

    # 2. 外部样式表（res.wx.qq.com 等，带 Referer 下载；进程内缓存，不落盘）
    for link in soup.find_all("link", {"rel": "stylesheet"}):
        href = (link.get("href") or "").strip()
        if not href:
            continue
        if href.startswith("//"):
            href = "https:" + href
        if not href.startswith(("http://", "https://")):
            continue
        try:
            blob = _CSS_CACHE.get(href)
            if blob is None:
                r = client.get(href)
                r.raise_for_status()
                blob = r.content
                _CSS_CACHE[href] = blob
            parts.append(f"/* {href} */\n{blob.decode('utf-8', errors='ignore')}")
        except Exception:
            parts.append(f"/* 外部样式 {href} 下载失败，已跳过 */")

    parts.append(_FALLBACK_CSS)
    # 保险：离线无 JS，正文容器内联的 visibility:hidden/opacity:0 必须强制可见
    parts.append(
        "#js_content{visibility:visible!important;opacity:1!important}"
        "#page-content{visibility:visible!important;opacity:1!important}"
    )
    return "\n".join(parts)


def _force_js_content_visible(content: str) -> str:
    """微信正文容器 #js_content 内联了 visibility:hidden;opacity:0（页面靠 JS 显示）。
    离线版无 JS → 必须清掉这两个内联样式，否则打开是白屏。"""
    def _fix(m):
        tag = m.group(0)
        sm = re.search(r'style="([^"]*)"', tag)
        if sm:
            s = re.sub(r'visibility\s*:\s*hidden\s*;?', '', sm.group(1))
            s = re.sub(r'opacity\s*:\s*0\s*;?', '', s)
            s = s.strip().rstrip(';').strip()
            tag = tag[:sm.start(1)] + s + tag[sm.end(1):]
        return tag
    return re.sub(r'<div[^>]*id="js_content"[^>]*>', _fix, content, count=1)


def save_article_files(biz: str, appmsgid: str, full_html: str, content_html: str, title: str = "", idx: int = 0, author: str = "", source: str = "", publish_time: int | None = None) -> dict:
    """落盘：
      - source.html  微信原始完整页面（100% 保真）
      - index.html   样式内联 + 图片本地化的可离线浏览还原版（含文章头部：标题/作者/公众号/时间）
      - images/ css/ 本地化资源

    返回 {html_path, images_dir}

    目录命名 {公众号名}/{appmsgid}_{idx}/（2026-08-28 起：公众号名优先，biz 兜底；
    历史目录均为 biz 命名，已于 2026-08-28 全量重命名为公众号名）：
    微信 appmsgid 是群发批次号，同批次多图文（idx=1/2/3）是不同文章，
    若目录不含 idx 会互相覆盖文件。idx=0 时保持无后缀（兼容历史目录）。
    """
    # 目录名：公众号名优先（source），无名称时回退 biz；统一清洗非法字符
    dir_name = source or biz
    safe_dir = re.sub(r"[^A-Za-z0-9_\-\u4e00-\u9fff]", "_", dir_name) or "unknown"
    safe_msgid = re.sub(r"[^A-Za-z0-9_-]", "_", appmsgid) or "unknown"
    sub = f"{safe_msgid}_{idx}" if idx else safe_msgid
    d = ARTICLES_DIR / safe_dir / sub
    d.mkdir(parents=True, exist_ok=True)
    images_dir = d / "images"
    images_dir.mkdir(exist_ok=True)
    # 不再创建 css/ 目录：外部样式已改为内存内联（见 collect_styles），避免 css 死文件冗余

    # 原始完整页面（被锁则写变体，返回实际路径）
    source_path = _write_text_robust(d / "source.html", full_html)

    # 图片本地化（仅正文区域）
    localized_content = localize_images(content_html or full_html, images_dir)
    # 离线无 JS：清除正文容器内联的 visibility:hidden / opacity:0（否则白屏）
    localized_content = _force_js_content_visible(localized_content)

    # 样式收集
    try:
        with httpx.Client(timeout=15, headers=_fetch_headers(), follow_redirects=True) as client:
            styles = collect_styles(full_html, css_dir, client)
    except Exception:
        styles = _FALLBACK_CSS

    safe_title = (re.sub(r"[<>&\"']", "", title) or "文章").strip()
    # 文章头部（标题 / 作者 / 公众号 / 时间），与微信原文头部信息一致
    head_meta_parts = []
    for label, val in (("作者", author), ("公众号", source)):
        if val:
            head_meta_parts.append(
                f'<span class="art-meta-item"><span class="art-meta-label">{label}</span>'
                f'<span class="art-meta-val">{re.sub(r"[<>&\"\']", "", val)}</span></span>'
            )
    if publish_time:
        try:
            from datetime import datetime, timezone
            dt = datetime.fromtimestamp(int(publish_time), tz=timezone.utc)
            head_meta_parts.append(
                f'<span class="art-meta-item"><span class="art-meta-label">发布于</span>'
                f'<span class="art-meta-val">{dt.strftime("%Y-%m-%d")}</span></span>'
            )
        except Exception:  # noqa: BLE001
            pass
    head_meta = "".join(head_meta_parts) or ""
    art_head = (
        f'<div class="art-head">'
        f'<h1 class="art-title">{safe_title}</h1>'
        f'{"<div class=\"art-meta\">" + head_meta + "</div>" if head_meta else ""}'
        f'</div>'
    )
    index_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{safe_title}</title>
<style>
{styles}
/* 文章头部（离线还原版自绘，与微信原文头部信息一致） */
.art-head{{max-width:677px;margin:0 auto;padding:28px 16px 8px}}
.art-title{{margin:0 0 12px;font-size:22px;line-height:1.4;color:#1a1a1a;font-weight:700;word-break:break-word}}
.art-meta{{font-size:13px;color:#999;display:flex;flex-wrap:wrap;gap:6px 16px}}
.art-meta-label{{color:#bbb;margin-right:4px}}
#page-content{{max-width:677px;margin:0 auto;padding:8px 16px 40px}}
</style>
</head>
<body>
{art_head}
<div id="page-content">{localized_content}</div>
</body>
</html>
"""
    index_path = _write_text_robust(d / "index.html", index_html)

    return {"html_path": str(index_path), "images_dir": str(images_dir)}
