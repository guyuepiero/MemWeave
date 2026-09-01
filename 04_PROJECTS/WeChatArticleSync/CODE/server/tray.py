"""微文收纳 · 托盘常驻程序
右下角托盘图标：左键/双击打开工作台；右键菜单可【打开工作台 / 重启服务 / 退出】。
退出 = 停止服务 + 退出托盘。服务日志写入 server.log（无窗口模式排障用）。

用法（无黑框启动）：start-tray.bat  或  pythonw.exe tray.py
"""
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser

import pystray
from PIL import Image

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_PY = os.path.join(BASE_DIR, ".venv", "Scripts", "python.exe")
SERVER_LOG = os.path.join(BASE_DIR, "server.log")
ICON_PATH = os.path.join(BASE_DIR, "tray_icon.png")
HOST, PORT = "127.0.0.1", 21888
URL = f"http://{HOST}:{PORT}"

server_proc: subprocess.Popen | None = None
_log_lock = threading.Lock()


def log(msg: str) -> None:
    """托盘自身日志（无窗口，统一落 server.log）"""
    with _log_lock:
        try:
            with open(SERVER_LOG, "a", encoding="utf-8") as f:
                f.write(f"[tray {time.strftime('%m-%d %H:%M:%S')}] {msg}\n")
        except OSError:
            pass


def port_in_use(host: str = HOST, port: int = PORT) -> bool:
    """探测服务是否已在监听"""
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def start_server() -> None:
    """拉起后端服务（无窗口子进程，日志落 server.log）"""
    global server_proc
    if port_in_use():
        log("检测到服务已在运行，跳过启动")
        return
    if server_proc and server_proc.poll() is None:
        return
    try:
        log_file = open(SERVER_LOG, "a", encoding="utf-8")
        server_proc = subprocess.Popen(
            [VENV_PY, "-m", "app.main"],
            cwd=BASE_DIR,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        log(f"服务已启动 pid={server_proc.pid}")
    except Exception as e:  # noqa: BLE001
        log(f"服务启动失败: {e}")


def stop_server() -> None:
    """停止服务（优先按 pid 树杀，兜底按端口找）"""
    global server_proc
    if server_proc and server_proc.poll() is None:
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(server_proc.pid)],
                capture_output=True, timeout=10,
            )
            log(f"服务已停止 pid={server_proc.pid}")
        except Exception as e:  # noqa: BLE001
            log(f"停止服务失败: {e}")
        server_proc = None
        return
    # 兜底：按端口找监听进程
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=10).stdout
        for line in out.splitlines():
            if f":{PORT}" in line and "LISTENING" in line:
                pid = line.split()[-1]
                subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True, timeout=10)
                log(f"兜底停止服务 pid={pid}")
                break
    except Exception as e:  # noqa: BLE001
        log(f"兜底停止失败: {e}")


def open_workbench(icon=None, item=None) -> None:
    webbrowser.open(URL)
    log("打开工作台")


def restart_server(icon=None, item=None) -> None:
    log("重启服务")
    stop_server()
    time.sleep(0.5)
    start_server()


def quit_app(icon=None, item=None) -> None:
    log("退出托盘（停止服务）")
    stop_server()
    if icon:
        icon.stop()


def main() -> None:
    # 启动服务（若已在运行则跳过）
    start_server()

    # 托盘图标
    try:
        image = Image.open(ICON_PATH).convert("RGBA")
    except OSError:
        image = Image.new("RGBA", (64, 64), (216, 90, 48, 255))
    menu = pystray.Menu(
        pystray.MenuItem("打开工作台", open_workbench, default=True),
        pystray.MenuItem("重启服务", restart_server),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出", quit_app),
    )
    icon = pystray.Icon("wechat_vault", image, "微文收纳 · 本地服务", menu)
    log("托盘已就绪")
    icon.run()  # 阻塞，直到退出


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        log(f"托盘异常退出: {e!r}")
        sys.exit(1)
