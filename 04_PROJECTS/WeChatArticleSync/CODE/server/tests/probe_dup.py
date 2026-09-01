"""临时脚本：定位专辑列表中重复条目的位置并对比内容（只读，不入库）。"""
import asyncio
import hashlib
import json
import re
import sys
import urllib.parse
import urllib.request

import httpx

sys.path.insert(0, ".")

from app import db  # noqa: E402

BIZ = "MzE5MTMyMzgwMA=="
ALBUM = "4059452088252891141"
TARGET_MSGID = "2247483799"


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
                        "msgid": str(a.get("msgid", "")),
                        "itemidx": str(a.get("itemidx", "")),
                        "create_time": a.get("create_time"),
                        "title": (a.get("title") or "")[:30],
                        "digest": (a.get("digest") or "")[:24],
                        "url": a.get("url") or a.get("content_url") or "",
                    }
                )
            cf = resp.get("continue_flag")
            if not cf or not lst:
                break
            last = lst[-1]
            begin_msgid, begin_itemidx = last.get("msgid"), last.get("itemidx")

    print(f"共 {len(entries)} 条")
    print()
    print(f"=== 重复条目 (msgid={TARGET_MSGID}) 的位置 ===")
    dup = [e for e in entries if e["msgid"] == TARGET_MSGID]
    for e in dup:
        print(f"  [第 {e['seq']} 个条目] itemidx={e['itemidx']} 时间={e['create_time']}")
        print(f"    标题: {e['title']}")
        print(f"    摘要: {e['digest']}")
        print(f"    链接: {e['url'][:110]}")
        print()
    if not dup:
        print("(本次抓取未发现重复条目，可能 key 已过期或列表已变)")
        return

    print("=== 3 条链接核心参数对比 ===")
    from urllib.parse import parse_qs, urlparse

    for e in dup:
        u = e["url"].replace("&amp;", "&")
        q = parse_qs(urlparse(u).query)
        core = {
            k: (q.get(k, [""])[0])[:24] for k in ("__biz", "mid", "idx", "sn")
        }
        print(
            f"  [第 {e['seq']} 个] __biz={core['__biz'][:14]} mid={core['mid']} "
            f"idx={core['idx']} sn={core['sn'][:12]}"
        )
    print()

    # 抓取第 1 条和第 3 条正文对比
    if len(dup) >= 2:
        print("=== 抓正文对比 (第1条 vs 第3条) ===")
        u1 = dup[0]["url"].replace("&amp;", "&")
        u3 = dup[-1]["url"].replace("&amp;", "&")

        async def fetch_text(u):
            async with httpx.AsyncClient(
                timeout=15,
                headers={"Referer": "https://mp.weixin.qq.com/", "User-Agent": ua, "Cookie": cookie},
                follow_redirects=True,
            ) as c:
                return (await c.get(u)).text

        h1, h3 = await fetch_text(u1), await fetch_text(u3)

        def body_md5(html):
            m = re.search(
                r'<div[^>]*id="js_content"[^>]*>(.*?)</div>\s*(?:<script|<div id="js_pc_qr_code")',
                html,
                re.S,
            )
            content = m.group(1) if m else html
            text = re.sub(r"<[^>]+>", "", content)
            return hashlib.md5(text.encode()).hexdigest()[:12], len(text)

        md1, ln1 = body_md5(h1)
        md3, ln3 = body_md5(h3)
        print(f"  第1条正文: md5={md1} 纯文本长度={ln1}")
        print(f"  第3条正文: md5={md3} 纯文本长度={ln3}")
        print(f"  → 正文完全相同: {'✅ 是' if md1 == md3 else '❌ 否'}")


asyncio.run(main())
