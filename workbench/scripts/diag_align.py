#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""diag_align.py — 诊断胶片条「对不齐」的根因，并核查裁剪素材可用性。

假设：条带显示的是 r.src（整帧照片，生物处于黑框中的原始位置），
不是主体居中的裁剪，所以不同图的生物高低位置不一致 → 看起来「很偏」。
需要验证：(1) 主体框在原图中的位置分布；(2) detail 裁剪素材是否齐全。
"""
import json, os, glob
from PIL import Image

WB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DER = os.path.join(WB, "assets", "derived.json")
DET = os.path.join(WB, "assets", "detail")

derived = json.load(open(DER, encoding="utf-8"))

K3 = ["DSC_1010", "DSC_1011", "DSC_1060", "DSC_1062"]
K1 = ["DSC_0214", "DSC_0242", "DSC_0361", "DSC_1540", "DSC_26982020"]

# derived.json 结构探测
sample_key = next(iter(derived)) if isinstance(derived, dict) else None
print("derived.json 顶层类型:", type(derived).__name__)
if isinstance(derived, dict):
    print("键样例:", list(derived.keys())[:3])
    first = derived[sample_key]
    print("单条结构:", json.dumps(first, ensure_ascii=False)[:400] if isinstance(first, (dict, list)) else first)
elif isinstance(derived, list):
    print("条数:", len(derived))
    print("单条结构:", json.dumps(derived[0], ensure_ascii=False)[:400])

def look(ids, tag):
    print(f"\n===== {tag} 主体框位置（归一化 y 中心 / 高度占比）=====")
    for i in ids:
        rec = None
        if isinstance(derived, dict):
            rec = derived.get(i)
        else:
            rec = next((r for r in derived if r.get("id") == i), None)
        if not rec:
            print(f"  {i}: 无 derived 记录"); continue
        box = rec.get("subject_box") or rec.get("box") or rec.get("bbox")
        img = rec.get("img") or rec.get("orig") or {}
        W = (img.get("w") if isinstance(img, dict) else None) or rec.get("W") or rec.get("width")
        H = (img.get("h") if isinstance(img, dict) else None) or rec.get("H") or rec.get("height")
        print(f"  {i}: box={box}  W×H={W}×{H}  keys={list(rec.keys())}")

look(K3, "K3 红胸樱虾")
look(K1, "K1 透明八腕")

# detail 裁剪素材核查
print("\n===== detail 裁剪素材 =====")
det_files = {os.path.basename(p).rsplit(".", 1)[0]: p for p in glob.glob(os.path.join(DET, "*"))}
print("detail 目录文件数:", len(det_files))
for i in K3 + K1:
    p = det_files.get(i)
    if p and os.path.exists(p):
        im = Image.open(p)
        print(f"  {i}: 裁剪存在 {im.size}  {os.path.getsize(p)//1024}KB")
    else:
        print(f"  {i}: 无裁剪文件")
