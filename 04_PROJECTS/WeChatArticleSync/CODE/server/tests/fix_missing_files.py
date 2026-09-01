"""临时脚本：补齐飞翔号缺失文件的 38 篇文章（抓正文 + 落盘 + 刷新 DB 路径）。"""
import asyncio
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import httpx

sys.path.insert(0, ".")

from app import db, service  # noqa: E402
from app.config import ARTICLES_DIR  # noqa: E402

BIZ = "MzE5MTMyMzgwMA=="


def get_session():
    s = json.loads(
        urllib.request.urlopen(
            "http://127.0.0.1:21888/api/sessions/debug?biz="
            + urllib.parse.quote(BIZ)
        ).read().decode()
    )
    return s


async def main():
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT * FROM articles WHERE biz=? ORDER BY id",
        (BIZ,),
    ).fetchall()
    conn.close()

    missing = [r for r in rows if not r["html_path"] or not Path(r["html_path"]).exists()]
    print(f"待补齐 {len(missing)} 篇")
    s = get_session()
    cookie = s.get("cookie") or ""
    ua = s.get("ua") or "Mozilla/5.0 Chrome/126.0"

    ok = 0
    fail = 0
    for i, r in enumerate(missing, 1):
        link = r["link"] or ""
        if not link:
            print(f"  [{i}/{len(missing)}] #{r['id']} {r['title'][:20]} 无链接，跳过")
            fail += 1
            continue
        try:
            async with httpx.AsyncClient(
                timeout=20,
                headers={
                    "Referer": "https://mp.weixin.qq.com/",
                    "User-Agent": ua,
                    "Cookie": cookie,
                },
                follow_redirects=True,
            ) as c:
                html = (await c.get(link)).text
            meta = {
                "biz": BIZ,
                "appmsgid": r["appmsgid"],
                "idx": r["idx"] or 0,
                "title": r["title"],
                "author": r["author"],
                "digest": r["digest"],
                "link": link,
                "cover": r["cover"],
                "publish_time": r["publish_time"],
                "source": r["source"],
                "album_id": r["album_id"],
            }
            res = service.save_article(meta, html, html)
            if res.get("ok"):
                ok += 1
                print(f"  [{i}/{len(missing)}] ✅ #{r['id']} {r['title'][:20]}")
            else:
                fail += 1
                print(f"  [{i}/{len(missing)}] ❌ #{r['id']} {r['title'][:20]} {res.get('error')}")
        except Exception as e:  # noqa: BLE001
            fail += 1
            print(f"  [{i}/{len(missing)}] ❌ #{r['id']} {r['title'][:20]} 抓取失败: {e}")
        await asyncio.sleep(0.8)

    print()
    print(f"补齐完成: 成功 {ok} / 失败 {fail}")

    # 最终验证
    conn = db.get_conn()
    rows2 = conn.execute(
        "SELECT id, html_path FROM articles WHERE biz=? ORDER BY id", (BIZ,)
    ).fetchall()
    still = [r for r in rows2 if not r["html_path"] or not Path(r["html_path"]).exists()]
    print(f"最终仍缺失: {len(still)} 篇")
    conn.close()


asyncio.run(main())
