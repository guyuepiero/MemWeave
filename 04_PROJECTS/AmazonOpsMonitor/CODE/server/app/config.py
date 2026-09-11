"""亚马逊运营监控台 · 服务端配置

工作台 = 运营监控(01-08 占位) + 选品分析(09 实装) 本地 Dashboard
架构参考: 04_PROJECTS/WeChatArticleSync/CODE/server (同款 FastAPI + 托盘模式)
"""
import os
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1]   # CODE/server
STATIC_DIR = SERVER_DIR / "app" / "static"          # 页面 index.html
DATA_DIR = SERVER_DIR / "data"                      # 数据集 JSON（替换即换类目）
LOG_DIR = SERVER_DIR / "logs"

# 类目选品树（Amazon Browse Tree Guide 分片 + 选品标记 + 爬取队列）
BTG_DIR = DATA_DIR / "btg"                          # 15 个大类分片 + index.json
BTG_PROGRESS = DATA_DIR / "btg_progress.json"       # 选品标记（节点 id -> 状态）
BTG_QUEUE = DATA_DIR / "bsr_queue.json"             # 待爬取节点队列（供爬虫脚本消费）
# 数据集 -> 类目节点绑定表（爬虫产出纯数组无 meta 时用它登记）: {文件名: {name,node,cat,sub,date}}
DATASET_NODES = DATA_DIR / "dataset_nodes.json"

# 立即采集：调用 amazon-scraper-pro 脚本（路径在 AI_OS 工作区下）
SCRAPER_SCRIPT = Path(r"C:\Users\guyuepiero\Documents\MemWeave v1.0\05_SKILLS\COMMON\amazon-scraper-pro\amazon_batch_v21.py")
# 爬虫 venv：workbuddy managed env（已装 playwright + openpyxl），避开工作台 venv（无 playwright）
SCRAPER_PY = Path(r"C:\Users\guyuepiero\.workbuddy\binaries\python\envs\default\Scripts\python.exe")
# 07_OUTPUTS：工作台采集产出的归档目录（与 bsr_cable_staples_100 同根）
OUTPUTS_DIR = Path(r"C:\Users\guyuepiero\Documents\MemWeave v1.0\07_OUTPUTS")

HOST = "127.0.0.1"
# 端口可用环境变量覆盖（AMZ_MONITOR_PORT）；默认 21889（避开微信工作台 21888 及常见软件）
PORT = int(os.environ.get("AMZ_MONITOR_PORT", "21889"))
URL = f"http://{HOST}:{PORT}"
TITLE = "亚马逊运营监控台"

# 桌面快捷方式 / 托盘提示里用的服务标识
SERVICE_KEY = "AmazonOpsMonitor"

for _d in (STATIC_DIR, DATA_DIR, LOG_DIR):
    _d.mkdir(parents=True, exist_ok=True)
