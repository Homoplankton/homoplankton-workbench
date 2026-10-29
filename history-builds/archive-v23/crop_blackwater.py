#!/usr/bin/env python3
"""不对称裁切：逐边裁掉黑边，主体四周留 15% 安全边距（按主体自身尺寸计）。
源：/Volumes/T7/Qwen_Homoplankton/LandingPage 原图
出：/Volumes/T7/Qwen_Homoplankton/LandingPageCropped/{id}.jpg（≤900px 长边）
box 无数据的（全暗帧）不裁，直接按原图缩样输出。
"""
import json
import os
import re

from PIL import Image

Image.MAX_IMAGE_PIXELS = None
LP = "/Volumes/T7/Qwen_Homoplankton/LandingPage"
OUT = "/Volumes/T7/Qwen_Homoplankton/LandingPageCropped"
BASE = os.path.dirname(os.path.abspath(__file__))
PAD = 0.15          # 每边留主体该向尺寸的 15%

meta = json.load(open(os.path.join(BASE, "lp_meta.json")))
# box 数据从 assets/data.js 解析
raw = open(os.path.join(BASE, "assets", "data.js")).read()
arr = json.loads(raw[raw.index("=") + 1:].rstrip().rstrip(";"))
box_by_id = {d["id"]: d.get("box") for d in arr}
meta_by_id = {m["id"]: m for m in meta}

os.makedirs(OUT, exist_ok=True)
out_meta = {}
n_crop = n_skip = 0
tot = 0
for i, m in enumerate(meta):
    src = os.path.join(LP, m["file"])
    if not os.path.isfile(src):
        print("缺源:", m["file"]); continue
    ident = m["id"]
    box = box_by_id.get(ident)
    with Image.open(src) as im:
        im = im.convert("RGB")
        W0, H0 = im.size
        if box:
            x0, y0, x1, y1 = box
            sx0, sy0, sx1, sy1 = x0 * W0, y0 * H0, x1 * W0, y1 * H0
            sw, sh = sx1 - sx0, sy1 - sy0
            mx, my = sw * PAD, sh * PAD
            cx0 = max(0, int(round(sx0 - mx))); cy0 = max(0, int(round(sy0 - my)))
            cx1 = min(W0, int(round(sx1 + mx))); cy1 = min(H0, int(round(sy1 + my)))
            cw, ch = cx1 - cx0, cy1 - cy0
            im2 = im.crop((cx0, cy0, cx1, cy1))
            n_crop += 1
            new_box = [round((sx0 - mx - cx0) / cw, 4) if sx0 - mx > cx0 else 0.0,
                       round((sy0 - my - cy0) / ch, 4) if sy0 - my > cy0 else 0.0,
                       round((sx1 + mx - cx0) / cw, 4) if sx1 + mx < cx1 else 1.0,
                       round((sy1 + my - cy0) / ch, 4) if sy1 + my < cy1 else 1.0]
            new_box = [min(max(v, 0.0), 1.0) for v in new_box]
            # 主体占比记录，供密度报告
            fill = (new_box[2]-new_box[0]) * (new_box[3]-new_box[1])
        else:
            im2 = im; new_box = None; fill = None
            n_skip += 1
        long_side = max(im2.size)
        if long_side > 900:
            sc = 900 / long_side
            im2 = im2.resize((max(1, int(im2.size[0] * sc)), max(1, int(im2.size[1] * sc))), Image.LANCZOS)
        dst = os.path.join(OUT, ident + ".jpg")
        im2.save(dst, "JPEG", quality=87, optimize=True, progressive=True)
    sz = os.path.getsize(dst)
    tot += sz
    out_meta[ident] = {"w": im2.size[0], "h": im2.size[1], "box": new_box,
                       "bytes": sz, "srcfile": m["file"], "fill": None if fill is None else round(fill, 3)}
    if (i + 1) % 30 == 0:
        print(f"  {i+1}/{len(meta)}", flush=True)

json.dump(out_meta, open(os.path.join(BASE, "crop_meta.json"), "w"), indent=1)
fills = [v["fill"] for v in out_meta.values() if v["fill"]]
import statistics
print(f"\n裁切 {n_crop}，未裁(全暗) {n_skip}；总计 {tot/1e6:.1f} MB，平均 {tot/len(out_meta)/1024:.0f} KB")
print(f"主体占裁后画面比例: 中位 {statistics.median(fills):.2f}" if fills else "无")
ar = [v["w"] / v["h"] for v in out_meta.values()]
print(f"裁后纵横比范围: {min(ar):.2f}–{max(ar):.2f}（方/矩形混合，无固定比例）")
