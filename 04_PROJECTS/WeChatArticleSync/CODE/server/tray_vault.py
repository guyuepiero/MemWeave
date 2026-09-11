# -*- coding: utf-8 -*-
"""微文收纳 托盘常驻管理（后台运行服务，无需保持命令行窗口）。

用法：
  pythonw tray_vault.py            # 正常托盘模式（无窗口）
  python  tray_vault.py --serve-only  # 调试：只拉起服务并退出（服务由 pythonw 继续跑）
  python  tray_vault.py --stop     # 调试：按端口停止服务

设计：
- 服务进程 = CODE/server/.venv/Scripts/pythonw.exe -m app.main（隐藏窗口）
- 托盘菜单：打开工作台 / 重启服务 / 退出（停服务）
- 双击托盘图标 = 打开工作台
- 服务 stdout/stderr 落 logs/server.log 便于排障
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

try:
    import pystray
    from PIL import Image, ImageDraw
except Exception:  # pragma: no cover - 缺依赖时给明确提示
    print("[ERROR] 缺少 pystray / pillow，请先执行: .venv\\Scripts\\pip install pystray pillow")
    sys.exit(1)

BASE = Path(__file__).resolve().parent            # CODE/server
PYW = BASE / ".venv" / "Scripts" / "pythonw.exe"  # 无窗口 python
LOG_DIR = BASE / "logs"
HOST = "127.0.0.1"
PORT = 21888
URL = f"http://{HOST}:{PORT}"

_serv: subprocess.Popen | None = None


# ---------- 服务控制 ----------
def _port_open(host: str = HOST, port: int = PORT, timeout: float = 0.5) -> bool:
    """探测端口是否已有服务监听。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex((host, port)) == 0


def _listening_pid() -> str | None:
    """用 netstat 找占用端口的 PID（解决托盘重启后无法追踪旧服务进程的问题）。

    注意：Windows netstat 输出含系统编码（GBK）字节，必须按 bytes 取回后
    以 errors='ignore' 解码，避免 text=True 按 UTF-8 解码时抛 UnicodeDecodeError。
    """
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True,
                             creationflags=subprocess.CREATE_NO_WINDOW).stdout
    except Exception:
        return None
    if not out:
        return None
    for line in out.decode("utf-8", errors="ignore").splitlines():
        if f":{PORT}" in line and "LISTENING" in line:
            parts = line.split()
            if parts and parts[-1].isdigit():
                return parts[-1]
    return None


def _ensure_server_started(auto_open: bool = True) -> bool:
    """服务未运行时用 pythonw 拉起；auto_open=True 且本次由本进程拉起时自动开浏览器。"""
    global _serv
    if _port_open():
        return True
    if not PYW.exists():
        return False
    LOG_DIR.mkdir(exist_ok=True)
    env = dict(os.environ, WEICHAT_VAULT_OPEN_BROWSER="0")
    logf = open(LOG_DIR / "server.log", "ab", buffering=0)
    _serv = subprocess.Popen(
        [str(PYW), "-m", "app.main"],
        cwd=str(BASE), env=env,
        stdout=logf, stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if auto_open:
        # 后台线程等端口就绪后自动开浏览器（uvicorn 冷启动约 1~3s）
        threading.Thread(target=_wait_and_open, daemon=True).start()
    return True


def _wait_and_open(max_wait: float = 15.0) -> None:
    for _ in range(int(max_wait / 0.3)):
        if _port_open():
            webbrowser.open(URL)
            return
        time.sleep(0.3)


def stop_server() -> None:
    """停服务：先终止本进程拉起的子进程，再按端口补杀残留（幂等）。"""
    global _serv
    if _serv is not None and _serv.poll() is None:
        try:
            _serv.terminate()
            _serv.wait(timeout=5)
        except Exception:
            try:
                _serv.kill()
            except Exception:
                pass
        _serv = None
    pid = _listening_pid()
    if pid and pid != str(os.getpid()):
        subprocess.run(["taskkill", "/PID", pid, "/F"],
                       capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)


def restart_server() -> None:
    stop_server()
    time.sleep(0.6)
    _ensure_server_started(auto_open=True)


# ---------- 托盘 UI ----------
def _make_icon() -> Image.Image:
    """64x64 蓝底白色文档图标（纯 Pillow 绘制，无字体依赖）。"""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([2, 2, 62, 62], radius=14, fill=(0x1F, 0x7A, 0xE6, 255))
    # 白色文档：主体 + 右上折角
    d.rounded_rectangle([14, 10, 50, 54], radius=3, fill=(255, 255, 255, 255))
    d.polygon([(50, 10), (50, 22), (38, 22), (38, 10)], fill=(0x1F, 0x7A, 0xE6, 255))
    # 文字行
    for y in (28, 35, 42):
        d.rounded_rectangle([20, y, 44 if y < 42 else 35, y + 3], radius=2,
                            fill=(0x1F, 0x7A, 0xE6, 255))
    return img


def _open_workbench(icon=None, item=None) -> None:  # noqa: ARG001
    webbrowser.open(URL)


def _on_restart(icon=None, item=None) -> None:  # noqa: ARG001
    if icon:
        icon.notify("正在重启服务...", "微文收纳")
    threading.Thread(target=_do_restart, daemon=True).start()


def _do_restart() -> None:
    restart_server()


def _on_quit(icon: pystray.Icon, item=None) -> None:  # noqa: ARG001
    stop_server()
    icon.stop()


def main() -> None:
    # ---- 调试模式 ----
    if "--serve-only" in sys.argv:
        ok = _ensure_server_started(auto_open=False)
        print("[serve-only] started" if ok else "[serve-only] port already open / failed")
        return
    if "--stop" in sys.argv:
        stop_server()
        print("[stop] done")
        return

    # ---- 正常托盘模式 ----
    if not _ensure_server_started(auto_open=True):
        raise SystemExit("[ERROR] venv pythonw 缺失，请确认 .venv 完整")

    menu = pystray.Menu(
        pystray.MenuItem("打开工作台", _open_workbench, default=True),
        pystray.MenuItem("重启服务", _on_restart),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出（停止服务）", _on_quit),
    )
    icon = pystray.Icon(
        "WeChatVault",
        _make_icon(),
        "微文收纳 v0911-5",
        menu,
    )
    icon.run()


if __name__ == "__main__":
    main()
