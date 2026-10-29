#!/usr/bin/env python3
"""select_and_crop.py — 生长发育序列实验：选样 + 从原图裁切主体放大图。

为什么从原图裁而不是用显示层：
  显示层长边仅 1500px，而诊断特征（蟹 zoea 的腹肢芽与刺式、螺 veliger 的原壳螺层数、
  头足类腕吸盘列数）是亚毫米级细节。早前用 560px 缩略图曾把船蛸误判为鱼类（门级错误）。
  原图长边可达 7000px，裁切主体区域后放大，才能支撑到属/种级鉴定与分期判断。

选样策略（无分类信息可用，故用形态代理做分层抽样）：
  按 EXIF 拍摄日期分 5 组（不同航次≈不同群落），组内按纵横比 h/w 取两端各一张，
  共 10 张。纵横比与主体占比是体型差异的弱代理，但比随机抽样更可能覆盖不同类群。

box 为归一化坐标 [x0,y0,x1,y1]，与分辨率无关，可直接映射到原图尺寸。
box 为 null（全暗帧）时退回整帧缩放。
"""
import json
import os
import sys
from collections import defaultdict

from PIL import Image, ImageOps

DATA = "/Users/jialingcai/Documents/qwen-agent/NZKKxizmz2/default/planktontest-v31-run108/assets/data.js"
SRC = "/Volumes/T7/Qwen_Homoplankton/PlanktonTest"
OUT = "/Users/jialingcai/Documents/qwen-agent/NZKKxizmz2/default/growthseq-exp/crops"
CROP_LONG = 1100          # 裁切图长边
MARGIN = 0.18             # 主体框外扩比例，避免切掉附肢

os.makedirs(OUT, exist_ok=True)


def load_records(path):
    raw = open(path, encoding="utf-8").read()
    i = raw.find("window.PLAYGROUND_DATA")
    eq = raw.find("=", i)
    pl, _ = json.JSONDecoder().raw_decode(raw[eq + 1:].lstrip())
    return pl["records"]


def pick(recs, n_per_date=2):
    by_date = defaultdict(list)
    for r in recs:
        dt = (r.get("attrs") or {}).get("DateTime", "?")[:10]
        by_date[dt].append(r)
    picked = []
    for dt in sorted(by_date):
        g = sorted(by_date[dt], key=lambda r: r["h"] / max(r["w"], 1))
        n = len(g)
        if n < 2:
            picked.append(g[0])
            continue
        # 取纵横比两端各一张，最大化形态差异
        idxs = [int(n * 0.12), int(n * 0.88)]
        seen = set()
        for k in idxs:
            k = max(0, min(k, n - 1))
            if k not in seen:
                seen.add(k)
                picked.append(g[k])
        if len(picked) >= len(recs):
            break
    return picked[:10]


def crop_subject(rec, dst):
    rid = rec["id"]
    src = os.path.join(SRC, rid + ".jpg")
    if not os.path.isfile(src):
        for ext in (".JPG", ".jpeg", ".png"):
            alt = os.path.join(SRC, rid + ext)
            if os.path.isfile(alt):
                src = alt
                break
        else:
            return None, "源文件缺失"
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)          # 尊重 EXIF 方向，避免裁错区域
        im = im.convert("RGB")
        W, H = im.size
        box = rec.get("box")
        if box and len(box) == 4:
            x0, y0, x1, y1 = box
            bw, bh = (x1 - x0) * W, (y1 - y0) * H
            mx, my = bw * MARGIN, bh * MARGIN
            L = max(0, int((x0 * W) - mx))
            T = max(0, int((y0 * H) - my))
            R = min(W, int((x1 * W) + mx))
            B = min(H, int((y1 * H) + my))
            if R - L < 8 or B - T < 8:
                L, T, R, B = 0, 0, W, H
            im2 = im.crop((L, T, R, B))
            mode = "crop"
        else:
            im2 = im
            mode = "full(box=null)"
        sc = CROP_LONG / max(im2.size)
        if sc < 1:
            im2 = im2.resize((max(1, int(im2.size[0] * sc)), max(1, int(im2.size[1] * sc))), Image.LANCZOS)
        im2.save(dst, "JPEG", quality=94, optimize=True, progressive=True)
        return (mode, im.size, im2.size, os.path.getsize(dst)), None


def main():
    recs = load_records(DATA)
    print(f"数据记录: {len(recs)} 条")
    picked = pick(recs)
    print(f"选样: {len(picked)} 张（按拍摄日期分层 × 纵横比两端）\n")
    print(f"{'#':>2} {'id':<26} {'日期':<11} {'相机':<22} {'原图w×h':<12} {'纵横比':>6} {'主体占比':>8} {'裁切':<14} {'输出KB':>7}")
    manifest = []
    for k, r in enumerate(picked, 1):
        rid = r["id"]
        dst = os.path.join(OUT, f"s{k:02d}_{rid}.jpg")
        info, err = crop_subject(r, dst)
        dt = (r.get("attrs") or {}).get("DateTime", "?")[:10]
        cam = (r.get("attrs") or {}).get("Model", "?")[:20]
        ar = r["h"] / max(r["w"], 1)
        box = r.get("box")
        frac = ((box[2] - box[0]) * (box[3] - box[1])) if box else None
        if err:
            print(f"{k:>2} {rid:<26} {dt:<11} {cam:<22} {'—':<12} {ar:>6.2f} "
                  f"{(f'{frac:.2f}' if frac is not None else 'null'):>8} {err:<14} {'—':>7}")
            continue
        mode, orig, outsz, nb = info
        print(f"{k:>2} {rid:<26} {dt:<11} {cam:<22} {str(orig[0])+'×'+str(orig[1]):<12} {ar:>6.2f} "
              f"{(f'{frac:.2f}' if frac is not None else 'null'):>8} {mode+' '+str(outsz[0])+'×'+str(outsz[1]):<14} {nb//1024:>7}")
        manifest.append({"n": k, "id": rid, "date": dt, "camera": cam,
                         "orig": list(orig), "aspect": round(ar, 3),
                         "box": box, "box_frac": round(frac, 3) if frac is not None else None,
                         "crop": os.path.basename(dst), "crop_size": list(outsz),
                         "src_w": r["w"], "src_h": r["h"],
                         "src_url": r["src"]})
    out_json = os.path.join(os.path.dirname(OUT), "sample_manifest.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    print(f"\n清单已写: {out_json}")
    print(f"裁切图目录: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
