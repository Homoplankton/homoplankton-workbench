#!/usr/bin/env python3
"""
下载档案站引用的全部 CDN 图片，原样落盘（不重编码），为自托管做准备。

外链带 auth_key 签名，2026-11-24 过期。本脚本在过期前把图片取回本地，
之后页面改指本地相对路径，永不过期，且观感与定版逐字节一致。

输出：
  assets/display/<id>.jpg   显示层（页面浮动图块）
  assets/full/<id>.jpg      灯箱层（点击放大）
  assets/assets_manifest.json  id -> {src_local, full_local, src_bytes, full_bytes} 映射
"""
import argparse
import concurrent.futures as cf
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
JPEG_MAGIC = b"\xff\xd8\xff"


def parse_records(html_path: Path):
    """从档案站 HTML 中解析 PLAYGROUND_DATA 的 records。"""
    text = html_path.read_text(encoding="utf-8")
    m = re.search(r"window\.PLAYGROUND_DATA=(\{.*?\});\n", text, re.S)
    if not m:
        sys.exit("❌ 未找到 PLAYGROUND_DATA，无法解析图片记录")
    data = json.loads(m.group(1))
    recs = data.get("records") or []
    if not recs:
        sys.exit("❌ records 为空")
    return recs


def fetch(url: str, dest: Path, retries: int = 4) -> tuple[bool, int, str]:
    """下载单个 URL 到 dest。原样写字节，不重编码。"""
    last = ""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", UA)
            with urllib.request.urlopen(req, timeout=60) as resp:
                blob = resp.read()
            if len(blob) < 1024:
                last = f"体积异常过小 ({len(blob)}B)"
            elif not blob.startswith(JPEG_MAGIC):
                last = f"非 JPEG 魔数 (前3字节 {blob[:3].hex()})"
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(blob)
                return True, len(blob), ""
        except Exception as e:  # noqa: BLE001 —— 逐个重试，失败原因带回
            last = f"{type(e).__name__}: {e}"
        time.sleep(1.5 * (attempt + 1))
    return False, 0, last


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", required=True, help="档案站 HTML 路径")
    ap.add_argument("--out", required=True, help="素材输出根目录")
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()

    html_path = Path(args.html)
    out = Path(args.out)
    recs = parse_records(html_path)
    print(f"解析到 {len(recs)} 条图片记录，双层共 {len(recs) * 2} 个下载任务")

    # 组装任务：(record_id, layer, url, dest)
    tasks = []
    for r in recs:
        rid = r["id"]
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", rid)
        for layer, key in (("display", "src"), ("full", "full")):
            url = r.get(key)
            if not url:
                print(f"⚠️  {rid} 缺少 {key} 字段，跳过")
                continue
            tasks.append((rid, layer, url, out / "assets" / layer / f"{safe}.jpg"))

    manifest = {}
    failures = []
    done = 0
    t0 = time.time()

    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(fetch, url, dest): (rid, layer, dest) for rid, layer, url, dest in tasks}
        for fut in cf.as_completed(futs):
            rid, layer, dest = futs[fut]
            ok, size, err = fut.result()
            done += 1
            if ok:
                manifest.setdefault(rid, {})[layer] = {
                    "local": f"assets/{layer}/{dest.name}",
                    "bytes": size,
                }
            else:
                failures.append((rid, layer, err))
                print(f"❌ {rid} [{layer}] 失败：{err}", file=sys.stderr)
            if done % 25 == 0 or done == len(tasks):
                el = time.time() - t0
                print(f"   进度 {done}/{len(tasks)}  用时 {el:.0f}s")

    # 完整性校验：每条记录两层都必须在
    incomplete = [rid for rid, v in manifest.items() if "display" not in v or "full" not in v]
    missing_ids = [r["id"] for r in recs if r["id"] not in manifest]

    (out / "assets").mkdir(parents=True, exist_ok=True)
    (out / "assets" / "assets_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
    )

    total = sum(v["bytes"] for m in manifest.values() for v in m.values())
    print()
    print(f"✅ 成功 {len(tasks) - len(failures)}/{len(tasks)} 个文件，共 {total / 1024 / 1024:.1f}MB")
    print(f"   显示层 {sum(1 for m in manifest.values() if 'display' in m)} 张，"
          f"灯箱层 {sum(1 for m in manifest.values() if 'full' in m)} 张")
    if failures:
        print(f"❌ 失败 {len(failures)} 项：{failures[:8]}")
    if incomplete:
        print(f"❌ 双层不完整 {len(incomplete)} 条：{incomplete[:8]}")
    if missing_ids:
        print(f"❌ 完全缺失 {len(missing_ids)} 条：{missing_ids[:8]}")

    return 1 if (failures or incomplete or missing_ids) else 0


if __name__ == "__main__":
    raise SystemExit(main())
