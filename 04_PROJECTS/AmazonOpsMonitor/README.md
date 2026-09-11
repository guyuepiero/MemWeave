# 亚马逊运营监控台 AmazonOpsMonitor

本地浏览器运行的亚马逊运营 Dashboard（FastAPI 服务 + 托盘常驻），桌面双击启动。

## 架构

```
桌面「亚马逊运营工作台.bat」  →  CODE/server/tray.py (pythonw 托盘常驻)
                                    └─ 拉起 FastAPI 服务 http://127.0.0.1:21889
                                          ├─ /            → 工作台页面 (选品分析 09 实装, 01-08 占位)
                                          ├─ /api/data    → data/ 目录主数据集 JSON
                                          └─ /api/health  → 健康检查
```

参考 `04_PROJECTS/WeChatArticleSync` 同款模式（本地服务 + 浏览器 + 托盘）。

## 启动 / 停止

| 动作 | 方式 |
|---|---|
| 启动 | 双击桌面「亚马逊运营工作台.bat」→ 托盘常驻 + 自动开浏览器 |
| 打开页面 | 双击托盘图标 / 托盘菜单「打开工作台」/ 浏览器访问 http://127.0.0.1:21889 |
| 重启服务 | 托盘右键 → 重启服务 |
| 停止 | 托盘右键 → 退出（停止服务）；或 `stop.bat` |

页面顶部左侧「导入数据集」仍可手动导入任意 JSON（覆盖服务端数据，仅本次会话）。

## 换类目 / 换数据

把爬虫产出的新 JSON 放入 `CODE/server/data/` 后刷新页面即可：
- 单文件: `data/amazon_xxx_FINAL.json`（自动取最新修改的那个）
- 指定文件: `data/current.json`（优先于其它）

页面会自动从 `/api/data` 拉取（兼容 `amazon_batch_v21.py` 28 字段格式）；
若直接双击 `index.html`（file:// 打开）则回退到页面内联数据。

## 服务端文件

```
CODE/server/
├── app/
│   ├── config.py        # 端口 21889 / 目录定义
│   ├── main.py          # FastAPI: 页面 + /api/data + /api/health
│   └── static/index.html# 工作台前端（单文件，零外链）
├── data/                # 数据集 JSON（替换即换数据）
├── tray.py              # 托盘常驻管理（打开/重启/退出）
├── start-tray.bat       # 启动入口（与桌面 bat 等价，放在 server 内）
├── run-console.bat      # 控制台调试模式（保留日志窗口）
├── stop.bat             # 停止服务
├── tools/make_icon.py   # 重新生成 appicon 图标
├── requirements.txt
├── appicon.ico / appicon.png
└── logs/server.log      # 服务日志（排障看这里）
```

## 模块状态

- 01-08（总览/ASIN 监控/流量趋势/关键词/异常/AI 日报/数据记录/竞品对比）: 占位，待接数据
- 09 选品分析: ✅ 实装 7 大视图（市场全景/销量/价格带/品牌集中度/品牌销量/卖家类型/上架时间）
- 数据: 内置 cable_staples 100 条样例；`first_available` 仅 5/100 有值，上架时间模块待补爬
