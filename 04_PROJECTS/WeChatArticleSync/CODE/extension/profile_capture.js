// 微文收纳 · 主页/专辑会话捕获脚本（M1 风险验证）
// 在公众号主页/专辑页 document_start 注入，拦截 getmsg / getalbum 请求，
// 捕获 key/uin/pass_ticket/appmsg_token 并转发给本地客户端。
// 关键点：复用浏览器真实发出的请求，客户端不自行构造签名。

(function () {
  if (window.__wechat_vault_session_loaded) return;
  window.__wechat_vault_session_loaded = true;

  function paramsOf(url) {
    try { return new URL(url).searchParams; } catch (e) { return null; }
  }

  function capture(urlStr) {
    if (!urlStr || typeof urlStr !== "string") return;
    if (!urlStr.includes("mp.weixin.qq.com")) return;
    const p = paramsOf(urlStr);
    if (!p) return;
    const isKey = urlStr.includes("action=getmsg");
    const isAlbum = urlStr.includes("action=getalbum");
    if (!isKey && !isAlbum) return;

    const payload = {
      kind: isKey ? "session.key" : "session.album",
      __biz: p.get("__biz") || "",
      key: p.get("key") || "",
      uin: p.get("uin") || "",
      pass_ticket: p.get("pass_ticket") || "",
      appmsg_token: p.get("appmsg_token") || "",
      exportkey: p.get("exportkey") || "",
      album_id: p.get("album_id") || "",
      begin_msgid: p.get("begin_msgid") || "",
      begin_itemidx: p.get("begin_itemidx") || "",
      cookie: document.cookie || "",
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
    if (isKey && !payload.__biz) return;
    if (isAlbum && !payload.album_id) return;

    try {
      chrome.runtime.sendMessage({ type: "session", payload });
      // 缓存最近一次会话：服务端重启后由后台重发，避免会话丢失
      chrome.storage.local.set({ vaultLastSession: payload });
    } catch (e) {}
  }

  // 拦截 fetch
  const origFetch = window.fetch;
  window.fetch = function (...args) {
    try {
      const u = args[0];
      if (typeof u === "string") capture(u);
      else if (u instanceof URL) capture(u.href);
      else if (u && u.url) capture(u.url);
    } catch (e) {}
    return origFetch.apply(this, args);
  };

  // 拦截 XHR
  const origOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (method, url) {
    try { capture(typeof url === "string" ? url : String(url)); } catch (e) {}
    return origOpen.apply(this, arguments);
  };
})();
