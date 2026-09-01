"""临时脚本：抓专辑列表按发布时间从旧到新排序，定位指定文章的专辑内编号。"""
import asyncio
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import httpx

sys.path.insert(0, ".")

BIZ = "MzE5MTMyMzgwMA=="
ALBUM = "4059452088252891141"
TARGETS = {"2247483804": "#514", "2247483799": "#515"}  # mid -> 内部编号


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
                ct = a.get("create_time")
                try:
                    ts = int(ct)
                except (TypeError, ValueError):
                    ts = 0
                entries.append(
                    {
                        "mid": str(a.get("msgid", "")),
                        "idx": str(a.get("itemidx", "")),
                        "ts": ts,
                        "date": datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%m-%d %H:%M") if ts else "?",
                        "title": (a.get("title") or "")[:26],
                    }
                )
            cf = resp.get("continue_flag")
            if not cf or not lst:
                break
            last = lst[-1]
            begin_msgid, begin_itemidx = last.get("msgid"), last.get("itemidx")

    # 按发布时间从旧到新排序（用户要求）
    entries.sort(key=lambda e: e["ts"])
    print(f"专辑共 {len(entries)} 篇，按发布时间从旧到新排序：")
    print()
    for i, e in enumerate(entries, 1):
        mark = " ◀◀" if e["mid"] in TARGETS else ""
        extra = f" [{TARGETS[e['mid']]}]" if e["mid"] in TARGETS else ""
        print(f"  #{i:>3} {e['date']} mid={e['mid']} idx={e['idx']} | {e['title']}{extra}{mark}")
    print()
    print("=== 目标两篇的专辑内编号 ===")
    for i, e in enumerate(entries, 1):
        if e["mid"] in TARGETS:
            print(f"  mid={e['mid']} ({TARGETS[e['mid']]}) → 专辑第 {i} 篇")


asyncio.run(main())
