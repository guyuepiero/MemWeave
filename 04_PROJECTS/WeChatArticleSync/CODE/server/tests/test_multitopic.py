# -*- coding: utf-8 -*-
"""多主题回归测试：追加/移除/多选筛选/后代匹配/清空。"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import db, syncer  # noqa: E402

BIZ = "MzMULTITOPIC"
TOKEN = "test_article"


def setup():
    db.init_db()
    c = db.get_conn()
    c.execute("DELETE FROM articles WHERE biz=?", (BIZ,))
    c.execute("DELETE FROM topics WHERE name LIKE 'UT-%'")
    c.commit()
    c.close()
    # 建主题：UT-父(id?) + UT-子
    pid = db.create_topic("UT-父", "#111111", 0)
    cid = db.create_topic("UT-子", "#222222", pid)
    return pid, cid


def test_multitopic():
    pid, cid = setup()
    # 插入测试文章
    conn = db.get_conn()
    conn.execute(
        "INSERT INTO articles(biz, appmsgid, idx, title, source) VALUES(?,?,?,?,?)",
        (BIZ, "9001", 0, "多主题A", "UT来源"),
    )
    aid = conn.execute("SELECT id FROM articles WHERE biz=? ORDER BY id DESC", (BIZ,)).fetchone()["id"]
    conn.commit()
    conn.close()

    # 1. 追加两个主题
    n = db.batch_append_topics([aid], [pid, cid])
    assert n == 2, f"追加应 2，实际 {n}"
    a = db.get_article(aid)
    names = {t["name"] for t in a["topics"]}
    assert names == {"UT-父", "UT-子"}, f"追加后主题 {a['topics']}"
    print("[PASS] 多主题追加: 一文两主题", a["topics"])

    # 2. 多选筛选任一命中（选子级应含后代匹配：选 UT-子）
    hit = db.list_articles(topic_ids=[cid])
    assert any(x["id"] == aid for x in hit), "按子主题筛选未命中"
    # 选父级也应命中（父的子孙包含子）
    hit_p = db.list_articles(topic_ids=[pid])
    assert any(x["id"] == aid for x in hit_p), "按父主题筛选应含子级文章"
    print("[PASS] 多选筛选: 任一命中 + 父含后代")

    # 3. 移除一个主题，主主题联动
    db.remove_article_topic(aid, cid)
    a2 = db.get_article(aid)
    assert {t["name"] for t in a2["topics"]} == {"UT-父"}, f"移除后 {a2['topics']}"
    assert a2["topic_name"] == "UT-父", "主主题应联动为剩余主题"
    print("[PASS] 移除主题: 主主题联动")

    # 4. 清空
    db.batch_clear_topics([aid])
    a3 = db.get_article(aid)
    assert a3["topics"] == [], f"清空后 {a3['topics']}"
    assert a3["topic_name"] is None, "清空后主主题应为空"
    print("[PASS] 清空主题")

    # 清理
    conn = db.get_conn()
    conn.execute("DELETE FROM articles WHERE biz=?", (BIZ,))
    conn.execute("DELETE FROM topics WHERE name LIKE 'UT-%'")
    conn.commit()
    conn.close()
    print("ALL MULTITOPIC TESTS PASSED")


if __name__ == "__main__":
    test_multitopic()
