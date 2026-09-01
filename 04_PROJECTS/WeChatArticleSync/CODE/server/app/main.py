"""微文收纳 · FastAPI 入口

启动: python -m app.main  （在 CODE/server 目录下）
访问: http://127.0.0.1:21888
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import db, routes_api, ws
from .config import ARTICLES_DIR, HOST, PORT, STATIC_DIR


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    # 上次进程遗留的 running 任务（协程已随旧进程消亡）标记为暂停，防僵尸任务
    db.reset_stale_running_tasks()
    # 仅 start.bat 用户启动时自动打开浏览器（后台/脚本启动不打扰）
    if os.environ.get("WEICHAT_VAULT_OPEN_BROWSER") == "1":
        import threading
        import time
        import webbrowser

        def _open_browser():
            time.sleep(1.5)
            try:
                webbrowser.open(f"http://{HOST}:{PORT}")
            except Exception:  # noqa: BLE001
                pass

        threading.Thread(target=_open_browser, daemon=True).start()
    yield


app = FastAPI(title="微文收纳", version="0.1.0", lifespan=lifespan)

app.include_router(routes_api.router)
app.include_router(ws.router)
# 本地文章文件服务：/files/{biz}/{appmsgid}/index.html（图片相对路径可用）
app.mount("/files", StaticFiles(directory=str(ARTICLES_DIR)), name="files")
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="ui")


@app.middleware("http")
async def no_cache(request, call_next):
    """本地工具：禁止浏览器缓存页面/资源，避免加载旧版前端代码导致功能异常。"""
    resp = await call_next(request)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    return resp


if __name__ == "__main__":
    import uvicorn

    from .config import HOST, PORT

    # use_colors=False：禁用 ANSI 颜色码，老版 cmd（conhost）不会显示 [32m 乱码
    uvicorn.run(app, host=HOST, port=PORT, log_level="info", use_colors=False)
