# -*- coding: utf-8 -*-
"""
BTG 类目中英合并构建器
读 07_OUTPUTS/Amazon类目选品管理中心/ 下 15 份 CSV（amztoolbox.top 导出）
按「英文完整路径 -> 中文完整路径」建映射，修正明显机翻译错后
把 zh（中文名）/ zhPath（中文路径）合并写回 server/data/btg/*.json 分片。
幂等：对已有 zh 字段覆盖重写；写前自动备份到 btg/.zh_bak_YYYYMMDD/。
用法: python build_zh.py [--dry-run]
"""
import csv, glob, json, os, re, shutil, sys, datetime

SERVER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../CODE/server
DATA = os.path.join(SERVER, "data", "btg")
CSV_DIR = r"C:/Users/guyuepiero/Documents/MemWeave v1.0/07_OUTPUTS/Amazon类目选品管理中心"

# ---------- 段级错译修正表 v1（home-improvement 高置信，key 必须存在于 CSV）----------
FIX = {
 "Fans": "风扇", "Nails": "钉子", "Nailers": "钉枪", "Sanders": "砂光机",
 "Routers": "修边机", "Router Bits": "修边机铣刀", "Router Fences": "修边机靠栅",
 "Router Parts & Accessories": "修边机零件及配件", "Transformers": "变压器",
 "Rulers": "直尺", "Punches": "冲子", "Drills": "钻", "Dies": "板牙",
 "Toilets": "马桶", "Urinals": "小便池", "Concrete": "混凝土", "Concrete Tools": "混凝土工具",
 "Mortar": "砂浆", "Grout": "填缝剂", "Rebar": "钢筋", "Flashing": "泛水板",
 "Gates": "大门", "Shackles": "卸扣", "Splines": "花键", "Hardware": "五金",
 "Hardware Cloth": "铁丝网", "Brackets": "支架", "Columns": "立柱", "Pickets": "栅栏尖桩",
 "Railings & Pickets": "栏杆和尖桩", "Newel Posts": "楼梯扶手柱", "Posts": "立柱",
 "Mailbox Posts": "邮箱立柱", "Post-Mount Mailboxes": "柱装邮箱", "Post Hole Diggers": "挖坑机",
 "Pier Blocks": "立柱墩块", "Braces": "护具", "Guards": "防护罩", "Covers": "罩",
 "Seals": "密封件", "Sleeves": "套管", "Axes": "斧头",
 "Files & Rasps": "锉刀和木锉", "File Handles": "锉刀柄", "Swiss Pattern Files": "瑞士纹锉",
 "American Pattern Files": "美式纹锉", "Nibblers": "冲剪机", "Loppers": "高枝剪",
 "Dead-Blow Hammers": "静音锤", "Jack Planes": "粗刨", "Japanese Planes": "日本刨",
 "Block Planes": "小型刨", "Smoothing Planes": "细刨", "Jointers": "平刨机",
 "Jointer Knives": "平刨刀片", "Levels": "水平仪", "Stud Finders": "龙骨探测仪",
 "Scribers": "划线器", "Chalk Lines": "粉线", "Plumb Bobs": "铅垂", "Tampers": "夯具",
 "Pry Bars": "撬棍", "Nail Pullers": "起钉器", "Putty Knives": "腻子刀",
 "Utility Knives": "美工刀", "Pipe Taps": "管螺纹丝锥", "Tap & Die Sets": "丝锥和板牙套件",
 "Ranges": "炉灶", "Freestanding Ranges": "独立式炉灶", "Slide-In Ranges": "滑入式炉灶",
 "Drop-In Ranges": "嵌入式炉灶", "Range Receptacles": "炉灶电源插座", "Island Lights": "中岛吊灯",
 "Pendants": "吊灯", "Vanity Suites": "浴室柜组合", "Wall Ovens": "嵌入式烤箱",
 "Oscillating Tools": "摆动工具", "Oscillating Tool Blades": "摆动工具锯片",
 "Pull Chains": "拉绳", "Pulls": "拉手", "Snaps": "按扣", "Strippers": "剥线器",
 "Wire Strippers": "剥线钳", "Wire Cutters": "剪线钳", "EMF Meters": "电磁场检测仪",
 "Testers": "测试仪", "Moisture Meters": "水分检测仪", "Humidity Meters": "湿度检测仪",
 "Recovery Straps": "拖车救援带", "Load Binders": "货物绑紧器", "Rope Barriers": "隔离绳",
 "Chain Barriers": "隔离链", "Catches": "碰珠", "Latches": "门闩", "Hasps": "搭扣",
 "Knockers": "门环", "Door Chimes & Bells": "门铃和铃铛", "Chimes": "铃",
 "Plungers": "皮搋子", "Elbows": "弯头", "Cable Ties": "尼龙扎带",
 "Garden Twine & Twist Ties": "园艺麻绳和扎带", "Twist Ties": "扎带",
 "Downspouts": "雨水管", "Gutters": "檐槽", "Window Insulation Kits": "窗户隔热套件",
 "Pocket & Bifold Door Hardware": "暗门和折叠门五金", "Sliding & Pocket Doors": "推拉门和暗门",
 "Screws": "螺丝", "Lag Screws": "木螺钉", "Socket Head Screws": "内六角螺丝",
 "Self-Tapping Screws": "自攻螺丝", "Nuts": "螺母", "Eye Nuts": "吊环螺母",
 "Thumb Nuts": "滚花螺母", "Wing Nuts": "蝶形螺母", "Acorn Nuts": "盖形螺母",
 "Push Nuts": "卡入螺母", "Union Nuts": "活接螺母", "Yor-Lok Nuts": "约尔洛克防松螺母",
 "Speed Nuts": "快速螺母", "Washers": "垫圈", "Lock Washers": "防松垫圈",
 "Spring Lock Washers": "弹簧防松垫圈", "Tooth Lock Washers": "齿形防松垫圈",
 "Belleville Washers": "碟形垫圈", "Wave Washers": "波形垫圈", "Countersunk Washers": "沉头垫圈",
 "Faucet Washers": "水龙头密封垫圈", "Bolts": "螺栓", "Anchors": "锚栓",
 "Wedge Anchors": "楔形锚栓", "Sleeve Anchors": "套筒锚栓", "Toggle Anchors": "弹簧翼锚栓",
 "Hollow-Wall Anchors": "空心墙锚栓", "Drywall Anchors": "石膏板锚栓", "Chemical Anchors": "化学锚栓",
 "Rivets": "铆钉", "Blind Rivets": "抽芯铆钉", "Solid Rivets": "实心铆钉",
 "Tubular Rivets": "空心铆钉", "Retaining Rings": "弹性挡圈", "Internal Retaining Rings": "内用弹性挡圈",
 "External Retaining Rings": "外用弹性挡圈", "Cotter Pins": "开口销", "Clevis Pins": "U 形销",
 "Hitch Pins": "拖挂销", "Dowel Pins": "定位销", "Quick-Release Pins": "快拆销",
 "Spring Pins": "弹性销", "Linchpins": "锁紧销", "Pins": "销", "Hex Keys": "内六角扳手",
 "Hex Nuts": "六角螺母", "Hex Nose": "六角端头", "Square Nose": "方端头",
 "Ball Nose": "球端头", "Rods": "杆", "Threaded Rods & Studs": "螺纹杆和螺柱",
 "Drill Bits": "钻头", "Twist Drill Bits": "麻花钻头", "Brad-Point Drill Bits": "定心钻头",
 "Forstner Drill Bits": "福斯特纳钻头", "Masonry Drill Bits": "砖石钻头",
 "Core Drills": "取芯钻", "Hole Saws": "开孔锯", "Hole Saw Arbors": "开孔锯心轴",
 "Countersink Drill Bits": "沉头钻头", "Hex-Shank Drill Bits": "六角柄钻头",
 "Rotary Hammer Drill Bits": "电锤钻头", "Drill Chucks": "钻夹头", "Chucks": "夹头",
 "Collets": "弹性夹头", "Reamers": "铰刀", "Taps": "丝锥", "Taps & Dies": "丝锥和板牙",
 "Tap Extractors": "丝锥取出器", "Torches": "喷灯", "Propane Torches": "丙烷喷灯",
 "Oxyacetylene Torches": "氧乙炔焊炬", "Heat Guns": "热风枪", "Glue Guns": "热熔胶枪",
 "Caulking Guns": "填缝胶枪", "Stick Electrodes": "焊条", "Electrode Holders": "焊钳",
 "Welding Helmets": "焊接面罩", "Welding Gloves": "焊接手套", "Welding Hammers": "焊渣锤",
 "Vise Grips & Locking Pliers": "大力钳", "Slip-Joint Pliers": "鲤鱼钳",
 "Snap-Ring Pliers": "卡簧钳", "Tongue-and-Groove Pliers": "水泵钳", "Pliers": "钳子",
 "Wrenches": "扳手", "Adjustable Wrenches": "活动扳手", "Open-End Wrenches": "开口扳手",
 "Box-End Wrenches": "梅花扳手", "Combination Wrenches": "两用扳手", "Pipe Wrenches": "管钳",
 "Torque Wrenches": "扭力扳手", "Caliper Kits & Sets": "卡尺套件",
 "Band Saws": "带锯", "Miter Saws": "斜切锯", "Table Saws": "台锯",
 "Cut-Off Wheels": "切割片", "Cutting Wheels": "切割片", "Abrasive Wheels & Discs": "砂轮和砂盘",
 "Flap Discs": "千页砂盘", "Flap Wheels": "千页轮", "Buffing Wheels": "抛光轮",
 "Hook & Loop Discs": "魔术贴砂盘", "Quick Change Discs": "快换砂盘",
 "Cup Brushes": "杯形钢丝刷", "Wheel Brushes": "轮形钢丝刷",
 "Wire Wheels & Brushes": "钢丝轮和钢丝刷", "Wire Scratch Brushes": "钢丝刷",
 "Angle Grinders": "角磨机", "Straight Grinders": "直磨机", "Die Grinders": "模具磨头",
 "Bench Grinders": "台式砂轮机", "Grinders": "磨机", "Rotary Tools": "旋转工具",
 "Multitools": "多功能工具", "Multitools & Accessories": "多功能工具及配件",
 "Air Compressors & Inflators": "空气压缩机和充气泵", "Tool Sets": "工具套装",
 "ESD Tool Sets": "防静电工具套装", "1,000 Volt Tool Sets": "1000V 绝缘工具套装",
 "Tool Bags": "工具包", "Tool Pouches": "工具袋", "Tool Boxes": "工具箱",
 "Tool Cabinets": "工具柜", "Tool Chests": "工具箱", "Tool Organizers": "工具整理器",
 "Workbenches": "工作台", "Vises": "台钳", "Bench Vises": "台式台钳",
 "Clamps": "夹具", "C-Clamps": "C 形夹", "Bar Clamps": "杆夹", "Pipe Clamps": "管夹",
 "Spring Clamps": "弹簧夹", "Bench Clamps": "台夹", "Hose Clamps": "喉箍",
 "Aerators": "起泡器", "Kitchen Sink Aerators": "厨房水槽起泡器",
 "Console Sinks": "独立台盆", "Pedestal Sinks": "立柱盆", "Vessel Sinks": "台上盆",
 "Kitchen Sinks": "厨房水槽", "Bathroom Sinks": "浴室台盆", "Faucets": "水龙头",
 "Kitchen Faucets": "厨房水龙头", "Touchless Faucets": "感应式水龙头",
 "Touch On Faucets": "触摸式水龙头", "Showerheads": "花洒", "Fixed Showerheads": "固定花洒",
 "Handheld Showerheads": "手持花洒", "Showers": "淋浴", "Shower Stalls": "淋浴房",
 "Steam Showers": "蒸汽淋浴房", "Whirlpool Bathtubs": "按摩浴缸", "Clawfoot Bathtubs": "爪足浴缸",
 "Walk-In Bathtubs": "步入式浴缸", "Bathtubs": "浴缸", "Bathroom Vanities": "浴室柜",
 "Bathroom Fixtures": "卫浴洁具", "Bathroom Hardware": "卫浴五金", "Grab Bars": "扶手杆",
 "Towel Bars": "毛巾杆", "Toilet Paper Holders": "卫生纸架", "Water Filters": "净水器",
 "Replacement Water Filters": "净水器替换滤芯", "Refrigerator Filters": "冰箱滤芯",
 "Furnace Filters": "炉子滤网", "Air Filters": "空气滤网", "Air Purifier Filters": "空气净化器滤网",
 "Vacuum Parts & Accessories": "吸尘器零件及配件", "Wet-Dry Vacuums": "干湿两用吸尘器",
 "Dust Collectors & Air Cleaners": "集尘器和空气净化器", "Washers": "洗衣机",
 "Dryers": "干衣机", "Washers & Dryers": "洗衣机和干衣机",
 "All-in-One Combination Washers & Dryers": "洗烘一体机", "Irons": "电熨斗",
 "Garment Steamers": "挂烫机", "Garment Steamer Accessories": "挂烫机配件",
 "Iron & Steamer Parts & Accessories": "熨斗和挂烫机零件及配件", "Water Heaters": "热水器",
 "Water Heater Parts": "热水器零件", "Pumps": "泵", "Water Pumps": "水泵",
 "Well Pumps": "井泵", "Sump Pumps": "污水泵", "Utility Pumps": "多用途泵",
 "Pump Accessories": "泵配件", "Range Hoods": "抽油烟机", "Fume & Smoke Extraction": "排烟系统",
 "Duct Tape": "布基胶带", "Electrical": "电气", "Electrical Wire": "电线", "Cables": "电缆",
 "Extension Cords": "延长线", "Power Cords": "电源线", "Cord Reels": "卷线盘",
 "Multi-Outlets": "多口排插", "Standard Outlets": "标准插座", "Outlets & Accessories": "插座及配件",
 "Outlet Covers": "插座盖板", "Electrical Boxes": "接线盒",
 "Electrical Boxes, Conduits & Fittings": "接线盒、线管和配件", "Wall Plates": "墙板",
 "Light Switches": "电灯开关", "Dimmer Switches": "调光开关", "Motion-Activated Switches": "感应开关",
 "Switches": "开关", "Light Sockets": "灯座", "Plugs": "插头", "Plug Receptacles": "插座",
 "Surge Protectors": "浪涌保护器", "Power Strips": "插线板",
 "Power Strips & Surge Protectors": "插线板和浪涌保护器", "Battery Chargers": "电池充电器",
 "Battery Packs": "电池组", "Low Voltage Transformers": "低压变压器",
 "Home Automation Devices": "家居自动化设备", "Hubs & Controllers": "网关和控制器",
 "Hubs": "网关", "Sensors": "传感器", "Motion Sensors": "人体感应器",
 "Smoke Detectors": "烟雾报警器", "Carbon Monoxide Detectors": "一氧化碳报警器",
 "Video Doorbells": "可视门铃", "Surveillance Cameras": "监控摄像头",
 "Bullet Cameras": "枪式摄像头", "Dome Cameras": "半球摄像头", "Hidden Cameras": "隐形摄像头",
 "Remote Controls": "遥控器", "Keypads & Remotes": "按键面板和遥控器", "Locks": "锁",
 "Locks & Latches": "锁和门闩", "Deadbolts": "插芯锁", "Padlocks": "挂锁",
 "Combination Padlocks": "密码挂锁", "Handlesets": "门把手套装", "Door Knobs": "门旋钮",
 "Door Levers": "门把手杆", "Door Closers": "闭门器", "Door Viewers": "猫眼",
 "Door Springs": "门弹簧", "Weather Stripping": "门窗密封条", "Windows": "窗户",
 "Casement Windows": "平开窗", "Double Hung Windows": "双悬窗", "Sliding Windows": "推拉窗",
 "Skylights & Roof Windows": "天窗和屋顶窗", "Window Screens": "纱窗",
 "Window Screen Accessories": "纱窗配件", "Window Hardware": "窗五金", "Glass Blocks": "玻璃砖",
 "Mirrors": "镜子", "Wall Mirrors": "壁挂镜", "Ceiling Medallions": "天花板花盘",
 "Wall Lamps & Sconces": "壁灯和壁烛灯", "Floor Lamps": "落地灯", "Table Lamps": "台灯",
 "Desk Lamps": "台灯", "Ceiling Lights": "吸顶灯", "Recessed Lighting": "嵌入式照明",
 "Track Lighting": "轨道照明", "Under-Cabinet Lights": "柜下灯", "Vanity Lights": "浴室柜灯",
 "Porch & Patio Lights": "门廊和露台灯", "Post Lights": "柱灯", "Path Lights": "小径灯",
 "Landscape Lighting": "景观照明", "String Lights": "灯串", "Night Lights": "夜灯",
 "Flashlights": "手电筒", "Handheld Flashlights": "手持手电筒", "Tactical Flashlights": "战术手电筒",
 "Light Bulbs": "灯泡", "LED Bulbs": "LED 灯泡", "Incandescent Bulbs": "白炽灯泡",
 "Halogen Bulbs": "卤素灯泡", "Compact Fluorescent Bulbs": "紧凑型荧光灯泡",
 "Fluorescent Tubes": "荧光灯管", "Black Light Bulbs": "黑光灯泡", "Lamp Shades": "灯罩",
 "Lamps & Shades": "灯具和灯罩", "Lighting Accessories": "照明配件", "Lamp Oil": "灯油",
 "Furniture Hardware": "家具五金", "Furniture Legs": "家具腿", "Furniture Pads": "家具垫",
 "Furniture Sliders": "家具移动垫", "Furniture Cups": "家具脚垫", "Drawer Slides": "抽屉滑轨",
 "Cabinet Hardware": "橱柜五金", "Hinges": "铰链", "Gate Hinges": "大门铰链",
 "Door Hinges": "门铰链", "Casters": "脚轮", "Wood Screws": "木螺丝",
 "Drywall Screws": "石膏板螺丝", "Sheet Metal Screws": "钣金螺丝", "Concrete Screws": "混凝土螺丝",
 "Machine Screws": "机用螺丝", "Hex Bolts": "六角螺栓", "Carriage Bolts": "马车螺栓",
 "Expansion Bolts": "膨胀螺栓", "U-Bolts": "U 型螺栓", "Hanger Bolts": "吊架螺栓",
 "Elevator Bolts": "电梯螺栓", "Wheel Bolts": "车轮螺栓", "Step Bolts": "阶梯螺栓",
 "Eyebolts": "吊环螺栓", "Standoffs": "支座", "Spacers": "垫片", "Spacers & Standoffs": "垫片和支座",
 "Grommet Kits": "索环套件", "Threaded Inserts": "螺纹嵌件", "Press-In Inserts": "压入嵌件",
 "Heat Set Inserts": "热熔嵌件", "Key Locking Inserts": "钥匙锁式嵌件", "Rivet Nuts": "铆螺母",
 "T-Nuts": "T 型螺母", "Slotted Nuts": "开槽螺母", "Coupling Nuts": "管接头螺母",
 "Compression Nuts": "压缩螺母", "Flange Nuts": "法兰螺母", "Locknuts": "锁紧螺母",
 "Panel Nuts": "面板螺母", "Weld Nuts": "焊接螺母", "Nut Drivers": "螺母起子",
 "Screwdrivers": "螺丝刀", "Screwdriver Sets": "螺丝刀套装", "Impact Drivers": "冲击起子",
 "Drill Drivers": "电钻起子", "Multi-Bit Drivers": "多用批头起子", "Square Drive": "方驱",
 "Star Drive": "六星驱动", "Phillips Head Drive": "十字驱动", "Power Screwdrivers": "电动螺丝刀",
 "Screw Guns": "螺丝枪", "Drill Presses": "钻床", "Hammer Drills": "电锤钻",
 "Rotary Hammers": "电锤", "Demolition Drills & Hammers": "拆除钻和电镐",
 "Circular Saws": "圆锯", "Jig Saws": "曲线锯", "Reciprocating Saws": "往复锯",
 "Scroll Saws": "线锯", "Metal-Cutting & Chop Saws": "金属切割锯", "Masonry Saws": "砖石锯",
 "Tile Saws": "瓷砖锯", "Shears": "剪刀", "Scissors": "剪刀", "Scissors & Shears": "剪刀和剪子",
 # ===== 2026-09-06 追加：14 大类无歧义硬伤（机器预筛，任意语境下机翻错义/音译人名都算错）=====
 "Bulbs": "灯泡", "Cameras": "相机", "Mice": "鼠标", "Rectifiers": "整流器",
 "Presses": "压力机", "Sprockets": "链轮", "Mufflers": "消音器", "Carburetors": "化油器",
 "Camshafts": "凸轮轴", "Kickboxing": "踢拳", "Leashes": "牵引绳", "Clipboards": "书写板",
 "Skirts": "半身裙", "Vanities": "浴室柜", "Teleprompters": "提词器",
 "Toilets & Parts": "马桶及配件", "Commercial Toilets": "商用马桶",
 "Toilet Spare Parts": "马桶备件", "Toilet Cleaners": "马桶清洁剂",
 "Cue Chalk": "台球巧粉", "Cue Tips": "台球杆皮头", "Cue Tip Tools": "台球皮头工具",
 "Brad Nails": "无头钉", "Collated Nails": "排钉", "Common Nails": "普通钉",
 "Finish Nails": "装饰钉", "Finishing Nails": "装饰钉",
 "Detail Sanders": "细节砂光机", "Random-Orbit Sanders": "随机轨道砂光机",
 "Arch Punches": "拱形冲子", "Drift Punches": "冲头", "Knockout Punches": "敲落冲子",
 "Personal Fans": "个人风扇", "Misting Fans": "喷雾风扇",
 "Punch Needle & Rug Punch": "戳针和地毯戳针", "Tip-Ups": "冰钓提竿器",
 "Exhaust Pipes & Tips": "排气管和尾喉", "Boost Gauges": "增压表",
 "Condenser Fans": "冷凝器风扇",
 # ===== 2026-09-06 追加2：清除「·」式整段音译垃圾（机翻把普通词当人名音译，19 段 29 节点）=====
 "Mat Cutters & Blades": "卡纸切割刀和刀片", "Mat Cutter Blades": "卡纸切割刀片",
 "Aida Cloth": "艾达布", "Appliques": "贴花",
 "Beaded Appliqué": "珠饰贴花", "Lace Appliqué": "蕾丝贴花",
 "Rack Fairings": "行李架导流罩", "Gooseneck Hitch": "鹅颈拖车钩",
 "Idler Pulleys": "惰轮", "Caliper Bleeder Screws": "卡钳放气螺丝",
 "Caliper Bolts & Pins": "卡钳螺栓和销", "Caliper Bushing Kits": "卡钳衬套套装",
 "Ram Air Kit": "冲压进气套件", "Trunk Lid Pull Down": "后备箱盖下拉器",
 "Mary Jane": "玛丽珍鞋", "Lehenga Cholis": "长裙和短上衣套装",
 "Shalwar Kemeez": "宽松裤和长衫套装", "Grill Brushes": "烤架清洁刷",
 "Grill Carts": "烤架推车", "Grill Racks": "烤网", "Lamés": "击剑金属衣",
 "Sabre Lamés": "佩剑金属衣",
 # ===== 2026-09-06 追加3：zhPath 半括号乱码批量清除（"X & Y" 结构机翻只取首词+残留"( X)"，183 段）=====
 # --- automotive 高频 ---
 "Switches & Relays": "开关和继电器", "Engines & Engine Parts": "发动机及发动机零件",
 "Body & Trim": "车身和饰件", "Bearings & Seals": "轴承和密封件",
 "Transmission & Drive Train": "变速箱和传动系统", "Body & Frame Parts": "车身和车架零件",
 "Clutches & Parts": "离合器及零件", "Transmissions & Parts": "变速箱及零件",
 "Pistons & Parts": "活塞及零件", "Wheel Accessories & Parts": "车轮配件和零件",
 "Accent & Off Road Lighting": "氛围灯和越野照明", "Paints & Primers": "油漆和底漆",
 "Consoles & Organizers": "中控台和收纳盒", "Snow & Ice": "冰雪用品",
 "Chains & Sprockets": "链条和链轮", "Forks & Accessories": "前叉及配件",
 "CV (Constant Velocity)": "等速万向节 (CV)", "Fans & Parts": "风扇及零件",
 "Windshields & Accessories": "挡风玻璃及配件", "Engine Heaters & Accessories": "发动机加热器及配件",
 "Pistons & Accessories": "活塞及配件", "Cam & Lifter Kits": "凸轮和挺杆套件",
 "Battery Wiring & Terminals": "电池电线和接线端子", "Running Boards & Steps": "侧踏板和踏步",
 "Mirrors & Accessories": "后视镜及配件", "Knee & Shin Protection": "护膝和护腿板",
 "Manifold & Parts": "歧管及零件", "Valve Cover & Stem": "气门室盖和气门杆",
 "Points & Condensers": "点火触点和电容器", "Fuses & Accessories": "保险丝及配件",
 "Lug Nuts & Accessories": "轮毂螺母及配件", "Horns & Accessories": "喇叭及配件",
 "Engine Hoists & Stands": "发动机吊架和支架", "Spark Plugs & Accessories": "火花塞及配件",
 "Chest & Back Protectors": "护胸和护背", "Transmission Filters & Accessories": "变速箱滤清器及配件",
 "Antennas & Parts": "天线及零件", "Snow Plow Attachments & Accessories": "除雪犁附件及配件",
 "Warning & Emergency Lights": "警示灯和应急灯", "Lowers & Deflectors": "下导流板和挡风板",
 "Clutch Cables & Lines": "离合器拉线和油管", "Headers & Mid-Pipes": "排气歧管和中段排气管",
 "Accessory Lighting & Kits": "辅助照明及套件", "Turn Signal Assemblies & Lenses": "转向灯总成和灯罩",
 "Rod & Main Bearings": "连杆轴承和主轴瓦", "Transaxle & Transmission": "变速驱动桥和变速箱",
 "Tube Seals & Kits": "管密封件和套件", "Exterior Ladders & Steps": "外部爬梯和踏板",
 "Valve Stems & Caps": "气门嘴和气门嘴帽", "Wheelbarrows & Replacement Parts": "手推车和替换零件",
 "Hitch Clips & Pins": "拖车钩夹片和销", "Sending Units & Cables": "发送单元和线缆",
 "High & Low Wiring Kits": "高低线束套件", "Side Marker & Turn Signal Combos": "侧示廓灯和转向灯组合",
 "Towing & Trailer Lighting": "牵引和拖车照明", "Transmission & Parts": "变速箱及零件",
 "Bushings & Bearings": "衬套和轴承", "Showers & Bathtubs": "淋浴和浴缸",
 "Polishing & Waxing Kits": "抛光打蜡套装", "Bug & Hood Shields": "防虫板和引擎盖挡板",
 "Side Window Wind Deflectors & Visors": "侧窗雨挡和遮阳板", "Center & Floor Consoles": "中控台和地板控制台",
 "Parking & Side Marker Combos": "驻车灯和侧示廓灯组合", "Kickstands & Jiffy Stands": "边撑和侧支架",
 "Chain & Sprocket Kits": "链条链轮套件", "Clamps & Brackets": "卡箍和支架",
 "Paint Remover & Stripper": "脱漆剂和除漆器", "Terminals & Ends": "接线端子和端头",
 "VIR (Valves in Receiver)": "接收器阀 (VIR)", "Pistons & Pins": "活塞和活塞销",
 "Dipsticks & Tubes": "机油尺和导管", "Pick-Up Tubes & Screens": "吸油管和滤网",
 "Primers & Drives": "注油器和驱动件", "Nuts & Bolts": "螺母和螺栓",
 "Piping & Piping Kits": "管路和管路套件", "Filter & Gasket Kits": "滤清器和垫片套件",
 "Lock Rings & Seals": "锁环和密封件", "Cap & Rotor Kit": "分电器盖和分火头套件",
 "Points & Condenser Kits": "触点和电容器套件", "Systems & Kits": "系统和套件",
 "Boots & Accessories": "防尘套及配件", "Body & Suspension Lift Kits": "车身和悬挂举升套件",
 "Shackles & Parts": "卸扣及零件", "Track Bar Hardware & Parts": "止推杆五金件和零件",
 "Stators & Winding": "定子和绕组", "Warning Buzzer & Chime": "警示蜂鸣器和提示音",
 "Differential Rings & Pinions": "差速器齿圈和主动锥齿轮", "Ring & Pinion Gears": "齿圈和主动齿轮",
 "Clamps & Straps": "卡箍和绑带", "Washes & Waxes": "洗车液和车蜡",
 "Stereos & Speakers": "车载音响和扬声器", "Cooktop & Ranges": "灶台和炉灶",
 "Tables & Tabletops": "桌子和桌面", "Industrial & Off-the-Road (OTR)": "工业和非公路 (OTR)",
 "Wheel Hubs & Bearings": "轮毂和轴承", "Upholstery & Trim Tools": "内饰和饰条工具",
 "Windshield & Glass Repair Tools": "挡风玻璃和玻璃修理工具", "Multimeters & Analyzers": "万用表和分析仪",
 "Metric Inserts & Kits": "公制嵌件和套件",
 # --- electronics ---
 "Lighting & Studio": "照明和影棚设备", "Filters & Accessories": "过滤器及配件",
 "Batteries & Chargers": "电池和充电器", "Light Meters & Accessories": "测光表及配件",
 "Speaker Parts & Components": "扬声器零件和组件", "Battery & Charger Sets": "电池和充电器套装",
 "Ink & Toner": "墨水和碳粉", "Bag & Case Accessories": "包和箱配件",
 "Light Boxes & Loupes": "看片灯箱和放大镜", "Camera Supports & Stabilizers": "相机支撑和稳定器",
 "Strobes & Flashes": "频闪灯和闪光灯", "CD & Tape Players": "CD 和磁带播放机",
 "Booms & Stands": "话筒吊杆和支架", "Wireless & Streaming Audio": "无线和流媒体音频",
 "Color Correction & Compensation Filters": "校色和补偿滤镜", "Sync & PC Cords": "同步线和电脑连接线",
 "Camera Mounts & Clamps": "相机支架和夹扣", "Gamepads & Standard Controllers": "手柄和标准控制器",
 "Slide, Negative & Print Pages": "幻灯片、底片和照片装帧页", "Thermal Paste & Pads": "导热硅脂和导热垫",
 "Point & Shoot Digital Cameras": "数码卡片相机", "Film & Slide Scanners": "胶片和幻灯片扫描仪",
 "Medium & Large-Format Cameras": "中画幅和大画幅相机", "Point & Shoot Film Cameras": "胶片卡片相机",
 "Camera & Camcorder Lens Bundles": "相机和摄像机镜头套装", "Hard Drive Bags & Cases": "硬盘包和硬盘盒",
 "Floppy & Tape Drives": "软盘驱动器和磁带驱动器", "Wall Plates & Connectors": "墙板和连接器",
 "Ceiling & In-Wall Speakers": "吸顶和入墙音箱", "Turntable Cartridges & Needles": "唱头和唱针",
 "Coin & Button Cell": "币形和纽扣电池", "Horns & Sirens": "警报喇叭和警笛",
 # --- arts-and-crafts ---
 "Paper & Paper Crafts": "纸张和纸艺用品", "Trim & Embellishments": "饰边和装饰",
 "Accessories, Hardware & Tools": "配件、五金和工具", "Boards & Canvas": "画板和画布",
 "Thread & Floss": "线和绣线", "Tools & Tool Sets": "工具和工具套装",
 "Weaving & Spinning": "编织和纺线", "Pins & Pincushions": "大头针和针插",
 "Drawing & Lettering Aids": "绘图和书写辅助工具", "Drying & Print Racks": "晾干架和晾画架",
 "Flat & Vertical Files": "平放式和立式文件柜", "Drawing Tables & Boards": "绘图桌和绘图板",
 "Glues & Pastes": "胶水和浆糊", "Albums & Refills": "相册和补充内页",
 "Dress Forms & Mannequins": "试衣人台和人模", "Eyelets & Grommets": "孔眼和金属扣眼",
 "Marking & Tracing Tools": "标记和描图工具", "Beading Cords & Threads": "串珠线和线绳",
 "Engraving Machines & Tools": "雕刻机和雕刻工具", "Earring Backs & Findings": "耳堵和首饰配件",
 "Ring Blanks & Findings": "戒指胚和首饰配件", "Macrame & Knotting": "绳编和打结",
 "Clothes & Accessories": "服装和配饰", "Gift Wrap Crinkle & Filler Paper": "礼品包装碎纸和填充纸",
 "Knitting Looms & Boards": "编织机和编织板", "Crane & Boom Cars": "起重机和吊臂车",
 "Storage Boxes & Organizers": "收纳盒和整理盒", "Sergers & Overlock Machines": "包缝机和锁边机",
 "Yarn & Tapestry": "毛线和挂毯", "Stuffing & Polyester Fill": "填充棉和涤纶填充料",
 "Sewing Patterns & Templates": "缝纫纸样和模板",
 # --- garden ---
 "Structures & Hardware": "结构和五金件", "Chainsaw Parts & Accessories": "链锯零件和配件",
 "Landscape Lighting & Accessories": "景观照明及配件", "Filters & Filter Media": "过滤器和过滤介质",
 "String Trimmer Parts & Accessories": "打草机零件和配件", "Hose Connectors & Accessories": "软管接头及配件",
 "Rain Barrels & Accessories": "雨水收集桶及配件", "Feeders & Feed": "喂食器和饲料",
 "Vertical & Wall Planters": "立式和壁挂式花盆", "Trimmers & Accessories": "修剪机及配件",
 "Filter Cartridges & Media": "滤芯和滤材", "Log Splitter Parts & Accessories": "劈木机零件和配件",
 "Flooring & Bases": "地板和底座", "Spare & Replacement Parts": "备件和替换件",
 "Parts & Connectors": "零件和连接器", "Rain Barrels": "雨水收集桶",
 "Stands & Bases": "支架和底座", "Flood & Perimeter": "泛光灯和周边灯",
 "Misting Parts & Accessories": "喷雾零件和配件", "Stools & Bar Chairs": "吧台凳和吧椅",
 "Umbrella Stands & Bases": "伞架和底座", "Snow & Ice Melters": "融雪化冰剂",
}

# ---------- 分大类歧义修正表 v2（2026-09-06）：同 en 段在不同大类语境正确译名不同，按 slug 覆盖 ----------
FIX_BY_SLUG = {
 "pet-supplies": {"Collars": "项圈", "Harnesses": "胸背带", "Leashes": "牵引绳", "Litter": "猫砂", "Tanks": "缸"},
 "baby-products": {"Bottles": "奶瓶", "Nipples": "奶嘴"},
 "beauty": {"Foundation": "粉底", "Serums": "精华"},
 "automotive": {"Hoods": "引擎盖", "Trunks": "后备箱", "Wheels": "轮毂", "Shocks": "减震器", "Spindles": "主轴", "Calipers & Parts": "卡钳及零件"},
 "fashion": {"Studs": "铆钉"},
}

# ---------- 分片文件名 -> 大类 slug（用 index.json titleEn/titleZh 匹配 CSV 前缀）----------

def load_index():
    with open(os.path.join(DATA, "index.json"), encoding="utf-8") as f:
        return json.load(f)

def csv_files_by_title():
    """CSV 中文文件名前缀 -> 文件路径"""
    out = {}
    for f in glob.glob(os.path.join(CSV_DIR, "*_叶子类目选品管理.csv")):
        base = os.path.basename(f)[: -len("_叶子类目选品管理.csv")]
        out[base] = f
    return out

def clean(s):
    return (s or "").strip().strip('"').strip()

def parse_csv(path):
    """返回 dict: en_path -> zh_path。
    注意：CSV 每行是「叶子完整路径」，但同一行的每层前缀（父级路径）也有对应中文前缀，
    故把所有前缀都纳入映射，保证树中父节点同样能拿到中文。"""
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    hdr, body = rows[0], rows[1:]
    try:
        eidx = hdr.index("英文完整路径"); zidx = hdr.index("中文完整路径")
    except ValueError:
        eidx, zidx = 3, 4
    m = {}
    for r in body:
        if len(r) <= max(eidx, zidx): continue
        ep, zp = clean(r[eidx]), clean(r[zidx])
        if not (ep and zp): continue
        eparts = [clean(x) for x in ep.split("/")]
        zparts = [clean(x) for x in zp.replace(" / ", "/").split("/")]
        if len(eparts) != len(zparts):
            # 中文段数不齐时退化为只记整行（末段对齐场景少，兜底）
            m.setdefault(ep, zp)
            continue
        for i in range(1, len(eparts) + 1):
            e_prefix = "/".join(eparts[:i])
            z_prefix = " / ".join(zparts[:i])
            # 前缀已存在时优先保留更早出现的（同 path 前缀翻译应一致）
            m.setdefault(e_prefix, z_prefix)
    return m

def fix_seg(zh, en_parts, zh_parts, slug=""):
    """按段级修正表重写中文路径（zh_parts 每段与 en_parts 对齐，逐段查 FIX）
    优先级：FIX_BY_SLUG[slug] > FIX（同段跨类语境词按大类取正确译）"""
    fix_local = FIX_BY_SLUG.get(slug, {})
    out = []
    for e, z in zip(en_parts, zh_parts):
        e, z = clean(e), clean(z)
        out.append(fix_local.get(e, FIX.get(e, z)))
    return " / ".join(out)

def main():
    dry = "--dry-run" in sys.argv
    idx = {i["slug"]: i for i in load_index()}
    # CSV 前缀 -> slug：先按 titleZh 前缀匹配，再按 titleEn 词首匹配
    title2slug = {}
    for i in idx.values():
        title2slug.setdefault(i["titleZh"], i["slug"])
        title2slug.setdefault(i["titleEn"], i["slug"])
    csvs = csv_files_by_title()

    fixed_keys, missing_keys = 0, []
    for slug, meta in idx.items():
        zh = meta.get("titleZh", "")
        en = meta.get("titleEn", "")
        f = csvs.get(zh) or csvs.get(en)
        if not f:
            print(f"[跳过] {slug}: 找不到对应 CSV（titleZh={zh}）")
            continue
        zm = parse_csv(f)
        tree_file = os.path.join(DATA, meta["file"])
        with open(tree_file, encoding="utf-8") as fp:
            doc = json.load(fp)
        trees = doc.get("tree") if isinstance(doc, dict) else doc
        if isinstance(trees, dict): trees = [trees]
        hit = miss = 0
        changed = 0

        def walk(ns):
            nonlocal hit, miss, changed
            for n in ns:
                p = n.get("path", "")
                zfull = zm.get(p)
                if zfull:
                    hit += 1
                    # 应用段级修正（英文段与中文段按 / 对齐）
                    parts_e = [clean(x) for x in p.split("/")]
                    zpath = fix_seg(zfull, parts_e, [clean(x) for x in zfull.replace(" / ", "/").split("/")], slug)
                    n["zh"] = zpath.split(" / ")[-1] if " / " in zpath else zpath
                    n["zhPath"] = zpath
                    changed += 1
                else:
                    miss += 1
                if n.get("children"):
                    walk(n["children"])
        for t in trees:
            if isinstance(t, dict) and "tree" in t: walk(t["tree"])
            elif isinstance(t, dict): walk([t])
            else: walk(t)

        print(f"[{slug}] 节点命中 {hit} / 未命中 {miss} / 写入 zh 变更 {changed} 修正段数 {len(FIX)}")
        if dry:
            continue
        # 备份
        bak = os.path.join(DATA, ".zh_bak_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
        os.makedirs(bak, exist_ok=True)
        shutil.copy2(tree_file, os.path.join(bak, meta["file"]))
        with open(tree_file, "w", encoding="utf-8") as fp:
            json.dump(doc, fp, ensure_ascii=False, separators=(",", ":"))
        print(f"    → 已写回 {meta['file']}（备份 {bak}）")

    # 修正表 key 有效性校验
    all_en = set()
    for f in csvs.values():
        for ep in parse_csv(f):
            for seg in ep.split("/"):
                all_en.add(clean(seg))
    for k in FIX:
        if k in all_en: fixed_keys += 1
        else: missing_keys.append(k)
    print("---")
    print(f"修正表命中真实段名: {fixed_keys}/{len(FIX)}；未命中（无害，忽略）: {len(missing_keys)}")
    if missing_keys:
        print("未命中样例:", missing_keys[:10])

if __name__ == "__main__":
    main()
