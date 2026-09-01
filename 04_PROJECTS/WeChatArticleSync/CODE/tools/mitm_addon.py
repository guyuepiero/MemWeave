"""微文收纳 · mitmproxy 插件（B 计划）

用途：微信电脑版客户端内的公众号主页（历史消息）请求走系统代理时，
拦截 getmsg / getalbum 请求，把真实会话（key/cookie/UA）推给本地服务，
服务即可用同一会话分页拉取全部历史。

使用：
  pip install mitmproxy
  mitmproxy -s mitm_addon.py        # 或 mitmdump -s mitm_addon.py
  系统代理设置为 127.0.0.1:8080，并在系统信任 mitmproxy CA 证书
  然后电脑版微信里打开目标公众号主页即可

注意：若微信客户端做了证书钉扎（连接报错/抓不到），此方案不可用。
"""
import json

from mitmproxy import http

SERVER = "http://127.0.0.1:8787/api/sessions"


def response(flow: http.HTTPFlow) -> None:
    url = flow.request.pretty_url or ""
    if "mp.weixin.qq.com" not in url:
        return
    if "action=getmsg" not in url and "action=getalbum" not in url:
        return

    q = flow.request.query
    try:
        cookies = "; ".join(f"{k}={v}" for k, v in flow.request.cookies.items())
    except Exception:
        cookies = ""
    payload = {
        "biz": q.get("__biz", ""),
        "key": q.get("key", ""),
        "uin": q.get("uin", ""),
        "pass_ticket": q.get("pass_ticket", ""),
        "appmsg_token": q.get("appmsg_token", ""),
        "album_id": q.get("album_id", ""),
        "begin_msgid": q.get("begin_msgid", ""),
        "cookie": cookies,
        "ua": flow.request.headers.get("User-Agent", ""),
    }
    if not payload["biz"]:
        return
    try:
        import requests

        requests.post(SERVER, json=payload, timeout=5)
        print(f"[vault] session captured: {payload['biz'][:20]}...")
    except Exception as e:  # noqa: BLE001
        print(f"[vault] push failed: {e}")
