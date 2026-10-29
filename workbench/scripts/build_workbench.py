#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_workbench.py — 把 claims.json + 本地图层组装成单文件工作台

体积策略（实测预算，2026-10-27 用户要求检查器显示完整图后调整）
-----------------------------------------------------------------
thumb  108 张  877 KB → base64 ≈ 1.2 MB   ⇒ 内嵌（网格）
full   108 张  5.9 MB → base64 ≈ 8.0 MB   ⇒ 内嵌（检查器，**整帧**长边 1200）
claims.json    515 KB                     ⇒ 内嵌
单文件约 9.7 MB。

为什么内嵌 full 而不是 detail：
  detail 是**主体裁剪**（比例 0.796 ≠ 原图 0.667），用户反馈检查器「严重裁切」。
  full 是整帧（比例 == 原图），压缩但保留完整画面——正是用户要的「as it is」。
  且 full(8MB) 比 detail(15MB) 更小，体积与观感双赢。
  detail 层仍保留在 assets/ 供其他用途（如生长序列工具），但不再进工作台。

三层素材语义（勿混用）：
  thumb  = 整帧缩略（网格，400px 长边）
  full   = 整帧中图（检查器，1200px 长边）← 检查器默认用这层
  detail = 主体裁剪（1200px 长边）        ← 仅历史/他工具使用，工作台不用

为什么用模板令牌而不是 f-string
-------------------------------
前端 CSS/JS 里有大量 { }，用 Python f-string 需要把每个花括号写成 {{ }}，
极易漏且报错信息难懂。这里改为读 template.html 并替换 /*@PAYLOAD@*/ 令牌。

⚠ JSON 注入 script 的安全处理：把 </ 转义为 <\\/，避免数据里出现 </script>
提前闭合标签（XSS / 解析中断）。
"""

import base64
import json
import os
import sys

WB = "/Users/jialingcai/Documents/qwen-agent/NZKKxizmz2/default/plankton-workbench"
CLAIMS = os.path.join(WB, "data", "claims.json")
TEMPLATE = os.path.join(WB, "template.html")
OUT = os.path.join(WB, "workbench.html")
TOKEN = "/*@PAYLOAD@*/"

THUMB_DIR = os.path.join(WB, "assets", "thumb")
FULL_DIR = os.path.join(WB, "assets", "full")


def embed(db, dirpath, field, label):
    n = miss = 0
    for im in db["images"]:
        iid = im["image_id"]
        p = os.path.join(dirpath, iid + ".jpg")
        if os.path.isfile(p):
            with open(p, "rb") as f:
                im[field] = "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()
            n += 1
        else:
            miss += 1
    print(f"[embed] {label}: {n} 张内嵌，缺失 {miss}")
    return n, miss


def main():
    for p, why in ((CLAIMS, "claim 数据库"), (TEMPLATE, "前端模板")):
        if not os.path.exists(p):
            sys.exit(f"ERROR: 找不到{why}：{p}")

    db = json.load(open(CLAIMS, encoding="utf-8"))
    tpl = open(TEMPLATE, encoding="utf-8").read()
    if TOKEN not in tpl:
        sys.exit(f"ERROR: 模板缺少令牌 {TOKEN}")

    tn, tm = embed(db, THUMB_DIR, "thumbData", "网格缩略图(thumb/整帧400px)")
    fn, fm = embed(db, FULL_DIR, "fullData", "检查器整帧(full/整帧1200px)")
    if tm or fm:
        print(f"  ⚠ 有缺失：thumb {tm} / full {fm}；前端会逐级回退 full→thumb")

    db["asset_note"] = (
        "thumb 与 full 均为整帧（比例==原图），已内嵌 base64，单文件自包含。"
        "full 供检查器完整展示；detail(主体裁剪)不内嵌、不使用——"
        "用户 2026-10-27 要求检查器显示完整图而非裁剪。")

    payload = json.dumps(db, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("</", "<\\/")
    payload = payload.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")

    html = tpl.replace(TOKEN, payload)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)

    sz = os.path.getsize(OUT)
    print(f"[out] {OUT}  {sz / 1024 / 1024:.2f} MB")
    print(f"      断言 {sum(len(i['claims']) for i in db['images'])} 条 · "
          f"文献 {len(db['references'])} 条 · 修正链 {len(db.get('revision_log', []))} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
