# 微文收纳 · 代码库（M0 骨架）

## 结构

```text
CODE/
├── server/                  # 本地客户端（Python FastAPI）
│   ├── requirements.txt
│   └── app/
│       ├── main.py          # 入口：python -m app.main
│       ├── config.py        # 端口 8787、数据目录
│       ├── db.py            # SQLite 数据访问（accounts/articles/topics）
│       ├── parser.py        # 微信文章页解析（适配层）
│       ├── storage.py       # 落盘 + 图片本地化
│       ├── exporters.py     # md/html/json/excel/txt/docx 导出
│       ├── syncer.py        # 历史抓取引擎（M1，当前骨架）
│       ├── routes_api.py    # REST API
│       ├── ws.py            # 扩展 WebSocket 通道
│       └── static/index.html# 工作台 UI
└── extension/               # Chrome/Edge 扩展（MV3）
    ├── manifest.json
    ├── background.js        # WS 连接 + 消息转发
    ├── content.js           # 文章页捕获
    ├── profile_capture.js   # 主页 getmsg key 拦截（M1 风险验证）
    ├── popup/               # 弹窗：同步当前页/批量/自动开关
    └── icons/
```

## 启动本地客户端（Windows）

**推荐：双击 `CODE/server/start.bat`**（在自己的终端环境启动，避免被文件监视类软件锁定数据文件）。

**一次安装，开机自启（推荐）**：双击 `CODE/server/install-autostart.bat`
- 创建「开机自启」快捷方式（登录后自动启动，最小化窗口）
- 创建桌面快捷方式 `WeChatVault`（想手动启动时双击）
- 卸载：双击 `uninstall-autostart.bat`；停止服务：双击 `stop.bat`

或命令行启动：

```bash
cd CODE/server
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m app.main
# 浏览器打开 http://127.0.0.1:8787
```

> 脚本均为纯 ASCII 内容（避免 GBK 终端乱码）；start.bat 已带端口占用检测（重复启动会提示已运行）。

> 说明：若数据库文件被本机其他进程（文件监视/同步/安全软件）以拒绝写入方式占用，
> 会出现 `attempt to write a readonly database`。对策：
> 1. 关闭占用该文件的程序后重试；
> 2. 或用环境变量把数据库指到别的目录：
>    `set WEICHAT_VAULT_DB=C:\YourPath\wechat_vault.db` 后再启动。

## 安装浏览器扩展

1. 打开 `chrome://extensions`（或 `edge://extensions`）
2. 右上角开启「开发者模式」
3. 点「加载已解压的扩展程序」→ 选择 `CODE/extension` 目录

## 使用（M0 链路）

1. 启动服务 + 安装扩展
2. 浏览器打开任意公众号文章页
3. 点扩展图标 → 「同步当前文章」（或开启「自动同步」，打开即存）
4. 打开 http://127.0.0.1:8787 → 文章库查看 → 导出 md/html/json/excel/txt/docx

## 验证会话拦截（M1 已实现）

- 打开公众号主页（mp.weixin.qq.com/mp/profile_ext?action=home&__biz=…）
- 扩展 `profile_capture.js` 会拦截 `getmsg` 请求并把 key/cookie/UA 会话推给客户端（`syncer.SESSIONS[biz]`）
- 工作台点击「同步」→ 后台任务分页拉取全部历史（getmsg offset 翻页）
- 同步范围：all / 1m / 3m / 6m / 1y / custom；模式：全量 / 增量（拉首页命中已存即停）
- key 过期 → 任务 paused；重新打开主页 → 扩展自动补 key → 任务从 last_offset 自动续跑
- 专辑页（appmsgalbum）：粘贴专辑链接 → 双游标分页抓取整本专辑

## REST 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/accounts/{biz}/sync?scope=&mode=&start_date= | 触发历史同步（后台任务） |
| POST | /api/albums/sync | 触发专辑同步 {biz, album_id, scope, mode} |
| GET | /api/tasks | 任务列表（状态/进度/计数） |
| POST | /api/tasks/{id}/cancel | 取消任务 |
| POST | /api/articles | 扩展单篇同步 |
| GET | /api/articles?biz=&topic_id=&q= | 文章查询 |
| POST | /api/accounts/resolve | 链接反查公众号 |
| POST | /api/export | 导出 {format: md/html/json/excel/txt/docx} |

## 测试

```bash
.venv\Scripts\python -m tests.test_engine   # 引擎逻辑测试（mock 微信接口）
```

## 数据目录

```text
DATA/
├── db/wechat_sync.db        # SQLite
├── articles/{biz}/{appmsgid}/   # source.html / index.html / images/ / article.md
└── exports/                 # 导出结果
```
