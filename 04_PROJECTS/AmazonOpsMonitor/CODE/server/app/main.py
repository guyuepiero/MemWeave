"""亚马逊运营监控台 · FastAPI 入口
访问: http://127.0.0.1:21889

- 页面: app/static/index.html (选品分析工作台, 内联数据兜底)
- API:  /api/data  返回 data/ 目录下主数据集 JSON（前端 fetch 优先，失败回退内联）
- API:  /api/btg/* 类目选品树（索引 / 分片 / 选品标记 / 爬取队列 / 立即采集）
- 托盘: tray.py 负责常驻管理 (pythonw 无窗口运行)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
import webbrowser
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

from .config import (
    BTG_DIR,
    BTG_PROGRESS,
    BTG_QUEUE,
    DATA_DIR,
    DATASET_NODES,
    HOST,
    OUTPUTS_DIR,
    PORT,
    SCRAPER_PY,
    SCRAPER_SCRIPT,
    SERVER_DIR,
    STATIC_DIR,
    URL,
)
from . import nr as nr_mod   # 新品榜(New Releases)可用性判定：部分节点 Amazon 不提供该榜

app = FastAPI(title="亚马逊运营监控台", version="0.1.0")

# 数据完整性阈值（2026-09-11）：同步入库前校验，低于此线判为「空榜/抓取异常」不入库
MIN_OK_RATIO = 0.2      # 目标条数的 20%
MIN_OK_ABS = 10         # 且绝对条数不低于 10

# 类目子路径 → BSR 榜单 slug 映射（Amazon bestsellers/<slug>/<node> 200 测试通过的别名）
# 来源：参考站与实测 hi / home-improvement / kitchen 均能 200；此处按 BTG 实际数据填 slug
_BTG_SLUG_MAP = {
    "Tools & Home Improvement": "home-improvement",
    "Home & Kitchen": "kitchen",
    "Industrial & Scientific": "industrial",
    "Sports & Outdoors": "sports",
    "Automotive": "automotive",
    "Health & Household": "hpc",
    "Beauty & Personal Care": "beauty",
    "Toys & Games": "toys-and-games",
    "Office Products": "office-products",
    "Grocery & Gourmet Food": "grocery",
    "Baby": "baby-products",
    "Pet Supplies": "pet-supplies",
    "Clothing, Shoes & Jewelry": "fashion",
    "Video Games": "videogames",
    "Arts, Crafts & Sewing": "arts-crafts",
}


def _resolve_slug(cat_name: str, node: str) -> str:
    """BTG 路径段 → BSR 榜单 slug。空/未知 → 'hi' 兜底（实测 200）。"""
    if not cat_name:
        return "hi"
    return _BTG_SLUG_MAP.get(cat_name, "hi")


# 立即采集任务表（内存，进程重启即丢；落盘以防需要可在 DATA_DIR/btg_runs.json）
_RUNS = {}  # run_id -> {status, started_at, finished_at, log_tail, exit_code, cmd, output_dir, items}
_RUNS_LOCK = threading.Lock()


@app.middleware("http")
async def _no_cache(request: Request, call_next):
    """本地工具一律禁缓存：避免改完前端浏览器仍拿旧版（微信工作台坑 19 同款对策）。"""
    resp = await call_next(request)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    return resp


def _atomic_write_json(path, obj):
    """原子写：先落 .tmp 再替换；写前若有旧文件留一份 .bak（数据安全）。"""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    if path.exists():
        try:
            path.replace(path.with_suffix(path.suffix + ".bak"))
        except Exception:  # pragma: no cover
            pass
    tmp.replace(path)


def _load_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # pragma: no cover
        return default


def _count_rows(path):
    """统计数据集条数（读失败返回 -1）。用于同步前比对，防止半成品覆盖好数据。"""
    try:
        j = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(j, dict):
            j = j.get("data") or j.get("list") or j.get("items") or []
        return len(j) if isinstance(j, list) else -1
    except Exception:
        return -1


def _latest_dataset():
    """取 data/ 目录主数据集: 优先 current.json, 否则最新修改的真数据集 .json。
    2026-09-09 修复(bug A): 跳过队列/进度/登记表等非数据集 json —— 此前 bsr_queue.json
    被采集流程 touch 到最新 mtime 后被误选, /api/data 返回空数组, 前端回退 9/3 内联旧数据。"""
    skip = {"btg_progress.json", "btg_progress.json.bak", "bsr_queue.json", "bsr_queue.json.bak",
            "dataset_nodes.json", "dataset_nodes.json.bak"}
    cand = []
    cur = DATA_DIR / "current.json"
    if cur.exists():
        cand.append(cur)
    for f in sorted(DATA_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        if f.name in skip or f.name == "current.json":
            continue
        cand.append(f)
    if not cand:
        return None
    return cand[0]


@app.get("/api/health")
def health():
    return {"ok": True, "service": "AmazonOpsMonitor", "port": PORT, "time": time.time()}


@app.get("/api/data")
def api_data(src: str = ""):
    """返回数据集。默认取 data/ 目录主数据集；传 src=文件名.json 可取指定数据集。"""
    if src:
        if not re.fullmatch(r"[\w\-. ]+\.json", src):
            return JSONResponse({"error": "非法文件名"}, status_code=400)
        f = DATA_DIR / src
        if not f.exists():
            return JSONResponse({"error": f"数据集不存在: {src}"}, status_code=404)
    else:
        f = _latest_dataset()
    if f is None:
        return JSONResponse({"error": "data/ 目录无数据集"}, status_code=404)
    try:
        rows = json.loads(f.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover
        return JSONResponse({"error": f"数据集解析失败: {exc}"}, status_code=500)
    if isinstance(rows, dict):
        rows = rows.get("data") or rows.get("list") or rows.get("items") or []
    meta = {
        "name": f.stem,
        "date": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d"),
        "src": f.name,
    }
    return {"meta": meta, "data": rows}


@app.get("/api/datasets")
def api_datasets():
    """扫描 data/ 下所有数据集，返回元信息清单 —— 类目树据此判断哪些类目已有本地数据。"""
    skip = {"btg_progress.json", "bsr_queue.json", DATASET_NODES.name, nr_mod.NR_INDEX.name}
    # 数据集 -> 类目节点绑定（爬虫产出纯数组无 meta 时，靠这张表登记 node）
    binds = _load_json(DATASET_NODES, {})
    out = []
    for f in sorted(DATA_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        if f.name in skip:
            continue
        try:
            j = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # pragma: no cover
            continue
        if isinstance(j, dict):
            meta = j.get("meta") or {}
            rows = j.get("data") or j.get("list") or j.get("items") or []
        else:
            meta, rows = {}, j
        if not isinstance(rows, list):
            continue
        meta = dict(meta)
        if not meta.get("node"):
            meta.update(binds.get(f.name) or {})
        rec = binds.get(f.name) or {}
        out.append({
            "src": f.name,
            "name": meta.get("name") or f.stem,
            "node": str(meta.get("node") or ""),
            "cat": meta.get("cat") or "",
            "sub": meta.get("sub") or "",
            "date": meta.get("date") or datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d"),
            "count": len(rows),
            "mtime": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
            # 2026-09-10 完整性：expected=采集目标条数（无登记则 0=未知）；incomplete=实际少于目标
            "expected": int(rec.get("expected") or 0),
            "incomplete": bool(rec.get("incomplete")) or bool(
                int(rec.get("expected") or 0) and len(rows) < int(rec.get("expected") or 0)),
            # 2026-09-08 详情卡细化：chart 区分 BSR热销榜/new新品榜；report 该数据集目录是否已有分析报告 .md
            "chart": _chart_of(f.name, rec),
            "has_report": _dataset_has_report(f.name, rec),
        })
    return out


# ---------------- 选品分析报告（s10 抽屉） ----------------
_REPORT_PAT = re.compile(r"(选品分析报告|分析报告|对比解读|双周对比|解读|report|报告)", re.IGNORECASE)
_REPORT_STOP = {"amazon", "bsr", "final", "data", "xlsx", "json", "csv", "分析", "选品", "报告"}


def _chart_of(src: str, rec: dict) -> str:
    """推断数据集榜单类型：登记 chart 优先，其次按文件名前缀 amazon_bsr_/amazon_new_。"""
    c = str(rec.get("chart") or "").lower()
    if c in ("bsr", "new"):
        return c
    if src.startswith("amazon_new_"):
        return "new"
    return "bsr" if src.startswith("amazon_bsr_") else ""


def _dataset_has_report(src: str, rec: dict) -> bool:
    """该数据集产物目录下是否已存在分析报告 .md（复用 api_report 定位策略的轻量版）。"""
    dirs = []
    sd = rec.get("src_dir")
    if sd and Path(sd).is_dir():
        dirs.append(Path(sd))
    else:
        stem = re.sub(r"\.json$", "", src).replace("-", "_")
        tokens = [t for t in stem.split("_") if t and t.lower() not in _REPORT_STOP]
        low_tokens = [t.lower() for t in tokens]
        sub = str(rec.get("sub") or "").split("/")[-1].lower()
        for d in OUTPUTS_DIR.iterdir():
            if not d.is_dir() or d.name.startswith("."):
                continue
            low = d.name.lower()
            hit = bool(low_tokens and any(t in low for t in low_tokens))
            if not hit and not low_tokens and sub and sub in low:
                hit = True
            if hit:
                dirs.append(d)
    pref_dir = "new_" if src.startswith("amazon_new_") else "bsr_" if src.startswith("amazon_bsr_") else ""
    if pref_dir:
        kept = [d for d in dirs if d.name.startswith(pref_dir)]
        if kept:
            dirs = kept
    for d in dirs:
        try:
            if any(_REPORT_PAT.search(p.name) for p in d.glob("*.md")):
                return True
        except Exception:
            continue
    return False


@app.get("/api/report")
def api_report(src: str = ""):
    """按数据集 src 在 07_OUTPUTS 定位其选品分析报告 .md（可能同节点多轮采集 -> 多目录，
    每目录取最新报告，整体按 mtime 降序返回，前端可切换）。

    定位策略：
    1. dataset_nodes.json 登记里的 src_dir（采集产物目录，采集自动写）直接扫描；
    2. 历史数据集无 src_dir -> 从数据集名抽核心词（去 amazon/bsr/_FINAL 后按 _ 拆），
       fuzzy 匹配 07_OUTPUTS 子目录名。
    """
    if not src:
        f = _latest_dataset()
        src = f.name if f else ""
    if not src or not re.fullmatch(r"[\w\-. ]+\.json", src):
        return JSONResponse({"error": "非法文件名"}, status_code=400)

    binds = _load_json(DATASET_NODES, {})
    rec = binds.get(src) or {}

    dirs: list[Path] = []
    sd = rec.get("src_dir")
    if sd and Path(sd).is_dir():
        dirs.append(Path(sd))
    else:
        stem = re.sub(r"\.json$", "", src).replace("-", "_")
        tokens = [t for t in stem.split("_") if t and t.lower() not in _REPORT_STOP]
        low_tokens = [t.lower() for t in tokens]
        sub = str(rec.get("sub") or "").split("/")[-1].lower()
        for d in OUTPUTS_DIR.iterdir():
            if not d.is_dir() or d.name.startswith("."):
                continue
            low = d.name.lower()
            hit = bool(low_tokens and any(t in low for t in low_tokens))
            if not hit and low_tokens and all(t in low for t in low_tokens):
                hit = True
            if not hit and not low_tokens and sub and sub in low:
                hit = True
            if hit:
                dirs.append(d)

    # 榜单前缀过滤：amazon_new_* 数据集只扫 new_* 目录（amazon_bsr_* 同理），防热销/新品报告互相污染
    pref_dir = ""
    if src.startswith("amazon_new_"):
        pref_dir = "new_"
    elif src.startswith("amazon_bsr_"):
        pref_dir = "bsr_"
    if pref_dir:
        kept = [d for d in dirs if d.name.startswith(pref_dir)]
        if kept:              # 目录名无前缀（旧登记）时回退不过滤，兼容历史
            dirs = kept

    reports = []
    for d in dirs:
        try:
            for p in sorted(d.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True):
                if not _REPORT_PAT.search(p.name):
                    continue
                st = p.stat()
                reports.append({
                    "dir": d.name,
                    "file": p.name,
                    "mtime": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
                    "size": st.st_size,
                    "text": p.read_text(encoding="utf-8", errors="replace"),
                })
        except Exception:
            continue
    reports.sort(key=lambda x: x["mtime"], reverse=True)
    if not reports:
        return {
            "dataset": src, "found": False,
            "note": "该数据集目录下未找到选品分析报告 .md。报告需在 WorkBuddy / 其他 AI 会话中调 amz-selection-engine 生成，"
                    "放入对应 07_OUTPUTS/<目录>/ 后，此抽屉即自动显示。",
        }
    return {"dataset": src, "found": True, "reports": reports}


# ---------------- 同类目跨期对比（数据集对比分析） ----------------
_compare_mod = None


def _compare_module():
    """懒加载 tools/compare.py（独立脚本模块，避免随 main.py 冷启动拖慢）。"""
    global _compare_mod
    if _compare_mod is None:
        import importlib.util

        p = SERVER_DIR / "tools" / "compare.py"
        spec = importlib.util.spec_from_file_location("compare_tool", p)
        _compare_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_compare_mod)
    return _compare_mod


def _valid_src(src: str) -> bool:
    return bool(src and re.fullmatch(r"[\w\-. ]+\.json", src))


def _load_two_srcs(src_a: str, src_b: str):
    """校验并读取 data/ 下两个数据集 -> (rows_a, rows_b, fa, fb)。"""
    if not _valid_src(src_a) or not _valid_src(src_b):
        raise ValueError("src_a/src_b 必须是 data/ 下的 .json 文件名")
    fa, fb = DATA_DIR / src_a, DATA_DIR / src_b
    if not fa.exists() or not fb.exists():
        raise FileNotFoundError(f"数据集不存在: {[p.name for p in (fa, fb) if not p.exists()]}")
    return json.loads(fa.read_text(encoding="utf-8")), json.loads(fb.read_text(encoding="utf-8")), fa, fb


def _compare_meta(src: str):
    """meta 不塞 date：引擎按 scraped_at 自动推导与定向（登记 date 偶与文件名不符）。"""
    rec = _load_json(DATASET_NODES, {}).get(src) or {}
    return {"name": rec.get("name") or "", "node": str(rec.get("node") or ""),
            "cat": rec.get("cat") or "", "sub": rec.get("sub") or "", "src": src}


@app.get("/api/btg/compare")
def api_btg_compare(src_a: str = "", src_b: str = ""):
    """同类目跨期对比。src_a/src_b = data/ 下两个数据集文件名（顺序不限，引擎自动按日期定旧→新）。
    返回 {a, b, market, churn, rankings, brands, detail, summary}。"""
    try:
        rows_a, rows_b, fa, fb = _load_two_srcs(src_a, src_b)
    except (ValueError, FileNotFoundError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": f"解析失败: {e}"}, status_code=500)
    try:
        out = _compare_module().compare(rows_a, rows_b, _compare_meta(src_a), _compare_meta(src_b))
    except Exception as e:
        return JSONResponse({"error": f"对比计算失败: {e}"}, status_code=500)
    if "error" in out:
        return JSONResponse({"error": out["error"]}, status_code=400)
    # detail 已含 kept 全部位移字段，去掉 rankings.all 冗余大表省流量
    out["rankings"].pop("all", None)
    out["a"]["src"], out["b"]["src"] = src_a, src_b
    binds = _load_json(DATASET_NODES, {})
    out["a"]["rec"], out["b"]["rec"] = binds.get(src_a) or {}, binds.get(src_b) or {}
    return out


@app.post("/api/btg/compare/export")
def api_btg_compare_export(payload: dict):
    """把两数据集对比导出为 Excel 归档（subprocess 走 SCRAPER_PY env 的 openpyxl）。
    body: {"src_a": "...json", "src_b": "...json"}
    产出: 07_OUTPUTS/<同批目录>/compare_<key>_<dateA>_vs_<dateB>.xlsx"""
    src_a = (payload or {}).get("src_a") or ""
    src_b = (payload or {}).get("src_b") or ""
    try:
        rows_a, rows_b, fa, fb = _load_two_srcs(src_a, src_b)
    except (ValueError, FileNotFoundError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": f"解析失败: {e}"}, status_code=500)
    binds = _load_json(DATASET_NODES, {})
    rec_a, rec_b = binds.get(src_a) or {}, binds.get(src_b) or {}
    try:
        out = _compare_module().compare(rows_a, rows_b, _compare_meta(src_a), _compare_meta(src_b))
    except Exception as e:
        return JSONResponse({"error": f"对比计算失败: {e}"}, status_code=500)
    if "error" in out:
        return JSONResponse({"error": out["error"]}, status_code=400)
    date_a, date_b = out["a"]["date"], out["b"]["date"]

    # 导出目录：优先登记 src_dir；都缺时按文件名前缀在 07_OUTPUTS 找 bsr_*/new_* 匹配目录
    out_dir = None
    for rec in (rec_a, rec_b):
        sd = rec.get("src_dir")
        if sd and Path(sd).is_dir():
            out_dir = Path(sd)
            break
    if out_dir is None:
        m = re.match(r"amazon_(bsr|new)_", src_a)
        pref = (m.group(1) + "_") if m else ""
        stem = re.sub(r"\.json$", "", src_a)
        toks = [t for t in re.sub(r"^amazon_(bsr|new)_", "", stem).split("_")
                if t and not re.fullmatch(r"\d{8}|FINAL", t)]
        cands = []
        for d in OUTPUTS_DIR.iterdir():
            if not d.is_dir() or d.name.startswith("."):
                continue
            if pref and not d.name.startswith(pref):
                continue
            if not pref and not (d.name.startswith("bsr_") or d.name.startswith("new_")):
                continue
            if toks and any(t.lower() in d.name.lower() for t in toks):
                cands.append(d)
        out_dir = cands[0] if cands else OUTPUTS_DIR
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        out_dir = OUTPUTS_DIR

    stem = re.sub(r"\.json$", "", src_a)
    key = re.sub(r"^amazon_(?:bsr|new)_", "", stem)
    key = re.sub(r"(?:_\d{8})?_FINAL$", "", key) or "data"
    out_name = f"compare_{key}_{date_a}_vs_{date_b}.xlsx"
    dest = out_dir / out_name
    if not SCRAPER_PY.exists():
        return JSONResponse({"error": f"导出环境缺失: {SCRAPER_PY}"}, status_code=500)
    tool = SERVER_DIR / "tools" / "compare_export.py"
    cmd = [str(SCRAPER_PY), str(tool), str(DATA_DIR / src_a), str(DATA_DIR / src_b), str(out_dir), out_name]
    try:
        no_win = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              creationflags=no_win, cwd=str(tool.parent), timeout=120)
    except Exception as e:
        return JSONResponse({"error": f"导出进程启动失败: {e}"}, status_code=500)
    if proc.returncode != 0 or not dest.exists():
        return JSONResponse({"error": f"导出失败: {proc.stdout[-400:]} {proc.stderr[-400:]}"}, status_code=500)
    return {"ok": True, "file": out_name, "dir": str(out_dir), "path": str(dest), "date_a": date_a, "date_b": date_b}


# ---------------- 类目选品树（BTG） ----------------
_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{0,40}$")


@app.get("/api/btg/index")
def btg_index():
    """15 个大类元信息（不含树体，约 2KB）。"""
    f = BTG_DIR / "index.json"
    if not f.exists():
        return JSONResponse({"error": "类目索引缺失，请先生成 data/btg/"}, status_code=404)
    return _load_json(f, [])


@app.get("/api/btg/tree/{key}")
def btg_tree(key: str):
    """返回单个大类的完整树（0.02~1.27MB，前端点开哪类才拉哪类）。"""
    if not _KEY_RE.match(key):
        return JSONResponse({"error": "非法类目 key"}, status_code=400)
    f = BTG_DIR / f"{key}.json"
    if not f.exists():
        return JSONResponse({"error": f"类目分片不存在: {key}"}, status_code=404)
    data = _load_json(f, None)
    if data is None:
        return JSONResponse({"error": "分片解析失败"}, status_code=500)
    return data


@app.get("/api/btg/nr-bulk")
def btg_nr_bulk():
    """新品榜可用性缓存全量：{"<slug>|<node>": {has,tiles,status,checked}}。
    前端 btgInit 一次拉取，用于给类目树/详情卡打「无新品榜」标记。"""
    return nr_mod.bulk()


@app.get("/api/btg/nr")
def btg_nr(node: str = "", slug: str = "", refresh: int = 0):
    """单节点新品榜可用性判定（带缓存；首次约 1~3s，之后命中缓存即时返回）。
    has=true 有榜 / false 无榜 / null 未判定（验证码、网络异常，不落缓存）。"""
    node, slug = (node or "").strip(), (slug or "").strip()
    if not node or not slug:
        return JSONResponse({"error": "node 与 slug 必填"}, status_code=400)
    return nr_mod.check(slug, node, refresh=bool(refresh))


@app.get("/api/btg/progress")
def btg_progress_get():
    """选品标记: {节点id: 状态}，状态 = none/follow/focus/skip。"""
    return _load_json(BTG_PROGRESS, {})


@app.post("/api/btg/progress")
def btg_progress_post(payload: dict):
    """全量保存选品标记。body: {"marks": {"9425951011": "focus", ...}}"""
    marks = (payload or {}).get("marks")
    if not isinstance(marks, dict):
        return JSONResponse({"error": "marks 必须是对象"}, status_code=400)
    ok = {}
    for k, v in marks.items():
        s = str(v or "none")
        if s not in ("none", "follow", "focus", "skip"):
            s = "none"
        ok[str(k)] = s
    _atomic_write_json(BTG_PROGRESS, ok)
    return {"ok": True, "count": len(ok)}


@app.get("/api/btg/queue")
def btg_queue_get():
    """待爬取节点队列（供 amazon_batch_v21.py 消费）。"""
    return _load_json(BTG_QUEUE, {"updated": None, "items": []})


@app.post("/api/btg/queue")
def btg_queue_post(payload: dict):
    """追加爬取队列，按 (node, chart) 去重（同节点可同时排队热销榜与新品榜）。
    body: {"items":[{node,cat,slug,path,query,chart,url_bsr,url_search}]}"""
    items = (payload or {}).get("items")
    if not isinstance(items, list):
        return JSONResponse({"error": "items 必须是数组"}, status_code=400)
    q = _load_json(BTG_QUEUE, {"updated": None, "items": []})
    old = {f"{str(it.get('node'))}:{it.get('chart') or 'bsr'}": it for it in (q.get("items") or [])}
    added = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        node = str(it.get("node") or "").strip()
        if not node.isdigit():
            continue
        chart = it.get("chart") or "bsr"
        if chart not in ("bsr", "new"):
            chart = "bsr"
        old[f"{node}:{chart}"] = {
            "node": node,
            "cat": it.get("cat") or "",
            "slug": it.get("slug") or "",
            "path": it.get("path") or "",
            "query": it.get("query") or "",
            "chart": chart,
            "url_bsr": it.get("url_bsr") or "",
            "url_search": it.get("url_search") or "",
            "status": old.get(f"{node}:{chart}", {}).get("status", "pending"),
            "added": old.get(f"{node}:{chart}", {}).get("added") or datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        added += 1
    out = {"updated": datetime.now().strftime("%Y-%m-%d %H:%M"), "items": list(old.values())}
    _atomic_write_json(BTG_QUEUE, out)
    return {"ok": True, "total": len(out["items"]), "added": added}


# ---------------- 立即采集（异步触发 amazon_batch_v21.py） ----------------


def _build_run_output_dir(cat: str, sub: str, count: int, chart: str = "bsr") -> Path:
    """产出目录：07_OUTPUTS/bsr_<子类>_<数量>/ 或 new_<子类>_<数量>/（不带日期，仿 bsr_cable_staples_100；
    采集日期进文件名，如 amazon_bsr_cable_staples_20260904_FINAL.json / amazon_new_..._FINAL.json）"""
    safe = lambda s: re.sub(r"[^A-Za-z0-9_]+", "_", str(s or "")).strip("_").lower() or "x"
    sub_tail = (sub or "").split("/")[-1] if sub else "node"
    pref = "new" if chart == "new" else "bsr"
    name = f"{pref}_{safe(sub_tail)}_{count}"
    d = OUTPUTS_DIR / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read_progress(path: str):
    """读 v21 进度文件尾行（每抓完一条 append 一行 JSON）。文件不存在/空/损坏返回 None。"""
    if not path:
        return None
    try:
        lines = [l for l in Path(path).read_text(encoding="utf-8", errors="ignore").splitlines() if l.strip()]
        if not lines:
            return None
        return json.loads(lines[-1])
    except Exception:
        return None


def _spawn_run(items: list, limit: int, pages: int) -> str:
    """启动 v21 子进程异步采集，返回 run_id。"""
    if not SCRAPER_SCRIPT.exists():
        raise FileNotFoundError(f"爬虫脚本不存在: {SCRAPER_SCRIPT}")
    if not SCRAPER_PY.exists():
        raise FileNotFoundError(f"爬虫 venv python 不存在: {SCRAPER_PY}")
    # 计算目录名（取第一个节点代表类目，多节点时分目录）
    first = items[0]
    cat = first.get("cat") or ""
    sub = first.get("path") or first.get("sub") or ""
    chart = first.get("chart") or "bsr"
    if chart not in ("bsr", "new"):
        chart = "bsr"
    # sub 是 "Tools & Home Improvement/Electrical/.../Cable Staples"，取最后一段作为 sub
    sub_tail = sub.split("/")[-1] if sub else first.get("sub") or "node"
    out_dir = _build_run_output_dir(cat, sub_tail, int(limit), chart)
    run_id = uuid.uuid4().hex[:12]
    log_path = out_dir / "run.log"
    progress_path = out_dir / "_progress.json"

    # 把队列临时写到 out_dir/_queue.json（避免污染 BTG_QUEUE）
    qtmp = out_dir / "_queue.json"
    qtmp.write_text(json.dumps({"updated": None, "items": items}, ensure_ascii=False, indent=1), encoding="utf-8")

    cmd = [
        str(SCRAPER_PY),
        str(SCRAPER_SCRIPT),
        "--mode", "btg-node",
        "--queue", str(qtmp),
        "--pages", str(pages),
        "--limit", str(limit),
        "--chart", chart,
        "--out", str(out_dir),
        "--delay", "3-8",
        "--progress-file", str(progress_path),
    ]
    # 进度文件清零（目录可能被多次 run 复用，防读到上次残留）
    try:
        progress_path.write_text("", encoding="utf-8")
    except Exception:
        pass
    log_f = open(log_path, "w", encoding="utf-8")

    def _runner():
        rec = {"run_id": run_id, "status": "running", "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
               "cmd": " ".join(cmd), "output_dir": str(out_dir), "log": str(log_path), "items": items,
               "chart": chart, "limit": limit, "pages": pages, "progress_path": str(progress_path)}
        with _RUNS_LOCK:
            _RUNS[run_id] = rec
        try:
            # CREATE_NO_WINDOW：pythonw 宿主下启动 v21 时禁止弹新 console 黑窗（2026-09-08 主公反馈）
            no_win = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            proc = subprocess.Popen(cmd, stdout=log_f, stderr=subprocess.STDOUT,
                                    creationflags=no_win,
                                    cwd=str(SCRAPER_SCRIPT.parent))
            exit_code = proc.wait()
            rec["exit_code"] = exit_code
            rec["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            rec["status"] = "done" if exit_code == 0 else "failed"
            # 采集完成：把 *_FINAL.json 复制到 server/data/ 并登记 dataset_nodes
            # 2026-09-10 修复（主公反馈）：中断/异常退出不再同步半成品；成功但条数不足 → 标记 incomplete 供前端警示
            if exit_code != 0:
                rec["sync_skipped"] = ("采集中断（exit=%s），未同步到 data/；已有数据集保持不变。"
                                       "产物保留在 %s" % (exit_code, out_dir))
            else:
                try:
                    for p in sorted(out_dir.glob("amazon_*_FINAL.json")):
                        # 从文件名提取榜单前缀与 sub_key（amazon_new_cable_staples_20260907_FINAL.json -> new/cable_staples）
                        m = re.match(r"amazon_(bsr|new)_(.+?)_\d{8}_FINAL", p.name)
                        if not m:
                            continue
                        pref, key = m.group(1), m.group(2)
                        it0 = items[0]
                        # 若多节点一次 run，用 key 找到对应 item；找不到回退首个
                        cur = next((x for x in items if re.sub(r"[^A-Za-z0-9_]+", "_", str((x.get("path") or x.get("sub") or "").split("/")[-1])).strip("_").lower() == key), None) or it0
                        sub_name = (cur.get("path") or cur.get("sub") or "node").split("/")[-1]
                        target = DATA_DIR / p.name      # 原名复制（修复 Path+str 拼接 bug）
                        cnt = _count_rows(p)
                        expected = int(limit or 0)
                        # 空榜/抓取异常防线（2026-09-11）：条数低于「目标的 20% 且至少 10 条」→ 判空榜，不入库
                        min_ok = max(MIN_OK_ABS, int(expected * MIN_OK_RATIO)) if expected else MIN_OK_ABS
                        if cnt < min_ok:
                            rec["sync_skipped"] = (rec.get("sync_skipped") or "") + \
                                f"{p.name}：仅 {cnt} 条 < 最低 {min_ok} 条（目标 {expected}），判为空榜/抓取异常，未入库；"
                            continue
                        # 防覆盖：新数据条数 < 已有数据集 → 保留旧数据，半成品不入库
                        old_cnt = _count_rows(target) if target.exists() else 0
                        if 0 <= cnt < old_cnt:
                            rec["sync_skipped"] = (rec.get("sync_skipped") or "") + \
                                f"{p.name}：新 {cnt} 条 < 现有 {old_cnt} 条，已保留原数据集；"
                            continue
                        shutil.copy2(p, target)
                        dn = _load_json(DATASET_NODES, {})
                        dn[p.name] = {
                            "name": sub_name,
                            "node": str(cur.get("node") or ""),
                            "cat": cur.get("cat") or cat,
                            "sub": sub_name,
                            "chart": pref,             # bsr=热销榜 / new=新品榜
                            "date": datetime.now().strftime("%Y-%m-%d"),
                            "src_dir": str(out_dir),   # 产物目录：选品分析报告（s10 抽屉）据此定位
                            # 完整性（2026-09-10）：expected=目标条数，count=实际，incomplete 供前端警示
                            "expected": expected,
                            "count": cnt,
                            "incomplete": bool(expected and cnt < expected),
                        }
                        _atomic_write_json(DATASET_NODES, dn)
                        rec["dataset_synced"] = str(target)
                except Exception as e:
                    rec["sync_error"] = str(e)
            # 标记队列项为 done
            try:
                q = _load_json(BTG_QUEUE, {"updated": None, "items": []})
                keys = {f"{str(it.get('node'))}:{chart}" for it in items}
                for it in q.get("items") or []:
                    if f"{str(it.get('node'))}:{it.get('chart') or 'bsr'}" in keys:
                        it["status"] = "done" if exit_code == 0 else "failed"
                        it["ran_at"] = rec["finished_at"]
                        it["output_dir"] = str(out_dir)
                _atomic_write_json(BTG_QUEUE, q)
            except Exception:
                pass
        except Exception as e:
            rec["status"] = "error"
            rec["error"] = str(e)
            rec["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        finally:
            log_f.close()
            # 日志尾部 80 行供前端查询
            try:
                tail = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()[-80:]
                with _RUNS_LOCK:
                    _RUNS[run_id]["log_tail"] = "\n".join(tail)
            except Exception:
                pass

    t = threading.Thread(target=_runner, daemon=True, name=f"btg-run-{run_id}")
    t.start()
    return run_id


@app.post("/api/btg/queue/run")
def btg_queue_run(payload: dict):
    """立即采集：body: {"items":[{node,cat,slug,path,query,chart,...}], "limit": 100, "pages": 2}
    异步启动 v21 子进程，落 07_OUTPUTS/amazon_bsr_<cat>_<sub>_<count>_<YYYYMMDD>/
    返回: {run_id, output_dir, cmd_preview}"""
    items = (payload or {}).get("items")
    if not isinstance(items, list) or not items:
        return JSONResponse({"error": "items 必须是非空数组"}, status_code=400)
    # 校验每个 item 必含 node（数字）
    clean = []
    for it in items:
        if not isinstance(it, dict):
            continue
        node = str(it.get("node") or "").strip()
        if not node.isdigit():
            continue
        clean.append({
            "node": node,
            "cat": it.get("cat") or "",
            "slug": (it.get("slug") or _resolve_slug(it.get("cat"), node)).strip(),
            "path": it.get("path") or "",
            "query": it.get("query") or "",
            # 榜单类型必须透传：漏了 _spawn_run 恒回退 bsr → 选新品榜也抓热销（2026-09-07/08 复现坑）
            "chart": it.get("chart") if it.get("chart") in ("bsr", "new") else "bsr",
        })
    if not clean:
        return JSONResponse({"error": "items 中无可用 node"}, status_code=400)
    limit = int((payload or {}).get("limit") or 100)
    pages = int((payload or {}).get("pages") or 2)
    try:
        run_id = _spawn_run(clean, limit, pages)
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    with _RUNS_LOCK:
        rec = _RUNS.get(run_id, {})
    return {"ok": True, "run_id": run_id, "output_dir": rec.get("output_dir"),
            "cmd_preview": rec.get("cmd"), "started_at": rec.get("started_at")}


@app.get("/api/btg/runs")
def btg_runs_list():
    """列出当前进程内所有采集 run（用于前端轮询）。"""
    with _RUNS_LOCK:
        items = []
        for rid, rec in _RUNS.items():
            items.append({
                "run_id": rid,
                "status": rec.get("status"),
                "started_at": rec.get("started_at"),
                "finished_at": rec.get("finished_at"),
                "output_dir": rec.get("output_dir"),
                "exit_code": rec.get("exit_code"),
                "limit": rec.get("limit"),
                "pages": rec.get("pages"),
                "chart": rec.get("chart"),
                "items": rec.get("items"),
                "log_tail": rec.get("log_tail"),
                "progress": _read_progress(rec.get("progress_path") or ""),
                "error": rec.get("error"),
                "sync_error": rec.get("sync_error"),
                "sync_skipped": rec.get("sync_skipped"),
                "dataset_synced": rec.get("dataset_synced"),
            })
        items.sort(key=lambda x: x.get("started_at") or "", reverse=True)
    return {"runs": items[:20]}


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn

    # 直接运行(调试/控制台): python -m app.main
    # 托盘模式由 tray.py 拉起，并控制是否自动开浏览器
    if os.environ.get("AMZ_MONITOR_OPEN_BROWSER", "0") == "1":
        threading.Timer(1.0, lambda: webbrowser.open(URL)).start()
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
