#!/usr/bin/env python3
"""
发布前脱敏：剥离仓库内所有 CDN 签名（auth_key）。

背景：历史构建产物里保留了 11673 条带 auth_key 的签名 URL，签名有效期到
2026-11-24。仓库一旦公开，任何人都能凭这些 URL 直接下载图片，
包括作者**并未公开**的 v23（93 图）素材。这超出「公开项目」的本意。

处置：只剥掉 `?auth_key=...` 及其后续签名参数，**保留 URL 基础路径**。
理由：
  - 无签名的 URL 取不到图（服务端拒绝），泄露面归零
  - 保留路径可维持台账/历史构建的可读性与可追溯性
  - 这些链接 2026-11-24 后本就会全部失效，剥离不损失任何长期价值
  - 比整段删除 URL 破坏性更小

安全措施：
  - 只处理文本文件，二进制与图片一律跳过
  - 只在指定目录内写回，绝不触碰源项目目录、外挂硬盘原图或已部署的公开仓库
  - 处理前逐文件备份到 .redact-backup/，可完整回滚
  - 处理后复查：仓库内 auth_key 命中必须为 0
"""
import argparse
import re
import shutil
import sys
from pathlib import Path

# 匹配 ?auth_key=<epoch>-<n>-<n>-<hex> 及其后可能的 & 参数
SIG = re.compile(r"[?&]auth_key=\d+-\d+-\d+-[0-9a-fA-F]+(?:&[^\s\"'\\,)<>]*)*")
# 兜底：任何残留的 auth_key= 片段
LOOSE = re.compile(r"auth_key=[^\s\"'\\,)<>]*")

TEXT_EXT = {".html", ".js", ".json", ".tsv", ".md", ".txt", ".py", ".mjs",
            ".cjs", ".css", ".bak-origsrc", ""}


def is_text(p: Path) -> bool:
    if p.suffix.lower() in TEXT_EXT:
        return True
    # 无扩展名或未知扩展名：嗅探前 4KB 是否含 NUL
    try:
        with p.open("rb") as f:
            head = f.read(4096)
        return b"\x00" not in head
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="要脱敏的仓库根目录")
    ap.add_argument("--dry-run", action="store_true", help="只报告不写入")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"❌ 目录不存在：{root}", file=sys.stderr)
        return 2

    backup = root / ".redact-backup"
    # 必须排除本脚本自身：它内部含匹配签名的正则字面量，
    # 若一并处理会把正则本身剥掉，脚本当场失效。
    self_name = Path(__file__).resolve().name

    changed = 0
    total_sigs = 0
    skipped_bin = 0
    details = []

    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        # 不处理备份目录自身、.git 与本脚本
        rel = p.relative_to(root).as_posix()
        if rel.startswith(".redact-backup/") or rel.startswith(".git/"):
            continue
        if p.resolve().name == self_name:
            continue
        if not is_text(p):
            skipped_bin += 1
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            skipped_bin += 1
            continue

        n = len(SIG.findall(text)) + len(LOOSE.findall(SIG.sub("", text)))
        if n == 0:
            continue

        new = SIG.sub("", text)
        new = LOOSE.sub("", new)          # 兜底清理残留
        # 清理可能出现的 "?&" 或行尾孤立 "?"
        new = new.replace("?&", "?")

        total_sigs += n
        changed += 1
        details.append((rel, n))

        if not args.dry_run:
            bk = backup / rel
            bk.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, bk)
            p.write_text(new, encoding="utf-8")

    mode = "（试运行，未写入）" if args.dry_run else ""
    print(f"{mode}脱敏范围：{root}")
    print(f"改动文件 {changed} 个，剥离签名 {total_sigs} 条，跳过二进制 {skipped_bin} 个")
    for rel, n in details[:15]:
        print(f"   {n:>6} 条  {rel}")
    if len(details) > 15:
        print(f"   …… 其余 {len(details) - 15} 个文件")

    if args.dry_run:
        return 0

    # 复查：仓库内不得残留任何 auth_key（本脚本自身含正则字面量，须排除）
    residue = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if rel.startswith(".redact-backup/") or rel.startswith(".git/"):
            continue
        if p.resolve().name == self_name:
            continue
        if not is_text(p):
            continue
        try:
            if "auth_key=" in p.read_text(encoding="utf-8", errors="ignore"):
                residue.append(rel)
        except Exception:
            pass

    if residue:
        print(f"❌ 仍残留 {len(residue)} 个文件含 auth_key：{residue[:6]}", file=sys.stderr)
        return 1
    print(f"✅ 复查通过：仓库内 auth_key 残留 0 处")
    print(f"   原件备份于 {backup}（确认无误后可删除）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
