# -*- coding: utf-8 -*-
"""克隆微信工作台已验证可显示图标的 .lnk 结构，生成亚马逊工作台桌面快捷方式。

根因复盘：此前手写 .lnk 缺 PIDL（LinkTargetIDList）段，explorer 解析带图标
快捷方式时依赖该段，缺失导致图标无法显示（虽然 IconLocation 字段写对了）。

方案：以桌面「微文收纳.lnk」（1856字节、图标显示正常）为模板，克隆其完整
二进制结构（含 PIDL 段），仅替换 RelativePath / WorkingDir / IconLocation 三个
字符串为亚马逊工作台的目标路径。字节级保真，零 COM 依赖。
"""
import struct
from pathlib import Path

TEMPLATE = Path(r"C:\Users\guyuepiero\Desktop\微文收纳.lnk")
DEST = Path.home() / "Desktop" / "亚马逊运营工作台.lnk"

SERVER = r"C:\Users\guyuepiero\Documents\MemWeave v1.0\04_PROJECTS\AmazonOpsMonitor\CODE\server"
TARGET_REL = r"..\..\..\..\..\..\Documents\MemWeave v1.0\04_PROJECTS\AmazonOpsMonitor\CODE\server\tray.py"
WORKDIR = SERVER
ICON = SERVER + r"\appicon.ico"


def _read_string(data: bytes, pos: int, enc: str) -> tuple[str, int]:
    cnt = struct.unpack_from("<H", data, pos)[0]
    pos += 2
    raw = data[pos:pos + cnt * 2]
    pos += cnt * 2 + 2
    return raw.decode(enc, "replace"), pos


def clone() -> bytes:
    data = TEMPLATE.read_bytes()
    flags = struct.unpack_from("<I", data, 0x14)[0]
    enc = "utf-16-le" if flags & 0x80 else "gbk"

    # 定位 StringData 起始
    pos = 0x4C
    if flags & 1:  # PIDL
        idl = struct.unpack_from("<H", data, pos)[0]
        pos += 2 + idl
    if flags & 2:  # LinkInfo
        li = struct.unpack_from("<I", data, pos)[0]
        pos += li

    string_start = pos
    parts = []  # (start_offset, end_offset, new_value_or_None)
    for lab, bit in [("Name", 0x4), ("RelativePath", 0x8), ("WorkingDir", 0x10),
                     ("Arguments", 0x20), ("IconLocation", 0x40)]:
        if flags & bit:
            s = pos
            cnt = struct.unpack_from("<H", data, pos)[0]
            pos += 2 + cnt * 2 + 2
            val, _ = _read_string(data, s, enc)
            newval = None
            if lab == "RelativePath":
                newval = TARGET_REL
            elif lab == "WorkingDir":
                newval = WORKDIR
            elif lab == "IconLocation":
                newval = ICON
            parts.append((lab, s, pos, val, newval))
            print(f"  [模板] {lab:13s} = {val!r}  ->  替换为 {newval!r}" if newval else f"  [保留] {lab:13s} = {val!r}")

    # 逐段替换：新值长度可能不同，需重排字节
    # 先按偏移从后往前替换，保持前面偏移不变
    out = bytearray(data)
    # 计算每个待替换段的旧长度和新编码
    edits = []  # (start, end, new_bytes)
    for lab, s, e, old, newval in parts:
        if newval is not None:
            nb = struct.pack("<H", len(newval)) + newval.encode("utf-16-le") + b"\x00\x00"
            edits.append((s, e, nb))
    # 从后往前替换
    edits.sort(key=lambda x: -x[0])
    for s, e, nb in edits:
        out[s:e] = nb
        # 后续所有 edit 的偏移不变（因为从后往前，前面的已处理过的不受影响）
    return bytes(out)


def verify(data: bytes) -> None:
    flags = struct.unpack_from("<I", data, 0x14)[0]
    pos = 0x4C
    if flags & 1:
        idl = struct.unpack_from("<H", data, pos)[0]
        pos += 2 + idl
    if flags & 2:
        li = struct.unpack_from("<I", data, pos)[0]
        pos += li
    enc = "utf-16-le" if flags & 0x80 else "gbk"
    print("\n--- 生成结果验证 ---")
    print("总大小:", len(data), "字节 | HasIDList=%d" % bool(flags & 1))
    for lab, bit in [("Name", 0x4), ("RelativePath", 0x8), ("WorkingDir", 0x10),
                     ("Arguments", 0x20), ("IconLocation", 0x40)]:
        if flags & bit:
            cnt = struct.unpack_from("<H", data, pos)[0]
            pos += 2
            raw = data[pos:pos + cnt * 2]
            pos += cnt * 2 + 2
            print(f"  {lab:13s} = {raw.decode(enc, 'replace')}")


def main() -> None:
    print("克隆模板:", TEMPLATE)
    data = clone()
    DEST.write_bytes(data)
    verify(data)
    print(f"\nwritten: {DEST} ({len(data)} bytes)")


if __name__ == "__main__":
    main()
