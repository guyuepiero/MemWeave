"""微文收纳 · 服务端配置"""
import os
from pathlib import Path

# 项目根目录: CODE/server/app/config.py -> parents[3] = WeChatArticleSync
PROJECT_DIR = Path(__file__).resolve().parents[3]
# 工作区根（MemWeave v1.0）= WeChatArticleSync 的上上层
WORKSPACE_ROOT = PROJECT_DIR.parents[1]
CODE_DIR = PROJECT_DIR / "CODE"
SERVER_DIR = CODE_DIR / "server"
STATIC_DIR = SERVER_DIR / "app" / "static"

DATA_DIR = PROJECT_DIR / "DATA"
DB_DIR = DATA_DIR / "db"
# 数据库位置可用环境变量覆盖（某些环境会锁定工作区内的文件，
# 可设 WEICHAT_VAULT_DB 指向工作区之外，如 %LOCALAPPDATA%\WeChatVault\wechat_vault.db）
_VDB_OVERRIDE = os.environ.get("WEICHAT_VAULT_DB")
if _VDB_OVERRIDE:
    DB_PATH = Path(_VDB_OVERRIDE)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
else:
    DB_PATH = DB_DIR / "wechat_vault.db"
ARTICLES_DIR = DATA_DIR / "articles"
# 导出目录：工作区知识库 RAW（用户指定）
EXPORT_DIR = WORKSPACE_ROOT / "06_KNOWLEDGE" / "RAW"

HOST = "127.0.0.1"
# 端口可用环境变量覆盖（WEICHAT_VAULT_PORT）；默认 21888（冷门端口，避开常见软件占用）
PORT = int(os.environ.get("WEICHAT_VAULT_PORT", "21888"))
WS_URL = f"ws://{HOST}:{PORT}/ws"

REFERER = "https://mp.weixin.qq.com/"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# 同步范围
SCOPE_ALL = "all"
SCOPES = {SCOPE_ALL, "1m", "3m", "6m", "1y", "custom"}

for _d in (DB_DIR, ARTICLES_DIR, EXPORT_DIR, STATIC_DIR):
    _d.mkdir(parents=True, exist_ok=True)
