"""同类目跨时间数据集对比引擎（热销榜 BSR / 新品榜 NEW 通用）

输入：两个数据集行数组（列表，元素为 dict，字段与 amazon_batch_v21 产出 *_FINAL.json 一致）
输出：结构化对比 dict —— 大盘 / 榜单换血 / 排名变动 / 品牌变化 / 明细差异

口径说明（如实标注，不硬凑）：
- 榜单顺序 == bsr_sub 名次 == 采集当时排名（1 起步，即数组 index+1）
- 无 Amazon 官方绝对销量：monthly_sales 为文本档位（"1K+"/"500+"…），
  档下限 = 解析数字；档中值 = 下限 × 1.5（区间 [n, 2n) 均匀假设）。
  「大盘月销量/月销售额」均为该假设下的估算值，仅用于同口径相对趋势（升/降），非绝对值。
- 大盘主口径取「两期均在榜（overlap）的同批商品」对比，剔除榜单换血噪声；
  另附全榜口径（含换血影响）供参考。

用法：
    python compare.py <json_a> <json_b>            # CLI 自测：打印 summary
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

# ---------------- 解析 ----------------
_PRICE_RE = re.compile(r"\$\s*([\d,]+(?:\.\d+)?)")
_NUM_RE = re.compile(r"([\d,]+)")
_K_RE = re.compile(r"^\s*([\d.]+)\s*[Kk]\+\s*$", re.IGNORECASE)


def _txt(v) -> str:
    return "" if v is None else str(v)


def parse_price(v):
    """\"$6.99\" / 6.99 / 10,04 -> float | None"""
    m = _PRICE_RE.search(_txt(v))
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            return None
    try:
        f = float(_txt(v).strip().replace(",", "").replace("$", ""))
        return f
    except ValueError:
        return None


def parse_sales_lower(v):
    """月销文本档 -> 档下限 int | None（\"2K+\" -> 2000, \"400+\" -> 400, \"400\" -> 400）
    仅接受「纯数字 或 数字+K」的档位文本；含说明性文字的（如 400+/月）先剥离后缀。"""
    s = _txt(v).strip()
    if not s or s in ("—", "-", "N/A"):
        return None
    m = _K_RE.match(s)
    if m:
        try:
            return int(round(float(m.group(1)) * 1000))
        except ValueError:
            return None
    m = re.match(r"^\s*([\d,]+)\s*\+?\s*$", s)
    if m:
        try:
            return int(m.group(1).replace(",", ""))
        except ValueError:
            return None
    # 兜底：取首个数字串（如 "1,000+"），再失败则 None
    m = _NUM_RE.search(s)
    return int(m.group(1).replace(",", "")) if m else None


def parse_int(v):
    m = _NUM_RE.search(_txt(v))
    return int(m.group(1).replace(",", "")) if m else None


def parse_float(v):
    m = re.search(r"([\d.]+)", _txt(v))
    try:
        return float(m.group(1)) if m else None
    except ValueError:
        return None


def _badges(x) -> dict:
    ac = _txt(x.get("amazon_choice")).strip().lower()
    bb = _txt(x.get("bestseller_badge")).strip().lower()
    return {
        "ac": ac not in ("", "—", "-", "no", "false", "0"),
        "bb": bb not in ("", "—", "-", "no", "false", "0"),
    }


def normalize_row(x, rank: int) -> dict:
    """把一条采集记录归一成对比用结构；rank 为榜单名次（1 起步）。"""
    price = parse_price(x.get("price"))
    sales_low = parse_sales_lower(x.get("monthly_sales"))
    haul = _txt(x.get("haul")).strip()
    is_haul = haul not in ("", "—", "-", "0", "false", "no", "null", "none")
    return {
        "asin": _txt(x.get("asin")).strip() or "—",
        "brand": ("Haul" if is_haul else (_txt(x.get("brand")).strip() or "—")),
        "haul": 1 if is_haul else 0,
        "title": _txt(x.get("title")).strip() or "—",
        "rank": rank,
        "price": price,
        "price_raw": _txt(x.get("price")),
        "sales_raw": _txt(x.get("monthly_sales")),
        "sales_low": sales_low,
        "sales_mid": round(sales_low * 1.5) if sales_low else None,
        "review": parse_int(x.get("review_count")),
        "rating": parse_float(x.get("rating")),
        "url": _txt(x.get("url")),
        ** _badges(x),
        "scraped_at": _txt(x.get("scraped_at"))[:19],
    }


def load_rows(rows):
    """rows -> {rank_index: normalized} 列表（保持榜单顺序）。"""
    if isinstance(rows, dict):
        rows = rows.get("data") or rows.get("list") or rows.get("items") or []
    out = []
    for i, x in enumerate(rows or []):
        if not isinstance(x, dict) or not x.get("asin"):
            continue
        out.append(normalize_row(x, i + 1))
    return out


def _meta_date(meta: dict, rows) -> str:
    if meta and meta.get("date"):
        return str(meta["date"])
    ts = [r.get("scraped_at") for r in rows if r.get("scraped_at")]
    if ts:
        return min(ts)[:10]
    return "—"


def _delta(old, new):
    """两个数字的增减信息；任一缺失返回 None delta。"""
    if old is None or new is None or old == 0:
        return {"old": old, "new": new, "delta": None, "delta_pct": None}
    d = new - old
    return {"old": old, "new": new, "delta": d, "delta_pct": d / old * 100}


def _sum(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) if vals else 0


def _mid(vals):
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return None
    n = len(vals)
    return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2


def _mean(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def _band_buckets(prices, edges=(5, 10, 20)):
    """价格带分布 -> [(标签, 计数)]；None 归 '—'。"""
    labels = [f"<${edges[0]}", *[f"${edges[i]}-{edges[i+1]}" for i in range(len(edges) - 1)], f">${edges[-1]}", "—"]
    cnt = [0] * (len(edges) + 2)
    for p in prices:
        if p is None:
            cnt[-1] += 1
        elif p < edges[0]:
            cnt[0] += 1
        elif p > edges[-1]:
            cnt[-2] += 1
        else:
            for i in range(len(edges) - 1):
                if edges[i] <= p < edges[i + 1]:
                    cnt[i + 1] += 1
                    break
            else:
                cnt[-2] += 1
    return [{"label": k, "n": v} for k, v in zip(labels, cnt)]


def _sales_band_counts(rows):
    """月销档分布：{档标签: n}；档取原始文本归类太碎，按数值区间归 9 档。"""
    edges = [0, 200, 500, 1000, 2000, 5000, 10000]
    labels = ["<200", "200-500", "500-1K", "1K-2K", "2K-5K", "5K-10K", ">10K", "—"]
    cnt = [0] * len(labels)
    for r in rows:
        v = r["sales_low"]
        if v is None:
            cnt[-1] += 1
        else:
            for i in range(len(edges) - 1):
                if edges[i] <= v < edges[i + 1]:
                    cnt[i] += 1
                    break
            else:
                cnt[-2] += 1
    return [{"label": k, "n": v} for k, v in zip(labels, cnt)]


def _first_last_ts(rows):
    ts = [r["scraped_at"] for r in rows if r["scraped_at"]]
    return (min(ts) if ts else "—", max(ts) if ts else "—")


# ---------------- 主对比 ----------------
def compare(rows_a, rows_b, meta_a=None, meta_b=None) -> dict:
    A, B = load_rows(rows_a), load_rows(rows_b)
    if not A or not B:
        return {"error": "数据集为空，无法对比"}

    # 自动方向：始终 早=旧(A) → 晚=新(B)；meta date 优先，其次 scraped_at
    def _key(rows, meta):
        d = (meta or {}).get("date") or ""
        if not d:
            ts = [r["scraped_at"] for r in rows if r["scraped_at"]]
            d = min(ts)[:10] if ts else ""
        return d

    if (_key(A, meta_a), _key(B, meta_b)) > (_key(B, meta_b), _key(A, meta_a)):
        A, B = B, A
        meta_a, meta_b = meta_b, meta_a

    n_a, n_b = len(A), len(B)
    by_asin_a = {r["asin"]: r for r in A}
    by_asin_b = {r["asin"]: r for r in B}
    overlap = sorted(set(by_asin_a) & set(by_asin_b))
    only_a = sorted(set(by_asin_a) - set(by_asin_b))
    only_b = sorted(set(by_asin_b) - set(by_asin_a))

    date_a, date_b = _meta_date(meta_a, A), _meta_date(meta_b, B)
    try:
        days = max(1, (datetime.strptime(date_b, "%Y-%m-%d") - datetime.strptime(date_a, "%Y-%m-%d")).days)
    except ValueError:
        days = 1

    # ---- 大盘 ----
    def market_metric(key_a, key_b):
        """同批(overlap)口径：对每个共同 ASIN 取两期指标求和。"""
        va = _sum(by_asin_a[k][key_a] for k in overlap)
        vb = _sum(by_asin_b[k][key_b] for k in overlap)
        return va, vb

    sales_lo_a, sales_lo_b = market_metric("sales_low", "sales_low")     # 同批月销下限合计
    sales_mi_a, sales_mi_b = market_metric("sales_mid", "sales_mid")     # 同批月销中值合计
    rev_a, rev_b = market_metric("sales_mid", "sales_mid")
    # 销售额需同时有价
    def revenue_same():
        va = _sum(by_asin_a[k]["sales_mid"] * by_asin_a[k]["price"] for k in overlap
                  if by_asin_a[k]["sales_mid"] is not None and by_asin_a[k]["price"] is not None)
        vb = _sum(by_asin_b[k]["sales_mid"] * by_asin_b[k]["price"] for k in overlap
                  if by_asin_b[k]["sales_mid"] is not None and by_asin_b[k]["price"] is not None)
        return va, vb
    rev_a, rev_b = revenue_same()

    # 全榜口径（含换血）供参考
    all_sales_a = _sum(r["sales_mid"] for r in A)
    all_sales_b = _sum(r["sales_mid"] for r in B)
    all_rev_a = _sum(r["sales_mid"] * r["price"] for r in A if r["sales_mid"] is not None and r["price"] is not None)
    all_rev_b = _sum(r["sales_mid"] * r["price"] for r in B if r["sales_mid"] is not None and r["price"] is not None)

    # 同批价格/评分/评论
    pa = _mean([by_asin_a[k]["price"] for k in overlap if by_asin_a[k]["price"] is not None])
    pb = _mean([by_asin_b[k]["price"] for k in overlap if by_asin_b[k]["price"] is not None])
    ra = _mean([by_asin_a[k]["rating"] for k in overlap if by_asin_a[k]["rating"] is not None])
    rb = _mean([by_asin_b[k]["rating"] for k in overlap if by_asin_b[k]["rating"] is not None])
    cva = _sum(by_asin_a[k]["review"] for k in overlap if by_asin_a[k]["review"] is not None)
    cvb = _sum(by_asin_b[k]["review"] for k in overlap if by_asin_b[k]["review"] is not None)
    rev_inc = cvb - cva
    rev_per_day = rev_inc / days

    def top_overlap(m=30):
        ta = set(r["asin"] for r in A[:m])
        tb = set(r["asin"] for r in B[:m])
        return len(ta & tb)
    top10_ov, top30_ov = top_overlap(10), top_overlap(30)

    market = {
        "days": days,
        "same_n": len(overlap),
        "sales_same": _delta(sales_mi_a, sales_mi_b),     # 月销中值（同批）
        "sales_same_lo": _delta(sales_lo_a, sales_lo_b),  # 月销下限（同批，稳健下界）
        "sales_all": _delta(all_sales_a, all_sales_b),    # 月销中值（全榜，含换血）
        "revenue_same": _delta(rev_a, rev_b),             # 月销售额 = Σ(月销中值×现价)，同批
        "revenue_all": _delta(all_rev_a, all_rev_b),
        "avg_price_same": _delta(pa, pb),
        "avg_rating_same": _delta(ra, rb),
        "review_same": {"old": cva, "new": cvb, "inc": rev_inc, "per_day": round(rev_per_day, 2)},
        "price_bands_a": _band_buckets([r["price"] for r in A]),
        "price_bands_b": _band_buckets([r["price"] for r in B]),
        "sales_bands_a": _sales_band_counts(A),
        "sales_bands_b": _sales_band_counts(B),
        "top10_overlap": top10_ov,
        "top30_overlap": top30_ov,
        "n_a": n_a, "n_b": n_b,
        "new_n": len(only_b), "drop_n": len(only_a),
    }

    # ---- 榜单换血 ----
    def churn_item(r):
        return {
            "asin": r["asin"], "brand": r["brand"], "haul": r["haul"], "title": r["title"],
            "rank": r["rank"], "price": r["price"], "price_raw": r["price_raw"],
            "sales_raw": r["sales_raw"], "sales_low": r["sales_low"],
            "review": r["review"], "rating": r["rating"],
            "ac": r["ac"], "bb": r["bb"], "url": r["url"],
        }
    churn = {
        "kept": len(overlap),
        "dropped": [churn_item(by_asin_a[k]) for k in only_a],
        "entered": [churn_item(by_asin_b[k]) for k in only_b],
    }

    # ---- 排名变动（同批） ----
    moves = []
    for k in overlap:
        a, b = by_asin_a[k], by_asin_b[k]
        d = a["rank"] - b["rank"]      # >0 上升；<0 下降
        moves.append({
            "asin": k, "brand": a["brand"], "haul": a["haul"], "title": a["title"], "url": a["url"],
            "rank_old": a["rank"], "rank_new": b["rank"], "delta": d,
            "price_old": a["price"], "price_new": b["price"],
            "rating_old": a["rating"], "rating_new": b["rating"],
            "rev_old": a["review"], "rev_new": b["review"], "rev_inc": (b["review"] - a["review"]) if (a["review"] is not None and b["review"] is not None) else None,
            "sales_old": a["sales_raw"], "sales_new": b["sales_raw"],
            "ac_old": a["ac"], "ac_new": b["ac"], "bb_old": a["bb"], "bb_new": b["bb"],
        })
    moves.sort(key=lambda x: x["rank_new"])      # 默认按新名次展示
    up = sorted([m for m in moves if m["delta"] > 0], key=lambda x: -x["delta"])
    down = sorted([m for m in moves if m["delta"] < 0], key=lambda x: x["delta"])
    flat = [m for m in moves if m["delta"] == 0]
    avg_move = _mean([abs(m["delta"]) for m in moves])

    rankings = {
        "same_n": len(moves), "up": len(up), "down": len(down), "flat": len(flat),
        "avg_abs_move": round(avg_move, 1) if avg_move is not None else None,
        "up_top": up[:20], "down_top": down[:20],
        "all": moves,   # 全量明细（前端排序/导出用）
    }

    # ---- 品牌 ----
    def brand_stat(rows):
        st = {}
        for r in rows:
            b = r["brand"] if r["brand"] and r["brand"] != "—" else "(未知)"
            s = st.setdefault(b, {"cnt": 0, "top": None, "sales_mid": 0, "rank_sum": 0})
            s["cnt"] += 1
            s["top"] = r["rank"] if s["top"] is None else min(s["top"], r["rank"])
            s["rank_sum"] += r["rank"]
            if r["sales_mid"] is not None:
                s["sales_mid"] += r["sales_mid"]
        for b in st:
            st[b]["share"] = st[b]["cnt"] / len(rows) * 100 if rows else 0
            st[b]["avg_rank"] = st[b]["rank_sum"] / st[b]["cnt"] if st[b]["cnt"] else None
        return st
    st_a, st_b = brand_stat(A), brand_stat(B)
    set_a, set_b = set(st_a), set(st_b)
    kept_brands = sorted(set_a & set_b)
    new_brands = sorted(set_b - set_a)
    gone_brands = sorted(set_a - set_b)
    brand_moves = []
    for b in kept_brands:
        x, y = st_a[b], st_b[b]
        brand_moves.append({
            "brand": b, "cnt_a": x["cnt"], "cnt_b": y["cnt"], "cnt_delta": y["cnt"] - x["cnt"],
            "share_a": round(x["share"], 1), "share_b": round(y["share"], 1),
            "top_a": x["top"], "top_b": y["top"],
            "avg_rank_a": x["avg_rank"], "avg_rank_b": y["avg_rank"],
        })
    brand_moves.sort(key=lambda z: (-z["cnt_b"], z["brand"]))
    brands = {
        "kept": [{"brand": b} for b in kept_brands],
        "new": [{"brand": b, "cnt": st_b[b]["cnt"], "top": st_b[b]["top"]} for b in new_brands],
        "gone": [{"brand": b, "cnt": st_a[b]["cnt"], "top": st_a[b]["top"]} for b in gone_brands],
        "moves": brand_moves,
    }

    # ---- 明细全量 ----
    def detail_row(m):
        return dict(m, status="kept")
    detail = [detail_row(m) for m in moves]
    detail += [dict(churn_item(by_asin_a[k]), status="dropped", rank_old=by_asin_a[k]["rank"], rank_new=None) for k in only_a]
    detail += [dict(churn_item(by_asin_b[k]), status="entered", rank_old=None, rank_new=by_asin_b[k]["rank"]) for k in only_b]
    detail.sort(key=lambda x: (x["status"] != "kept", x.get("rank_new") or 999))

    # ---- 要点总结 ----
    def fmt_pct(d):
        if not d or d.get("delta_pct") is None:
            return "数据不足"
        p = d["delta_pct"]
        return f"{'+' if p >= 0 else ''}{p:.1f}%"
    summary = []
    if date_a != date_b:
        span = f"{date_a} → {date_b}"
        summary.append(f"对比区间 {span}（间隔 {days} 天，同批在榜 {len(overlap)} 个 ASIN，占两期 {round(len(overlap) / max(n_a, n_b) * 100)}%）")
    ms = market["sales_same"]
    if ms and ms["delta_pct"] is not None:
        trend = "上升" if ms["delta_pct"] > 0 else "下降" if ms["delta_pct"] < 0 else "持平"
        summary.append(f"大盘月销量(估, 同批口径): {_fmt_num(ms['old'])} → {_fmt_num(ms['new'])}（{trend} {abs(ms['delta_pct']):.1f}%）；全榜口径 {fmt_pct(market['sales_all'])}")
    rv = market["revenue_same"]
    if rv and rv["delta_pct"] is not None:
        trend = "上升" if rv["delta_pct"] > 0 else "下降" if rv["delta_pct"] < 0 else "持平"
        summary.append(f"大盘月销售额(估): {_fmt_money(rv['old'])} → {_fmt_money(rv['new'])}（{trend} {abs(rv['delta_pct']):.1f}%）；全榜口径 {fmt_pct(market['revenue_all'])}")
    ap = market["avg_price_same"]
    if ap and ap["delta_pct"] is not None and ap["old"] is not None and ap["new"] is not None:
        summary.append(f"同批商品均价: ${ap['old']:.2f} → ${ap['new']:.2f}（{'+' if ap['delta'] >= 0 else ''}{ap['delta']:.2f}，{fmt_pct(ap)}）")
    ar = market["avg_rating_same"]
    if ar and ar["old"] is not None and ar["new"] is not None:
        d = ar["delta"]
        summary.append(f"同批商品评分: {ar['old']:.2f} → {ar['new']:.2f}（{'+' if d is not None and d >= 0 else ''}{'—' if d is None else f'{d:.2f}'}）")
    rv2 = market["review_same"]
    if rv2 and rv2["old"]:
        sd = "+" if rev_per_day >= 0 else ""
        summary.append(f"同批评论存量: {_fmt_num(rv2['old'])} → {_fmt_num(rv2['new'])}（净增 {sd}{_fmt_num(rv2['inc'])}，约 {sd}{rev_per_day:.1f} 条/天 → 估算大盘活跃度{'上行' if rev_per_day > 0 else '下行'}）")
    summary.append(f"榜单换血: 掉出 {len(only_a)} 个 / 新进 {len(only_b)} 个；Top10 重合 {top10_ov}/10，Top30 重合 {top30_ov}/30")
    summary.append(f"排名变动(同批 {len(moves)}): 上升 {len(up)} · 下降 {len(down)} · 持平 {len(flat)}，平均位移 {round(avg_move, 1) if avg_move is not None else '—'} 位")
    summary.append(f"品牌: 保留 {len(kept_brands)} 个 · 新进 {len(new_brands)} 个 · 掉榜 {len(gone_brands)} 个")
    summary.append("口径提示: 月销量/月销售额为文本档位估算值（档中值=下限×1.5），仅供同口径升降趋势参考，非 Amazon 官方绝对值")

    return {
        "a": {"date": date_a, "n": n_a, "meta": meta_a or {}},
        "b": {"date": date_b, "n": n_b, "meta": meta_b or {}},
        "market": market,
        "churn": churn,
        "rankings": rankings,
        "brands": brands,
        "detail": detail,
        "summary": summary,
    }


def _fmt_num(n):
    return "—" if n is None else f"{n:,}"


def _fmt_money(n):
    return "—" if n is None else f"${n:,.0f}"


# ---------------- CLI 自测 ----------------
def main():
    if len(sys.argv) < 3:
        print("用法: python compare.py <json_a> <json_b>")
        return 1
    a, b = sys.argv[1], sys.argv[2]
    da = json.loads(Path(a).read_text(encoding="utf-8"))
    db = json.loads(Path(b).read_text(encoding="utf-8"))
    out = compare(da, db)
    if "error" in out:
        print("ERROR:", out["error"])
        return 1
    print("=" * 70)
    for s in out["summary"]:
        print("·", s)
    print("=" * 70)
    print(json.dumps(out["market"], ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
