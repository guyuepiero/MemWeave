"""临时脚本：对比专辑列表与库，找出失败/缺失的条目（只读，不入库）。"""
import asyncio
import json
import sys
import urllib.parse
import urllib.request

import httpx

sys.path.insert(0, ".")

from app import db  # noqa: E402

BIZ = "MzE5MTMyMzgwMA=="
ALBUM = "4059452088252891141"


def get_session():
    s = json.loads(
        urllib.request.urlopen(
            "http://127.0.0.1:21888/api/sessions/debug?biz="
            + urllib.parse.quote(BIZ)
        ).read().decode()
    )
    return s


async def main():
    s = get_session()
    cookie = s.get("cookie") or ""
    ua = s.get("ua") or "Mozilla/5.0 Chrome/126.0"
    headers = {
        "Referer": "https://mp.weixin.qq.com/mp/appmsgalbum?__biz=" + BIZ,
        "User-Agent": ua,
        "Cookie": cookie,
    }
    entries = []
    begin_msgid, begin_itemidx = 0, 0
    while True:
        async with httpx.AsyncClient(timeout=15, headers=headers) as c:
            r = await c.get(
                "https://mp.weixin.qq.com/mp/appmsgalbum",
                params={
                    "action": "getalbum",
                    "__biz": BIZ,
                    "album_id": ALBUM,
                    "f": "json",
                    "count": 10,
                    "begin_msgid": begin_msgid,
                    "begin_itemidx": begin_itemidx,
                    "uin": "",
                    "key": "",
                    "pass_ticket": "",
                    "wxtoken": "",
                    "appmsg_token": "",
                },
            )
            resp = r.json().get("getalbum_resp") or {}
            lst = resp.get("article_list") or []
            for a in lst:
                entries.append(
                    {
                        "seq": len(entries) + 1,
                        "mid": str(a.get("msgid", "")),
                        "idx": str(a.get("itemidx", "")),
                        "create_time": a.get("create_time"),
                        "title": (a.get("title") or "")[:40],
                        "url": a.get("url") or a.get("content_url") or "",
                    }
                )
            cf = resp.get("continue_flag")
            if not cf or not lst:
                break
            last = lst[-1]
            begin_msgid, begin_itemidx = last.get("msgid"), last.get("itemidx")

    print(f"专辑列表共 {len(entries)} 条")
    print()

    # 库里现有飞翔号文章（appmsgid -> idx 集合）
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT appmsgid, idx FROM articles WHERE biz=? AND album_id=?",
        (BIZ, ALBUM),
    ).fetchall()
    conn.close()
    in_db = {(r["appmsgid"], r["idx"]) for r in rows}
    in_db_mids = {r["appmsgid"] for r in rows}
    print(f"库里该专辑已有 {len(in_db)} 条 (appmsgid, idx) 对")
    print()

    print("=== 列表中有、但库里 (appmsgid, idx) 完全对不上的条目 ===")
    missing = []
    for e in entries:
        key = (e["mid"], int(e["idx"]))
        # 库里 idx 可能存成 0（历史 bug），idx=1 的文章在库里是 idx=0
        in_db_key = key in in_db or (int(e["idx"]) == 1 and (e["mid"], 0) in in_db)
        if not in_db_key:
            missing.append(e)
    for e in missing:
        mid_in_db = e["mid"] in in_db_mids
        tag = "【mid 在库 → 待补 idx 篇(bug 已修, 重同步补齐)】" if mid_in_db else "【mid 完全不在库 → 疑似失败篇】"
        print(f"  第{e['seq']}条 mid={e['mid']} idx={e['idx']} {tag}")
        print(f"    标题: {e['title']}")
        print(f"    链接: {e['url'][:110]}")
        print()
    print(f"缺失合计: {len(missing)} 条（预期 = 2 条待补 idx + 1 条失败）")


asyncio.run(main())
