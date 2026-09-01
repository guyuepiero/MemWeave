"""微文收纳 · REST API"""
import asyncio
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel, Field
import httpx

from . import db, exporters, service, syncer
from .config import ARTICLES_DIR, EXPORT_DIR

router = APIRouter(prefix="/api")


def _local_url(a: dict) -> str:
    """由 html_path 得到可浏览的本地 URL（/files/...），图片相对路径可用。"""
    p = a.get("html_path") or ""
    if not p:
        return ""
    try:
        rel = Path(p).resolve().relative_to(ARTICLES_DIR.resolve())
        return "/files/" + rel.as_posix()
    except ValueError:
        return ""


def _remove_article_files(row: dict) -> list[str]:
    """删除该文章的本地文件目录 articles/{biz}/{appmsgid}/（带路径守卫）。"""
    html = row.get("html_path") or ""
    if not html:
        return []
    try:
        art_dir = Path(html).resolve().parent
        base = ARTICLES_DIR.resolve()
        if art_dir == base or base not in art_dir.parents:
            return [f"跳过：路径不在文章库内 {art_dir}"]
        rel = art_dir.relative_to(base)
        # 目录名 = 公众号名（中文/字母数字/下划线/连字符）或 biz；文章目录 = appmsgid[_idx]
        if len(rel.parts) != 2 or not all(re.fullmatch(r"[A-Za-z0-9_\-\u4e00-\u9fff]+", p) for p in rel.parts):
            return [f"跳过：非标准文章目录 {art_dir}"]
        if art_dir.exists():
            shutil.rmtree(art_dir)
            return [str(art_dir)]
        return [f"{art_dir}（不存在，跳过）"]
    except Exception as e:  # noqa: BLE001
        return [f"文件清理失败（可能被占用）：{e}"]


class SyncArticleIn(BaseModel):
    url: str = ""
    html: str = ""
    title: str = ""
    author: str = ""
    biz: str = ""
    appmsgid: str = ""
    idx: int = 0
    publish_time: int | None = None
    source: str = ""
    cover: str = ""
    topic_id: int | None = None


class ResolveIn(BaseModel):
    link: str


class ExportIn(BaseModel):
    format: str = Field(pattern="^(md|html|json|excel|txt|docx)$")
    biz: str = ""
    topic_id: int = 0
    ids: list[int] = []


class ArticlePatchIn(BaseModel):
    topic_id: int | None = None
    attrs: dict | None = None
    album_id: str | None = None
    paid_unlocked: bool | None = None


class ArticleContentIn(BaseModel):
    content_html: str = ""
    content_md: str = ""


class BatchTopicIn(BaseModel):
    ids: list[int] = []
    topic_id: int | None = None
    topic_ids: list[int] = []  # 多主题：追加式（不清旧关联）


class RemoveTopicIn(BaseModel):
    ids: list[int] = []
    topic_id: int | None = None


class TopicIn(BaseModel):
    name: str
    color: str = "#378ADD"
    parent_id: int = 0


class OpenFolderIn(BaseModel):
    target: str = "articles"  # articles | exports


class AlbumSyncIn(BaseModel):
    biz: str
    album_id: str
    scope: str = "all"
    start_date: str = ""
    mode: str = "all"


@router.get("/health")
def health():
    return {"ok": True, "articles": db.count_articles(), "accounts": len(db.list_accounts())}


# ---------- 公众号 ----------
@router.post("/accounts/resolve")
async def resolve_account(body: ResolveIn):
    try:
        info = await syncer.resolve_account_from_link(body.link)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"反查失败: {e}")
    return info


@router.get("/accounts")
def accounts():
    return db.list_accounts()


@router.post("/accounts/{biz}/sync")
async def sync_account(biz: str, scope: str = "all", start_date: str = "", mode: str = "all"):
    """触发历史同步（后台任务）。mode: all=全量 / incremental=增量。"""
    if not syncer.SESSIONS.get(biz):
        raise HTTPException(status_code=400, detail="请先在浏览器打开该公众号主页，让扩展捕获会话凭据")
    start_ts, end_ts = syncer.scope_to_range(scope, start_date)
    task_id = db.create_task("history", biz, scope=scope, mode=mode,
                             start_ts=start_ts, end_ts=end_ts, start_date=start_date)
    asyncio.create_task(syncer.run_task(task_id))
    return {"task_id": task_id, "status": "running", "biz": biz, "scope": scope, "mode": mode}


# ---------- 专辑 ----------
@router.post("/albums/sync")
async def sync_album(body: AlbumSyncIn):
    if not syncer.SESSIONS.get(body.biz):
        raise HTTPException(status_code=400, detail="尚未捕获该公众号的会话凭据：请先在浏览器打开该公众号的任意专辑页，让扩展自动捕获后再点同步")
    start_ts, end_ts = syncer.scope_to_range(body.scope, body.start_date)
    db.upsert_album(body.biz, body.album_id)
    task_id = db.create_task("album", body.biz, scope=body.scope, mode=body.mode,
                             album_id=body.album_id, start_ts=start_ts, end_ts=end_ts,
                             start_date=body.start_date)
    asyncio.create_task(syncer.run_task(task_id))
    return {"task_id": task_id, "status": "running", "album_id": body.album_id}


@router.get("/albums")
def albums(biz: str = ""):
    return db.list_albums(biz)


class SessionIn(BaseModel):
    biz: str
    key: str = ""
    uin: str = ""
    pass_ticket: str = ""
    appmsg_token: str = ""
    album_id: str = ""
    begin_msgid: str = ""
    cookie: str = ""
    ua: str = ""


@router.post("/sessions")
def import_session(body: SessionIn):
    """供 mitmproxy 插件（电脑版微信抓包）推送真实会话；也会自动续跑暂停任务。"""
    if not body.biz:
        raise HTTPException(status_code=400, detail="缺少 biz")
    acc = db.get_account(body.biz)
    syncer.SESSIONS[body.biz] = body.model_dump()
    syncer.SESSIONS[body.biz]["account_name"] = (acc or {}).get("name", "")
    resumed = syncer.resume_paused(body.biz)
    return {"ok": True, "resumed": resumed}


@router.get("/sessions")
def sessions():
    """调试用：查看扩展已捕获的公众号会话（不含敏感值）。"""
    return [
        {"biz": b, "has_key": bool(s.get("key")), "has_cookie": bool(s.get("cookie"))}
        for b, s in syncer.SESSIONS.items()
    ]


@router.get("/sessions/debug")
def sessions_debug(biz: str = ""):
    """本地调试：导出完整会话（含 key/cookie），用于复现 getalbum/getmsg 请求。"""
    if biz:
        s = syncer.SESSIONS.get(biz)
        return s or {}
    return {b: {k: v for k, v in s.items() if k != "account_name"} for b, s in syncer.SESSIONS.items()}


# ---------- 任务 ----------
@router.get("/tasks")
def tasks(status: str = ""):
    rows = db.list_tasks(status=status)
    return [syncer.task_snapshot(r["id"]) for r in rows if syncer.task_snapshot(r["id"])]


@router.get("/tasks/{task_id}")
def task(task_id: int):
    snap = syncer.task_snapshot(task_id)
    if not snap:
        raise HTTPException(status_code=404, detail="任务不存在")
    return snap


@router.post("/tasks/{task_id}/cancel")
def cancel_task(task_id: int):
    mem = syncer.TASKS.get(task_id)
    if mem:
        mem["cancel"] = True
    db.update_task(task_id, status="cancelled")
    return {"ok": True}


@router.delete("/tasks/{task_id}")
def delete_task(task_id: int):
    """删除任务记录；运行中的先取消。"""
    mem = syncer.TASKS.get(task_id)
    if mem and mem.get("status") == "running":
        mem["cancel"] = True
        db.update_task(task_id, status="cancelled")
    db.delete_task(task_id)
    syncer.TASKS.pop(task_id, None)
    return {"ok": True}


@router.delete("/tasks")
def delete_tasks(status: str = "done"):
    """批量删除指定状态的任务记录（默认 done）。"""
    n = db.delete_tasks_by_status(status)
    for tid in [k for k, v in syncer.TASKS.items() if v.get("status") == status]:
        syncer.TASKS.pop(tid, None)
    return {"ok": True, "deleted": n}


# ---------- 文章 ----------
@router.post("/articles")
def sync_article(body: SyncArticleIn):
    """接收扩展捕获的文章（html 为文章正文/完整页面 HTML）。"""
    if not body.html and not body.url:
        raise HTTPException(status_code=400, detail="html 与 url 至少提供一个")
    payload = body.model_dump()
    res = service.sync_article_payload(payload)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error", "同步失败"))
    return res


@router.get("/articles")
def articles(biz: str = "", topic_id: str = "", q: str = "", limit: int = 500,
             author: str = "", source: str = "", date_from: str = "", date_to: str = "",
             include_total: str = "0", offset: int = 0, paid: str = "", album_id: str = "",
             topic_ids: str = ""):
    tid = int(topic_id) if str(topic_id).isdigit() else 0
    tids = [int(x) for x in str(topic_ids).split(",") if str(x).isdigit()] if topic_ids else None
    d1 = int(date_from) if str(date_from).isdigit() else 0
    d2 = int(date_to) if str(date_to).isdigit() else 0
    arts = db.list_articles(biz, tid, q, limit, author, source, d1, d2, offset, paid, album_id, topic_ids=tids)
    for a in arts:
        a["local_url"] = _local_url(a)
    if include_total == "1":
        total = db.count_articles_filtered(biz, tid, q, author, source, d1, d2, paid, topic_ids=tids)
        return {"items": arts, "total": total}
    return arts


@router.get("/articles/{article_id}")
def article(article_id: int):
    a = db.get_article(article_id)
    if not a:
        raise HTTPException(status_code=404, detail="文章不存在")
    a["local_url"] = _local_url(a)
    return a


@router.put("/articles/{article_id}")
def patch_article(article_id: int, body: ArticlePatchIn):
    attrs = json.dumps(body.attrs, ensure_ascii=False) if body.attrs is not None else None
    db.update_article(article_id, body.topic_id, attrs, album_id=body.album_id)
    if body.paid_unlocked is not None:
        db.update_paid_status(article_id, body.paid_unlocked)
    return {"ok": True}


def _rebuild_article_content(row: dict, content_html: str, content_md: str = "") -> str:
    """重建文章本地 index.html（含文章头部 + 正文；图片本地化），返回 html_path。
    供「粘贴补录」「文件上传补录」共用。"""
    from pathlib import Path

    hp = row.get("html_path") or ""
    d = Path(hp).parent if hp else None
    if not d:
        raise ValueError("文章无本地目录，无法补录")
    import re as _re
    from . import storage as _storage

    images_dir = d / "images"
    images_dir.mkdir(exist_ok=True)
    localized = _storage.localize_images(content_html, images_dir)
    localized = _storage._force_js_content_visible(localized)
    with httpx.Client(timeout=15, headers=_storage._fetch_headers(), follow_redirects=True) as c:
        styles = _storage.collect_styles(content_html, d / "css", c)  # css 不落盘，仅兼容签名
    safe_title = (_re.sub(r"[<>&\"']", "", row.get("title") or "") or "文章").strip()
    author = row.get("author") or ""
    source = row.get("source") or ""
    head_meta = ""
    parts = []
    for label, val in (("作者", author), ("公众号", source)):
        if val:
            parts.append(f'<span class="art-meta-item"><span class="art-meta-label">{label}</span><span class="art-meta-val">{_re.sub(r"[<>&\"\']", "", val)}</span></span>')
    if row.get("publish_time"):
        from datetime import datetime, timezone
        try:
            dt = datetime.fromtimestamp(int(row["publish_time"]), tz=timezone.utc)
            parts.append(f'<span class="art-meta-item"><span class="art-meta-label">发布于</span><span class="art-meta-val">{dt.strftime("%Y-%m-%d")}</span></span>')
        except Exception:  # noqa: BLE001
            pass
    if parts:
        head_meta = f'<div class="art-meta">{"".join(parts)}</div>'
    art_head = f'<div class="art-head"><h1 class="art-title">{safe_title}</h1>{head_meta}</div>'
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
/* ---- 图片拖拽调序（编辑模式）---- */
#imgEditBar{{position:fixed;right:16px;top:16px;z-index:9999;display:flex;flex-direction:column;gap:6px}}
#imgEditBar button{{padding:6px 12px;border:none;border-radius:6px;font-size:13px;cursor:pointer}}
#imgEditBar .go{{background:#378ADD;color:#fff}}
#imgEditBar .save{{background:#0e7a3d;color:#fff;display:none}}
#imgEditBar .cancel{{background:#eee;color:#555;display:none}}
body.img-edit img{{cursor:grab;border:2px dashed transparent;transition:border-color .15s}}
body.img-edit img.drag-over{{border-color:#ff7a00}}
body.img-edit img.dragging{{opacity:.5;border-color:#378ADD}}
body.img-edit #page-content img{{width:auto;max-width:100%}}
body.img-edit p.drop-before{{box-shadow:0 -3px 0 #ff7a00}}
body.img-edit p.drop-after{{box-shadow:0 3px 0 #ff7a00}}
</style>
</head>
<body>
{art_head}
<div id="page-content">{localized}</div>
<script>
(function(){{
  var bar = document.createElement('div');
  bar.id = 'imgEditBar';
  bar.innerHTML = '<button class="go" id="imgEditGo">调整图片</button><button class="save" id="imgEditSave">保存顺序</button><button class="cancel" id="imgEditCancel">取消</button>';
  document.body.appendChild(bar);
  var editing = false;
  var dragPara = null; // 正在拖拽的图片所在段落
  var content = document.getElementById('page-content');
  function allImgs(){{ return Array.prototype.slice.call(document.querySelectorAll('#page-content img')); }}
  function clearDropMarks(){{ content.querySelectorAll('p').forEach(function(p){{ p.classList.remove('drop-before', 'drop-after'); }}); }}
  function enableEdit(){{
    editing = true;
    document.body.classList.add('img-edit');
    document.getElementById('imgEditGo').style.display = 'none';
    document.getElementById('imgEditSave').style.display = 'inline-block';
    document.getElementById('imgEditCancel').style.display = 'inline-block';
    allImgs().forEach(function(im){{
      im.draggable = true;
      im.addEventListener('dragstart', function(e){{
        e.dataTransfer.setData('text/plain', 'img');
        dragPara = im.parentNode; // 图片所在段落整体拖动
        im.classList.add('dragging');
      }});
      im.addEventListener('dragend', function(){{
        im.classList.remove('dragging');
        dragPara = null;
        clearDropMarks();
      }});
    }});
    // 所有段落（图片段 + 文字段）都可作为拖放目标
    content.querySelectorAll('p').forEach(function(p){{
      p.addEventListener('dragover', function(e){{
        if (!editing || !dragPara || dragPara === p) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        var r = p.getBoundingClientRect();
        var before = e.clientY < r.top + r.height / 2;
        p.classList.remove('drop-before', 'drop-after');
        p.classList.add(before ? 'drop-before' : 'drop-after');
      }});
      p.addEventListener('dragleave', function(){{ p.classList.remove('drop-before', 'drop-after'); }});
      p.addEventListener('drop', function(e){{
        if (!editing || !dragPara || dragPara === p) return;
        e.preventDefault();
        clearDropMarks();
        var r = p.getBoundingClientRect();
        var before = e.clientY < r.top + r.height / 2;
        // 拖到段落上沿 → 插到段前；下沿 → 段后；同一段不处理
        if (before) p.parentNode.insertBefore(dragPara, p);
        else p.parentNode.insertBefore(dragPara, p.nextSibling);
        dragPara = null;
      }});
    }});
  }}
  function disableEdit(){{
    editing = false;
    document.body.classList.remove('img-edit');
    document.getElementById('imgEditGo').style.display = 'inline-block';
    document.getElementById('imgEditSave').style.display = 'none';
    document.getElementById('imgEditCancel').style.display = 'none';
    allImgs().forEach(function(im){{ im.draggable = false; }});
  }}
  document.getElementById('imgEditGo').addEventListener('click', enableEdit);
  document.getElementById('imgEditCancel').addEventListener('click', function(){{ location.reload(); }});
  document.getElementById('imgEditSave').addEventListener('click', function(){{
    var btn = document.getElementById('imgEditSave');
    btn.textContent = '保存中…';
    fetch('/api/articles/{article_id}/content-html', {{
      method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify({{html: content.innerHTML}})
    }}).then(function(r){{ return r.json(); }}).then(function(d){{
      btn.textContent = '✅ 已保存';
      setTimeout(function(){{ location.reload(); }}, 600);
    }}).catch(function(e){{
      btn.textContent = '保存失败';
      alert('保存失败: ' + e.message);
    }});
  }});
}})();
</script>
</body>
</html>
"""
    idx_path = _storage._write_text_robust(d / "index.html", index_html)
    # 同步生成 md（供导出/Obsidian 使用）
    from . import exporters as _exp
    md = (content_md or "").strip() or _exp.md_from_html(content_html)
    db.update_article_content(row.get("id"), md, content_html, str(idx_path))
    return str(idx_path)


@router.post("/articles/{article_id}/content")
def patch_article_content(article_id: int, body: ArticleContentIn):
    """补录付费解锁的完整正文：粘贴 HTML → 重建本地 index.html（工作台直接打开观看）。"""
    row = db.get_article(article_id)
    if not row:
        raise HTTPException(status_code=404, detail="文章不存在")
    content_html = (body.content_html or "").strip()
    if not content_html:
        raise HTTPException(status_code=400, detail="请粘贴解锁后的正文 HTML")
    try:
        idx_path = _rebuild_article_content(row, content_html, body.content_md or "")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"补录失败: {e}")
    return {"ok": True, "id": article_id, "html_path": idx_path}


@router.post("/articles/{article_id}/content-file")
async def patch_article_content_file(article_id: int, file: UploadFile = File(...)):
    """补录付费解锁的完整正文：上传 PDF / Word 文件（微信文章可另存为 PDF/Word）。
    解析文件内容 → 重建本地 index.html。"""
    row = db.get_article(article_id)
    if not row:
        raise HTTPException(status_code=404, detail="文章不存在")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="上传文件为空")
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件超过 20MB，请压缩后上传")
    try:
        from . import file_parse as _fp
        # 解析前先确定图片落盘目录（docx 内嵌图 / 图片型 PDF 渲染用）
        from pathlib import Path as _P
        images_dir = _P(row.get("html_path") or "").parent / "images" if row.get("html_path") else None
        content_html = _fp.parse_file(file.filename or "", data, images_dir)
        if not content_html.strip():
            raise ValueError("未能从文件中解析出正文内容（可能是扫描版 PDF，需另存为可复制文本的格式）")
        idx_path = _rebuild_article_content(row, content_html)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"文件解析失败: {e}")
    return {"ok": True, "id": article_id, "html_path": idx_path, "source": file.filename}


class ImageReorderIn(BaseModel):
    order: list[str]  # 目标顺序的图片文件名（images/docx_img_01.jpeg 这种相对路径）


def _read_index_html(article_id: int) -> tuple[dict, str, Path]:
    """读文章本地 index.html，返回 (row, html, 目录 Path)。"""
    from pathlib import Path as _P
    row = db.get_article(article_id)
    if not row:
        raise HTTPException(status_code=404, detail="文章不存在")
    hp = row.get("html_path") or ""
    d = _P(hp).parent if hp else None
    if not d or not (d / "index.html").exists():
        raise HTTPException(status_code=400, detail="文章无本地页面，无法调整图片顺序")
    return row, (d / "index.html").read_text(encoding="utf-8", errors="ignore"), d


@router.get("/articles/{article_id}/images")
def article_images(article_id: int):
    """列出文章本地页中按当前顺序排列的图片（含缩略图 URL）。"""
    import re as _re
    _, html, d = _read_index_html(article_id)
    # 匹配 <p><img src="images/xxx"></p> 结构（每图独立段落）
    imgs = _re.findall(r'<img src="(images/[^"]+)"', html)
    from fastapi.responses import JSONResponse
    items = []
    for i, src in enumerate(imgs, 1):
        fname = src.split("/")[-1]
        items.append({"idx": i, "file": fname, "src": src})
    return {"ok": True, "count": len(items), "items": items}


@router.post("/articles/{article_id}/images/reorder")
def reorder_article_images(article_id: int, body: ImageReorderIn):
    """按目标顺序重排文章本地页中的图片段落（<p><img></p> 整体移动）。"""
    import re as _re
    row, html, d = _read_index_html(article_id)
    order = [o.strip().replace("\\", "/") for o in body.order if o and o.strip()]
    if not order:
        raise HTTPException(status_code=400, detail="顺序列表为空")
    # 提取所有图片段落（<p ...><img src="images/xxx" .../></p>，含属性）
    pat = re.compile(r'<p[^>]*>\s*<img src="(images/[^"]+)"[^>]*/?>\s*</p>')
    blocks = pat.findall(html)
    if not blocks:
        raise HTTPException(status_code=400, detail="正文中没有可调整的图片")
    # 校验 order 与现有图片一一对应（允许子集：只调整提供的那些）
    src_by_file = {b.split("/")[-1]: b for b in blocks}
    unknown = [o for o in order if o.split("/")[-1] not in src_by_file]
    if unknown:
        raise HTTPException(status_code=400, detail=f"包含不存在的图片: {unknown[:3]}")
    # 目标顺序：order 中的按新序，其余保持原相对顺序
    ordered_srcs = [src_by_file[o.split("/")[-1]] for o in order]
    remaining = [b for b in blocks if b not in ordered_srcs]
    # 重建：非图片段落保持原位，图片段落按新序填充（保持每图段落结构一致）
    img_block_map = {}
    for m in pat.finditer(html):
        img_block_map[m.group(1)] = m.group(0)
    new_order_srcs = ordered_srcs + remaining
    new_order_blocks = [img_block_map[s] for s in new_order_srcs]

    def _replace(m: re.Match) -> str:
        return new_order_blocks.pop(0) if new_order_blocks else m.group(0)

    new_html = pat.sub(_replace, html)
    from . import storage as _storage
    _storage._write_text_robust(d / "index.html", new_html)
    return {"ok": True, "count": len(new_order_srcs), "items": [s.split("/")[-1] for s in new_order_srcs]}


class ContentHtmlIn(BaseModel):
    html: str


@router.post("/articles/{article_id}/content-html")
def patch_article_content_html(article_id: int, body: ContentHtmlIn):
    """整体替换文章正文（<div id=page-content> 内 HTML）——支持图片拖到任意段落前后。
    校验：新内容的图片必须都是原页面已有的（防注入新图片）。"""
    import re as _re
    _, html, d = _read_index_html(article_id)
    new_inner = (body.html or "").strip()
    if not new_inner:
        raise HTTPException(status_code=400, detail="内容为空")
    old_srcs = set(_re.findall(r'<img src="(images/[^"]+)"', html))
    new_srcs = set(_re.findall(r'<img src="(images/[^"]+)"', new_inner))
    if not new_srcs:
        raise HTTPException(status_code=400, detail="正文中没有图片")
    unknown = new_srcs - old_srcs
    if unknown:
        raise HTTPException(status_code=400, detail=f"包含未知图片: {sorted(unknown)[:3]}")
    # 图片数量一致（防丢图）
    if len(_re.findall(r'<img', new_inner)) != len(_re.findall(r'<img', html)):
        raise HTTPException(status_code=400, detail="图片数量不一致，操作已取消")
    # 用 BeautifulSoup 精准替换 page-content 内容（保留其余结构）
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    pc = soup.find(id="page-content")
    if pc is None:
        raise HTTPException(status_code=400, detail="未找到正文容器")
    new_div = BeautifulSoup(f'<div id="page-content">{new_inner}</div>', "html.parser").div
    pc.replace_with(new_div)
    from . import storage as _storage
    _storage._write_text_robust(d / "index.html", str(soup))
    return {"ok": True}


class SyncLinkIn(BaseModel):
    url: str
    album_id: str = ""


@router.post("/articles/sync-link")
async def sync_article_link(body: SyncLinkIn):
    """单篇链接同步：抓取文章页 → 解析 → 入库；可指定归属专辑（用于手动归档）。"""
    url = (body.url or "").strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="请提供有效的文章链接")
    try:
        # 优先用已有会话（浏览器捕获的 cookie），无会话则匿名抓取公开页
        from urllib.parse import parse_qs, urlparse
        q = parse_qs(urlparse(url).query)
        biz = (q.get("__biz") or [""])[0]
        session = syncer.SESSIONS.get(biz) if biz else None
        html = await service.fetch_article_page(url, session)
        payload = {"url": url, "html": html, "album_id": body.album_id}
        res = service.sync_article_payload(payload)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"同步失败: {e}")
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error", "同步失败"))
    return res


@router.post("/articles/batch-topic")
def batch_topic(body: BatchTopicIn):
    """批量设置文章主题。

    - 传 topic_ids（数组）→ 追加式：在现有主题上增加，不清旧关联
    - 仅传 topic_id（单个，兼容旧前端）→ 覆盖式设置为单主题；0/None 表示清除
    """
    if not body.ids:
        raise HTTPException(status_code=400, detail="未选择文章")
    if body.topic_ids:
        n = db.batch_append_topics(body.ids, body.topic_ids)
        return {"ok": True, "updated": n, "mode": "append"}
    n = db.batch_set_topic(body.ids, body.topic_id)
    return {"ok": True, "updated": n, "mode": "replace"}


@router.post("/articles/batch-remove-topic")
def batch_remove_topic(body: RemoveTopicIn):
    """批量移除文章的指定主题（多主题下的「取消某个主题」）。topic_id=None 表示清空全部。"""
    if not body.ids:
        raise HTTPException(status_code=400, detail="未选择文章")
    if body.topic_id:
        n = sum(db.remove_article_topic(aid, body.topic_id) for aid in body.ids)
        return {"ok": True, "removed": n, "mode": "remove"}
    n = db.batch_clear_topics(body.ids)
    return {"ok": True, "cleared": n, "mode": "clear"}


@router.delete("/articles/{article_id}")
def delete_article(article_id: int):
    row = db.delete_article(article_id)
    if not row:
        raise HTTPException(status_code=404, detail="文章不存在")
    removed = _remove_article_files(row)
    return {"ok": True, "removed_files": removed}


@router.delete("/accounts/{biz}")
def delete_account(biz: str):
    """删除公众号及其全部文章（DB 记录 + 本地文件，路径守卫）。"""
    result = db.delete_account(biz)
    if not result:
        raise HTTPException(status_code=404, detail="公众号不存在")
    acc = result["account"]
    removed = []
    for row in result["articles"]:
        removed += _remove_article_files(row)
    # 清理空目录（articles/{公众号名或biz}/）：文章文件已在上方逐篇删除
    acc_name = (acc.get("name") or "").strip()
    for candidate in [acc_name, biz]:
        if not candidate:
            continue
        biz_dir = ARTICLES_DIR / re.sub(r"[^A-Za-z0-9_\-\u4e00-\u9fff]", "_", candidate)
        try:
            if biz_dir.exists() and biz_dir.is_dir():
                remaining = [p for p in biz_dir.iterdir()]
                if not remaining:
                    biz_dir.rmdir()
                    removed.append(f"{biz_dir}（空目录已清理）")
        except Exception as e:  # noqa: BLE001
            removed.append(f"目录清理失败: {e}")
    return {
        "ok": True,
        "deleted_articles": len(result["articles"]),
        "account": acc.get("name") or acc.get("biz", ""),
        "removed_files": removed,
    }


# ---------- 导出 ----------
@router.post("/export")
def export(body: ExportIn):
    if body.ids:
        articles = [db.get_article(i) for i in body.ids]
        articles = [a for a in articles if a]
        tag = "filtered"  # 导出「当前筛选结果」，目录名标识 filtered
    else:
        articles = db.list_articles(biz=body.biz, topic_id=body.topic_id)
        tag = body.biz or (f"topic_{body.topic_id}" if body.topic_id else "all")
    if not articles:
        raise HTTPException(status_code=400, detail="没有可导出的文章")
    try:
        result = exporters.run_export(body.format, articles, tag=tag)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


# ---------- 主题 ----------
@router.get("/topics")
def topics():
    return db.list_topics()


@router.post("/topics")
def add_topic(body: TopicIn):
    tid = db.create_topic(body.name, body.color, body.parent_id)
    return {"id": tid, "name": body.name, "color": body.color, "parent_id": body.parent_id}


@router.delete("/topics/{topic_id}")
def remove_topic(topic_id: int):
    n = db.delete_topic(topic_id)
    return {"ok": True, "deleted": n}


@router.get("/facets")
def facets(paid: str = "", author: str = "", source: str = "", album_id: str = "",
           topic_id: str = "", date_from: str = "", date_to: str = "", topic_ids: str = ""):
    """筛选用：各维度「剩余可选」列表，任意筛选条件全联动（付费/作者/来源/专辑/主题/日期）。
    规则：某维度自身条件不参与该维度自身列表过滤（已选值保留在下拉中），其余维度互相过滤。"""
    tids = [int(x) for x in str(topic_ids).split(",") if str(x).isdigit()] if topic_ids else None
    return db.list_facets(paid, author, source, album_id,
                          int(topic_id) if str(topic_id).isdigit() else 0,
                          int(date_from) if str(date_from).isdigit() else 0,
                          int(date_to) if str(date_to).isdigit() else 0,
                          topic_ids=tids)


@router.post("/open-folder")
def open_folder(body: OpenFolderIn):
    """在系统文件管理器中打开本地数据目录（文章库 / 导出），便于用户核验同步真实性。"""
    p = EXPORT_DIR if body.target == "exports" else ARTICLES_DIR
    p.mkdir(parents=True, exist_ok=True)
    try:
        if os.name == "nt":
            subprocess.Popen(["explorer", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
        return {"ok": True, "path": str(p)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "path": str(p)}
