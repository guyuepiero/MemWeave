// 微文收纳 · 文章页捕获脚本（https://mp.weixin.qq.com/s/*）
// 提取文章结构化信息 + 源格式正文 HTML

(function () {
  if (window.__wechat_vault_loaded) return;
  window.__wechat_vault_loaded = true;

  function jsVar(name) {
    const m = new RegExp('var\\s+' + name + '\\s*=\\s*["\']([^"\']*)["\']').exec(document.documentElement.innerHTML);
    return m ? m[1] : "";
  }
  // 兜底：从 URL query 提取 mid(批次号=appmsgid)/idx（微信文章页 JS 变量可能缺失）
  function urlMidIdx() {
    let mid = "", idx = "";
    try {
      const u = new URL(location.href);
      mid = u.searchParams.get("mid") || "";
      idx = u.searchParams.get("idx") || "";
    } catch (e) { /* ignore */ }
    return { mid, idx };
  }
  function meta(attr, key) {
    const el = document.querySelector(`meta[${attr}="${key}"]`);
    return el ? (el.content || "").trim() : "";
  }
  function accountName() {
    const el = document.getElementById("js_name");
    if (el && el.innerText.trim()) return el.innerText.trim();
    return jsVar("nickname") || "";
  }

  function extract() {
    const acc = accountName();
    const u = urlMidIdx();
    const appmsgid = jsVar("appmsgid") || u.mid || "";
    const idxRaw = jsVar("idx") || u.idx || "0";
    return {
      url: location.href,
      title: meta("property", "og:title") || document.title || "",
      author: meta("name", "author") || acc,
      biz: jsVar("biz") || "",
      appmsgid,
      idx: parseInt(idxRaw, 10) || 0,
      publish_time: (jsVar("ct") && /^\d+$/.test(jsVar("ct"))) ? parseInt(jsVar("ct"), 10) : null,
      cover: meta("property", "og:image") || "",
      source: acc,
      digest: meta("name", "description") || "",
      html: document.documentElement.outerHTML,
    };
  }

  // 响应 popup / background 的抓取请求
  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg && msg.type === "extract") {
      const data = extract();
      sendResponse({ ok: true, payload: data });
      if (msg.sync) {
        chrome.runtime.sendMessage({ type: "sync_article", payload: data });
      }
    }
    return true;
  });

  // 自动同步开关：打开文章页即自动捕获
  chrome.storage.local.get({ autoSync: false }, (cfg) => {
    if (cfg.autoSync) {
      const data = extract();
      if (data.biz && data.html) {
        data.batch_id = "a" + Date.now();
        data.batch_label = "自动同步（打开文章即存）";
        chrome.runtime.sendMessage({ type: "sync_article", payload: data });
      }
    }
  });
})();
