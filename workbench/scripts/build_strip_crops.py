#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_strip_crops.py — 为胶片条生成主体居中的精简裁剪并内嵌进站点

为什么不用整帧 r.src：
  整帧照片里生物处于原始构图位置（有的在左上、有的在右下、有的是横构图），
  排进一条横向带子时高低参差 → 用户看到的「很偏」。主体居中裁剪消除这个偏差。

为什么不用 assets/detail 的 1200px 裁剪：
  胶片条里单图显示高度约 34–46vh，1200px 是浪费。这里降到 640px 长边、JPEG q82，
  39 个成员约 1.5MB，base64 后约 2MB，可接受。焦点放大用 scale（同一张图放大，
  不重新请求 full-res），清晰度对「看不同角度」足够。

为什么覆盖**全部**图片，而不只是 AI 分组成员：
  用户会用「指认模式」把任意几张图声明为同一只生物。若只给现有分组成员准备裁剪，
  用户新指认的组会回退到整帧照片 → 重新出现「对不齐」。所以裁剪必须覆盖全库，
  任何新组都自带对齐的主体居中图。实测 108 张约 4MB base64，单文件仍可接受。

输出：把 window.__KIN_CROPS__ = {...} 注入站点（在挂载脚本之前）。
"""
import base64, io, json, os, re, sys
from PIL import Image

WB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DET = os.path.join(WB, "assets", "detail")
MOUNT = os.path.join(WB, "scripts", "kinship_mount.js")

# 覆盖全库：凡有 detail 裁剪的图都进 crops（用户指认出的新组也要对齐）
all_ids = {f[:-4] for f in os.listdir(DET) if f.endswith(".jpg")}
js = open(MOUNT, encoding="utf-8").read()
in_groups = set(re.findall(r'"((?:DSC|_Y3A)[^"]+)"', js))
members = all_ids
print(f"detail 裁剪总数: {len(all_ids)}  其中在 AI 分组内: {len(all_ids & in_groups)}")
print(f"本次生成覆盖: {len(members)} 张（全库）")

LONG = 640
QUAL = 82
crops = {}
missing = []
total = 0
for mid in sorted(members):
    src = os.path.join(DET, mid + ".jpg")
    if not os.path.exists(src):
        missing.append(mid); continue
    im = Image.open(src).convert("RGB")
    w, h = im.size
    sc = LONG / max(w, h)
    if sc < 1:
        im = im.resize((round(w * sc), round(h * sc)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=QUAL, optimize=True, progressive=True)
    b = buf.getvalue()
    total += len(b)
    crops[mid] = "data:image/jpeg;base64," + base64.b64encode(b).decode()

print(f"生成裁剪: {len(crops)} 张, 原始合计 {total//1024}KB, base64 约 {int(total*4/3)//1024}KB")
if missing:
    print(f"缺 detail 源（将回退整帧）: {missing}")

# 写出 crops 的 JS 片段文件，供注入脚本读取
out = os.path.join(WB, "data", "kin_crops.js")
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w", encoding="utf-8") as f:
    f.write("window.__KIN_CROPS__ = " + json.dumps(crops, ensure_ascii=False) + ";\n")
print(f"已写 {out} ({os.path.getsize(out)//1024}KB)")
