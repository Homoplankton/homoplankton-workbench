#!/usr/bin/env python3
"""LandingPage 选图预处理 v2（规则2搁置版）：
- 每张浮动元素图成品 ≥1MB；原图本就 <1MB 则原样复制、零缩减
- 灯箱用完整原图：逐字节复制到 staging，不重编码
- 检测主体框（自动阈值），用于视觉尺寸多样化
"""
import json
import os
import shutil

from PIL import Image

Image.MAX_IMAGE_PIXELS = None
LP = "/Volumes/jialingcai"  # placeholder overwritten below
LP = "/Volumes/T7/Qwen_Homoplankton/LandingPage"
ROOT = os.path.dirname(os.path.abspath(__file__))
DISP = os.path.join(ROOT, "disp")
FULL = os.path.join(ROOT, "staging_full")
MIN_B = 1024 * 1024
LADDER = [(2000, 92), (1800, 95), (1600, 95), (1400, 96), (1200, 96)]


def find_disp(src, dst):
    for edge, q in LADDER:
        with Image.open(src) as im:
            im.draft("RGB", (edge, edge))
            im = im.convert("RGB")
            w0, h0 = im.size
            if max(w0, h0) > edge:
                sc = edge / max(w0, h0)
                im = im.resize((int(w0 * sc), int(h0 * sc)), Image.LANCZOS)
            im.save(dst, "JPEG", quality=q, optimize=True, progressive=True)
        if os.path.getsize(dst) >= MIN_B:
            return im.size, os.path.getsize(dst)
    return None, None


def main():
    os.makedirs(DISP, exist_ok=True)
    os.makedirs(FULL, exist_ok=True)
    files = sorted(f for f in os.listdir(LP)
                   if not f.startswith("._") and f.lower().endswith((".jpg", ".jpeg")))
    meta = []
    copied = tiny = 0
    for i, f in enumerate(files, 1):
        src = os.path.join(LP, f)
        stem = os.path.splitext(f)[0]
        full_dst = os.path.join(FULL, f"f{i:03d}.jpg")
        shutil.copy2(src, full_dst)                    # 灯箱=逐字节原图
        box = None
        with Image.open(src) as im:
            im.draft("L", (900, 900))
            g = im.convert("L")
            g.thumbnail((900, 900))
            px = list(g.getdata())
            n = len(px)
            mean = sum(px) / n
            var = sum((p - mean) ** 2 for p in px) / n
            sd = var ** 0.5
            t = max(14, mean + 3 * sd)
            idxs = [k for k, p in enumerate(px) if p > t]
            if len(idxs) > n * 0.001:
                w, h = g.size
                xs = [k % w for k in idxs]
                ys = [k // w for k in idxs]
                xs.sort(); ys.sort()
                x0 = xs[int(len(xs) * 0.003)]; x1 = xs[int(len(xs) * 0.997)]
                y0 = ys[int(len(ys) * 0.003)]; y1 = ys[int(len(ys) * 0.997)]
                bw, bh = x1 - x0, y1 - y0
                x0 = max(0, x0 - bw * 0.06) / w
                x1 = min(w - 1, x1 + bw * 0.06) / w
                y0 = max(0, y0 - bh * 0.06) / h
                y1 = min(h - 1, y1 + bh * 0.06) / h
                box = [round(x0, 3), round(y0, 3), round(x1, 3), round(y1, 3)]
            ow, oh = im.size
        dname = f"p{i:03d}.jpg"
        dpath = os.path.join(DISP, dname)
        size = find_disp(src, dpath)
        if size[0] is None:
            shutil.copy2(src, dpath)                   # 凑不到1MB：用原图（更小就更小）
            copied += 1
            dw, dh = ow, oh
        else:
            dw, dh = size
        sz = os.path.getsize(dpath)
        meta.append({"file": f, "id": stem, "disp": dname, "w": dw, "h": dh,
                    "dbytes": sz, "full": os.path.basename(full_dst),
                    "fbytes": os.path.getsize(full_dst), "box": box,
                    "ow": ow, "oh": oh})
        if i % 15 == 0:
            print(f"  {i}/{len(files)}", flush=True)
    json.dump(meta, open(os.path.join(ROOT, "lp_meta.json"), "w"), indent=1)
    import statistics
    dbs = [m["dbytes"] for m in meta]
    fbs = [m["fbytes"] for m in meta]
    under = [m for m in meta if m["dbytes"] < MIN_B]
    print(f"\n共 {len(meta)} 张；回退用原图: {copied}；仍<1MB: {len(under)}")
    print(f"浮动图: 中位 {statistics.median(dbs)/1e6:.2f} MB, 总 {sum(dbs)/1e6:.0f} MB")
    print(f"原图:   中位 {statistics.median(fbs)/1e6:.2f} MB, 总 {sum(fbs)/1e6:.0f} MB")
    if under:
        print("仍<1MB 明细:", [(m['file'], round(m['dbytes']/1024)) for m in under])
    fx = [(m["box"][2] - m["box"][0]) for m in meta if m["box"]]
    fy = [(m["box"][3] - m["box"][1]) for m in meta if m["box"]]
    print(f"主体宽占比: 中位 {statistics.median(fx):.2f} / 最窄 {min(fx):.2f}")
    print(f"主体高占比: 中位 {statistics.median(fy):.2f} / 最高 {max(fy):.2f}")
    noBox = [m["file"] for m in meta if not m["box"]]
    print("无主体框(全暗):", len(noBox))


if __name__ == "__main__":
    main()
