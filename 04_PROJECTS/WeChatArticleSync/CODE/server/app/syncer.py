"""微文收纳 · 同步引擎（M1）

能力：
- getmsg 分页抓取公众号全部历史（替代已下线的 RSS 订阅）
- 同步范围过滤：all / 1m / 3m / 6m / 1y / custom
- 增量更新：拉首页命中已存在文章即停 → 持续获得更新
- 断点续传：key 过期 → 任务暂停，补 key 后从 last_offset 续跑
- 专辑页 getalbum 双游标抓取
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx

from . import db, service
from .config import REFERER, UA

# 内存会话：扩展从浏览器真实会话拦截到的凭据（M1 用；正式版可加密落盘）
SESSIONS: dict[str, dict] = {}
# 进程内任务状态（最新进度；db 存持久字段）
TASKS: dict[int, dict] = {}

PAGE_SIZE = 10
LIST_DELAY = 0.25   # 列表页翻页间隔
CONTENT_DELAY = 0.4  # 正文抓取间隔（限速 ~2.5 req/s）


# ---------- 工具 ----------
def scope_to_range(scope: str, start_date: str = "") -> tuple[int | None, int | None]:
    if scope == "all":
        return None, None
    now = datetime.now(timezone.utc)
    start = {
        "1m": now - timedelta(days=30),
        "3m": now - timedelta(days=90),
        "6m": now - timedelta(days=180),
        "1y": now - timedelta(days=365),
    }.get(scope)
    if start is None and scope == "custom" and start_date:
        try:
            start = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
        except ValueError:
            start = None
    if start is None:
        return None, None
    return int(start.timestamp()), int(now.timestamp())


async def resolve_account_from_link(link: str) -> dict:
    """抓取文章页并反查公众号。"""
    html = await service.fetch_article_page(link)
    from .parser import parse_article

    parsed = parse_article(html, url=link)
    if not parsed["biz"]:
        raise ValueError("未能从该链接解析出公众号标识 __biz")
    acc = db.upsert_account(parsed["biz"], parsed["source"])
    return {
        "account_id": acc,
        "biz": parsed["biz"],
        "name": parsed["source"] or "未知公众号",
        "article_title": parsed["title"],
    }


# ---------- 微信接口（复用浏览器真实会话） ----------
async def _fetch_json(url: str, session: dict, params: dict) -> dict:
    async with httpx.AsyncClient(
        timeout=15,
        headers=service.session_headers(session),
        cookies=service._cookie_dict(session),
        follow_redirects=True,
    ) as client:
        r = await client.get(url, params=params)
        try:
            data = r.json()
        except json.JSONDecodeError:
            return {"ret": -1, "msg": "非 JSON 响应（可能触发风控/验证）"}
        # 防御：微信偶发返回 JSON 字符串/数组（非对象）→ 统一转成带 msg 的错误 dict，
        # 避免上层对 str/list 调 .get() 崩出 "str object has no attribute get"
        if not isinstance(data, dict):
            return {"ret": -1, "msg": f"响应类型异常（{type(data).__name__}，前 120 字: {str(data)[:120]}）"}
        return data


async def fetch_getmsg_page(session: dict, offset: int) -> dict:
    params = {
        "action": "getmsg",
        "__biz": session.get("__biz", ""),
        "f": "json",
        "offset": offset,
        "count": PAGE_SIZE,
        "is_ok": 1,
        "scene": "",
        "uin": session.get("uin", ""),
        "key": session.get("key", ""),
        "pass_ticket": session.get("pass_ticket", ""),
        "wxtoken": "",
        "appmsg_token": session.get("appmsg_token", ""),
        "x5": 0,
    }
    return await _fetch_json("https://mp.weixin.qq.com/mp/profile_ext", session, params)


def parse_getmsg(data: dict) -> tuple[list[dict], int, bool, str]:
    """返回 (items, next_offset, can_continue, error)。
    公众号全部历史文章总数（app_msg_cnt）写入 SESSIONS 对应条目，供任务完成后回填。"""
    if data.get("ret", 0) != 0:
        return [], 0, False, data.get("msg") or data.get("errmsg") or f"ret={data.get('ret')}"
    try:
        lst = json.loads(data.get("general_msg_list", "{}")).get("list", [])
    except json.JSONDecodeError:
        return [], 0, False, "general_msg_list 解析失败"
    items = []
    for m in lst:
        comm = m.get("comm_msg_info", {})
        ext = m.get("app_msg_ext_info", {})
        item = {
            "appmsgid": str(comm.get("id", "")),
            "publish_time": comm.get("datetime"),
            "title": ext.get("title", ""),
            "digest": ext.get("digest", ""),
            "cover": ext.get("cover", ""),
            "author": ext.get("author", ""),
            "link": (ext.get("content_url", "") or "").replace("&amp;", "&"),
        }
        items.append(item)
        for sub in ext.get("multi_app_msg_item_list") or []:
            items.append({
                "appmsgid": item["appmsgid"],
                "publish_time": item["publish_time"],
                "title": sub.get("title", ""),
                "digest": sub.get("digest", ""),
                "cover": sub.get("cover", ""),
                "author": sub.get("author", ""),
                "link": (sub.get("content_url", "") or "").replace("&amp;", "&"),
            })
    return items, int(data.get("next_offset", 0) or 0), bool(data.get("can_msg_continue", 1)), ""


async def fetch_album_page(session: dict, album_id: str, begin_msgid=0, begin_itemidx=0) -> dict:
    params = {
        "action": "getalbum",
        "__biz": session.get("__biz", ""),
        "album_id": album_id,
        "f": "json",
        "count": PAGE_SIZE,
        "begin_msgid": begin_msgid,
        "begin_itemidx": begin_itemidx,
        "uin": session.get("uin", ""),
        "key": session.get("key", ""),
        "pass_ticket": session.get("pass_ticket", ""),
        "wxtoken": "",
        "appmsg_token": session.get("appmsg_token", ""),
    }
    return await _fetch_json("https://mp.weixin.qq.com/mp/appmsgalbum", session, params)


def parse_album(data: dict) -> tuple[list[dict], int, int, int, str]:
    """解析 getalbum 响应；返回 (items, continue_flag, next_begin_msgid, next_begin_itemidx, error)。

    兼容 2026 微信改版的三种响应差异：
    - 错误标识：ret 可能在顶层，也可能在 base_resp{ret, err_msg} 里
    - 游标：新格式响应**不再返回 next_begin_msgid**——翻页靠客户端自取
      「本页最后一条的 msgid+itemidx」作下一页起点；本函数在取不到服务器游标时自动回退到该规则
    - 类型：create_time/itemidx 为字符串，统一转 int
    """
    def _int(v):
        try:
            return int(v or 0)
        except (TypeError, ValueError):
            return 0

    # ret 可能在顶层，也可能在 base_resp 里
    ret = data.get("ret")
    if ret is None:
        br = data.get("base_resp") or {}
        ret = br.get("ret", br.get("err_code"))
    if ret is not None and ret != 0:
        br = data.get("base_resp") or {}
        msg = br.get("err_msg") or data.get("msg") or data.get("errmsg") or f"ret={ret}"
        # 10004/200003 等 = 会话 key 失效/风控（微信端拒绝），给出明确指引
        if str(ret) in ("10004", "200003", "200013"):
            msg = f"会话已失效（微信返回 ret={ret}）：请在微信内重新打开该专辑页，让扩展重新捕获会话后再点同步"
        return [], 0, 0, 0, msg
    resp = data.get("getalbum_resp")
    if resp is None:
        keys = ",".join(list(data.keys())[:8])
        return [], 0, 0, 0, f"响应结构异常（顶层键: {keys}）"
    lst = resp.get("article_list") or []
    # 坑（2026-08-06）：微信 getalbum 在「某页只有 1 篇文章」时 article_list 返回**对象**而非数组
    # （如 {"msgid":..., "itemidx":..., ...}）→ 遍历 dict 拿到的是字符串 key，a.get() 直接崩。
    # 统一归一为列表；元素非 dict（理论防御）跳过。
    if isinstance(lst, dict):
        lst = [lst]
    items = []
    for a in lst:
        if not isinstance(a, dict):
            continue
        items.append({
            "appmsgid": str(a.get("msgid") or a.get("appmsgid") or ""),
            "publish_time": _int(a.get("create_time") or a.get("datetime")),
            "title": a.get("title", ""),
            "digest": a.get("digest", "") or "",
            "cover": a.get("cover_img_1_1") or a.get("cover") or "",
            "author": a.get("author", "") or "",
            "link": (a.get("url") or a.get("content_url") or "").replace("&amp;", "&"),
            "itemidx": _int(a.get("itemidx")),
        })
    # 兼容多个游标字段名
    continue_flag = _int(resp.get("continue_flag", resp.get("has_more", resp.get("can_msg_continue", 0))))
    n_msgid = _int(resp.get("next_begin_msgid", resp.get("next_msgid", 0)))
    n_itemidx = _int(resp.get("next_begin_itemidx", resp.get("next_itemidx", 0)))
    # 新格式不返回游标 → 自取本页最后一条的 msgid/itemidx 作下一页起点
    if not n_msgid and items:
        n_msgid = _int(items[-1].get("appmsgid"))
        n_itemidx = items[-1].get("itemidx") or 0
    return items, continue_flag, n_msgid, n_itemidx, ""


# ---------- 任务执行 ----------
def _add_detail(task: dict, item: dict, kind: str, reason: str = "") -> None:
    """记录单篇文章的同步结果明细（failed/existing/skipped），供任务面板展示。"""
    try:
        details = task.setdefault("details", [])
        if len(details) < 500:  # 防止明细无限膨胀
            details.append({
                "kind": kind,
                "title": (item.get("title") or "")[:80],
                "link": (item.get("link") or item.get("url") or "")[:300],
                "reason": reason[:200],
            })
    except Exception:  # noqa: BLE001
        pass


async def _sync_item(item: dict, task: dict) -> None:
    """抓取单篇正文并入库（失败计数并记录明细，不中断任务）。"""
    link = item.get("link", "")
    if not link:
        task["skipped"] += 1
        _add_detail(task, item, "skipped", "无文章链接，跳过")
        return
    biz = task["biz"]
    session = SESSIONS.get(biz) or {}
    try:
        html = await service.fetch_article_page(link, session)
    except Exception as e:  # noqa: BLE001
        task["failed"] += 1
        _add_detail(task, item, "failed", f"正文抓取失败: {e}")
        return
    acc = db.get_account(biz)
    item["source"] = (acc or {}).get("name", "")
    item["biz"] = biz
    item["url"] = link
    item["html"] = html
    item["idx"] = item.get("itemidx") or item.get("idx") or 0
    if task.get("album_id"):
        item["album_id"] = task["album_id"]
    try:
        res = service.sync_article_payload(item)
        if res.get("ok"):
            created = res.get("created")
            task["synced"] += 1 if created else 0
            task["existing"] += 0 if created else 1
            if not created:
                _add_detail(task, item, "existing", "库中已存在同公众号同 appmsgid 同 idx 的文章")
        else:
            task["failed"] += 1
            _add_detail(task, item, "failed", res.get("error") or "入库失败")
    except Exception as e:  # noqa: BLE001
        task["failed"] += 1
        _add_detail(task, item, "failed", f"入库异常: {e}")


def _mark(task_id: int, status: str, error: str = "") -> None:
    t = TASKS.get(task_id)
    if t:
        t["status"] = status
        if error:
            t["error"] = error
    # 任务结束时把明细持久化（details 只记录 failed/existing/skipped，避免刷屏）
    details_json = ""
    if t and t.get("details"):
        import json
        details_json = json.dumps(t["details"], ensure_ascii=False)
    db.update_task(task_id, status=status, error=error, details_json=details_json)


async def _run_history(task_row: dict) -> None:
    task_id = task_row["id"]
    biz = task_row["biz"]
    scope = task_row["scope"] or "all"
    mode = task_row["mode"] or "all"
    start_ts = task_row["start_ts"]
    end_ts = task_row["end_ts"]
    offset = task_row["last_offset"] or 0

    task = TASKS[task_id] = {
        "status": "running", "biz": biz, "type": "history",
        "scope": scope, "mode": mode, "progress": offset,
        "last_offset": offset, "error": "", "cancel": False,
        "synced": 0, "existing": 0, "skipped": 0, "failed": 0,
        "album_id": "", "details": [],
    }
    _mark(task_id, "running")

    while True:
        if task.get("cancel"):
            _mark(task_id, "cancelled")
            return
        session = SESSIONS.get(biz)
        if not session:
            _mark(task_id, "paused", "会话丢失，请重新打开该公众号主页")
            return
        try:
            data = await fetch_getmsg_page(session, offset)
        except Exception as e:  # noqa: BLE001
            _mark(task_id, "paused", f"网络错误: {e}")
            return
        # 公众号全部历史文章总数（getmsg 响应 app_msg_cnt），用于工作台显示「共 N 篇」
        try:
            total = int(data.get("app_msg_cnt") or 0)
            if total > 0:
                db.update_account_total(biz, total)
        except (TypeError, ValueError):
            pass
        items, next_offset, can_continue, err = parse_getmsg(data)
        if err:
            _mark(task_id, "paused", f"key 失效或风控: {err}（请重新打开主页补 key）")
            return

        for item in items:
            ts = item.get("publish_time")
            if ts:
                if start_ts and ts < start_ts:
                    _mark(task_id, "done")
                    return
                if end_ts and ts > end_ts:
                    continue
            if db.appmsgid_exists(biz, item["appmsgid"], item.get("itemidx") or item.get("idx") or 0):
                if mode == "incremental":
                    _mark(task_id, "done")
                    return
                task["existing"] += 1
                _add_detail(task, item, "existing", "库中已存在同公众号同 appmsgid 同 idx 的文章")
                continue
            await _sync_item(item, task)
            await asyncio.sleep(CONTENT_DELAY)

        if not can_continue or next_offset == 0 or next_offset == offset:
            _mark(task_id, "done")
            return
        offset = next_offset
        task["progress"] = offset
        task["last_offset"] = offset
        db.update_task(task_id, progress=offset, last_offset=offset)
        await asyncio.sleep(LIST_DELAY)


async def _run_album(task_row: dict) -> None:
    task_id = task_row["id"]
    biz = task_row["biz"]
    album_id = task_row["album_id"]
    begin_msgid = task_row["last_offset"] or 0
    begin_itemidx = task_row["last_itemidx"] or 0

    task = TASKS[task_id] = {
        "status": "running", "biz": biz, "type": "album",
        "scope": task_row["scope"] or "all", "mode": task_row["mode"] or "all",
        "progress": begin_msgid, "last_offset": begin_msgid, "error": "",
        "cancel": False, "synced": 0, "existing": 0, "skipped": 0, "failed": 0,
        "album_id": album_id, "details": [],
    }
    _mark(task_id, "running")

    stall = 0          # 游标未前进的连续轮数（防死循环）
    last_cursor = (begin_msgid, begin_itemidx)

    while True:
        if task.get("cancel"):
            _mark(task_id, "cancelled")
            return
        session = SESSIONS.get(biz)
        if not session:
            _mark(task_id, "paused", "会话丢失，请重新打开该专辑/主页")
            return
        try:
            data = await fetch_album_page(session, album_id, begin_msgid, begin_itemidx)
        except Exception as e:  # noqa: BLE001
            _mark(task_id, "paused", f"网络错误: {e}")
            return
        items, continue_flag, n_msgid, n_itemidx, err = parse_album(data)
        try:
            print(
                f"[album][task {task_id}] begin_msgid={begin_msgid} "
                f"ret={data.get('ret')} base_resp={data.get('base_resp')} "
                f"keys={list(data.keys())[:8]} items={len(items)} "
                f"continue={continue_flag} n_msgid={n_msgid} n_itemidx={n_itemidx} err={err!r}"
            )
        except Exception:  # noqa: BLE001
            pass
        if err:
            _mark(task_id, "paused", f"专辑接口异常: {err}")
            return

        # 记录专辑名（getalbum_resp.base_info.title），供工作台按专辑分组展示
        try:
            bi = (data.get("getalbum_resp") or {}).get("base_info") or {}
            album_title = (bi.get("title") or "").strip()
            if album_title:
                db.upsert_album(biz, album_id, album_title)
        except Exception:  # noqa: BLE001
            pass

        for item in items:
            if db.appmsgid_exists(biz, item["appmsgid"], item.get("itemidx") or item.get("idx") or 0):
                task["existing"] += 1
                _add_detail(task, item, "existing", "库中已存在同公众号同 appmsgid 同 idx 的文章")
                continue
            await _sync_item(item, task)
            await asyncio.sleep(CONTENT_DELAY)

        # 专辑增量：必须翻完整本专辑才能停——微信专辑从 begin_msgid=0 返回的是"最早"的文章，
        # 且专辑内排序不保证按时间，"第一条/整页已存即停"都会漏掉后面未入库的文章。
        # 已存项跳过不重复入库（幂等），翻到 continue_flag=False（专辑末尾）才算完成。
        if not continue_flag:
            _mark(task_id, "done")
            return

        # 防死循环：微信说还有下一页，但游标不前进 → 连续 N 轮后判定异常停止
        if (n_msgid, n_itemidx) == last_cursor:
            stall += 1
            if stall >= 5:
                _mark(task_id, "paused", f"翻页游标连续 {stall} 轮未前进，疑似专辑接口异常，已自动停止（请重新打开专辑页后重试）")
                return
        else:
            stall = 0
            last_cursor = (n_msgid, n_itemidx)

        begin_msgid, begin_itemidx = n_msgid, n_itemidx
        task["progress"] = begin_msgid
        task["last_offset"] = begin_msgid
        task["last_itemidx"] = begin_itemidx
        db.update_task(task_id, progress=begin_msgid, last_offset=begin_msgid, last_itemidx=begin_itemidx)
        await asyncio.sleep(LIST_DELAY)


async def run_task(task_id: int) -> None:
    row = db.get_task(task_id)
    if not row:
        return
    try:
        if row["type"] == "album":
            await _run_album(row)
        else:
            await _run_history(row)
    except Exception as e:  # noqa: BLE001
        # 带上异常位置，避免出现只有 "str object has no attribute get" 无法定位的裸错误
        import traceback
        tb = traceback.format_exc().strip().splitlines()
        detail = f"{type(e).__name__}: {e} @ {tb[-1].strip() if tb else '?'}"
        _mark(task_id, "failed", detail)


def task_snapshot(task_id: int) -> dict:
    """db 持久状态 + 进程内进度合并"""
    row = db.get_task(task_id)
    if not row:
        return {}
    d = dict(row)
    # 扩展手动同步任务：统计存在 last_offset(synced)/last_itemidx(existing)/progress(总数)
    if d.get("type") == "manual":
        d.setdefault("synced", d.get("last_offset") or 0)
        d.setdefault("existing", d.get("last_itemidx") or 0)
        d.setdefault("skipped", 0)
        d.setdefault("failed", 0)
    mem = TASKS.get(task_id)
    if mem:
        d.update({k: mem[k] for k in ("progress", "last_offset", "synced", "existing", "skipped", "failed", "error", "status")})
        if mem.get("details"):
            d["details"] = mem["details"]
    else:
        # 进程外（服务重启后）：从 db 读持久化的明细
        try:
            import json
            d["details"] = json.loads(row["details_json"] or "[]")
        except Exception:  # noqa: BLE001
            d["details"] = []
    return d


def resume_paused(biz: str) -> int:
    """会话补 key 后：把该公众号所有 paused 的历史/专辑任务续跑（从断点创建新任务）。"""
    rows = db.list_tasks(status="paused", biz=biz)
    launched = 0
    for r in rows:
        new_id = db.create_task(
            r["type"], biz, scope=r["scope"], mode=r["mode"],
            album_id=r["album_id"], start_ts=r["start_ts"], end_ts=r["end_ts"],
            last_offset=r["last_offset"], last_itemidx=r["last_itemidx"],
            start_date=r["start_date"],
        )
        db.update_task(r["id"], status="resumed")
        asyncio.get_event_loop().create_task(run_task(new_id))
        launched += 1
    return launched
