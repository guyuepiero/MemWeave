# -*- coding: utf-8 -*-
"""
14 大类错译嫌疑探测器（机器预筛 → 人工精修，策略 A）
读 15 份 CSV 中除工具类外的 14 份，段级提取 (en -> zh 集合)。
仅输出高嫌疑条目：① en 命中「领域硬伤对照表」且 CSV 现译 ≠ 标准译名；
② zh 命中中文错译黑名单串。已存在于 build_zh.FIX 的 en 自动跳过（跑 build_zh 会全局自动修正）。
用法: python scan_zh_suspect.py            # 输出到 Temp/suspect.txt
"""
import csv, glob, os, sys
from collections import defaultdict

CSV_DIR = r"C:/Users/guyuepiero/Documents/MemWeave v1.0/07_OUTPUTS/Amazon类目选品管理中心"
TOOLS = "工具和家居装修"
OUT = os.path.join(os.environ.get("TEMP", "."), "suspect_14.txt")

def clean(s):
    return (s or "").strip().strip('"').strip()

def segs_of(csv_path):
    """返回 {en: {zh: n}} 段级映射（仅 en/zh 段数对齐的行）"""
    m = defaultdict(lambda: defaultdict(int))
    with open(csv_path, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    for r in rows[1:]:
        if len(r) < 5: continue
        ep = clean(r[3]); zp = clean(r[4]).replace(" / ", "/")
        if not (ep and zp): continue
        e = [clean(x) for x in ep.split("/")]
        z = [clean(x) for x in zp.split("/")]
        if len(e) != len(z): continue
        for a, b in zip(e, z):
            if a and b: m[a][b] += 1
    return m

# ---------- 领域硬伤对照表：en 多义词/音译坑 -> 正确品类译名（任意类目语境下机翻错义都算错）----------
SUSPECT = {
 # 工具/通用五金（与 FIX 互补：这里只收 FIX 未收录的词）
 "Punches": "冲子", "Dies": "模具", "Grommets": "金属孔眼", "Bushings": "衬套",
 "Caps": "盖帽", "Caps & Plugs": "盖帽和堵头", "Plugs": "堵头",
 # 家居/卫浴
 "Toilets": "马桶", "Bidets": "妇洗器", "Urinals": "小便池", "Vanities": "浴室柜",
 "Faucets": "水龙头", "Showerheads": "花洒", "Tubs": "浴缸", "Sinks": "水槽",
 # 建筑/混凝土
 "Concrete": "混凝土", "Mortar": "砂浆", "Grout": "填缝剂", "Rebar": "钢筋",
 "Flashing": "泛水板", "Caulk": "密封胶", "Insulation": "保温材料",
 "Drywall": "石膏板", "Plywood": "胶合板", "Lumber": "木材", "Studs": "立柱",
 # 电气
 "Transformers": "变压器", "Fuses": "保险丝", "Breakers": "断路器",
 "Solenoids": "电磁阀", "Relays": "继电器", "Capacitors": "电容器",
 "Resistors": "电阻器", "Diodes": "二极管", "Transistors": "晶体管",
 "Rectifiers": "整流器", "Inverters": "逆变器", "Converters": "转换器",
 "Actuators": "执行器", "Servos": "舵机", "Encoders": "编码器",
 "Potentiometers": "电位器", "Thermistors": "热敏电阻", "Varistors": "压敏电阻",
 # 机械
 "Gears": "齿轮", "Sprockets": "链轮", "Pulleys": "皮带轮", "Belts": "皮带",
 "Couplings": "联轴器", "Bearings": "轴承", "Bushings2": "轴套", "Shafts": "轴",
 "Spindles": "主轴", "Lathes": "车床", "Mills": "铣床", "Presses": "压力机",
 "Guillotines": "裁切机", "Shears": "剪板机", "Benders": "弯管机",
 # 照明
 "Bulbs": "灯泡", "Fixtures": "灯具", "Ballasts": "镇流器", "Lenses": "镜片",
 # 五金紧固件
 "Nails": "钉子", "Staples": "卡钉", "Tacks": "图钉", "Pins": "销",
 "Rivets": "铆钉", "Washers": "垫圈", "Bolts": "螺栓", "Nuts": "螺母",
 "Screws": "螺丝", "Anchors": "锚栓", "Hooks": "挂钩", "Latches": "门闩",
 "Hinges": "铰链", "Casters": "脚轮", "Handles": "把手", "Knobs": "旋钮",
 # 测量
 "Rulers": "直尺", "Calipers": "卡尺", "Gauges": "仪表", "Meters": "仪表",
 "Scales": "秤", "Protractors": "量角器", "Compasses": "圆规",
 # 服装/面料
 "Shirts": "衬衫", "Trousers": "长裤", "Socks": "袜子", "Shoes": "鞋",
 "Boots": "靴子", "Sandals": "凉鞋", "Sneakers": "运动鞋", "Hats": "帽子",
 "Caps": "帽子", "Gloves": "手套", "Scarves": "围巾", "Belts": "腰带",
 "Sweaters": "毛衣", "Jackets": "夹克", "Coats": "外套", "Dresses": "连衣裙",
 "Skirts": "半身裙", "Shorts": "短裤", "Underwear": "内衣", "Socks": "袜子",
 # 宠物
 "Leashes": "牵引绳", "Collars": "项圈", "Harnesses": "胸背带", "Cages": "笼子",
 "Tanks": "缸", "Wheels": "跑轮", "Litter": "猫砂", "Chews": "磨牙零食",
 # 办公
 "Staplers": "订书机", "Binder": "文件夹", "Folders": "文件夹", "Clipboards": "书写板",
 "Notebooks": "笔记本", "Pens": "钢笔", "Pencils": "铅笔", "Markers": "马克笔",
 "Highlighters": "荧光笔", "Erasers": "橡皮", "Rulers2": "直尺", "Scissors2": "剪刀",
 # 乐器
 "Guitars": "吉他", "Pianos": "钢琴", "Keyboards": "键盘", "Drums": "鼓",
 "Violins": "小提琴", "Amplifiers": "功放", "Microphones": "麦克风", "Speakers": "音箱",
 # 汽车/户外
 "Wheels": "轮毂", "Tires": "轮胎", "Brakes": "刹车", "Bumpers": "保险杠",
 "Fenders": "挡泥板", "Hoods": "引擎盖", "Trunks": "后备箱", "Mirrors": "后视镜",
 "Windshields": "挡风玻璃", "Headlights": "前大灯", "Taillights": "尾灯",
 "Mufflers": "消音器", "Radiators": "散热器", "Alternators": "发电机",
 "Starters": "起动机", "Carburetors": "化油器", "Camshafts": "凸轮轴",
 "Pistons": "活塞", "Spark Plugs": "火花塞", "Shocks": "减震器", "Struts": "减震支柱",
 # 电子
 "Speakers": "扬声器", "Headphones": "耳机", "Earbuds": "耳塞", "Cameras": "相机",
 "Lenses": "镜头", "Screens": "屏幕", "Displays": "显示屏", "Keyboards": "键盘",
 "Mice": "鼠标", "Chargers": "充电器", "Adapters": "适配器", "Cables": "数据线",
 "Connectors": "连接器", "Ports": "接口", "Drives": "驱动器", "Storage": "存储",
 # 母婴
 "Pacifiers": "安抚奶嘴", "Bottles": "奶瓶", "Nipples": "奶嘴", "Diapers": "尿布",
 "Strollers": "婴儿车", "Car Seats": "儿童安全座椅", "Cribs": "婴儿床", "High Chairs": "餐椅",
 # 美妆
 "Mascara": "睫毛膏", "Lipstick": "口红", "Foundation": "粉底", "Concealer": "遮瑕膏",
 "Serums": "精华", "Moisturizers": "保湿霜", "Sunscreen": "防晒霜", "Shampoo": "洗发水",
 "Conditioner": "护发素", "Lotions": "乳液", "Toners": "爽肤水",
}

# 中文错译黑名单串兜底（任意语境都属硬伤）
BAD_ZH = ["粉丝", "指甲", "统治者", "拳打", "拳击", "变形金刚", "桑德斯", "盖茨",
          "厕所", "迫击炮", "扳道工", "马车螺栓", "溜冰场", "丈夫", "丈夫们", "根管",
          "护墙板", "护壁板", "指甲油", "钉子户", "小费", "提示", "给料机", "送料机",
          "栅栏式", "拳", "拳王"]

def load_fix_keys():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import importlib.util
    spec = importlib.util.spec_from_file_location("build_zh", os.path.join(os.path.dirname(os.path.abspath(__file__)), "build_zh.py"))
    bz = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bz)
    return bz.FIX

def main():
    fix = load_fix_keys()
    all_en = set()
    hits = []
    for f in sorted(glob.glob(os.path.join(CSV_DIR, "*_叶子类目选品管理.csv"))):
        base = os.path.basename(f)[: -len("_叶子类目选品管理.csv")]
        if base == TOOLS: continue
        m = segs_of(f)
        for en, zmap in m.items():
            all_en.add(en)
            if en in fix: continue  # build_zh 会自动修
            zs = sorted(zmap.keys())
            hit = None
            if en in SUSPECT and any(z != SUSPECT[en] for z in zs):
                hit = f"应={SUSPECT[en]}"
            elif any(any(b in z for b in BAD_ZH) for z in zs):
                hit = "黑名单串"
            if hit:
                hits.append((base, en, ",".join(zs), hit))
    # 校验对照表 key 有效性（防失控：只报不阻断）
    miss = [k for k in SUSPECT if k not in all_en and k != "Bushings2" and k != "Rulers2" and k != "Scissors2"]
    lines = []
    lines.append(f"14 类唯一段名: {len(all_en)} | 嫌疑命中: {len(hits)} | 对照表 key 未在真实段名出现: {len(miss)}")
    if miss: lines.append("表内无效 key: " + ", ".join(miss[:15]))
    lines.append("")
    for base, en, zs, note in sorted(hits):
        lines.append(f"{base} | {en} = {zs}   [{note}]")
    with open(OUT, "w", encoding="utf-8") as fp:
        fp.write("\n".join(lines))
    print(f"写出 {OUT}，共 {len(lines)-2} 条嫌疑")
    print("无效 key:", miss if miss else "无")

if __name__ == "__main__":
    main()
