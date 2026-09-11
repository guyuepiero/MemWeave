# -*- coding: utf-8 -*-
"""生成 亚马逊运营监控台 应用图标 appicon.ico / appicon.png（Amazon 风格）。

设计（贴合 Amazon 品牌意象，非商标复制）：
- 深蓝黑圆角底（#232F3E Amazon 深色系，微渐变上亮下暗）
- 中央白色粗体 "A"（运营工作台 = 字母 A 之上/之下的监控意象）
- 底部橙色微笑弧线（#FF9900 Amazon 橙），从 A 左侧下方扫过、右端上挑成箭头
  —— 呼应 Amazon logo "a→z" 的经典微笑箭头，传达「全链路、向上」感

输出：server 根目录 appicon.png(256) + appicon.ico(16/24/32/48/64/128/256)
"""
from pathlib import Path

import struct

from PIL import Image, ImageDraw, ImageFont

S = 256
OUT = Path(__file__).resolve().parent.parent  # CODE/server

# ---------- 字体 ----------
_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\arial.ttf",
]


def _font(size: int) -> ImageFont.FreeTypeFont:
    for p in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


# ---------- 贝塞尔曲线采样 ----------
def _bezier(p0, p1, p2, n=90):
    pts = []
    for i in range(n + 1):
        t = i / n
        x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t ** 2 * p2[0]
        y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t ** 2 * p2[1]
        pts.append((x, y))
    return pts


def _draw_smile(d: ImageDraw.ImageDraw) -> None:
    """橙色微笑弧线 + 右端上挑箭头（Amazon 橙 #FF9900）。"""
    orange = (0xFF, 0x99, 0x00, 255)
    # 弧线：左下 → 中间微沉 → 右上（视觉从 A 下方穿过）
    arc = _bezier((34, 178), (128, 208), (196, 128))
    d.line(arc, fill=orange, width=15, joint="curve")
    # 端头圆盖
    d.ellipse([27, 171, 41, 185], fill=orange)
    # 右端箭头（上挑 45° 实心三角，顶点 ≈ (238, 84)）
    tip = (232, 80)
    d.polygon([tip, (182, 96), (202, 128)], fill=orange)
    # 箭头根端圆滑：补一个小圆
    d.ellipse([176, 90, 194, 108], fill=orange)


def _bmp_block(img: Image.Image) -> bytes:
    """将 RGBA 图编码为 ICO 内的 32bpp DIB 块（bottom-up BGRA + 全 0 AND 掩码）。

    explorer 对 ICO 中小尺寸的 PNG 压缩块支持不稳定（会出现空白图标），
    因此 ≤64px 一律用未压缩 BMP/DIB 块，仅 128/256 用 PNG 块。
    """
    w, h = img.size
    pixels = img.load()
    xor = bytearray()
    # DIB 像素自下而上
    for y in range(h - 1, -1, -1):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            xor += bytes((b, g, r, a))
    and_row = ((w + 31) // 32) * 4  # 每行按 4 字节对齐
    and_mask = b"\x00" * (and_row * h)
    header = struct.pack(
        "<IiiHHIIiiII",
        40, w, h * 2, 1, 32, 0, w * h * 4, 0, 0, 0, 0,
    )
    return header + bytes(xor) + and_mask


def _png_block(img: Image.Image) -> bytes:
    import io

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _write_mixed_ico(img: Image.Image, path: Path) -> None:
    """混合 ICO：16/24/32/48/64 用 BMP 块，128/256 用 PNG 块（最兼容）。"""
    import struct

    entries = []  # (w, data, is_png)
    for size in (16, 24, 32, 48, 64):
        entries.append((size, _bmp_block(img.resize((size, size), Image.LANCZOS)), False))
    for size in (128, 256):
        entries.append((size, _png_block(img.resize((size, size), Image.LANCZOS)), True))

    count = len(entries)
    header = struct.pack("<HHH", 0, 1, count)
    offset = 6 + 16 * count
    out = bytearray(header)
    for w, data, is_png in entries:
        out += struct.pack(
            "<BBBBHHII",
            w if w < 256 else 0,
            w if w < 256 else 0,
            0, 0, 1, 32, len(data), offset,
        )
        offset += len(data)
    for _, data, _ in entries:
        out += data
    path.write_bytes(bytes(out))


def build() -> None:
    # 1) 渐变底（256 逐行：上亮 #2E3D4F → 下暗 #18222E）
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    for y in range(S):
        k = y / S
        r = int(0x2E + (0x18 - 0x2E) * k)
        g = int(0x3D + (0x22 - 0x3D) * k)
        b = int(0x4F + (0x2E - 0x4F) * k)
        for x in range(S):
            img.putpixel((x, y), (r, g, b, 255))
    # 圆角遮罩
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=52, fill=255)
    img.putalpha(mask)

    d = ImageDraw.Draw(img)

    # 2) 中央白色粗体 A（占上部偏中，留出下方弧线空间）
    fnt = _font(150)
    txt = "A"
    bb = d.textbbox((0, 0), txt, font=fnt)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    tx = (S - tw) / 2 - bb[0] + 4
    ty = (S - th) / 2 - bb[1] - 26  # 整体略上移
    d.text((tx, ty), txt, font=fnt, fill=(0xFF, 0xFF, 0xFF, 255))

    # 3) 橙色微笑箭头（压住 A 底部、向右上挑出）
    _draw_smile(d)

    # 4) 顶部细条：右侧一枚小"信号圆点+弧"表示监控（低调，不抢 A）
    d.arc([176, 20, 216, 60], start=200, end=340, fill=(0xFF, 0x99, 0x00, 200), width=5)
    d.ellipse([204, 14, 220, 30], fill=(0xFF, 0x99, 0x00, 220))

    # 输出 —— 关键经验：ICO 一律用 Pillow 默认 PNG 块格式
    # （微文收纳 WeChatVaultServer/appicon.ico 同款全 PNG 结构，explorer 显示正常；
    #  手写 BMP/DIB 块反而会被 explorer 解析失败显示空白，禁止使用）
    OUT.mkdir(exist_ok=True)
    img.save(OUT / "appicon.png")
    img.save(
        OUT / "appicon.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print("OK ->", OUT / "appicon.png", OUT / "appicon.ico")


if __name__ == "__main__":
    build()
