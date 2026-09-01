// 微文收纳 · 弹窗逻辑
const $ = (id) => document.getElementById(id);

function refreshStatus() {
  chrome.runtime.sendMessage({ type: "get_status" }, (res) => {
    const dot = $("dot"), txt = $("connText");
    const on = res && res.connected;
    dot.className = "dot " + (on ? "on" : "off");
    txt.textContent = on ? `已连接 · 队列 ${res.queued}` : "未连接本地客户端（请先启动服务）";
  });
}

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

// 兼容 http/https 与 /s/xxx、/s?__biz=… 两种链接格式
function isWechatArticle(url) {
  if (!url) return false;
  try {
    const u = new URL(url);
    return u.hostname === "mp.weixin.qq.com" &&
      (u.pathname === "/s" || u.pathname.startsWith("/s/"));
  } catch (e) {
    return false;
  }
}

// 先尝试与页面通信；若内容脚本未注入（页面在装扩展前就打开了），注入后再试
async function extractFromTab(tab) {
  try {
    return await chrome.tabs.sendMessage(tab.id, { type: "extract", sync: true });
  } catch (e) {
    try {
      await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["content.js"] });
      return await chrome.tabs.sendMessage(tab.id, { type: "extract", sync: true });
    } catch (e2) {
      throw e2;
    }
  }
}

function showDebugTab() {
  activeTab().then((tab) => {
    const el = $("tabInfo");
    if (!tab) { el.textContent = "未获取到当前标签页"; return; }
    const ok = isWechatArticle(tab.url);
    el.textContent = `当前标签页：${tab.url || "(无地址)"} ${ok ? "✅ 微信文章" : "❌ 非微信文章"}`;
    el.style.color = ok ? "#0F6E56" : "#A32D2D";
  });
}

$("syncBtn").addEventListener("click", async () => {
  const tab = await activeTab();
  if (!tab || !isWechatArticle(tab.url)) {
    showDebugTab();
    alert("当前页不是公众号文章。\n\n注意：文章必须在本浏览器（Chrome/Edge）里打开，微信客户端内置浏览器里打开的无法识别。\n地址形如：mp.weixin.qq.com/s/xxx 或 mp.weixin.qq.com/s?__biz=…");
    return;
  }
  try {
    const res = await extractFromTab(tab);
    if (res && res.ok) {
      // 单篇同步也带批次信息，记入同步任务
      const payload = { ...res.payload, batch_id: "m" + Date.now(), batch_label: "同步当前文章" };
      chrome.runtime.sendMessage({ type: "sync_article", payload });
      alert("已发送到本地客户端：" + (res.payload.title || "").slice(0, 30));
    } else alert("抓取失败：" + ((res && res.error) || "页面可能未加载完成"));
  } catch (e) {
    alert("无法与页面通信，请刷新文章页后重试");
  }
  refreshStatus();
});

$("batchBtn").addEventListener("click", async () => {
  const all = await chrome.tabs.query({});
  const tabs = all.filter((t) => isWechatArticle(t.url));
  if (!tabs.length) { alert("没有打开的微信文章标签页（需为 mp.weixin.qq.com/s/…）"); return; }
  const batch_id = "b" + Date.now();
  const items = [];
  for (const t of tabs) {
    try {
      const res = await extractFromTab(t);
      if (res && res.ok && res.payload && res.payload.html) items.push({ ...res.payload, batch_id, batch_label: `批量同步 ${tabs.length} 个标签页` });
    } catch (e) { /* 未加载完的标签页跳过 */ }
  }
  if (!items.length) { alert("未能从标签页捕获到文章（可能均未加载完成）"); return; }
  chrome.runtime.sendMessage({ type: "sync_batch", items }, (res) => {
    alert(`已批量发送 ${res && res.count ? res.count : 0} 篇文章到本地客户端`);
  });
  refreshStatus();
});

$("dashBtn").addEventListener("click", () => {
  chrome.tabs.create({ url: "http://127.0.0.1:21888" });
});

chrome.storage.local.get({ autoSync: false }, (cfg) => {
  $("autoSync").checked = cfg.autoSync;
});
$("autoSync").addEventListener("change", (e) => {
  chrome.storage.local.set({ autoSync: e.target.checked });
});

refreshStatus();
showDebugTab();
setInterval(() => { refreshStatus(); showDebugTab(); }, 3000);
