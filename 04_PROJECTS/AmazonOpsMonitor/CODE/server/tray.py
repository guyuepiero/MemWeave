# -*- coding: utf-8 -*-
"""亚马逊运营监控台 · 托盘常驻管理（后台运行服务，无需保持命令行窗口）。

用法：
  pythonw tray.py                  # 正常托盘模式（无窗口，桌面启动端指向它）
  python  tray.py --serve-only     # 调试：只拉起服务并退出
  python  tray.py --stop           # 调试：按端口停止服务

设计（参考 WeChatArticleSync/tray_vault.py 同款成熟模式）：
- 服务进程 = .venv/Scripts/pythonw.exe -m app.main（隐藏窗口）
- 托盘菜单：打开工作台 / 重启服务 / 退出（停服务）
- 双击托盘图标 = 打开工作台
- 服务日志落 logs/server.log
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
except Exception:  # pragma: no cover
    print("[ERROR] 缺少 pystray / pillow，请先执行: .venv\\Scripts\\pip install pystray pillow")
    sys.exit(1)

BASE = Path(__file__).resolve().parent                # CODE/server
PYW = BASE / ".venv" / "Scripts" / "pythonw.exe"      # 无窗口 python
LOG_DIR = BASE / "logs"
HOST = "127.0.0.1"
PORT = int(os.environ.get("AMZ_MONITOR_PORT", "21889"))
URL = f"http://{HOST}:{PORT}"

_serv: subprocess.Popen | None = None


# ---------- 服务控制 ----------
def _port_open(host: str = HOST, port: int = PORT, timeout: float = 0.5) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex((host, port)) == 0


def _listening_pid() -> str | None:
    """用 netstat 找占用端口的 PID（解决托盘重启后无法追踪旧服务进程的问题）。

    Windows netstat 输出为 GBK 字节，须按 bytes 取回后 errors='ignore' 解码。
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
        # 服务已在跑：点启动端 = 打开一次工作台（仅此处一次，无双开）
        if auto_open:
            webbrowser.open(URL)
        return True
    if not PYW.exists():
        return False
    LOG_DIR.mkdir(exist_ok=True)
    # 浏览器只由本进程 _wait_and_open 开一次；服务进程 env 置 0 禁其自开，
    # 否则 main.py 的 AMZ_MONITOR_OPEN_BROWSER=1 定时自开 + 此处 = 每次启动双开标签（2026-09-08 坑）
    env = dict(os.environ, AMZ_MONITOR_OPEN_BROWSER="0")
    logf = open(LOG_DIR / "server.log", "ab", buffering=0)
    _serv = subprocess.Popen(
        [str(PYW), "-m", "app.main"],
        cwd=str(BASE), env=env,
        stdout=logf, stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if auto_open:
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
    """64x64 深蓝底 + 白色上升折线（运营监控台意象），纯 Pillow 绘制。"""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([2, 2, 62, 62], radius=14, fill=(0x1E, 0x2A, 0x3A, 255))
    # 三条柱
    d.rounded_rectangle([10, 32, 20, 52], radius=2, fill=(0x3B, 0x82, 0xF6, 255))
    d.rounded_rectangle([24, 24, 34, 52], radius=2, fill=(0x5C, 0xA6, 0xFA, 255))
    d.rounded_rectangle([38, 15, 48, 52], radius=2, fill=(0x8F, 0xC7, 0xFF, 255))
    # 上升折线
    d.line([(12, 50), (20, 42), (29, 45), (39, 34), (54, 20)], fill=(0xFF, 0xD1, 0x66, 255), width=3)
    d.ellipse([50, 16, 58, 24], fill=(0xFF, 0xD1, 0x66, 255))
    return img


def _open_workbench(icon=None, item=None) -> None:  # noqa: ARG001
    webbrowser.open(URL)


def _on_restart(icon=None, item=None) -> None:  # noqa: ARG001
    if icon:
        icon.notify("正在重启服务...", "亚马逊运营监控台")
    threading.Thread(target=restart_server, daemon=True).start()


def _on_quit(icon: pystray.Icon, item=None) -> None:  # noqa: ARG001
    stop_server()
    icon.stop()


def main() -> None:
    if "--serve-only" in sys.argv:
        ok = _ensure_server_started(auto_open=False)
        print("[serve-only] started" if ok else "[serve-only] port already open / failed")
        return
    if "--stop" in sys.argv:
        stop_server()
        print("[stop] done")
        return

    if not _ensure_server_started(auto_open=True):
        raise SystemExit("[ERROR] venv pythonw 缺失，请确认 .venv 完整")

    menu = pystray.Menu(
        pystray.MenuItem("打开工作台", _open_workbench, default=True),
        pystray.MenuItem("重启服务", _on_restart),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出（停止服务）", _on_quit),
    )
    icon = pystray.Icon(
        "AmazonOpsMonitor",
        _make_icon(),
        "亚马逊运营监控台",
        menu,
    )
    icon.run()


if __name__ == "__main__":
    main()
