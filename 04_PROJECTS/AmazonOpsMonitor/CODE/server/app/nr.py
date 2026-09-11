# -*- coding: utf-8 -*-
"""节点「新品榜 New Releases」可用性判定 + 本地缓存（2026-09-11）

为什么需要
----------
Amazon 只有部分浏览节点提供 New Releases 榜单。无榜节点打开
/gp/new-releases/<slug>/<node> 仍返回 200 且 <title> 正常，但商品网格是空的。
工作台详情卡此前一刀切按热销榜模板拼 URL，于是对这类节点给出一个
"看似正常、打开是空榜"的死链（如 Wire Strippers node 553398）。

判定原理（2026-09-11 实测校准：7 节点 × 热销/新品 × 纯 HTTP / 浏览器 双通道）
----------------------------------------------------------------------------
  有榜页  HTML 含 div.zg-grid-general-faceout ≈ 31  （服务端直出，无需 JS）
  无榜页  同 URL 仍 200、title 仍带类目名，网格为空（仅 1 个占位）→ tiles ≤ 1
  ⇒ tiles >= MIN_TILES(3) 判「有榜」；tiles <= 2 判「无榜」
  被验证码 / 网络拦截 → has=None(unknown)，**不写缓存**，下次再试（避免误判成无榜）

【坑·2026-09-11 已排除，勿再犯】title 里的类目名出现 "undefined" ≠ 节点无效：
  真节点 553574(Ladder Racks) 的 **BSR 页有 15 个商品卡**，标题同样是 "Best undefined"；
  假节点 9999999999 的 title 也是 undefined。⇒ undefined 只代表 Amazon 没渲染出类目名，
  与节点有效/无效、有榜/无榜都无关。**判定只看 tiles，不要引入 title 判断。**

缓存文件: data/nr_index.json
  { "<slug>|<node>": {"has": true|false, "tiles": 31, "status": "ok|empty|...", "checked": "YYYY-MM-DD HH:MM"} }

CLI（在 CODE/server 目录下运行）:
  python -m app.nr list                      # 查看缓存
  python -m app.nr check home-improvement 553398
  python -m app.nr seed                      # 预热：已登记数据集节点 + 15 大类根节点
  python -m app.nr seed --refresh            # 强制重判
  python -m app.nr scan home-improvement --limit 200 --sleep 1.5   # 扫某大类（默认只扫叶子）
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:  # 包内引用（python -m app.nr / from .nr import ...）
    from .config import BTG_DIR, DATA_DIR, DATASET_NODES
except ImportError:  # 兜底：直接跑脚本
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.config import BTG_DIR, DATA_DIR, DATASET_NODES

NR_INDEX = DATA_DIR / "nr_index.json"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
TILE_MARK = "zg-grid-general-faceout"
MIN_TILES = 3           # 网格商品卡 ≥ 此数判「有榜」
TIMEOUT = 15            # 单次请求超时（秒）
_lock = threading.Lock()


def nr_url(slug: str, node: str) -> str:
    return f"https://www.amazon.com/gp/new-releases/{slug}/{node}"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _load_cache() -> dict:
    if not NR_INDEX.exists():
        return {}
    try:
        return json.loads(NR_INDEX.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(d: dict) -> None:
    tmp = NR_INDEX.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(NR_INDEX)


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def fetch(slug: str, node: str, timeout: int = TIMEOUT) -> dict:
    """纯 HTTP 判定（无需浏览器）。返回 {has, tiles, status, checked}；has=None 表示未判定。"""
    req = Request(nr_url(slug, node), headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "identity",
    })
    try:
        with urlopen(req, timeout=timeout) as r:
            html = r.read().decode("utf-8", "replace")
    except HTTPError as e:
        return {"has": None, "tiles": None, "status": f"http{e.code}", "checked": _now()}
    except (URLError, TimeoutError, OSError) as e:
        return {"has": None, "tiles": None, "status": f"net:{type(e).__name__}", "checked": _now()}
    if "Enter the characters you see below" in html:
        return {"has": None, "tiles": None, "status": "captcha", "checked": _now()}
    tiles = html.count(TILE_MARK)
    has = tiles >= MIN_TILES
    return {"has": has, "tiles": tiles, "status": "ok" if has else "empty", "checked": _now()}


def check(slug: str, node: str, refresh: bool = False) -> dict:
    """单节点判定（带缓存）。返回 {has, tiles, status, checked, cached, url}。"""
    key = f"{slug}|{node}"
    if not refresh:
        hit = _load_cache().get(key)
        if hit and hit.get("has") is not None:
            return {**hit, "cached": True, "url": nr_url(slug, node)}
    info = fetch(slug, node)
    if info.get("has") is not None:          # 只在确定时落缓存
        with _lock:
            cache = _load_cache()
            cache[key] = info
            _save_cache(cache)
    return {**info, "cached": False, "url": nr_url(slug, node)}


def bulk() -> dict:
    """全量缓存（前端 btgInit 一次拉取，用于整棵树的标记）。"""
    return _load_cache()


# ---------------- 预热 / 扫描 ----------------

def _index() -> list:
    return _load_json(BTG_DIR / "index.json", []) or []


def _slug_maps() -> dict:
    """key / titleEn / titleZh → slug 的宽松映射（数据集 cat 字段两种写法都见过）。"""
    m = {}
    for c in _index():
        for k in ("key", "titleEn", "titleZh"):
            if c.get(k) and c.get("slug"):
                m[c[k]] = c["slug"]
    return m


def seed_pairs() -> list:
    """预热清单：已登记数据集的节点 + 15 大类根节点。去重保序。"""
    m = _slug_maps()
    pairs = []
    for rec in (_load_json(DATASET_NODES, {}) or {}).values():
        node = str(rec.get("node") or "").strip()
        slug = m.get(rec.get("cat")) or (rec.get("cat") or "").strip()
        if node and slug:
            pairs.append((slug, node))
    for c in _index():
        if c.get("rootId") and c.get("slug"):
            pairs.append((c["slug"], str(c["rootId"])))
    seen, out = set(), []
    for p in pairs:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _iter_nodes(key: str, leaves_only: bool = True):
    d = _load_json(BTG_DIR / f"{key}.json", None)
    if not d:
        return
    stack = list(d.get("tree") or [])
    while stack:
        n = stack.pop()
        kids = n.get("children") or []
        if n.get("id") and (not leaves_only or not kids):
            yield str(n["id"])
        stack.extend(kids)


def run_pairs(pairs, refresh: bool = False, sleep: float = 1.2, log=print) -> dict:
    """顺序判定若干 (slug, node)，落缓存。返回统计。"""
    stat = {"ok": 0, "empty": 0, "unknown": 0, "total": len(pairs)}
    for slug, node in pairs:
        r = check(slug, node, refresh=refresh)
        if r.get("has") is True:
            stat["ok"] += 1
            flag = "有榜"
        elif r.get("has") is False:
            stat["empty"] += 1
            flag = "无榜"
        else:
            stat["unknown"] += 1
            flag = "未判定"
        log(f"[{flag}] {slug}/{node} tiles={r.get('tiles')} status={r.get('status')}")
        if not r.get("cached"):
            # 命中缓存=没发网络请求，无需限速 → 重跑时已判定节点瞬间跳过，直达断点
            time.sleep(sleep)
    return stat


def main(argv=None):
    ap = argparse.ArgumentParser(description="新品榜 New Releases 可用性判定")
    ap.add_argument("mode", choices=["list", "check", "seed", "scan"])
    ap.add_argument("args", nargs="*", help="check: <slug> <node>；scan: <类目key>")
    ap.add_argument("--refresh", action="store_true", help="忽略缓存强制重判")
    ap.add_argument("--limit", type=int, default=0, help="scan 最多判定多少个节点")
    ap.add_argument("--sleep", type=float, default=1.2, help="每次请求间隔秒（默认 1.2，勿调过小）")
    ap.add_argument("--all-nodes", action="store_true", help="scan 时含非叶子节点")
    a = ap.parse_args(argv)

    if a.mode == "list":
        c = bulk()
        for k, v in sorted(c.items()):
            print(f"{'有榜' if v.get('has') else '无榜'}  {k:34} tiles={v.get('tiles')} {v.get('checked')}")
        print(f"合计 {len(c)} 条；无榜 {sum(1 for v in c.values() if v.get('has') is False)} 条")
        return 0

    if a.mode == "check":
        if len(a.args) < 2:
            print("用法: python -m app.nr check <slug> <node>")
            return 2
        r = check(a.args[0], a.args[1], refresh=a.refresh)
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0

    if a.mode == "seed":
        pairs = seed_pairs()
        print(f"预热 {len(pairs)} 个节点…")
        print(json.dumps(run_pairs(pairs, refresh=a.refresh, sleep=a.sleep), ensure_ascii=False))
        return 0

    if a.mode == "scan":
        if not a.args:
            print("用法: python -m app.nr scan <类目key> [--limit N]")
            return 2
        key = a.args[0]
        slug = _slug_maps().get(key) or key
        nodes = list(_iter_nodes(key, leaves_only=not a.all_nodes))
        if a.limit:
            nodes = nodes[:a.limit]
        print(f"扫描 {key}（slug={slug}）{len(nodes)} 个节点…")
        print(json.dumps(run_pairs([(slug, n) for n in nodes], refresh=a.refresh, sleep=a.sleep),
                         ensure_ascii=False))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
