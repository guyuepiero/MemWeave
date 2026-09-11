"""WeChatVaultServer - 图标生成（公众号/微信绿主题）
Usage: python tools/make_icon.py
Output: ../appicon.png + ../appicon.ico (multi-size, 覆盖原文件前请手动备份)
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent  # WeChatVaultServer/
S = 256


def _font(size: int):
    """粗体字体（系统字体，零外链）。"""
    for name in ("arialbd.ttf", "seguisb.ttf", "calibrib.ttf"):
        try:
            return ImageFont.truetype(f"C:/Windows/Fonts/{name}", size)
        except Exception:
            continue
    return ImageFont.load_default()


def build() -> None:
    # 1) 微信绿对角渐变底（左上亮 #2BC57A → 右下深 #06AD56）
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    for y in range(S):
        for x in range(S):
            k = (x + y) / (2 * S)
            r = int(0x2B + (0x06 - 0x2B) * k)
            g = int(0xC5 + (0xAD - 0xC5) * k)
            b = int(0x7A + (0x56 - 0x7A) * k)
            img.putpixel((x, y), (r, g, b, 255))
    # 圆角遮罩
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=52, fill=255)
    img.putalpha(mask)

    d = ImageDraw.Draw(img)

    # 2) 中央白色对话气泡（圆角矩形 + 右下尾巴，朝右表示公众号推送）
    bx0, by0, bx1, by1 = 38, 96, 218, 200
    d.rounded_rectangle([bx0, by0, bx1, by1], radius=22, fill=(255, 255, 255, 255))
    # 尾巴：右下三角（贴气泡底边、向右下延伸，公众号消息气泡形态）
    d.polygon(
        [(bx1 - 56, by1 - 1), (bx1 - 28, by1 - 1), (bx1 - 52, by1 + 18)],
        fill=(255, 255, 255, 255),
    )

    # 3) 气泡内"公众号文章卡片"线条：1 条标题（粗绿）+ 3 条摘要（细浅绿）
    # 标题（粗、深绿）
    d.rounded_rectangle(
        [bx0 + 22, by0 + 22, bx0 + 148, by0 + 22 + 12],
        radius=5, fill=(0x07, 0xC1, 0x60, 255),
    )
    # 摘要 1
    d.rounded_rectangle(
        [bx0 + 22, by0 + 44, bx0 + 170, by0 + 44 + 6],
        radius=2, fill=(0xA8, 0xDC, 0xB7, 255),
    )
    # 摘要 2
    d.rounded_rectangle(
        [bx0 + 22, by0 + 58, bx0 + 148, by0 + 58 + 6],
        radius=2, fill=(0xA8, 0xDC, 0xB7, 255),
    )
    # 摘要 3
    d.rounded_rectangle(
        [bx0 + 22, by0 + 72, bx0 + 166, by0 + 72 + 6],
        radius=2, fill=(0xA8, 0xDC, 0xB7, 255),
    )

    # 4) 右上角"推送通知"小圆点（浅绿底 + 深绿心，呼应公众号推送）
    d.ellipse([218, 22, 238, 42], fill=(0xFF, 0xFF, 0xFF, 200))
    d.ellipse([224, 28, 232, 36], fill=(0x06, 0xAD, 0x56, 255))

    # 输出
    OUT.mkdir(exist_ok=True)
    img.save(OUT / "appicon.png")
    img.save(
        OUT / "appicon.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print("OK ->", OUT / "appicon.png", OUT / "appicon.ico")


if __name__ == "__main__":
    build()