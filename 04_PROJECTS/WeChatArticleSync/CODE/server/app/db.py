"""微文收纳 · SQLite 数据访问层"""
import sqlite3

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  biz TEXT UNIQUE NOT NULL,
  name TEXT DEFAULT '',
  avatar TEXT DEFAULT '',
  signature TEXT DEFAULT '',
  description TEXT DEFAULT '',
  created_at TEXT DEFAULT (datetime('now','localtime')),
  last_sync_at TEXT,
  total_articles INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS topics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  color TEXT DEFAULT '#378ADD',
  parent_id INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS articles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  biz TEXT NOT NULL,
  appmsgid TEXT,
  idx INTEGER DEFAULT 0,
  title TEXT DEFAULT '',
  author TEXT DEFAULT '',
  digest TEXT DEFAULT '',
  link TEXT DEFAULT '',
  cover TEXT DEFAULT '',
  publish_time INTEGER,
  source TEXT DEFAULT '',
  topic_id INTEGER,
  album_id TEXT,
  html_path TEXT DEFAULT '',
  images_dir TEXT DEFAULT '',
  content_md TEXT DEFAULT '',
  attrs_json TEXT DEFAULT '{}',
  is_paid INTEGER DEFAULT 0,
  paid_unlocked INTEGER DEFAULT 0,
  synced_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_articles_biz_appmsgid_idx ON articles(biz, appmsgid, idx);

CREATE TABLE IF NOT EXISTS article_topics (
  article_id INTEGER NOT NULL,
  topic_id INTEGER NOT NULL,
  PRIMARY KEY (article_id, topic_id)
);
CREATE INDEX IF NOT EXISTS ix_article_topics_topic ON article_topics(topic_id);

CREATE TABLE IF NOT EXISTS albums (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  biz TEXT DEFAULT '',
  album_id TEXT UNIQUE,
  title TEXT DEFAULT '',
  cover TEXT DEFAULT '',
  description TEXT DEFAULT '',
  create_time INTEGER
);

CREATE TABLE IF NOT EXISTS sync_tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  type TEXT DEFAULT 'history',
  biz TEXT DEFAULT '',
  album_id TEXT,
  scope TEXT DEFAULT 'all',
  mode TEXT DEFAULT 'all',
  start_date TEXT DEFAULT '',
  start_ts INTEGER,
  end_ts INTEGER,
  status TEXT DEFAULT 'pending',
  progress INTEGER DEFAULT 0,
  last_offset INTEGER DEFAULT 0,
  last_itemidx INTEGER DEFAULT 0,
  error TEXT DEFAULT '',
  created_at TEXT DEFAULT (datetime('now','localtime'))
);
"""

_EXTRA_COLUMNS = {
    "accounts": [
        ("total_articles", "INTEGER DEFAULT 0"),
    ],
    "articles": [
        ("is_paid", "INTEGER DEFAULT 0"),
        ("paid_unlocked", "INTEGER DEFAULT 0"),
    ],
    "sync_tasks": [
        ("mode", "TEXT DEFAULT 'all'"),
        ("start_date", "TEXT DEFAULT ''"),
        ("last_itemidx", "INTEGER DEFAULT 0"),
        ("details_json", "TEXT DEFAULT '[]'"),
        ("label", "TEXT DEFAULT ''"),
    ],
}


def get_conn() -> sqlite3.Connection:
    """打开连接；遇外部进程瞬时锁定（readonly）时带退避重试。"""
    import time

    last_err = None
    for _ in range(5):
        try:
            conn = sqlite3.connect(DB_PATH, timeout=15)
            conn.row_factory = sqlite3.Row
            # 2026-08-07: WAL → DELETE。WAL 模式每次写库都会产生 .db-wal/.db-shm 伴随文件，
            # 本机外部安全/同步软件把这些"临时文件"成批移进回收站（44 万+ 个）。
            # 单用户本地应用无并发写需求，DELETE 模式零伴随文件，回收站不再堆积。
            conn.execute("PRAGMA journal_mode=DELETE")
            conn.execute("PRAGMA foreign_keys=ON")
            return conn
        except sqlite3.OperationalError as e:
            last_err = e
            time.sleep(1.0)
    raise RuntimeError(f"无法以读写模式打开数据库 {DB_PATH}: {last_err}")


def init_db() -> None:
    conn = get_conn()
    conn.executescript(SCHEMA)
    # 兼容旧库：补齐新增列
    for table, cols in _EXTRA_COLUMNS.items():
        existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for col, ddl in cols:
            if col not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
    # 兼容旧库：移除 accounts 冗余 article_count 列（遮蔽了子查询计数）
    acc_cols = {r[1] for r in conn.execute("PRAGMA table_info(accounts)").fetchall()}
    if "article_count" in acc_cols:
        conn.execute("ALTER TABLE accounts DROP COLUMN article_count")
    # 兼容旧库：appmsgid 全局唯一索引会误伤跨公众号撞号 → 改为 (biz, appmsgid) 复合唯一
    # （微信不同公众号的 appmsgid 可以相同，全局唯一会导致同步时覆盖归属）
    # 2026-08-04 再升级：微信 appmsgid 是「群发批次号」，同批次多图文用 idx 区分 →
    # 去重键必须含 idx，否则同批次 idx=2/3 的文章会被误杀
    old_idx = {r[1] for r in conn.execute("PRAGMA index_list(articles)").fetchall()}
    if "ux_articles_appmsgid" in old_idx:
        conn.execute("DROP INDEX IF EXISTS ux_articles_appmsgid")
    if "ux_articles_biz_appmsgid" in old_idx:
        conn.execute("DROP INDEX IF EXISTS ux_articles_biz_appmsgid")
    if "ux_articles_biz_appmsgid_idx" not in old_idx:
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_articles_biz_appmsgid_idx ON articles(biz, appmsgid, idx)"
        )
    # 兼容旧库：topics 重建为两级结构（去 UNIQUE(name)、加 parent_id）
    topic_cols = {r[1] for r in conn.execute("PRAGMA table_info(topics)").fetchall()}
    if "parent_id" not in topic_cols:
        conn.executescript(
            """
            CREATE TABLE topics_new (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL,
              color TEXT DEFAULT '#378ADD',
              parent_id INTEGER DEFAULT 0
            );
            INSERT INTO topics_new(id, name, color, parent_id)
              SELECT id, name, color, 0 FROM topics;
            DROP TABLE topics;
            ALTER TABLE topics_new RENAME TO topics;
            """
        )
    # 2026-08-28: 多主题支持——把旧的单主题关联（articles.topic_id）迁移进 article_topics
    # （幂等：只插入尚不存在的关联；articles.topic_id 保留为主主题兼容字段）
    conn.execute(
        """INSERT OR IGNORE INTO article_topics(article_id, topic_id)
           SELECT id, topic_id FROM articles WHERE topic_id IS NOT NULL AND topic_id != 0"""
    )
    conn.commit()
    conn.close()


# ---------- accounts ----------
def upsert_account(biz: str, name: str = "") -> int:
    conn = get_conn()
    conn.execute(
        "INSERT INTO accounts(biz, name) VALUES(?, ?) "
        "ON CONFLICT(biz) DO UPDATE SET name=COALESCE(NULLIF(?, ''), accounts.name)",
        (biz, name, name),
    )
    conn.commit()
    row = conn.execute("SELECT id FROM accounts WHERE biz=?", (biz,)).fetchone()
    conn.close()
    return row["id"]


def list_accounts():
    conn = get_conn()
    rows = conn.execute(
        "SELECT *, (SELECT COUNT(*) FROM articles a WHERE a.biz=accounts.biz) AS article_count "
        "FROM accounts ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_account(biz: str):
    conn = get_conn()
    row = conn.execute("SELECT * FROM accounts WHERE biz=?", (biz,)).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_account(biz: str) -> dict | None:
    """删除公众号及其全部文章记录；返回被删文章行列表（供调用方清文件）。"""
    conn = get_conn()
    acc = conn.execute("SELECT * FROM accounts WHERE biz=?", (biz,)).fetchone()
    if not acc:
        conn.close()
        return None
    rows = conn.execute("SELECT * FROM articles WHERE biz=?", (biz,)).fetchall()
    conn.execute("DELETE FROM articles WHERE biz=?", (biz,))
    conn.execute("DELETE FROM accounts WHERE biz=?", (biz,))
    conn.commit()
    conn.close()
    return {"account": dict(acc), "articles": [dict(r) for r in rows]}


# ---------- articles ----------
def upsert_article(data: dict) -> tuple[int, bool]:
    """插入文章；同公众号同 appmsgid 同 idx 已存在返回 (id, False)（幂等刷新）。

    去重键 = (biz, appmsgid, idx) 三元组：
    - biz：微信不同公众号的 appmsgid 可以相同（跨号撞号），必须带公众号
    - idx：微信 appmsgid 是「群发批次号」，同批次多图文用 idx(1/2/3) 区分，
      是不同文章！去重不带 idx 会把同批次的第 2/3 篇误杀为重复
    """
    appmsgid = data.get("appmsgid") or ""
    biz = data.get("biz", "")
    idx = data.get("idx") or 0
    conn = get_conn()
    if appmsgid and biz:
        row = conn.execute(
            "SELECT id FROM articles WHERE biz=? AND appmsgid=? AND idx=?",
            (biz, appmsgid, idx),
        ).fetchone()
        if row:
            # 已存在：刷新文件路径与内容（重同步 = 幂等刷新）
            conn.execute(
                """UPDATE articles SET biz=?, idx=?, title=?, author=?, digest=?, link=?,
                   cover=?, publish_time=?, source=?, topic_id=?, album_id=?,
                   html_path=?, images_dir=?, content_md=?, attrs_json=?, is_paid=? WHERE id=?""",
                (
                    data.get("biz", ""),
                    data.get("idx", 0),
                    data.get("title", ""),
                    data.get("author", ""),
                    data.get("digest", ""),
                    data.get("link", ""),
                    data.get("cover", ""),
                    data.get("publish_time"),
                    data.get("source", ""),
                    data.get("topic_id"),
                    data.get("album_id"),
                    data.get("html_path", ""),
                    data.get("images_dir", ""),
                    data.get("content_md", ""),
                    data.get("attrs_json", "{}"),
                    1 if data.get("is_paid") else 0,
                    row["id"],
                ),
            )
            conn.commit()
            conn.close()
            return row["id"], False
    cur = conn.execute(
        """INSERT INTO articles
           (biz, appmsgid, idx, title, author, digest, link, cover,
            publish_time, source, topic_id, album_id, html_path, images_dir, content_md, attrs_json, is_paid)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            data.get("biz", ""),
            appmsgid,
            data.get("idx", 0),
            data.get("title", ""),
            data.get("author", ""),
            data.get("digest", ""),
            data.get("link", ""),
            data.get("cover", ""),
            data.get("publish_time"),
            data.get("source", ""),
            data.get("topic_id"),
            data.get("album_id"),
            data.get("html_path", ""),
            data.get("images_dir", ""),
            data.get("content_md", ""),
            data.get("attrs_json", "{}"),
            1 if data.get("is_paid") else 0,
        ),
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id, True


def _topic_filter(conn, topic_ids: list[int]) -> tuple[str, list[int]]:
    """多主题筛选：任一命中（含后代）。返回 (SQL 片段, 展开后的后代 id 列表)。

    选「管理」→ 匹配打了「管理」或其任意子级主题的文章（与单主题时代后代语义一致）；
    选多个主题 → 任一命中即匹配（OR）。
    """
    if not topic_ids:
        return "", []
    expanded: list[int] = []
    for t in topic_ids:
        for i in _topic_with_descendants(conn, int(t)):
            if i not in expanded:
                expanded.append(i)
    ph = ",".join("?" * len(expanded))
    return f" AND a.id IN (SELECT DISTINCT article_id FROM article_topics WHERE topic_id IN ({ph}))", expanded


def list_articles(biz: str = "", topic_id: int = 0, q: str = "", limit: int = 500,
                  author: str = "", source: str = "", date_from: int = 0, date_to: int = 0,
                  offset: int = 0, paid: str = "", album_id: str = "", topic_ids: list[int] | None = None):
    conn = get_conn()
    sql = "SELECT a.*, t.name AS topic_name, t.color AS topic_color, p.name AS topic_parent, " \
          "al.title AS album_name FROM articles a " \
          "LEFT JOIN topics t ON t.id=a.topic_id " \
          "LEFT JOIN topics p ON p.id=t.parent_id " \
          "LEFT JOIN albums al ON al.album_id = a.album_id AND al.biz = a.biz WHERE 1=1"
    args = []
    if biz:
        sql += " AND a.biz=?"
        args.append(biz)
    if album_id == "__other__":
        sql += " AND (a.album_id IS NULL OR a.album_id='')"
    elif album_id:
        sql += " AND a.album_id=?"
        args.append(album_id)
    # 多主题筛选优先；兼容旧的单 topic_id（前端新代码走 topic_ids）
    tids = list(topic_ids or [])
    if topic_id and not tids:
        tids = [topic_id]
    if tids:
        tsql, targs = _topic_filter(conn, tids)
        sql += tsql
        args += targs
    if q:
        sql += " AND (a.title LIKE ? OR a.source LIKE ?)"
        args += [f"%{q}%", f"%{q}%"]
    if author:
        sql += " AND a.author LIKE ?"
        args.append(f"%{author}%")
    if source:
        sql += " AND a.source LIKE ?"
        args.append(f"%{source}%")
    if paid:
        # 付费筛选：paid=全部付费 / unlocked=已解锁 / locked=未解锁付费 / free=免费
        if paid == "free":
            sql += " AND COALESCE(a.is_paid,0)=0"
        else:
            sql += " AND COALESCE(a.is_paid,0)=1"
            if paid == "unlocked":
                sql += " AND COALESCE(a.paid_unlocked,0)=1"
            elif paid == "locked":
                sql += " AND COALESCE(a.paid_unlocked,0)=0"
    if date_from:
        sql += " AND COALESCE(a.publish_time,0) >= ?"
        args.append(date_from)
    if date_to:
        sql += " AND COALESCE(a.publish_time,0) <= ?"
        args.append(date_to)
    sql += " ORDER BY COALESCE(a.publish_time,0) DESC LIMIT ? OFFSET ?"
    args += [limit, offset]
    rows = conn.execute(sql, args).fetchall()
    # 每篇附加完整主题列表（article_topics 关联）
    tmap = {t[0]: t for t in conn.execute("SELECT id, name, color FROM topics")}
    arts = []
    for r in rows:
        d = dict(r)
        tids_row = get_article_topics(conn, d["id"])
        d["topics"] = [
            {"id": t, "name": tmap[t][1], "color": tmap[t][2]}
            for t in tids_row if t in tmap
        ]
        arts.append(d)
    conn.close()
    return arts


def get_article(article_id: int):
    conn = get_conn()
    row = conn.execute(
        "SELECT a.*, t.name AS topic_name, al.title AS album_name FROM articles a "
        "LEFT JOIN topics t ON t.id=a.topic_id "
        "LEFT JOIN albums al ON al.album_id = a.album_id AND al.biz = a.biz "
        "WHERE a.id=?",
        (article_id,),
    ).fetchone()
    if row:
        d = dict(row)
        tmap = {t[0]: t for t in conn.execute("SELECT id, name, color FROM topics")}
        d["topics"] = [
            {"id": t, "name": tmap[t][1], "color": tmap[t][2]}
            for t in get_article_topics(conn, article_id) if t in tmap
        ]
    conn.close()
    return d if row else None


def update_article(article_id: int, topic_id=None, attrs=None, album_id=None):
    conn = get_conn()
    if topic_id is not None:
        # 单篇设置主主题（保持与多主题关联一致：写入关联表）
        conn.execute("UPDATE articles SET topic_id=? WHERE id=?", (topic_id, article_id))
        conn.execute(
            "INSERT OR IGNORE INTO article_topics(article_id, topic_id) VALUES(?, ?)",
            (article_id, topic_id),
        )
    if attrs is not None:
        conn.execute("UPDATE articles SET attrs_json=? WHERE id=?", (attrs, article_id))
    if album_id is not None:
        # album_id 传空串表示移出专辑（归入"未归入专辑"）
        conn.execute("UPDATE articles SET album_id=? WHERE id=?", (album_id or None, article_id))
    conn.commit()
    conn.close()


def update_paid_status(article_id: int, unlocked: bool) -> None:
    """人工标注：该付费文章是否已付费解锁（paid_unlocked=1）。"""
    conn = get_conn()
    conn.execute("UPDATE articles SET paid_unlocked=? WHERE id=?", (1 if unlocked else 0, article_id))
    conn.commit()
    conn.close()


def update_article_content(article_id: int, content_md: str, content_html: str, html_path: str) -> None:
    """补录付费解锁的完整正文：更新 md 与本地 index.html 路径。"""
    conn = get_conn()
    conn.execute(
        "UPDATE articles SET content_md=?, html_path=?, paid_unlocked=1 WHERE id=?",
        (content_md, html_path, article_id),
    )
    conn.commit()
    conn.close()


def batch_set_topic(ids: list[int], topic_id: int | None) -> int:
    """批量设置文章主题（topic_id=None/0 表示清除）。返回受影响行数。

    覆盖式语义（兼容旧前端）：设置后文章仅保留该单一主题（先清关联再写入）。
    """
    if not ids:
        return 0
    conn = get_conn()
    ph = ",".join("?" * len(ids))
    cur = conn.execute(
        f"UPDATE articles SET topic_id=? WHERE id IN ({ph})",
        [topic_id if topic_id else None] + list(ids),
    )
    # 同步多主题关联表：覆盖 = 清空该批文章全部关联，再写入单一主题（如有）
    conn.execute(f"DELETE FROM article_topics WHERE article_id IN ({ph})", ids)
    if topic_id:
        for aid in ids:
            conn.execute(
                "INSERT OR IGNORE INTO article_topics(article_id, topic_id) VALUES(?, ?)",
                (aid, topic_id),
            )
    conn.commit()
    conn.close()
    return cur.rowcount


# ---------- 多主题（article_topics 关联表）----------
def get_article_topics(conn, article_id: int) -> list[int]:
    """返回文章关联的主题 id 列表（含主主题，按 topic_id 升序）。"""
    return [r[0] for r in conn.execute(
        "SELECT topic_id FROM article_topics WHERE article_id=? ORDER BY topic_id",
        (article_id,),
    )]


def batch_append_topics(ids: list[int], topic_ids: list[int]) -> int:
    """批量追加主题（追加式，不清旧关联）。返回新增关联数。"""
    if not ids or not topic_ids:
        return 0
    conn = get_conn()
    n = 0
    for aid in ids:
        for tid in topic_ids:
            cur = conn.execute(
                "INSERT OR IGNORE INTO article_topics(article_id, topic_id) VALUES(?, ?)",
                (aid, tid),
            )
            n += cur.rowcount
        # 同步主主题字段：文章无主主题时取最小关联 id
        row = conn.execute("SELECT topic_id FROM articles WHERE id=?", (aid,)).fetchone()
        if row and not row["topic_id"]:
            first = conn.execute(
                "SELECT MIN(topic_id) m FROM article_topics WHERE article_id=?", (aid,)
            ).fetchone()["m"]
            if first:
                conn.execute("UPDATE articles SET topic_id=? WHERE id=?", (first, aid))
    conn.commit()
    conn.close()
    return n


def remove_article_topic(article_id: int, topic_id: int) -> int:
    """移除单篇文章的某个主题。移除后若无关联则主主题置空。返回删除行数。"""
    conn = get_conn()
    cur = conn.execute(
        "DELETE FROM article_topics WHERE article_id=? AND topic_id=?", (article_id, topic_id)
    )
    n = cur.rowcount
    if n:
        left = conn.execute(
            "SELECT MIN(topic_id) m FROM article_topics WHERE article_id=?", (article_id,)
        ).fetchone()["m"]
        conn.execute(
            "UPDATE articles SET topic_id=? WHERE id=?",
            (left if left else None, article_id),
        )
        conn.commit()
    conn.close()
    return n


def batch_clear_topics(ids: list[int]) -> int:
    """批量清空文章的全部主题关联。返回受影响文章数。"""
    if not ids:
        return 0
    conn = get_conn()
    ph = ",".join("?" * len(ids))
    cur = conn.execute(f"DELETE FROM article_topics WHERE article_id IN ({ph})", ids)
    n = cur.rowcount
    conn.execute(f"UPDATE articles SET topic_id=NULL WHERE id IN ({ph})", ids)
    conn.commit()
    conn.close()
    return len(ids)


def delete_article(article_id: int) -> dict | None:
    """删除文章记录，返回被删行（供调用方清理文件）；不存在返回 None。"""
    conn = get_conn()
    row = conn.execute("SELECT * FROM articles WHERE id=?", (article_id,)).fetchone()
    if not row:
        conn.close()
        return None
    conn.execute("DELETE FROM articles WHERE id=?", (article_id,))
    conn.execute("DELETE FROM article_topics WHERE article_id=?", (article_id,))
    conn.commit()
    conn.close()
    return dict(row)


def count_articles() -> int:
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) c FROM articles").fetchone()["c"]
    conn.close()
    return n


def count_articles_filtered(biz: str = "", topic_id: int = 0, q: str = "",
                            author: str = "", source: str = "", date_from: int = 0, date_to: int = 0,
                            paid: str = "", topic_ids: list[int] | None = None) -> int:
    """与 list_articles 相同筛选条件下的总数（不带 LIMIT 截断）。"""
    conn = get_conn()
    sql = "SELECT COUNT(*) c FROM articles a WHERE 1=1"
    args = []
    if biz:
        sql += " AND a.biz=?"
        args.append(biz)
    tids = list(topic_ids or [])
    if topic_id and not tids:
        tids = [topic_id]
    if tids:
        tsql, targs = _topic_filter(conn, tids)
        sql += tsql
        args += targs
    if q:
        sql += " AND (a.title LIKE ? OR a.source LIKE ?)"
        args += [f"%{q}%", f"%{q}%"]
    if author:
        sql += " AND a.author LIKE ?"
        args.append(f"%{author}%")
    if source:
        sql += " AND a.source LIKE ?"
        args.append(f"%{source}%")
    if paid:
        if paid == "free":
            sql += " AND COALESCE(a.is_paid,0)=0"
        else:
            sql += " AND COALESCE(a.is_paid,0)=1"
            if paid == "unlocked":
                sql += " AND COALESCE(a.paid_unlocked,0)=1"
            elif paid == "locked":
                sql += " AND COALESCE(a.paid_unlocked,0)=0"
    if date_from:
        sql += " AND COALESCE(a.publish_time,0) >= ?"
        args.append(date_from)
    if date_to:
        sql += " AND COALESCE(a.publish_time,0) <= ?"
        args.append(date_to)
    n = conn.execute(sql, args).fetchone()["c"]
    conn.close()
    return n


def update_account_total(biz: str, total: int) -> None:
    """记录公众号在微信侧的全部历史文章数（getmsg 接口 app_msg_cnt，供工作台显示进度）。"""
    if not biz or total <= 0:
        return
    conn = get_conn()
    conn.execute("UPDATE accounts SET total_articles=? WHERE biz=?", (total, biz))
    conn.commit()
    conn.close()


def appmsgid_exists(biz: str, appmsgid: str, idx: int = 0) -> bool:
    """同公众号同 appmsgid 同 idx 是否已存在（去重键含 idx：同批次多图文是不同文章）。"""
    if not appmsgid:
        return False
    conn = get_conn()
    row = conn.execute(
        "SELECT id FROM articles WHERE biz=? AND appmsgid=? AND idx=?",
        (biz, appmsgid, idx),
    ).fetchone()
    conn.close()
    return row is not None


# ---------- albums ----------
def upsert_album(biz: str, album_id: str, title: str = "", cover: str = "") -> int:
    conn = get_conn()
    conn.execute(
        "INSERT INTO albums(biz, album_id, title, cover) VALUES(?,?,?,?) "
        "ON CONFLICT(album_id) DO UPDATE SET title=COALESCE(NULLIF(?, ''), albums.title)",
        (biz, album_id, title, cover, title),
    )
    conn.commit()
    row = conn.execute("SELECT id FROM albums WHERE album_id=?", (album_id,)).fetchone()
    conn.close()
    return row["id"]


def list_albums(biz: str = ""):
    conn = get_conn()
    sql = ("SELECT al.*, acc.name AS account_name FROM albums al "
           "LEFT JOIN accounts acc ON acc.biz = al.biz WHERE 1=1")
    args = []
    if biz:
        sql += " AND al.biz=?"
        args.append(biz)
    rows = conn.execute(sql + " ORDER BY al.id", args).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------- sync_tasks ----------
def create_task(
    type_: str, biz: str, scope: str = "all", mode: str = "all",
    album_id: str = "", start_ts=None, end_ts=None,
    last_offset: int = 0, last_itemidx: int = 0, start_date: str = "",
) -> int:
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO sync_tasks
           (type, biz, scope, mode, album_id, start_ts, end_ts,
            last_offset, last_itemidx, start_date, status)
           VALUES (?,?,?,?,?,?,?,?,?,?,'pending')""",
        (type_, biz, scope, mode, album_id, start_ts, end_ts,
         last_offset, last_itemidx, start_date),
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def create_manual_task(batch_id: str, label: str, biz: str = "") -> int:
    """创建扩展同步（单篇/批量）的任务记录；同 batch_id 复用已有任务。返回 task_id。"""
    conn = get_conn()
    row = conn.execute(
        "SELECT id FROM sync_tasks WHERE type='manual' AND scope=? LIMIT 1",
        (batch_id,),
    ).fetchone()
    if row:
        conn.close()
        return row["id"]
    cur = conn.execute(
        """INSERT INTO sync_tasks (type, biz, scope, mode, label, status)
           VALUES ('manual', ?, ?, 'all', ?, 'running')""",
        (biz, batch_id, label),
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def finish_manual_task(batch_id: str, synced: int, existing: int, failed: int) -> None:
    """扩展同步批次完成：更新任务统计并标记 done。"""
    conn = get_conn()
    conn.execute(
        """UPDATE sync_tasks SET status='done', progress=?,
           last_offset=?, last_itemidx=?, error=? WHERE type='manual' AND scope=?""",
        (synced + existing + failed, synced, existing, f"失败 {failed}" if failed else "", batch_id),
    )
    conn.commit()
    conn.close()


def update_task(task_id: int, status: str = "", progress: int | None = None,
                last_offset: int | None = None, last_itemidx: int | None = None,
                error: str = "", details_json: str = ""):
    conn = get_conn()
    sets, args = [], []
    if status:
        sets.append("status=?")
        args.append(status)
    if progress is not None:
        sets.append("progress=?")
        args.append(progress)
    if last_offset is not None:
        sets.append("last_offset=?")
        args.append(last_offset)
    if last_itemidx is not None:
        sets.append("last_itemidx=?")
        args.append(last_itemidx)
    if error:
        sets.append("error=?")
        args.append(error)
    if details_json is not None:
        sets.append("details_json=?")
        args.append(details_json)
    if sets:
        args.append(task_id)
        conn.execute(f"UPDATE sync_tasks SET {', '.join(sets)} WHERE id=?", args)
        conn.commit()
    conn.close()


def get_task(task_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM sync_tasks WHERE id=?", (task_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def reset_stale_running_tasks():
    """服务启动时调用：把上次进程遗留的 running 任务标记为 paused（防僵尸任务）。"""
    conn = get_conn()
    conn.execute(
        "UPDATE sync_tasks SET status='paused', "
        "error='服务重启中断，请重新打开主页/专辑页后重新同步（将从断点续跑）' "
        "WHERE status='running'"
    )
    conn.commit()
    conn.close()


def list_tasks(status: str = "", biz: str = "", type_: str = "", limit: int = 50):
    conn = get_conn()
    sql = "SELECT * FROM sync_tasks WHERE 1=1"
    args = []
    if status:
        sql += " AND status=?"
        args.append(status)
    if biz:
        sql += " AND biz=?"
        args.append(biz)
    if type_:
        sql += " AND type=?"
        args.append(type_)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_task(task_id: int) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM sync_tasks WHERE id=?", (task_id,))
    conn.commit()
    conn.close()


def delete_tasks_by_status(status: str) -> int:
    conn = get_conn()
    cur = conn.execute("DELETE FROM sync_tasks WHERE status=?", (status,))
    conn.commit()
    n = cur.rowcount
    conn.close()
    return n


# ---------- topics ----------
def list_topics():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM topics ORDER BY parent_id, id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def create_topic(name: str, color: str = "#378ADD", parent_id: int = 0) -> int:
    """创建主题；同一父级下重名则复用现有 id 并更新颜色。"""
    name = (name or "").strip()
    if not name:
        raise ValueError("主题名称不能为空")
    conn = get_conn()
    row = conn.execute(
        "SELECT id FROM topics WHERE name=? AND parent_id=?", (name, parent_id)
    ).fetchone()
    if row:
        conn.execute("UPDATE topics SET color=? WHERE id=?", (color, row["id"]))
        conn.commit()
        conn.close()
        return row["id"]
    cur = conn.execute(
        "INSERT INTO topics(name, color, parent_id) VALUES(?, ?, ?)",
        (name, color, parent_id),
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def _topic_with_descendants(conn, topic_id: int) -> list[int]:
    """递归收集某主题及其全部后代主题 id（多级主题树）。"""
    ids = [topic_id]
    frontier = [topic_id]
    while frontier:
        ph = ",".join("?" * len(frontier))
        nxt = [r[0] for r in conn.execute(
            f"SELECT id FROM topics WHERE parent_id IN ({ph})", frontier).fetchall()]
        ids += nxt
        frontier = nxt
    return ids


def delete_topic(topic_id: int) -> int:
    """递归删除主题及其全部后代主题；相关文章 topic_id 置空并清理关联。返回受影响主题数。"""
    conn = get_conn()
    ids = _topic_with_descendants(conn, topic_id)
    ph = ",".join("?" * len(ids))
    conn.execute(f"UPDATE articles SET topic_id=NULL WHERE topic_id IN ({ph})", ids)
    conn.execute(f"DELETE FROM article_topics WHERE topic_id IN ({ph})", ids)
    cur = conn.execute(f"DELETE FROM topics WHERE id IN ({ph})", ids)
    conn.commit()
    conn.close()
    return cur.rowcount


def list_facets(paid: str = "", author: str = "", source: str = "", album_id: str = "",
                topic_id: int = 0, date_from: int = 0, date_to: int = 0,
                topic_ids: list[int] | None = None):
    """筛选全联动：给定当前筛选条件，返回各维度「剩余可选」列表。

    规则：某维度自身的条件不参与该维度自身列表的过滤（保证已选值仍在下拉中，
    例如选了作者 A，作者下拉仍显示全部作者）；其余维度互相按当前条件过滤。
    主题列表按「文章实际关联主题 → 一级祖先」归并，与 list_articles 的多级匹配语义一致。
    """
    conn = get_conn()
    tids_all = list(topic_ids or [])
    if topic_id and not tids_all:
        tids_all = [topic_id]

    def _cond(exclude: str = ""):
        """构建过滤条件（统一 a. 前缀，供单表/联表查询复用）。exclude: 排除自身维度。"""
        sql = " WHERE 1=1"
        args = []
        if paid == "free":
            sql += " AND COALESCE(a.is_paid,0)=0"
        elif paid:
            sql += " AND COALESCE(a.is_paid,0)=1"
            if paid == "unlocked":
                sql += " AND COALESCE(a.paid_unlocked,0)=1"
            elif paid == "locked":
                sql += " AND COALESCE(a.paid_unlocked,0)=0"
        if exclude != "author" and author:
            sql += " AND a.author LIKE ?"
            args.append(f"%{author}%")
        if exclude != "source" and source:
            sql += " AND a.source LIKE ?"
            args.append(f"%{source}%")
        if exclude != "album" and album_id:
            if album_id == "__other__":
                sql += " AND (a.album_id IS NULL OR a.album_id='')"
            else:
                sql += " AND a.album_id=?"
                args.append(album_id)
        if exclude != "topic" and tids_all:
            tsql, targs = _topic_filter(conn, tids_all)
            sql += tsql
            args += targs
        if date_from:
            sql += " AND COALESCE(a.publish_time,0) >= ?"
            args.append(date_from)
        if date_to:
            sql += " AND COALESCE(a.publish_time,0) <= ?"
            args.append(date_to)
        return sql, args

    # 作者（不应用 author 自身条件）
    s, a = _cond("author")
    authors = [r[0] for r in conn.execute(
        "SELECT DISTINCT a.author FROM articles a" + s +
        " AND a.author IS NOT NULL AND a.author!='' ORDER BY a.author", a)]
    # 来源（不应用 source 自身条件）
    s, a = _cond("source")
    sources = [r[0] for r in conn.execute(
        "SELECT DISTINCT a.source FROM articles a" + s +
        " AND a.source IS NOT NULL AND a.source!='' ORDER BY a.source", a)]
    # 专辑（不应用 album 自身条件；join albums/accounts 取公众号名）
    s, a = _cond("album")
    albums = [{"album_id": r[0], "title": r[1], "account_name": r[2]} for r in conn.execute(
        "SELECT DISTINCT a.album_id, al.title, acc.name FROM articles a "
        "LEFT JOIN albums al ON al.album_id=a.album_id AND al.biz=a.biz "
        "LEFT JOIN accounts acc ON acc.biz=a.biz" + s +
        " AND a.album_id IS NOT NULL AND a.album_id!='' "
        "ORDER BY acc.name, al.title", a)]
    # 主题（不应用 topic 自身条件）：文章实际关联的主题 → 归并到一级/二级候选
    s, a = _cond("topic")
    sql_join = s.replace("a.", "a2.")  # 条件统一改用 a2 别名（articles 子查询）
    topic_ids = [r[0] for r in conn.execute(
        "SELECT DISTINCT at.topic_id FROM article_topics at "
        "JOIN articles a2 ON a2.id=at.article_id" + sql_join, a)]
    tmap = {t[0]: t for t in conn.execute("SELECT id, parent_id, name FROM topics")}
    parent_of = {tid: (t[1] or 0) for tid, t in tmap.items()}
    name_of = {tid: t[2] for tid, t in tmap.items()}

    def _l1_of(tid):
        """向上找一级祖先（parent_id 为 NULL/0 的即顶级）。"""
        seen = set()
        cur = tid
        while cur and cur not in seen:
            seen.add(cur)
            par = parent_of.get(cur, 0)
            if not par:
                return cur
            cur = par
        return None

    l1_ids = {lid for t in topic_ids if (lid := _l1_of(t))}
    l1_topics = [{"id": i, "name": name_of[i]} for i in l1_ids if i in name_of]
    l1_topics.sort(key=lambda x: x["name"])
    # 二级候选：非一级主题；若当前选了主题，则限其一级祖先下（前端按层级树展示）
    cur_l1s = {_l1_of(int(t)) for t in tids_all} if tids_all else set()
    l2_topics = [{"id": t, "name": name_of[t], "parent_id": parent_of[t]}
                 for t in topic_ids
                 if t in name_of and parent_of.get(t, 0)
                 and (not cur_l1s or (_l1_of(t) in cur_l1s))]
    l2_topics.sort(key=lambda x: (x["name"], x["id"]))
    conn.close()
    return {"authors": authors, "sources": sources, "albums": albums,
            "l1_topics": l1_topics, "l2_topics": l2_topics}
