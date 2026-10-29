#!/usr/bin/env python3
"""render_preview.py — S4 视觉自评门：合成真实预览图供肉眼检查。

用真实素材 + 页面实际布局坐标合成，模拟羽化遮罩与纯黑底。
仿真通过 ≠ 好看，此图必须用 Read 工具亲自看过才能交付。

用法:
  python3 render_preview.py <入口.html> <data.js> <素材目录> --out preview.png
                            [--zone top|mid|bottom|all] [--vw 1440] [--vh 900] [--seed 42]

--zone all 时输出上/中/下三段拼接图。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None


def dump_layout(entry, data, vw, vh, seed):
    """用 node 装载真实页面脚本，导出布局坐标"""
    js = r"""
const fs=require("fs"),vm=require("vm");
const [,,entry,dataPath,VWs,VHs,SEEDs,outPath]=process.argv;
const VW=+VWs,VH=+VHs;
function rng(seed){let a=seed>>>0;return()=>{a|=0;a=(a+0x6D2B79F5)|0;let t=Math.imul(a^(a>>>15),1|a);t=(t+Math.imul(t^(t>>>7),61|t))^t;return((t^(t>>>14))>>>0)/4294967296;};}
function mkEl(){const el={style:{},dataset:{},classList:{add(){},remove(){},toggle(){},contains(){return false}},addEventListener(){},appendChild(){},remove(){},querySelector(){const i=mkEl();i.dataset.image="x";return i},set src(v){},get src(){return""},set alt(v){},getContext(){return{clearRect(){},beginPath(){},arc(){},fill(){},createRadialGradient(){return{addColorStop(){}}},set fillStyle(v){}}}};Object.defineProperty(el,"innerHTML",{set(){},get(){return""}});return el;}
let fieldH=0;const field=mkEl();
Object.defineProperty(field.style,"height",{set(v){fieldH=parseFloat(v)||0},get(){return fieldH+"px"},configurable:true});
const canvas=mkEl();
const doc={getElementById:id=>id==="field"?field:canvas,createElement:mkEl};
const M=Object.create(Math);M.random=rng(+SEEDs);
const html=fs.readFileSync(entry,"utf8");
const scripts=[...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)].map(m=>m[1]);
const js=scripts[scripts.length-1];
const ctx=vm.createContext({window:{innerWidth:VW,innerHeight:VH,scrollY:0},document:doc,Math:M,JSON,Object,Array,Set,Map,String,Number,Boolean,Date,RegExp,Image:function(){return{addEventListener(){},set src(v){}}},parseFloat,parseInt,isNaN,console:{warn(){},error(){}},setTimeout:()=>0,clearTimeout(){},innerWidth:VW,innerHeight:VH,addEventListener(){},matchMedia:()=>({matches:false}),requestAnimationFrame:()=>0});
vm.runInContext(fs.readFileSync(dataPath,"utf8"),ctx);
vm.runInContext(js+"\n;globalThis.__T=tiles;globalThis.__adv=advance;",ctx);
vm.runInContext("__adv(8,0.016)",ctx);
const tiles=vm.runInContext("__T",ctx);
fs.writeFileSync(outPath,JSON.stringify({VW,VH,H:fieldH,tiles:tiles.map(t=>({id:t.id,w:t.w,h:t.h,x:t.px,y:t.py,z:1000-t.w}))}));
"""
    with tempfile.NamedTemporaryFile("w", suffix=".cjs", delete=False, encoding="utf-8") as f:
        f.write(js)
        tmp = f.name
    out = tempfile.mktemp(suffix=".json")
    try:
        r = subprocess.run(["node", tmp, entry, data, str(vw), str(vh), str(seed), out],
                           capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            print("!! 布局导出失败:\n" + r.stderr[-1500:], file=sys.stderr)
            sys.exit(2)
        return json.load(open(out))
    finally:
        for p in (tmp, out):
            if os.path.exists(p):
                os.remove(p)


def load_records(data_path):
    raw = open(data_path, encoding="utf-8").read()
    m = re.search(r"window\.(?:PLAYGROUND_DATA|BW_DATA)\s*=\s*(\{.*\}|\[.*\])\s*;?\s*$", raw.strip(), re.S)
    payload = json.loads(m.group(1))
    recs = payload["records"] if isinstance(payload, dict) else payload
    return {r["id"]: r for r in recs}


def feather(arr, w, h, ratio=0.24):
    """模拟 CSS radial mask：76% 内实心，边缘渐隐"""
    yy, xx = np.mgrid[0:h, 0:w]
    r = np.sqrt(((xx - w / 2) / (w * 0.64)) ** 2 + ((yy - h / 2) / (h * 0.64)) ** 2)
    return arr * np.clip((1.0 - r) / ratio, 0, 1)[..., None]


def render(zone, d, recs, matdir, vw, vh):
    H = d["H"]
    if zone == "top":
        y0 = 0
    elif zone == "mid":
        y0 = int(H / 2 - vh / 2)
    elif zone == "bottom":
        y0 = max(0, int(H - vh))
    else:
        y0 = 0
    sheet = Image.new("RGB", (vw, vh), (0, 0, 0))
    for t in sorted(d["tiles"], key=lambda x: x["z"]):
        if t["y"] >= y0 + vh or t["y"] + t["h"] <= y0:
            continue
        rec = recs.get(t["id"])
        if not rec:
            continue
        # 素材定位：本地目录优先按 id 找，其次用记录里的源文件名
        cand = None
        for key in (t["id"], rec.get("srcfile"), rec.get("file")):
            if not key:
                continue
            for ext in (".jpg", ".jpeg", ".png", ""):
                p = os.path.join(matdir, os.path.basename(str(key)) + ("" if ext == "" or str(key).lower().endswith(ext) else ext))
                if os.path.isfile(p):
                    cand = p
                    break
            if cand:
                break
        if not cand:
            continue
        w, h = max(1, int(t["w"])), max(1, int(t["h"]))
        try:
            im = Image.open(cand).convert("RGB").resize((w, h), Image.LANCZOS)
        except Exception:
            continue
        a = np.asarray(im).astype(np.float32)
        rgb = feather(a, w, h).astype(np.uint8)
        # alpha 由羽化半径决定：实心区不透明，边缘渐隐
        yy, xx = np.mgrid[0:h, 0:w]
        rr = np.sqrt(((xx - w / 2) / (w * 0.64)) ** 2 + ((yy - h / 2) / (h * 0.64)) ** 2)
        alpha = (np.clip((1.0 - rr) / 0.24, 0, 1) * 255).astype(np.uint8)
        sheet.paste(Image.fromarray(rgb), (int(t["x"]), int(t["y"] - y0)), Image.fromarray(alpha))
    return sheet


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("entry")
    ap.add_argument("data")
    ap.add_argument("matdir", help="本地素材目录（用于合成；页面运行时用远程URL）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--zone", default="top", choices=["top", "mid", "bottom", "all"])
    ap.add_argument("--vw", type=int, default=1440)
    ap.add_argument("--vh", type=int, default=900)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()

    for f in (a.entry, a.data):
        if not os.path.isfile(f):
            print("!! 文件不存在: " + f, file=sys.stderr)
            return 2
    if not os.path.isdir(a.matdir):
        print("!! 素材目录不存在: " + a.matdir, file=sys.stderr)
        return 2

    d = dump_layout(a.entry, a.data, a.vw, a.vh, a.seed)
    recs = load_records(a.data)
    print(f"画布高度 {d['H']:.0f}px ≈ {d['H']/a.vh:.1f} 屏，{len(d['tiles'])} 个元素")

    if a.zone == "all":
        parts = [render(z, d, recs, a.matdir, a.vw, a.vh) for z in ("top", "mid", "bottom")]
        out = Image.new("RGB", (a.vw, a.vh * 3), (0, 0, 0))
        for i, p in enumerate(parts):
            out.paste(p, (0, i * a.vh))
        out.save(a.out, quality=88)
    else:
        render(a.zone, d, recs, a.matdir, a.vw, a.vh).save(a.out, quality=88)
    print(f"✅ 预览已生成: {a.out}（{os.path.getsize(a.out)//1024} KB）")
    print("⚠️ 必须用 Read 工具亲自查看此图，确认无边框外露、无堆叠、无大片空白")
    return 0


if __name__ == "__main__":
    sys.exit(main())
