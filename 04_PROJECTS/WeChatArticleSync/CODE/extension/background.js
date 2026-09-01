// 微文收纳 · 后台 Service Worker
// 职责：维护到本地客户端的 WebSocket 连接，转发扩展捕获的数据
const SERVER_WS = "ws://127.0.0.1:21888/ws";
let ws = null;
let connected = false;
let queue = [];

function setBadge(n) {
  try {
    if (n > 0) {
      chrome.action.setBadgeText({ text: String(n) });
      chrome.action.setBadgeBackgroundColor({ color: "#D85A30" });
    } else {
      chrome.action.setBadgeText({ text: "" });
    }
  } catch (e) {}
}

function connect() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
  try { ws = new WebSocket(SERVER_WS); } catch (e) { setTimeout(connect, 3000); return; }

  ws.onopen = () => {
    connected = true;
    setBadge(0);
    if (queue.length) {
      const pending = queue;
      queue = [];
      pending.forEach(send);
    }
    // 服务端重启后自动重发最近一次捕获的会话（key 可能已过期，但可减少手动操作）
    chrome.storage.local.get({ vaultLastSession: null }, (r) => {
      if (r.vaultLastSession) {
        send({ kind: r.vaultLastSession.kind || "session.key", payload: r.vaultLastSession });
      }
    });
  };
  ws.onclose = () => { connected = false; setTimeout(connect, 3000); };
  ws.onerror = () => { try { ws.close(); } catch (e) {} };
  ws.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data);
      if (msg.kind === "sync.result") {
        const ok = (msg.results || []).filter(r => r && r.ok).length;
        const fail = (msg.results || []).length - ok;
        setBadge(fail);
        chrome.notifications?.create ? chrome.notifications.create({
          type: "basic", iconUrl: "icons/icon128.png", title: "微文收纳",
          message: `同步完成：成功 ${ok} 篇${fail ? `，失败 ${fail} 篇` : ""}`
        }) : null;
      }
    } catch (e) {}
  };
}

function send(msg) {
  if (connected && ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(msg));
  } else {
    queue.push(msg);
    connect();
  }
}

// 接收 content script / popup 消息
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || !msg.type) return;
  switch (msg.type) {
    case "sync_article": {
      const { payload } = msg;
      if (payload && payload.html) {
        send({ kind: "sync.article", payload });
        sendResponse({ ok: true, queued: true });
      } else {
        sendResponse({ ok: false, error: "缺少文章 HTML" });
      }
      break;
    }
    case "sync_batch": {
      const items = msg.items || [];
      if (items.length) {
        send({ kind: "sync.batch", payload: items });
        sendResponse({ ok: true, count: items.length });
      } else {
        sendResponse({ ok: false, error: "批量列表为空" });
      }
      break;
    }
    case "session": {
      send({ kind: msg.payload.kind || "session.key", payload: msg.payload });
      sendResponse({ ok: true });
      break;
    }
    case "get_status": {
      sendResponse({ connected, queued: queue.length });
      break;
    }
  }
});

chrome.runtime.onStartup?.addListener(connect);
connect();

// ===== 备用捕获通道：webRequest（不依赖页面脚本注入）=====
// 只要浏览器发出 getmsg/getalbum 请求，这里就一定能看到 URL 参数。
function buildSessionPayload(urlStr, kind) {
  try {
    const p = new URL(urlStr).searchParams;
    const payload = {
      kind,
      __biz: p.get("__biz") || "",
      key: p.get("key") || "",
      uin: p.get("uin") || "",
      pass_ticket: p.get("pass_ticket") || "",
      appmsg_token: p.get("appmsg_token") || "",
      exportkey: p.get("exportkey") || "",
      album_id: p.get("album_id") || "",
      begin_msgid: p.get("begin_msgid") || "",
      begin_itemidx: p.get("begin_itemidx") || "",
      ua: navigator.userAgent || "",
    };
    // 2026 微信新格式：key/uin/pass_ticket 藏在 scenenote 内嵌 URL 里
    const scenenote = p.get("scenenote");
    if (scenenote) {
      try {
        const inner = new URL(decodeURIComponent(scenenote));
        const sp = inner.searchParams;
        payload.key = payload.key || sp.get("key") || "";
        payload.uin = payload.uin || sp.get("uin") || "";
        payload.pass_ticket = payload.pass_ticket || sp.get("pass_ticket") || "";
        payload.appmsg_token = payload.appmsg_token || sp.get("appmsg_token") || "";
        payload.exportkey = payload.exportkey || sp.get("exportkey") || "";
      } catch (e) {}
    }
    return payload;
  } catch (e) { return null; }
}

async function sendSessionWithCookies(payload) {
  try {
    const cookies = await chrome.cookies.getAll({ domain: "mp.weixin.qq.com" });
    payload.cookie = cookies.map(c => `${c.name}=${c.value}`).join("; ");
  } catch (e) { payload.cookie = ""; }
  send({ kind: payload.kind, payload });
  chrome.storage.local.set({ vaultLastSession: payload });
}

if (chrome.webRequest) {
  chrome.webRequest.onBeforeRequest.addListener(
    (details) => {
      const url = details.url || "";
      if (!url.includes("mp.weixin.qq.com")) return;
      const isKey = url.includes("action=getmsg");
      const isAlbum = url.includes("action=getalbum");
      if (!isKey && !isAlbum) return;
      const payload = buildSessionPayload(url, isKey ? "session.key" : "session.album");
      if (!payload) return;
      if (isKey && !payload.__biz) return;
      if (isAlbum && !payload.album_id) return;
      sendSessionWithCookies(payload);
    },
    { urls: ["*://mp.weixin.qq.com/*"] },
    []
  );
}
