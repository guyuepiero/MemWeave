"""微文收纳 · 本地文件解析（付费文章补录用）：PDF / XPS / Word → 正文 HTML

策略（按源格式尽可能还原）：
- PDF/XPS 优先提取文字层：用 PyMuPDF get_text("html") 保留字号/颜色样式；
  同时提取页内图片（get_images）落盘 images/ 插入正文
- 无文字层（微信导出常为图片型）→ 每页渲染为高清 PNG（220dpi）整页嵌入，排版 100% 保真
- Word（.docx）→ 段落 + 内嵌图片提取
"""
import io
import re
from pathlib import Path

_DPI = 220  # 渲染 dpi：220 放大仍清晰（120 时文字过小）


def _esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _paragraphs_to_html(paragraphs: list[str], images: list[str] | None = None) -> str:
    """段落列表 → <p> HTML；图片列表在文首插入（每张一行居中）。"""
    out = []
    for img in images or []:
        out.append(f'<p style="text-align:center"><img src="{img}" style="max-width:100%"></p>')
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        p = re.sub(r"\n+", "\n", p)
        out.append(f"<p>{_esc(p).replace(chr(10), '<br>')}</p>")
    return "\n".join(out)


# ---------- PDF / XPS ----------
def _fitz_extract_rich(data: bytes, filetype: str, images_dir: Path) -> tuple[str, bool]:
    """用 PyMuPDF 提取文档正文（带样式 HTML + 页内图片）。

    返回 (html, has_text)：has_text=False 表示无文字层（图片型文档，调用方应渲染整页）。
    文字 HTML 用 fitz get_text("html") 保留字号/颜色；图片用 get_images 提取落盘 images/。
    """
    import fitz

    try:
        doc = fitz.open(stream=data, filetype=filetype)
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"无法解析文件（可能已损坏或加密）：{e}") from e

    pages_html: list[str] = []
    img_rels: list[str] = []
    total_text_len = 0
    try:
        for pi, page in enumerate(doc):
            # 页内图片提取（get_images → extract_image）
            try:
                for img in page.get_images(full=True):
                    xref = img[0]
                    try:
                        info = doc.extract_image(xref)
                        ext = info.get("ext", "png")
                        if ext not in ("png", "jpg", "jpeg", "gif", "webp"):
                            ext = "png"
                        name = f"doc_img_{pi + 1:02d}_{xref}.{ext}"
                        (images_dir / name).write_bytes(info["image"])
                        img_rels.append(f"images/{name}")
                    except Exception:  # noqa: BLE001
                        continue
            except Exception:  # noqa: BLE001
                pass
            # 文字层 HTML（带字号/颜色样式）
            try:
                page_html = page.get_text("html") or ""
            except Exception:  # noqa: BLE001
                page_html = ""
            # 文字量判定：只统计纯文本长度（HTML 骨架不算文字，否则图片型 PDF 会误判有文字）
            try:
                plain_len = len((page.get_text("text") or "").strip())
            except Exception:  # noqa: BLE001
                plain_len = 0
            total_text_len += plain_len
            if page_html.strip():
                pages_html.append(page_html)
    finally:
        doc.close()

    # 文字量过少（< 40 字）判定图片型文档
    if total_text_len < 40:
        return "", False

    # 组装：图片集中插在每页 HTML 前（保序大致对应原文）
    html = ""
    for i, ph in enumerate(pages_html):
        page_imgs = [r for r in img_rels if f"_{i + 1:02d}_" in r]
        for r in page_imgs:
            html += f'<p style="text-align:center"><img src="{r}" style="max-width:100%"></p>'
        html += _normalize_fitz_html(ph)
    # 未被页面序号匹配的图片（如 xref 名称不规整）追加文末
    used = {r for r in img_rels if f"_{i + 1:02d}_" in r for i in range(len(pages_html))}
    for r in img_rels:
        if r not in used:
            html += f'<p style="text-align:center"><img src="{r}" style="max-width:100%"></p>'
    return html, True


def _normalize_fitz_html(page_html: str) -> str:
    """把 fitz get_text("html") 的绝对定位 HTML 转成语义化段落流。

    fitz 输出 <p style="top:..pt;left:..pt;line-height:..pt"><span style="font-size:..pt">text</span></p>
    ——绝对定位在流式布局会重叠，这里去掉定位、按字号把大字号段落升为标题。
    """
    import re as _re

    body = _re.search(r"<body[^>]*>(.*?)</body>", page_html, _re.S)
    src = body.group(1) if body else page_html
    out = []
    for m in _re.finditer(
        r"<p[^>]*>(.*?)</p>", src, _re.S
    ):
        inner = m.group(1)
        # 字号在 span 的 style 里（font-size:..pt）
        fs = _re.search(r"font-size:([\d.]+)pt", inner)
        size = float(fs.group(1)) if fs else 12.0
        # 提取文本
        text = _re.sub(r"<[^>]+>", "", inner)
        text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&#xb7;", "·")
        text = text.strip()
        if not text:
            continue
        # 大字号（>=17pt）视为标题；14-16 视为小标题；其余正文
        if size >= 17:
            out.append(f"<h3>{_esc(text)}</h3>")
        elif size >= 14:
            out.append(f"<h4>{_esc(text)}</h4>")
        else:
            out.append(f"<p>{_esc(text)}</p>")
    return "\n".join(out)


def _fitz_render_pages(data: bytes, filetype: str, images_dir: Path, prefix: str) -> list[str]:
    """无文字层文档：每页渲染为高清 PNG（_DPI），返回 images/ 相对路径列表。"""
    import fitz
    doc = fitz.open(stream=data, filetype=filetype)
    rels = []
    try:
        for i, page in enumerate(doc):
            pix = page.get_pixmap(dpi=_DPI)
            name = f"{prefix}_page_{i + 1:02d}.png"
            (images_dir / name).write_bytes(pix.tobytes("png"))
            rels.append(f"images/{name}")
    finally:
        doc.close()
    return rels


def parse_pdf(data: bytes, images_dir: Path | None = None) -> str:
    """PDF → HTML。优先文字层（样式+图片），图片型则渲染整页（保真）。"""
    if images_dir is None:
        raise ValueError("缺少图片目录，无法解析 PDF")
    images_dir.mkdir(parents=True, exist_ok=True)
    html, has_text = _fitz_extract_rich(data, "pdf", images_dir)
    # 有文字层但提取后正文为空（如纯图形页的 HTML 骨架）→ 退回整页渲染
    if has_text and html.strip():
        return html
    try:
        rels = _fitz_render_pages(data, "pdf", images_dir, "pdf")
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"PDF 渲染失败（可能已损坏或加密）：{e}") from e
    if not rels:
        raise ValueError("PDF 无内容可提取")
    return _paragraphs_to_html([], rels)


def parse_xps(data: bytes, images_dir: Path | None = None) -> str:
    """XPS → HTML（微信「另存为」可选 XPS 文档）。优先文字层，否则每页渲染图片保真。"""
    if images_dir is None:
        raise ValueError("缺少图片目录，无法解析 XPS")
    images_dir.mkdir(parents=True, exist_ok=True)
    html, has_text = _fitz_extract_rich(data, "xps", images_dir)
    if has_text and html.strip():
        return html
    try:
        rels = _fitz_render_pages(data, "xps", images_dir, "xps")
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"XPS 渲染失败（可能已损坏）：{e}") from e
    if not rels:
        raise ValueError("XPS 无内容可提取")
    return _paragraphs_to_html([], rels)


# ---------- Word ----------
def _is_tiny_image(blob: bytes, ext: str, min_side: int = 30) -> bool:
    """判断图片是否为极小装饰图（微信转 Word 夹带的图标/分隔条/序号符号），
    宽或高 < min_side 即视为装饰图跳过，避免正文被一堆小图标干扰。
    仅解析图片头部尺寸，不引入 PIL 依赖：
    - PNG: 签名8字节 + IHDR长度4 + "IHDR"4 + 宽4 + 高4（偏移16~24，大端）
    - JPEG: 扫描 SOF0/SOF2 marker 读宽高（偏移+3,+5）
    """
    try:
        if ext == ".png" and blob[:8] == b"\x89PNG\r\n\x1a\n" and len(blob) >= 24:
            w = int.from_bytes(blob[16:20], "big")
            h = int.from_bytes(blob[20:24], "big")
            return w < min_side or h < min_side
        if ext in (".jpg", ".jpeg") and len(blob) > 4 and blob[:2] == b"\xff\xd8":
            i = 2
            while i + 9 < len(blob):
                if blob[i] != 0xFF:
                    i += 1
                    continue
                marker = blob[i + 1]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3):
                    h = int.from_bytes(blob[i + 5:i + 7], "big")
                    w = int.from_bytes(blob[i + 7:i + 9], "big")
                    return w < min_side or h < min_side
                if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                    i += 2
                    continue
                seg_len = int.from_bytes(blob[i + 2:i + 4], "big")
                if seg_len < 2:
                    break
                i += 2 + seg_len
    except Exception:  # noqa: BLE001
        pass
    return False


def parse_docx(data: bytes, images_dir: Path | None = None) -> str:
    """Word → HTML 段落 + 内嵌图片（按文档 rId 引用顺序，顺序与原文一致）。

    docx 内图片顺序由 rId 引用关系决定（非 zip 文件名排序！），
    必须遍历文档流时读 a:blip 的 r:embed → related_parts[rId] 取图。
    """
    from docx import Document
    from docx.oxml.ns import qn

    try:
        doc = Document(io.BytesIO(data))
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"无法解析 Word 文件（可能已损坏或不是有效的 .docx）：{e}") from e

    if images_dir is not None:
        images_dir.mkdir(parents=True, exist_ok=True)
    body = doc.element.body
    from docx.text.paragraph import Paragraph as _P

    out: list[str] = []
    img_counter = 0
    # 已落盘图片缓存（同一 rId 复用，避免重复写文件）
    saved: dict[str, str] = {}

    def _save_rid_img(rid: str) -> str | None:
        """按 rId 保存图片到 images_dir，返回相对路径；失败返回 None。
        跳过 1x1 占位图（微信转 Word 常夹带 140 字节的透明占位点）。"""
        nonlocal img_counter
        if rid in saved:
            return saved[rid]
        if images_dir is None:
            return None
        try:
            part = doc.part.related_parts.get(rid)
            if part is None:
                return None
            blob = part.blob
            pname = str(part.partname)  # /word/media/image5.jpeg
            ext = Path(pname).suffix.lower() or ".png"
            if ext not in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"):
                ext = ".png"
            # 极小装饰图过滤（图标/分隔条/序号符号，宽或高 <30px 跳过）
            if _is_tiny_image(blob, ext):
                return None
            img_counter += 1
            name = f"docx_img_{img_counter:02d}{ext}"
            (images_dir / name).write_bytes(blob)
            rel = f"images/{name}"
            saved[rid] = rel
            return rel
        except Exception:  # noqa: BLE001
            return None

    for child in body.iterchildren():
        if child.tag != qn("w:p"):
            continue
        para = _P(child, doc)
        # 段落内图片（w:drawing / w:pict 的 a:blip）→ 按 rId 顺序插入
        for blip in child.findall(".//" + qn("a:blip")):
            rid = blip.get(qn("r:embed"))
            if rid:
                rel = _save_rid_img(rid)
                if rel:
                    out.append(f'<p style="text-align:center"><img src="{rel}" style="max-width:100%"></p>')
        text = para.text.strip()
        if not text:
            continue
        style = (para.style.name or "").lower() if para.style else ""
        runs = []
        for r in para.runs:
            t = _esc(r.text)
            if r.bold:
                t = f"<b>{t}</b>"
            if r.italic:
                t = f"<i>{t}</i>"
            runs.append(t)
        inner = "".join(runs) or _esc(text)
        if "heading" in style or "标题" in style:
            level = re.search(r"(\d+)", style)
            lvl = int(level.group(1)) if level else 1
            tag = f"h{min(lvl + 1, 4)}"
            out.append(f"<{tag}>{inner}</{tag}>")
        elif "list" in style or "列表" in style:
            out.append(f"<p>• {inner}</p>")
        else:
            out.append(f"<p>{inner}</p>")
    if not out:
        raise ValueError("未能从 Word 文件中解析出正文内容")
    return "\n".join(out)


def parse_file(filename: str, data: bytes, images_dir: Path | None = None) -> str:
    """按扩展名分发解析，返回 HTML 正文。不支持的类型抛 ValueError。"""
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return parse_pdf(data, images_dir)
    if ext in (".xps", ".oxps"):
        return parse_xps(data, images_dir)
    if ext in (".docx", ".doc"):
        if ext == ".doc":
            raise ValueError("暂不支持 .doc 老格式，请在 Word 中另存为 .docx 后上传")
        return parse_docx(data, images_dir)
    raise ValueError(f"不支持的文件类型 {ext}，请上传 PDF、XPS 或 Word（.docx）文件")
