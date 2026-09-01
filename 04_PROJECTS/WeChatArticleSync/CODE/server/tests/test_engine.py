"""同步引擎进程内测试：mock 微信接口，验证分页/范围/增量/去重/专辑。

运行: .venv/Scripts/python -m tests.test_engine   （在 CODE/server 下）
"""
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, service, syncer  # noqa: E402

BIZ = "MzTEST"
NOW = int(time.time())

PAGES = {
    0: {
        "ret": 0, "can_msg_continue": 1, "next_offset": 10,
        "general_msg_list": json.dumps({"list": [
            {"comm_msg_info": {"id": "1001", "datetime": NOW - 5 * 86400},
             "app_msg_ext_info": {"title": "文章A", "digest": "", "cover": "", "author": "",
                                  "content_url": "https://mp.weixin.qq.com/s/a"}},
            {"comm_msg_info": {"id": "1002", "datetime": NOW - 20 * 86400},
             "app_msg_ext_info": {"title": "文章B", "digest": "", "cover": "", "author": "",
                                  "content_url": "https://mp.weixin.qq.com/s/b"}},
        ]}),
    },
    10: {
        "ret": 0, "can_msg_continue": 0, "next_offset": 0,
        "general_msg_list": json.dumps({"list": [
            {"comm_msg_info": {"id": "1003", "datetime": NOW - 100 * 86400},
             "app_msg_ext_info": {"title": "文章C", "digest": "", "cover": "", "author": "",
                                  "content_url": "https://mp.weixin.qq.com/s/c"}},
        ]}),
    },
}

ALBUM_PAGES = [
    {
        "getalbum_resp": {
            "continue_flag": 1, "next_begin_msgid": 555, "next_begin_itemidx": 1,
            "article_list": [
                {"msgid": "2001", "title": "专辑文1", "digest": "", "cover": "",
                 "author": "", "content_url": "https://mp.weixin.qq.com/s/alb1"},
            ],
        }
    },
    {
        "getalbum_resp": {
            "continue_flag": 0, "next_begin_msgid": 0, "next_begin_itemidx": 0,
            "article_list": [
                {"msgid": "2002", "title": "专辑文2", "digest": "", "cover": "",
                 "author": "", "content_url": "https://mp.weixin.qq.com/s/alb2"},
            ],
        }
    },
]


async def fake_getmsg(session, offset):
    return PAGES.get(offset, {"ret": 0, "can_msg_continue": 0, "next_offset": 0, "general_msg_list": "{}"})


async def fake_album(session, album_id, begin_msgid=0, begin_itemidx=0):
    return ALBUM_PAGES[0 if begin_msgid == 0 else 1]


async def fake_fetch_page(link, session=None):
    msgid = link.split("/")[-1]
    return f"""<html><head>
<meta property="og:title" content="标题 {msgid}">
<script>var biz="{BIZ}";var appmsgid="{msgid}";var idx="1";var ct="{NOW}";var nickname="测试号";</script>
</head><body><div id="js_content"><p>正文 {msgid}</p></div></body></html>"""


def setup():
    db.init_db()
    syncer.SESSIONS[BIZ] = {"__biz": BIZ, "key": "k", "uin": "u", "pass_ticket": "p",
                            "appmsg_token": "t", "cookie": "a=1", "ua": "test"}
    syncer.fetch_getmsg_page = fake_getmsg
    syncer.fetch_album_page = fake_album
    service.fetch_article_page = fake_fetch_page
    # 清理该测试号数据
    conn = db.get_conn()
    conn.execute("DELETE FROM articles WHERE biz=?", (BIZ,))
    conn.execute("DELETE FROM sync_tasks WHERE biz=?", (BIZ,))
    conn.commit()
    conn.close()


def test_full_history():
    tid = db.create_task("history", BIZ, scope="all", mode="all")
    asyncio.run(syncer.run_task(tid))
    s = syncer.task_snapshot(tid)
    assert s["status"] == "done", s
    assert s["synced"] == 3, f"期望同步 3 篇，实际 {s}"
    print("[PASS] 全量历史: 3 篇入库", s)


def test_scope_1m():
    start_ts, end_ts = syncer.scope_to_range("1m")
    tid = db.create_task("history", BIZ, scope="1m", mode="all", start_ts=start_ts, end_ts=end_ts)
    asyncio.run(syncer.run_task(tid))
    s = syncer.task_snapshot(tid)
    # A(5天) B(20天) 在范围内入库；C(100天) 触发停止
    assert s["status"] == "done", s
    assert s["synced"] == 0, "已存在应全部跳过，实际:" + str(s)
    print("[PASS] 范围过滤 1m: 已存在跳过，正确在越界处停止", s)


def test_incremental():
    # 先删掉最新的 A，模拟“新发布一篇文章”
    conn = db.get_conn()
    conn.execute("DELETE FROM articles WHERE appmsgid='1001'")
    conn.commit()
    conn.close()
    tid = db.create_task("history", BIZ, scope="all", mode="incremental")
    asyncio.run(syncer.run_task(tid))
    s = syncer.task_snapshot(tid)
    assert s["status"] == "done", s
    assert s["synced"] == 1, "增量应只补 A，实际:" + str(s)
    print("[PASS] 增量更新: 命中已存在即停，仅补新文 1 篇", s)


def test_album():
    tid = db.create_task("album", BIZ, scope="all", mode="all", album_id="ALB001")
    asyncio.run(syncer.run_task(tid))
    s = syncer.task_snapshot(tid)
    assert s["status"] == "done", s
    assert s["synced"] == 2, f"专辑应同步 2 篇，实际 {s}"
    print("[PASS] 专辑同步: 双游标翻页 2 篇入库", s)


# 2026-08-06 真机踩坑：微信 getalbum 在「某页只有 1 篇文章」时 article_list 返回**对象**而非数组
# （真实返回: {"getalbum_resp": {"article_list": {"msgid": "...", "itemidx": "1", ...}}}）
# 旧代码 for a in lst 遍历 dict → 拿到字符串 key → a.get() 崩 "str object has no attribute get"
def test_album_single_object():
    async def fake_album_single(session, album_id, begin_msgid=0, begin_itemidx=0):
        return {
            "base_resp": {"exportkey_token": "", "ret": 0},
            "getalbum_resp": {
                "continue_flag": 0,
                "article_list": {
                    "cover_img_1_1": "https://mmbiz.qpic.cn/x/300",
                    "create_time": str(NOW - 86400),
                    "itemidx": "1",
                    "msgid": "3001",
                    "title": "单篇对象专辑文",
                    "url": "https://mp.weixin.qq.com/s/alb_single",
                },
            },
        }
    syncer.fetch_album_page = fake_album_single
    # 直接单测 parse_album：兼容 dict 形态 article_list
    items, continue_flag, n_msgid, n_itemidx, err = syncer.parse_album(asyncio.run(fake_album_single(None, "ALB-SINGLE")))
    assert err == "", f"应无错误，实际: {err}"
    assert continue_flag == 0
    assert len(items) == 1, f"应解析出 1 篇，实际 {len(items)}"
    assert items[0]["appmsgid"] == "3001" and items[0]["itemidx"] == 1, items
    # 端到端：单篇对象页任务应 done 且入库 1 篇（不崩溃）
    tid = db.create_task("album", BIZ, scope="all", mode="all", album_id="ALB-SINGLE")
    asyncio.run(syncer.run_task(tid))
    s = syncer.task_snapshot(tid)
    assert s["status"] == "done", f"单篇对象应正常完成，实际 {s}"
    assert s["synced"] == 1, f"应入库 1 篇，实际 {s}"
    print("[PASS] 专辑单篇对象: article_list=dict 兼容，1 篇入库", s)


if __name__ == "__main__":
    setup()
    test_full_history()
    test_scope_1m()
    test_incremental()
    test_album()
    test_album_single_object()
    print("\nALL TESTS PASSED")
