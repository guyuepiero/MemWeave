"""微文收纳 · 微信文章页解析（适配层 parsers/wechat）"""
import re
from typing import Optional

from bs4 import BeautifulSoup

# 微信对广告/推广文 meta author 常写死的泛化署名，不携带真实作者信息
_GENERIC_AUTHOR_WORDS = {"推广", "广告", "unknown", "未知", "佚名"}


def _js_var(html: str, name: str) -> Optional[str]:
    """提取页面内 var xxx = "..." 或 var xxx = 123"""
    m = re.search(r"var\s+" + name + r"\s*=\s*[\"']([^\"']*)[\"']", html)
    if m:
        return m.group(1).strip()
    m = re.search(r"var\s+" + name + r"\s*=\s*(\d+)", html)
    if m:
        return m.group(1).strip()
    return None


def _meta(soup: BeautifulSoup, key: str, attr: str = "property") -> Optional[str]:
    for tag in soup.find_all("meta"):
        if tag.get(attr) == key:
            return tag.get("content")
    return None


def parse_article(html: str, url: str = "") -> dict:
    """从公众号文章页 HTML 提取结构化信息。

    返回 dict：biz / appmsgid / idx / title / author / digest / link /
              cover / publish_time / source / content_html
    """
    soup = BeautifulSoup(html, "html.parser")
    biz = _js_var(html, "biz") or ""
    if not biz:
        m = re.search(r'__biz=([A-Za-z0-9=]+)', html)
        biz = m.group(1) if m else ""
    appmsgid = _js_var(html, "appmsgid") or ""
    idx = _js_var(html, "idx") or "0"
    # 兜底：JS 变量缺失时从 URL/HTML 的 mid/idx 参数提取（2026 微信页面 JS 变量常缺失）
    if (not appmsgid or idx == "0") and url:
        try:
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(url).query)
            if not appmsgid:
                appmsgid = q.get("mid", [""])[0] or ""
            if idx == "0" or not _js_var(html, "idx"):
                idx = q.get("idx", ["0"])[0] or "0"
        except Exception:  # noqa: BLE001
            pass
    nickname = _js_var(html, "nickname") or ""

    title = _meta(soup, "og:title") or ((soup.title.string or "").strip() if soup.title else "")
    digest = _meta(soup, "description", "name") or ""
    cover = _meta(soup, "og:image") or ""
    # 公众号名：优先页面内的 #js_name 元素，其次 nickname 变量
    js_name_el = soup.find(id="js_name")
    account_name = (js_name_el.get_text(strip=True) if js_name_el else "") or nickname or ""
    author = _meta(soup, "author", "name") or account_name or ""
    # 防御：微信广告文 meta author 常被标为"推广"等泛化词（无实际作者信息），
    # 此时回退为公众号名，避免作者下拉出现无意义孤值
    if author.strip() in _GENERIC_AUTHOR_WORDS:
        author = account_name
    publish_time = None
    ct = _js_var(html, "ct")
    if ct and ct.isdigit():
        publish_time = int(ct)
    if not publish_time:
        m = re.search(r'var\s+createTime\s*=\s*"?(\d+)"?', html)
        if m:
            publish_time = int(m.group(1))
    if not publish_time:
        em = soup.find(id="publish_time")
        if em:
            t = re.findall(r"\d{4}-\d{2}-\d{2}", em.get_text())
            if t:
                from datetime import datetime, timezone

                publish_time = int(
                    datetime.strptime(t[0], "%Y-%m-%d")
                    .replace(tzinfo=timezone.utc)
                    .timestamp()
                )

    content_div = soup.find(id="js_content")
    content_html = str(content_div) if content_div else ""

    # 付费文章识别：微信付费文有 js_pay_preview_filter / mp-pay-preview-filter 专属标签
    # （付费正文被预览过滤器截断，静态 HTML 不含完整内容）。
    # 注意：不能用 data-offset（普通文图片懒加载也用它）或 pay_subscribe（非付费文 JS 也含）
    is_paid = 1 if (
        "js_pay_preview_filter" in html
        or "mp-pay-preview-filter" in html
    ) else 0

    return {
        "biz": biz,
        "appmsgid": appmsgid,
        "idx": int(idx) if idx.isdigit() else 0,
        "title": title,
        "author": author,
        "digest": digest,
        "link": url,
        "cover": cover,
        "publish_time": publish_time,
        "source": account_name,
        "content_html": content_html,
        "is_paid": is_paid,
    }
