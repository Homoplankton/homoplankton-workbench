# SOP —— 六阶段详细步骤

## S0 需求锁定

一轮 `AskUserQuestion` 问全（≤4 个问题，按返工代价排序）：

1. 图片文件夹路径（找不到先定位，不猜）
2. 是否已人工筛选（决定 S1.0）
3. 重叠口径：图框零相交（默认）/ 主体不重叠（羽化暗边可叠，需告知露框风险）
4. 视觉参数是否沿用 v23 默认（尺寸带 / 禁飞区 / 密度 / 素材策略）

**规模闸门**：>200 张时先报告 `张数 × 单张均值` 的上传体积、耗时量级、首屏并发数，等用户决定。

## S0.1 环境探测（一次做完，之后固定复用）

素材脚本依赖 **PIL + numpy**，宿主把它们放在独立包集合里。开工第一件事就是把环境探明并**记下结论**，不要每步重猜（见 lessons #12：反复试探解释器吃掉了大量时间）。

```bash
# 找出同时具备 PIL 与 numpy 的包集合
for d in "<qw>/resources/packages/pip/local/sets/"*/; do
  libs=$(ls "$d" 2>/dev/null | grep -E '^(numpy|PIL)$' | tr '\n' ',')
  [ -n "$libs" ] && echo "$(basename "$d")  [$libs]"
done
```

选定后用 `PYTHONPATH=<该集合> <运行时解释器>` 调用所有 python 脚本。本机实测可用组合：

```
PY="<qw>/resources/runtimes/python/3.14.6/bin/python3"
S="<qw>/resources/packages/pip/local/sets/93d8ccef52e9fb999777d713facae11c"   # PIL 12.3.0 / numpy 2.5.3
PYTHONPATH="$S" "$PY" scripts/prep_assets.py ...
```

（`<qw>` = qwen-agent 根目录；集合哈希随环境变化，**以探测结果为准**，不要照抄。）

铁律：
- **不要为了绕开缺依赖而手写替代脚本。** 绕过版会静默丢掉主体框检测、文件名与记录的排序一致性等既有保证。缺依赖就修环境。
- `/usr/bin/python3` 常有 PIL 但无 numpy，只能用于不含 numpy 的轻量操作；正式素材生成一律用探测出的组合。
- 确实要手写替代时，**必须逐条验证一一对应**：id 序列 == 源文件名序列、宽高比逐张比对，不能只抽样看前三条。

## S1 素材准备

### S1.0 背景筛选（可选）

```bash
python3 scripts/screen_blackwater.py <文件夹> --out screen_result.json
```

原理：四周 8% 条带的近黑占比（edge_dark）+ 大面积饱和亮色占比（sat_lit）双指标分层：
- `edge_dark ≥ 0.85` → 明确黑水
- `sat_lit ≥ 0.15 且 whole_dark < 0.30` → 明确非黑水（礁石/珊瑚/蓝绿水体）
- `lit ≥ 0.80 且 edge_dark < 0.30` → 明确非黑水（浅水/船面/沙地）
- 其余 → **灰带，必须逐张拼图人工判定**

灰带判定要点（历史踩坑）：白天打光压暗背景的微距照（红蛙鱼、红珊瑚、管子鱼洞穴）像素上很像黑水，只能靠看到"人为器物/底材/礁石纹理"剔除；采样杯记录照按用户口径处理。

输出剔除清单给用户过目，不静默丢弃。

### S1.1 去重抽样（张数超需求时）

```bash
python3 scripts/prep_assets.py <文件夹> --out-dir <项目>/assets_stage --dedupe --sample N
```

三步：变体合并（`-Edit|-Edit\d*|Enhanced-NR|copy|尾数字` 同 stem 归一，取最大文件）→ 连拍归组（同年月且序号差 ≤4，并查集，每组取最大）→ 类目×色调双层轮转抽样。

### S1.2 素材生成

显示层**只有一个主控变量：长边像素**（`--display-long`，默认 1500）。

- 屏幕图块只有 162–206px（手机 89–101px），长边 1500 已远超需求，与 v23 观感一致；再高只增负载不增清晰度。
- 质量阶梯在**同一长边封顶**下逐级提质量（q78→84→88→92），达标即停；只缩不放。
- `--min-mb` 已降级为**质量护栏**（默认 0）：单张不足此值时提质量，但**绝不放大、绝不回退原图**。

> ⚠️ 历史 bug（见 lessons #11）：旧实现为凑「≥1MB」而把长边逐级**缩小**（2000→1200），
> 缩小只会让文件更小，故阶梯必然全败并 `copy2` 塞入原图 —— 一张 7000px/3MB 原图被拿去
> 渲染 200px 图块，整页负载爆炸、首屏长时间纯黑。**不要恢复任何「为凑字节数而改尺寸」的逻辑。**

灯箱层：`--full-mode source` 直接上传源原图（零本地复制，省一倍磁盘）；`copy` 则先复制副本再传。灯箱层永不为显示效果重编码，只在点开时加载。

**交付前强制检查**：`report.json` 里 `display_used_original` 必须为 **0**。非 0 即素材门未过，
说明显示层回退成了原图，页面负载会失控 —— 不得继续交付。

box（主体框）：灰度图 `mean+3σ` 阈值 → 非黑像素 0.3/99.7 百分位包围盒 → 6% 外扩 → 归一化。全暗帧（有效像素 <0.1%）记 null。**只用于尺寸校正，不用于裁切、不用于碰撞。**

### S1.3 上传与 data.js

```bash
# 1) 生成素材（一次到位，含主体框）
python3 scripts/prep_assets.py <文件夹> --stage <项目>/stage --out <项目>/assets/data.js \
        --full-mode source --report <项目>/assets/report.json

# 2) 上传：一次传一整批，路径逐字取自清单文件，不要手敲、不要人为拆分往返
python3 <apps-builder>/scripts/deliver/upload_asset.py <显示层 p0001..pNNNN.jpg 全部路径>

# 3) 回填 URL
python3 scripts/apply_urls.py <项目>/assets/data.js \
        --display-urls disp_urls.tsv --full-urls full_urls.tsv --out <项目>/assets/data.js

# 4) 并发校验外链（必做，见下）
python3 scripts/check_urls.py <项目>/assets/data.js --layer both --workers 8
```

上传要点：
- `upload_asset.py` 接受多个文件参数，**一批传完**，不要拆成多次往返。
- 路径必须从脚本产出的清单文件逐字读取（手敲 41 条曾出现大量不存在的路径）。
- 灯箱层若已上传过且链接仍有效，可**复用**已有 URL，无需重传原图。
- 宿主注入的上传 SDK **不是普通可导入模块**，无法用外部包装器并发调用；提速只能落在
  「减少往返次数」与「并发化自建校验」上。

`scripts/check_urls.py`（只用标准库，不依赖 SDK）：8 路并发、URL 去重、HEAD 取不到体积时退化为
Range GET 首字节，能识别图床返回的几百字节错误页。实测 208 个链接 3 秒（串行 curl 约 10 秒）。
退出码 1 = 有异常链接并逐条打印，**必须在交付前跑到退出码 0**。

### 数据 schema（v1）

```js
window.PLAYGROUND_DATA = {
  schema: "plankton-playground/v1",
  title: "…",
  config: { /* 任意 CFG 键的覆盖 */ },
  records: [{
    id: "DSC_0077",           // 唯一键，也是 DOM data-id
    src: "https://…",          // 显示层
    full: "https://…",         // 灯箱原图
    w: 900, h: 600,            // 显示层像素尺寸（决定纵横比）
    box: [0.21, 0.18, 0.79, 0.83] | null,
    attrs: { taxon: "Cnidaria", location: "…", depth: "…", date: "…", /* 任意 */ }
  }]
};
```

兼容：records 里用 `u`/`fu` 的旧数据也能跑（引擎自动映射）。

**attrs 自动填充来源**（prep_assets 应尽力而为）：EXIF（DateTimeOriginal、Make/Model、FocalLength）、目录路径推断的类目、用户 sidecar（同名 `.json`/`.csv`/`.xmp` 的任意列）。塞进去即可，页面不用不影响。

## S2 生成页面

```bash
python3 scripts/build_page.py --template assets/playground.html --data <data.js路径或URL> \
  --title "…" --out <项目>/<描述性入口名>.html [--config '{"voidRatio":1.35}']
```

入口名必须描述性（如 `blackwater-plankton-archive.html`），禁止 index.html。

**默认会自动套用 `assets/config.approved.json`**（用户已验收的调优：密度 +27%、速度 +20%、
消除静止图、刷新随机尺寸+强制跳变、四处缺陷修复全开）。构建日志会打印
「已注入配置 12 项（预设 config.approved.json）」——**看不到这行就说明预设没生效，必须排查**。

- 单项微调：`--config '{"spacingFactor":0.6}'` —— 只覆盖指定键，其余仍用预设。
- 复现 v23/v2 保守基线（或跑等价性校验）：`--no-preset`。
- 换预设：`--preset <路径>`。

> 为什么预设放在构建期注入、而不写进引擎 CFG 默认值：引擎默认必须与 v23 逐字一致，
> 否则 `check_equivalence.cjs` 这道门永久失效 —— 而正是它在本轮迭代抓出三个真实缺陷。
> 预设把「用户认可的调优」与「引擎基线」解耦：基线可验，成品是验收过的样子。
> 详见 lessons #19。

### 扩展点（未来功能挂这里，不改引擎）

| 需求形态 | 挂法 |
|---|---|
| 点击显示元数据面板 | `Playground.on("lightbox:before", ({record}) => { 渲染 record.attrs; return false; })` 拦截默认灯箱；或不拦截、在 `lightbox:open` 里追加面板 |
| 按谱系/标签聚拢 | `Playground.relayout("taxon", t => t.attrs.taxon)` —— 同键记录在放置顺序中连续 → 自然落进相邻带 |
| 平滑重组动画 | `Playground.setConfig({morph: 1})` + `Playground.setTargets(t => 计算目标)`，到位后自动重算 |
| 筛选/高亮子集 | 遍历 `Playground.tiles`，改 `t.el.style.opacity/filter`，或 `classList` |
| 统计/图例/导航 | `Playground.records` 只读全量数据，自行渲染 DOM |
| 每帧自定义效果 | `Playground.on("frame", ({t, frame}) => …)`（注意性能，别做 O(n²)） |
| 新增粒子/背景 | 独立 canvas 层自行叠加，不动引擎的 #snow |
| **同一生物多角度条带（已实现）** | `assets/kinship_mount.js`：`on("lightbox:open"/"lightbox:close")` 内建胶片条 + 指认纠正；分组数据由 `scripts/inject_kinship.py` 写成 `window.__KIN_GROUPS__` 注入，无分组时整体静默关闭。详见 `references/kinship.md` 与 S6 |

引擎对外只暴露：`tiles`（含 attrs/几何/预算）、`records`、`config`、`canvasHeight`、`layout()`、`setConfig()`、`relayout()`、`setTargets()`、`tileById()`、`openLB/closeLB`、`on/off/emit`。核心不认识 taxon/location/depth 等任何业务词。

> ⚠️ **`tileById(id)` 返回的 tile 对象没有 `src` 字段**（URL 在 `records` 里）。
> 取图片 URL 一律用 `Playground.records.find(r => r.id === id)`。
> 曾因此误判「站点破图」，实际站点正常（见 lessons #24）。

## S3 验证门

```bash
node scripts/verify_layout.mjs <入口.html> <data.js> [--vw 1440 --vh 900] [--seeds 5] [--frames 601]
```

内部：无头 vm 装载**真实页面脚本**（不是复刻品），mulberry32 定种随机，逐帧调 `advance()`，断言见 SKILL.md。四种视口都要跑：1440×900、1280×680、1920×1080、390×844。

改动引擎后额外跑：

```bash
node scripts/check_equivalence.cjs assets/baseline-v23.html assets/playground.html <data.js>
```

morph=0 时 300 帧逐帧坐标偏差必须 <0.01px。

### S3.1 三道必过门（缺一不可）

```bash
# ① 布局：四视口都要跑，且必须看到「==> 全部通过」四行
for v in 1440:900 1280:680 1920:1080 390:844; do
  vw="${v%%:*}"; vh="${v##*:}"
  echo "===== ${vw}x${vh} ====="
  node scripts/verify_layout.mjs <入口.html> <data.js> --vw "$vw" --vh "$vh" --seeds 3 --frames 601
  echo "退出码: $?"                                    # ← 必须打印并检查
done

# ② 素材：display_used_original 必须为 0
python3 -c "import json;r=json.load(open('<report.json>'));print('used_original:',r['display_used_original']);assert r['display_used_original']==0,'显示层回退成原图，素材门未过'"

# ③ 外链：并发校验两层，退出码必须为 0
python3 scripts/check_urls.py <data.js> --layer both --workers 8
```

**若启用了刷新随机尺寸（`randomSize=1`），追加第 ④ 道门：**

```bash
# ④ 接力刷新：验证强制跳变保证成立（0 违规 / 0 越界 / 0 乒乓），并打印用户指认图块的宽度序列
node scripts/reload_chain.cjs <入口.html> '<完整configJSON>' 1440 900 12 DSC_1297
node scripts/reload_chain.cjs <入口.html> '<完整configJSON>' 390 844 10 DSC_1297   # 手机端允许退化为带内随机
# 可选：查钳位堆积（「只有两档来回切」的根因）
node scripts/rsize_concentration.cjs <入口.html> '<完整configJSON>' 1440 900 60
```

接力脚本用 localStorage 桩把「本次宽度」传给「下次加载」，精确复刻真实浏览器的刷新链条 —— 这是唯一能验证
「每次都看得出变化」的方式；只数 distinct 值个数会漏掉钳位堆积与两值乒乓（见 lessons #18）。

> ⚠️ **陷阱：`verify_layout.mjs` 的 config 取自第二个参数（数据文件），不是入口页。**
> 引擎代码读入口 HTML，但 `PLAYGROUND_DATA.config` 从传入的 data.js 解析。
> 若入口页是构建期注入了预设的（`--preset`），而验证时传了 config 为空的原始 data.js，
> 就会按引擎默认值跑 → 弱动/密度断言假失败（实测同一页面：传预设数据 15/15 通过，传空 config 数据 2 项 FAIL）。
> **验证时传的 data.js 必须与构建时注入的是同一份**（即 `data_final.js` 这类含 config 的文件），
> 或直接把构建产物内联页对应的数据文件一并保存下来备查。

> ⚠️ **空输出 ≠ 通过**（见 lessons #14）。用 `grep` 过滤验证输出时，脚本抛错的信息会被一并滤掉，
> 空结果极易被误读成「没有失败」。**必须同时检查退出码，并确认成功标记的行数 == 视口数。**
> 汇报任何验证结论前，先看未过滤的原始输出尾部。

> 阈值已全部尺度无关（每屏密度比、画布高度上限随 N 伸缩），换更大图库不会误报失败。
> 新增视口或张数时不要改回绝对阈值。

## S4 视觉自评门

```bash
python3 scripts/render_preview.py <入口.html> <data.js> <素材目录> --out preview.png [--zone top|mid|bottom|all]
```

合成图 = 真实素材 + 布局坐标 + 羽化模拟 + 纯黑底。用 Read 亲眼看，按 SKILL.md 清单检查。发现问题 → 修 → 重跑 S3 → 重新合成。**禁止跳过。**

## S5 定版交付

1. `history/vN/` 快照（入口 + assets）
2. `history/MANIFEST.md` 追加 `| vN | 日期 | 摘要 | 交付方式 |`
3. 单文件版（内联 data.js）
4. 文件交付工具发送 + 如实取舍声明

## 迭代场景速查

| 用户说 | 改哪 |
|---|---|
| 太挤/太空 | `voidRatio`（1.25 密 ↔ 1.85 疏），跑 S3 |
| 图太大/太小 | `loF`/`hiF`，跑 S3 |
| 动得太快/太慢/不明显 | `wxLo..wyHi`、`RCAP`，跑 S3 |
| 贴屏幕边 | `MX` |
| 背景脏/像灰点 | 检查是否混入柔斑——星尘必须纯白锐利、无 createRadialGradient |
| 打开全黑 | 十有八九是画布高度公式或 reveal 逻辑，跑 verify 看首屏断言 |
| 方框叠方框 | 碰撞口径必须是图框级；检查不动点预算是否被主体级判据污染 |
| 回退 | `history/vN/` 逐字复制回根，再只改被要求的一处 |
