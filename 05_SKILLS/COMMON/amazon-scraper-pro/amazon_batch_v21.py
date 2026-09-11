# -*- coding: utf-8 -*-
"""
amazon_batch_v21.py — Amazon 批量采集脚本（自建，Playwright + Chromium）
技能：amazon-scraper-pro

两种模式：
  1. BSR 榜单批量  --mode bsr        [--category <key>] [--pages N]
     类目 Best Sellers 榜单 -> 提取 ASIN -> 详情页 27 字段（field_mapping_v2.json v2.2）
  2. ASIN 详情      --mode asin      [--asins B0XXX,B0YYY | --input file.txt]
     直接按 ASIN/URL 列表抓详情页 27 字段（field_mapping_v2.json v2.2）
  3. BTG 节点采集  --mode btg-node   [--queue <bsr_queue.json>] [--node <id>] [--slug <slug>]
     从工作台 bsr_queue.json 读取节点（也可手动指定 node+slug），按节点抓 BSR 榜单+详情。
     适用于「类目选品树选定某节点 → 立即采集」。

通用参数：
  --limit N          小样本限制（默认 0 = 不限）
  --headful          有头模式（默认无头；调试/截图比对用）
  --screenshot       每个详情页保存截图到 out/screenshots/
  --delay 3-8        随机延迟区间（秒）
  --out <dir>        输出目录（默认 out/）
  --mapping <path>   字段映射文件（默认同目录 field_mapping_v2.json）

输出：
  Excel 表格（.xlsx，utf-8）+ 原始 JSON（.json），文件名带时间戳

反爬策略：
  - 随机 UA（Chrome/Edge/Firefox 轮换）
  - 随机延迟 + 指数退避冷却（连续失败）
  - 验证码/机器人检测 -> 停止并提示人工处理
  - 每 ASIN 最多重试 3 次

用法示例：
  python amazon_batch_v21.py --mode bsr --category kitchen --limit 3 --headful --screenshot
  python amazon_batch_v21.py --mode asin --asins B0FN5NY3TB,B0C1XXX --limit 2
"""
import argparse
import json
import os
import random
import re
import sys
import time
from datetime import datetime

from playwright.sync_api import sync_playwright

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MAPPING = os.path.join(SCRIPT_DIR, "field_mapping_v2.json")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
]

EMPTY = "—"


def load_mapping(path=DEFAULT_MAPPING):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_asin_from_url(url):
    m = re.search(r"/dp/([A-Z0-9]{10})", url)
    return m.group(1) if m else url


def clean_text(t):
    if not t:
        return EMPTY
    return re.sub(r"\s+", " ", t).strip()


def parse_float(t):
    if not t:
        return EMPTY
    m = re.search(r"(\d+(?:\.\d+)?)", t.replace(",", ""))
    return m.group(1) if m else EMPTY


def parse_int(t):
    if not t:
        return EMPTY
    m = re.search(r"(\d+)", t.replace(",", ""))
    return m.group(1) if m else EMPTY


def first_match(page, selectors, attr=None):
    """按顺序尝试选择器，返回第一个非空文本/属性；失败返回 None"""
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el:
                if attr:
                    val = el.get_attribute(attr)
                else:
                    val = el.inner_text()
                if val and val.strip():
                    return val.strip()
        except Exception:
            continue
    return None


def parse_bsr(page):
    """从页面全文提取 BSR 排名（大类 + 细分类目）。兼容折叠区。"""
    try:
        text = page.evaluate("""() => {
            const nodes = document.querySelectorAll('tr, li, .a-row, div');
            for (const el of nodes) {
                const t = (el.innerText || '').trim();
                if (t.includes('Best Sellers Rank') && t.length < 1200 && t.length > 20) return t;
            }
            return '';
        }""")
        if text:
            ranks = re.findall(r"#([\d,]+)\s+in\s+([^\n(]+)", text)
            if ranks:
                first, last = ranks[0], ranks[-1]
                return (parse_int(first[0]),
                        clean_text(first[1]),
                        parse_int(last[0]),
                        clean_text(last[1].split("(")[0]))
    except Exception:
        pass
    return EMPTY, EMPTY, EMPTY, EMPTY


def parse_bullet_table(page, label):
    """全文扫描 tr/li/div 中含 label 的节点，提取同节点内 label 后的值。
    兼容 detailBullets 表格、techSpec、A+ 描述区、右侧 about this item 等多种结构。"""
    try:
        val = page.evaluate("""(label) => {
            const nodes = document.querySelectorAll('tr, li, .a-row, .a-column, span, div');
            for (const el of nodes) {
                const t = (el.innerText || '').trim();
                if (!t || t.length > 250) continue;
                const idx = t.indexOf(label);
                if (idx < 0) continue;
                // 同节点内 label 后内容；多行取第一行
                const after = t.substring(idx + label.length);
                const firstLine = after.split(/\\n/)[0].trim().replace(/^[:：]\\s*/, '').trim();
                if (firstLine && firstLine.length < 100 && firstLine !== label) {
                    return firstLine;
                }
            }
            return '';
        }""", label)
        if val:
            return clean_text(val)
    except Exception:
        pass
    return EMPTY


def lock_us_zipcode(page, zipcode="90010"):
    """通过 Amazon glow 地址变更接口，把配送位置锁定为美区邮编。
    规避国内 IP 被切到港区出口视图（Export Sales LLC）导致价格/卖家失真。
    前置：需先访问 amazon.com 建立 session（有 csrf cookie）。
    返回 True=成功。"""
    try:
        page.goto("https://www.amazon.com/", wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2500)
        ok = page.evaluate("""(zipcode) => {
            const csrf = (document.cookie.match(/csrf=([^;]+)/)||[])[1] || '';
            const form = new URLSearchParams();
            form.set('locationType','LOCATION_INPUT');
            form.set('zipCode', zipcode);
            form.set('storeContext','generic');
            form.set('deviceType','web');
            form.set('pageType','Gateway');
            form.set('actionSource','glow');
            try {
                const r = fetch('/portal-migration/hz/glow/address-change', {
                    method:'POST',
                    headers:{'anti-csrftoken-a2z':csrf,'x-requested-with':'XMLHttpRequest',
                             'content-type':'application/x-www-form-urlencoded;charset=UTF-8'},
                    body: form.toString()
                });
                return r.then(async (resp) => resp.status + '|' + (await resp.text()).slice(0,120));
            } catch(e) { return 'ERR|' + e.message; }
        }""", zipcode)
        page.wait_for_timeout(1500)
        return isinstance(ok, str) and "isAddressUpdated" in ok
    except Exception:
        return False


def is_haul_page(page):
    """Amazon Haul 低价商城页识别：URL 带 s=bazaar 参数（haul/出口精简页统一标识）。
    不可用页面文本判据——常规详情页导航/推广也含 Amazon Haul 字样，会误伤全部页面。"""
    try:
        u = (page.url or "").lower()
        return "s=bazaar" in u or "/haul" in u
    except Exception:
        return False


def classify_seller(name):
    """卖家分类：自营 / 港区出口（Export Sales，非美区真实卖家）/ 第三方"""
    if re.search(r"Amazon Export Sales|Export Sales", name, re.I):
        return "Amazon Export Sales LLC(港区出口·非美区真实卖家)"
    if name.strip() in ("Amazon", "Amazon.com"):
        return "Amazon.com(自营)"
    return f"{name}(第三方)"


def parse_seller(page):
    """销售方 + 发货方；识别港区出口主体防误判自营。大小写兼容跨行匹配。"""
    seller, shipped = EMPTY, EMPTY
    try:
        text = page.evaluate("""() => {
            // 优先 buybox 卖家区；排除 Amazon Resale（翻新/二手卡，非主卖家）
            const el = document.querySelector('#merchant-info') || document.querySelector('#merchantInfo');
            if (el) {
                const t = (el.innerText || '').trim();
                if (t && t.length < 300 && !t.includes('Resale')) return t;
            }
            // 兜底：优先最短含 Ships from 节点，其次 Sold by（排除 Resale 卡等噪音）
            let best = '';
            const pick = (kw) => {
                for (const n of document.querySelectorAll('div, span')) {
                    const t = (n.innerText || '').trim();
                    // 长度 20-200：过滤 'Ships from:' 这类残缺节点与超大容器
                    if (t.includes(kw) && t.length >= 20 && t.length < 200 && !t.includes('Amazon Resale')
                            && (best === '' || t.length < best.length)) best = t;
                }
            };
            pick('Ships from');
            if (!best) pick('Sold by');
            return best;
        }""")
        if text:
            m_sold = re.search(r"[Ss]old by\s*:?\s+([^\n]+?)(?:\s*\.|\s*Returns|\n|$)", text)
            m_ship = re.search(r"[Ss]hips from\s*:?\s+([^\n]+?)(?:\s*\.|\s*Sold|\n|$)", text)
            if m_sold:
                seller = classify_seller(clean_text(m_sold.group(1)))
            if m_ship:
                shipped = clean_text(m_ship.group(1))
    except Exception:
        pass
    if seller == EMPTY:
        prof = first_match(page, ["#sellerProfileTriggerId"])
        if prof:
            seller = classify_seller(clean_text(prof))
    return seller, shipped


def scrape_product(page, asin, mapping, with_screenshot=False, out_dir="out"):
    """抓单个产品详情页，返回字段 dict（27 字段，field_mapping_v2.json v2.2）"""
    url = f"https://www.amazon.com/dp/{asin}?language=en_US&currency=USD"
    fields = {f["key"]: EMPTY for f in mapping["fields"]}
    fields["asin"] = asin
    fields["url"] = url
    fields["scraped_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2500 + random.randint(0, 2000))
    except Exception as e:
        fields["title"] = f"导航失败: {e}"
        return fields

    # bazaar 精简页跳出：bazaar = 出口版商品页变体（无 BSR 区块/无美区卖家），重试拿正常版
    bazaar_retry = 0
    while "bazaar" in page.url and bazaar_retry < 3:
        bazaar_retry += 1
        try:
            clean = url.split("?")[0] + "?language=en_US&currency=USD&disable-bazaar=true"
            page.goto(clean, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(2500 + random.randint(0, 1500))
        except Exception:
            break

    # 关掉"ship to X" 横幅（Amazon 对非美 IP 强推，遮挡页面）
    for sel in ["#glow-ingress-block-search-form input[data-action-type='DISMISS']",
                "button[aria-label='Dismiss']", "span[data-action='DISMISS']",
                "input[type='submit'][value='Dismiss']"]:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                page.wait_for_timeout(500)
                break
        except Exception:
            continue

    # 展开折叠区（Product Details / Description / About this item），让 BSR/规格可见
    for sel in ["#productDetails_expanderTables_depthLeft", "a[data-action='expand-product-details']",
                "button[aria-label*='see more']", "#feature-bullets button.a-expander-prompt",
                "div#productDescription p a"]:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                page.wait_for_timeout(400)
        except Exception:
            continue

    # 验证码/机器人检测
    html = page.content()
    if "Enter the characters you see below" in html or "Robot Check" in html or "api-services-support@amazon.com" in html:
        fields["title"] = "CAPTCHA-被验证码拦截，需人工处理"
        return fields

    fmap = {f["key"]: f for f in mapping["fields"]}

    # 标题 / 品牌
    t = first_match(page, fmap["title"]["selectors"])
    if t:
        fields["title"] = clean_text(t)
    # 品牌: 优先 bylineInfo（"Visit the X Store"），其次用全文扫描 Brand 标签
    brand_el = first_match(page, ["#bylineInfo", "#brand", "a#bylineInfo", "span#bylineInfo",
                                  "a[href*='/stores/']", "div#titleBlockRightBylineFeature span"])
    if brand_el:
        b = re.sub(r"^Visit the\s+", "", brand_el)
        b = re.sub(r"\s+Store\s*$", "", b)
        if ":" in b:
            b = b.split(":", 1)[1].strip()
        if b and b.strip():
            fields["brand"] = clean_text(b)
    # 兜底：从右侧 "Brand: XXX" 区域抓
    if fields.get("brand", EMPTY) == EMPTY:
        fields["brand"] = parse_bullet_table(page, "Brand")

    # 价格 / 划线价
    price = first_match(page, fmap["price"]["selectors"])
    fields["price"] = price if price else EMPTY
    lp = first_match(page, fmap["list_price"]["selectors"])
    # 清理单位价注释（如 "$0.12 / count"）和 < price 的异常值
    if lp and price:
        # 含 / count、per unit、per count 等就是单位价，不是划线价
        if re.search(r"/\s*count\b|per\s+unit|per\s+count", lp, re.I):
            lp = ""
        else:
            try:
                lp_num = float(re.search(r"[\d.]+", lp).group())
                price_num = float(re.search(r"[\d.]+", price).group())
                if lp_num < price_num:
                    lp = ""
            except Exception:
                pass
    fields["list_price"] = lp if lp else EMPTY

    # 评分 / 评论数
    rating = first_match(page, fmap["rating"]["selectors"], attr="title")
    if not rating:
        rating = first_match(page, fmap["rating"]["selectors"])
    fields["rating"] = parse_float(rating) if rating else EMPTY
    rc = first_match(page, fmap["review_count"]["selectors"])
    fields["review_count"] = parse_int(rc) if rc else EMPTY

    # Haul 低价商城标记（优先判定，影响销量列语义）
    fields["haul"] = EMPTY
    is_haul = is_haul_page(page)
    if is_haul:
        fields["haul"] = "Amazon Haul"
        # —— Haul 页结构补丁：价格/划线价/评分/评论数容器与常规页不同 ——
        hpd = first_match(page, ["#corePriceDisplay_desktop_feature_div"])
        if hpd:
            hpd = clean_text(hpd)
            # 主售价：优先取紧凑两位小数价（$0.98），防拆分节点 "$0 . 98" 误抓
            m = re.search(r"\$(\d+\.\d{2})", hpd) or re.search(r"\$(\d+(?:\.\d+)?)", hpd)
            if m:
                fields["price"] = f"${m.group(1)}"
            # Haul Typical Price 即划线对比价（唯一划线价来源）
            # 注意：haul 补丁覆盖 price 后常规解析的脏 list_price（如 per-count 单价）可能残留，
            #       故无 Typical 文本时必须显式置空，不能沿用常规解析值
            m2 = re.search(r"Haul Typical Price:\s*\$(\d+(?:\.\d+)?)", hpd, re.I)
            if m2:
                fields["list_price"] = f"${m2.group(1)}"
            else:
                fields["list_price"] = EMPTY
        # 评分/评论数：haul 专属容器（文本形如 "3.6 (184)" 或 "3.6 184"）
        for sel in ("#haulAverageCustomerReviewDesktop_feature_div",
                    "#haulCustomerReviews_feature_div"):
            hr = first_match(page, [sel])
            if not hr:
                continue
            hr = clean_text(hr)
            m = (re.search(r"(\d(?:\.\d+)?)\s*\((\d+)\)", hr)
                 or re.search(r"(\d(?:\.\d+)?)\s+(\d+)", hr))
            if m and 0 < float(m.group(2)) < 1000000:
                fields["rating"] = parse_float(m.group(1))
                fields["review_count"] = int(float(m.group(2)))
                break

    # 前台月销量标识（仅常规详情页渲染，榜单页无）：
    #   热品组件 tk_bought -> K值/纯数字；新品组件 new_on_amazon -> New on Amazon；
    #   常规页面两组件皆无 -> <50（月销不足 50 前台不显示）；Haul 页 -> —
    fields["monthly_sales"] = EMPTY
    if not is_haul:
        ms = first_match(page, fmap["monthly_sales"]["selectors"])
        if ms:
            mtxt = clean_text(ms)
            m = re.search(r"([\d.,]+\s*K?)\+?\s*bought in past month", mtxt)
            if m:
                fields["monthly_sales"] = re.sub(r"\s+", "", m.group(1)) + ("+" if "+" in m.group(0) else "")
            elif re.search(r"New on Amazon", mtxt):
                fields["monthly_sales"] = "New on Amazon"
        else:
            fields["monthly_sales"] = "<50"

    # 首次上架日（Date First Available）：Product information > Additional Information 表内行
    #   定位 th.prodDetSectionEntry 文本匹配 → 同行 td.prodDetAttrValue。
    #   注意：部分老 listing/模板与 Haul 页不渲染该行 -> 记 —
    fields["first_available"] = EMPTY
    if not is_haul:
        try:
            dfa = page.evaluate("""() => {
                const ths = document.querySelectorAll('th.prodDetSectionEntry');
                for (const th of ths) {
                    if ((th.innerText || '').trim() === 'Date First Available') {
                        const tr = th.closest('tr');
                        const td = tr && tr.querySelector('td.prodDetAttrValue');
                        return td ? td.innerText.trim() : null;
                    }
                }
                return null;
            }""")
            if dfa:
                fields["first_available"] = dfa
        except Exception:
            pass

    # BSR（大类 + 细分类目）
    bsr_main, bsr_main_cat, bsr_sub, bsr_sub_cat = parse_bsr(page)
    fields["bsr_main"] = bsr_main
    fields["bsr_main_category"] = bsr_main_cat
    fields["bsr_sub"] = bsr_sub
    fields["bsr_sub_category"] = bsr_sub_cat

    # 徽章
    if first_match(page, fmap["bestseller_badge"]["selectors"]):
        fields["bestseller_badge"] = "Best Seller"
    if first_match(page, fmap["amazon_choice"]["selectors"]):
        fields["amazon_choice"] = "Amazon's Choice"

    # 五点卖点
    bullets = []
    try:
        for li in page.query_selector_all("#feature-bullets ul li span.a-list-item"):
            btxt = clean_text(li.inner_text())
            if btxt and btxt != EMPTY:
                bullets.append(btxt)
    except Exception:
        pass
    fields["bullets"] = bullets

    # 尺寸 / 重量
    fields["dimensions"] = parse_bullet_table(page, "Product Dimensions")
    fields["weight"] = parse_bullet_table(page, "Item Weight")

    # 颜色
    color = first_match(page, fmap["color"]["selectors"])
    if color:
        fields["color"] = clean_text(color) if color else EMPTY
    # 兜底：从右侧 "Color: XXX" 区域抓
    if fields.get("color", EMPTY) == EMPTY:
        fields["color"] = parse_bullet_table(page, "Color")

    # 可售状态
    avail = first_match(page, fmap["availability"]["selectors"])
    if avail:
        fields["availability"] = clean_text(avail) if "In Stock" in avail else "缺货/不可售"

    # 卖家 / 发货
    seller, shipped = parse_seller(page)
    fields["seller"] = seller
    fields["shipped_by"] = shipped

    # 港区检测：Export Sales LLC 出现 = 非美区出口视图，价格/卖家均非美区真实值
    try:
        is_export = page.evaluate(
            "() => document.body.innerText.includes('Amazon Export Sales') || document.body.innerText.includes('Export Sales')"
        )
        if "bazaar" in page.url:
            fields["geo_note"] = "⚠️bazaar出口精简页·无BSR/卖家区，多次重试未跳出"
        else:
            fields["geo_note"] = "⚠️港区出口视图·价格/卖家非美区真实值，需美区代理" if is_export else "美区视图"
    except Exception:
        fields["geo_note"] = EMPTY

    # 优惠券
    coupon = first_match(page, fmap["coupon"]["selectors"])
    fields["coupon"] = clean_text(coupon) if coupon else "无"

    # 主图
    img = first_match(page, fmap["image_url"]["selectors"], attr="src")
    fields["image_url"] = img if img else EMPTY

    # 截图
    if with_screenshot:
        shot_dir = os.path.join(out_dir, "screenshots")
        os.makedirs(shot_dir, exist_ok=True)
        page.screenshot(path=os.path.join(shot_dir, f"{asin}.png"), full_page=False)

    return fields


def scrape_bestseller_list(page, node_id, url_template=None, pages=1, limit=0):
    """抓类目 Best Sellers 榜单，返回 ASIN 列表
    node_id 仅作标识；url_template 决定实际访问路径（store 前缀如 /hi/ 必需，
    例如 Electrical Cable Staples 需 /gp/bestsellers/hi/{node}，无前缀会抓到空页）"""
    asins = []
    base = url_template or f"https://www.amazon.com/gp/bestsellers/{node_id}"
    for p in range(1, pages + 1):
        url = f"{base}/ref=zg_bs_pg_{p}?pg={p}" if p > 1 else base
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(2000 + random.randint(0, 1500))
            # 自适应滚动触发懒加载：滚到商品链接数不再增长为止（兜底 60 轮 ≈ 45s）
            # 2026-09-08 坑：固定滚 10×600px 对 Best Sellers(服务端直出)够用，
            # 但 New Releases 懒加载重，只触发 ~32/50，导致 2 页只提取到 62 而非 100。
            # 现改为每轮滚 700px 后统计 /dp/ 链接数，连续 4 轮无增长即认为到底。
            last_cnt = -1
            stable = 0
            for _ in range(60):
                page.evaluate("window.scrollBy(0, 700)")
                page.wait_for_timeout(500 + random.randint(0, 250))
                cnt = len(page.query_selector_all("a[href*='/dp/']"))
                if cnt == last_cnt:
                    stable += 1
                    if stable >= 4:
                        break
                else:
                    stable = 0
                    last_cnt = cnt
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(800 + random.randint(0, 500))
        except Exception as e:
            print(f"[!] 榜单页访问异常(第{p}页): {type(e).__name__}: {str(e)[:100]}")
            continue
        html = page.content()
        if "Enter the characters you see below" in html:
            print("[!] 榜单页被验证码拦截，停止翻页")
            break
        # 榜单项链接 _p13n-zg-list-tree a[href*='/dp/'] 或 div[data-asin]
        links = page.query_selector_all("a[href*='/dp/']")
        seen = set()
        for a in links:
            href = a.get_attribute("href") or ""
            m = re.search(r"/dp/([A-Z0-9]{10})", href)
            if m and m.group(1) not in seen:
                seen.add(m.group(1))
                asins.append(m.group(1))
        if limit and len(asins) >= limit:
            break
        time.sleep(1 + random.random() * 2)
    # 去重保序
    return list(dict.fromkeys(asins))[:limit] if limit else list(dict.fromkeys(asins))


def load_asin_input(path):
    asins = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            m = re.search(r"([A-Z0-9]{10})", line)
            if m:
                asins.append(m.group(1))
    return asins


def cell_value(v):
    if isinstance(v, list):
        return "\n".join(str(x) for x in v)
    return v


def write_excel(rows, path):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Amazon数据"
    keys = list(rows[0].keys()) if rows else []
    header_fill = PatternFill("solid", fgColor="2F5597")
    header_font = Font(color="FFFFFF", bold=True)
    ws.append(keys)
    for c in range(1, len(keys) + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill = header_fill
        cell.font = header_font
    for r in rows:
        ws.append([cell_value(r.get(k, EMPTY)) for k in keys])
    # 列宽自适应（卖点合并为换行文本）
    for c in range(1, len(keys) + 1):
        col_vals = [cell_value(r.get(keys[c - 1], "")) for r in rows[:50]]
        maxlen = max(len(str(keys[c - 1])), *(len(str(v)) if v else 0 for v in col_vals))
        ws.column_dimensions[get_column_letter(c)].width = min(max(maxlen * 1.2, 8), 60)
    wb.save(path)


def main():
    # Windows 控制台/重定向 stdout 默认 gbk，print "✓/·/→" 等字符会 UnicodeEncodeError
    # 崩在收尾打印导致 run 误报 failed（2026-09-07 22:49 坑：100 条数据已落盘仍 exit=1）
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="Amazon 批量采集 v21")
    ap.add_argument("--mode", choices=["bsr", "asin", "btg-node"], required=True, help="bsr=类目榜单批量, asin=ASIN详情, btg-node=从工作台队列读节点采集")
    ap.add_argument("--category", default="kitchen", help="类目 key（field_mapping_v2.json categories 中定义），仅 bsr 模式")
    ap.add_argument("--pages", type=int, default=1, help="榜单翻页数")
    ap.add_argument("--asins", default="", help="逗号分隔 ASIN 列表")
    ap.add_argument("--input", default="", help="ASIN 列表文件（每行一个）")
    # btg-node 模式专用（亚马逊运营工作台「立即采集」按钮）
    ap.add_argument("--queue", default="", help="btg_node 模式：bsr_queue.json 路径（工作台产出）")
    ap.add_argument("--node", default="", help="btg-node 模式：单节点直接指定（与 --queue 二选一或多选）")
    ap.add_argument("--slug", default="", help="btg-node 模式：单节点的类目 slug（与 --node 配套，如 hi / home-improvement）")
    ap.add_argument("--chart", choices=["bsr", "new"], default="bsr",
                    help="榜单类型: bsr=热销榜(Best Sellers, /gp/bestsellers/), new=新品榜(New Releases, /gp/new-releases/)。队列项带 chart 时优先用队列值")
    ap.add_argument("--limit", type=int, default=0, help="小样本限制条数")
    ap.add_argument("--headful", action="store_true", help="有头模式")
    ap.add_argument("--screenshot", action="store_true", help="保存详情页截图")
    ap.add_argument("--delay", default="3-8", help="随机延迟区间(秒)，默认 3-8")
    ap.add_argument("--out", default="out", help="输出目录")
    ap.add_argument("--progress-file", default="", help="进度上报文件：每抓完一条 append 一行 JSON {done,total,cur,ok}（工作台实时进度用，不传则跳过）")
    ap.add_argument("--zipcode", default="90010", help="美区邮编锁定（glow 接口），默认 90010 Los Angeles")
    ap.add_argument("--mapping", default=DEFAULT_MAPPING, help="字段映射文件")
    args = ap.parse_args()

    mapping = load_mapping(args.mapping)
    out_dir = args.out
    os.makedirs(out_dir, exist_ok=True)

    # 延迟区间解析
    try:
        d1, d2 = (float(x) for x in args.delay.split("-"))
    except Exception:
        d1, d2 = 3.0, 8.0

    # btg-node 模式：从工作台 bsr_queue.json（或 --node/--slug）取节点，格式与 scrape_bestseller_list 兼容
    btg_targets = []  # [(node_id, slug, sub_path, chart), ...]
    if args.mode == "btg-node":
        if args.queue and os.path.exists(args.queue):
            try:
                qj = json.loads(open(args.queue, encoding="utf-8").read())
                items = (qj.get("items") or []) if isinstance(qj, dict) else []
                for it in items:
                    if it.get("status") in ("done", "skipped"):
                        continue
                    node = str(it.get("node") or "").strip()
                    slug = (it.get("slug") or "").strip()
                    chart = (it.get("chart") or args.chart or "bsr").strip()
                    if chart not in ("bsr", "new"):
                        chart = "bsr"
                    if node:
                        btg_targets.append((node, slug, it.get("path") or it.get("sub") or "", chart))
            except Exception as e:
                print(f"[!] 队列读取失败: {e}")
        if args.node:
            btg_targets.append((args.node.strip(), (args.slug or "").strip(), "", args.chart))
        # 去重保序
        seen = set()
        dedup = []
        for t in btg_targets:
            if t[0] in seen:
                continue
            seen.add(t[0])
            dedup.append(t)
        btg_targets = dedup
        if not btg_targets:
            print("[!] btg-node 模式需 --queue 或 --node，可执行: --queue xxx/bsr_queue.json 或 --node 6396128011 --slug hi")
            sys.exit(1)
        print(f"[*] BTG 节点模式：{len(btg_targets)} 个节点")

    asins = []
    if args.mode == "bsr":
        cats = mapping.get("categories", {})
        cat = cats.get(args.category)
        if not cat:
            print(f"[!] 未知类目 key: {args.category}，可用: {list(cats.keys())}")
            sys.exit(1)
        print(f"[*] BSR 榜单模式：{cat['name']} (node {cat['node_id']})")
    elif args.mode == "btg-node":
        pass  # 已在上面解析为 btg_targets
    else:
        if args.asins:
            asins = [a.strip() for a in args.asins.split(",") if a.strip()]
        elif args.input:
            asins = load_asin_input(args.input)
        else:
            print("[!] asin 模式需 --asins 或 --input")
            sys.exit(1)
        if args.limit:
            asins = asins[:args.limit]
        print(f"[*] ASIN 详情模式：{len(asins)} 个")

    rows = []
    fail_count = 0
    # 手动管理 playwright 生命周期（勿用 with 只包前段：with 退出即销毁 page，
    # 采集主体在其外会报 Event loop is closed —— 2026-09-07 22:22 坑）
    p = sync_playwright().start()
    try:
        browser = p.chromium.launch(headless=not args.headful)
    except Exception as e:
        print(f"[!] 浏览器启动失败: {type(e).__name__}: {str(e)[:150]}")
        sys.exit(1)
    ctx = browser.new_context(
        user_agent=random.choice(USER_AGENTS),
        locale="en-US",
        viewport={"width": 1366, "height": 900},
    )
    # 强制美区：语言 en_US + 币种 USD（Amazon 对国内 IP 默认切港区/显示 HKD）
    ctx.add_cookies([
        {"name": "lc-main", "value": "en_US", "domain": ".amazon.com", "path": "/"},
        {"name": "i18n-prefs", "value": "USD", "domain": ".amazon.com", "path": "/"},
    ])
    page = ctx.new_page()
    # 邮编锁定（glow 接口切美区视图，规避 Export Sales 港区出口价/卖家失真）
    if lock_us_zipcode(page, args.zipcode):
        print(f"[*] 已锁定美区邮编 {args.zipcode}（Los Angeles）")
    else:
        print("[!] 邮编锁定失败，继续（价格/卖家可能为港区出口视图）")

    # 多节点分批产出：每个节点一份 _FINAL.json + .xlsx（每节点独立文件组）
    # 单节点（bsr/asin）保持向后兼容
    node_batches = []  # [(label, asin_list, sub_key, chart), ...]
    if args.mode == "btg-node":
        for (node, slug, sub, chart) in btg_targets:
            # slug 兜底：BTG 索引用 home-improvement，BSR 榜单实际 hi 也可 200，故两种都尝试
            chart_path = "new-releases" if chart == "new" else "bestsellers"
            base = (f"https://www.amazon.com/gp/{chart_path}/{slug}/{node}"
                    if slug else f"https://www.amazon.com/gp/{chart_path}/{node}")
            sub_list = scrape_bestseller_list(page, node, url_template=base, pages=args.pages, limit=args.limit)
            label = f"{slug or 'node'}_{node}".strip("_")
            # sub 是 path 如 "Tools & Home Improvement/Electrical/.../Cable Staples"
            tail = (sub or "").split("/")[-1] if sub else ""
            sub_key = re.sub(r"[^A-Za-z0-9]+", "_", tail).strip("_").lower() or node
            if sub:
                label = f"{slug or 'node'}_{sub.replace('/', '_').replace(' ', '_')}"
            node_batches.append((label, sub_list, sub_key, chart))
            if not sub_list:
                print(f"[!] 节点 {node} 榜单未提取到 ASIN（可能 CAPTCHA）")
    elif args.mode == "bsr":
        node_batches.append((args.category, asins, args.category, "bsr"))
    else:  # asin
        node_batches.append(("asin_batch", asins, "asin_batch", "bsr"))

    if not any(b[1] for b in node_batches):
        print("[!] 全部节点榜单均未提取到 ASIN，结束（exit=1）")
        # 手动生命周期：此处退出前需显式清理（无 with 自动关，且不再有二次关闭崩溃）
        try:
            browser.close()
            p.stop()
        except Exception:
            pass
        sys.exit(1)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    date = datetime.now().strftime("%Y%m%d")
    for batch_label, batch_asins, sub_key, chart in node_batches:
        if not batch_asins:
            continue
        print(f"\n=== 批次 {batch_label}：{len(batch_asins)} 个 ASIN ===")
        rows = []
        fail_count = 0
        for i, asin in enumerate(batch_asins, 1):
            print(f"  [{i}/{len(batch_asins)}] {asin} ...", end=" ", flush=True)
            for attempt in range(1, 4):
                try:
                    row = scrape_product(page, asin, mapping, with_screenshot=args.screenshot, out_dir=out_dir)
                    break
                except Exception as e:
                    row = {"asin": asin, "title": f"抓取异常: {e}"}
                    if attempt < 3:
                        wait = (2 ** attempt) + random.random() * 2
                        print(f"失败(第{attempt}次)，冷却 {wait:.0f}s", end=" ")
                        time.sleep(wait)
            if row.get("title", "").startswith(("CAPTCHA", "导航失败", "抓取异常")):
                fail_count += 1
            rows.append(row)
            # 实时进度上报：每抓完一条 append 一行 JSON（工作台轮询读尾行渲染，不影响主流程）
            if args.progress_file:
                try:
                    with open(args.progress_file, "a", encoding="utf-8") as pf:
                        pf.write(json.dumps({
                            "done": i, "total": len(batch_asins), "cur": asin,
                            "ok": 0 if row.get("title", "").startswith(("CAPTCHA", "导航失败", "抓取异常")) else 1,
                            "ts": datetime.now().strftime("%H:%M:%S"),
                        }, ensure_ascii=False) + "\n")
                except Exception:
                    pass
            cool = d1 + random.random() * (d2 - d1)
            print(f"冷却 {cool:.1f}s")
            time.sleep(cool)

        # 输出：btg-node 每节点文件组直接落 out_dir（07_OUTPUTS/bsr_<子类>_<数量>/ 或 new_<子类>_<数量>/），文件名带日期
        if args.mode == "btg-node":
            os.makedirs(out_dir, exist_ok=True)
            pref = "new" if chart == "new" else "bsr"
            xlsx_path = os.path.join(out_dir, f"amazon_{pref}_{sub_key}_{date}_FINAL.xlsx")
            json_path = os.path.join(out_dir, f"amazon_{pref}_{sub_key}_{date}_FINAL.json")
        else:
            os.makedirs(out_dir, exist_ok=True)
            xlsx_path = os.path.join(out_dir, f"amazon_{args.mode}_{ts}.xlsx")
            json_path = os.path.join(out_dir, f"amazon_{args.mode}_{ts}.json")

        write_excel(rows, xlsx_path)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
        print(f"[✓] {batch_label}：{len(rows)} 条 | 异常 {fail_count} 条")
        print(f"    Excel: {xlsx_path}")
        print(f"    JSON : {json_path}")
        if fail_count:
            for r in rows:
                if r.get("title", "").startswith(("CAPTCHA", "导航失败", "抓取异常")):
                    print(f"      {r['asin']} -> {r['title'][:60]}")

    browser.close()
    p.stop()


if __name__ == "__main__":
    main()
