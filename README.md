# Homoplankton 研究工作台 — 私有仓库

浮游生物影像的研究工作台与项目源料。**私有仓库，不对外公开。**

档案站（公开展示部分）在另一个仓库：
<https://github.com/Homoplankton/homoplankton-blackwater-archive>

## 为什么这个仓库是私有的

工作台是**研究过程中的裁决工具**，不是展示页。其中含 **43 张图的 AI 草案分类与
发育分期，尚未经作者确认**。界面用琥珀色「AI 待确认」与「✓已确认」区分两者，
但索引抓取的是文本而非样式，公开后错误的分类会与作者的专业署名绑定。

地点、水深、水温字段在全部 108 张图上均为空值，未记录 GPS 坐标或潜点名称。

## 仓库结构

```
workbench/
  workbench.html          工作台单文件（图片 base64 内嵌，可离线双击打开）
  workbench.delivered.html  同上，交付版副本
  template.html           构建模板（左栏可编辑、表格视图、分类树、红点标记等）
  scripts/                构建与测试脚本
    build_workbench.py    组装单文件（内嵌 full 层而非 detail 层）
    build_claims.py       生成 claims.json（含 full/w/h/aspect/box_norm 字段）
    apply_triage.py       108 图分类处置回填（43 include + 65 skip）
    ingest_feedback.py    摄取人工裁决，写入错题集/锚点/准确率台账
    kinship_mount.js      同生物关联条带挂载层 v4.1
    test_wb_v2.mjs        52 项浏览器测试
    build_strip_crops.py  条带裁剪（已弃用，主体裁剪被否决）
  data/
    claims.json           617 条断言 / 82 条文献 / 8 条修订记录
    kinship.json          13 个同生物分组，覆盖 39 张图
    group_refs.json       48 条文献按 16 个形态组归类
    error_book.json       错题集（多标签失效模式）
    anchors.json          已确认图按分类路径索引
    accuracy_ledger.json  批次级准确率统计
    decisions/            人工裁决导出文件的投递目录
  assets/
    thumb/ full/ detail/  三层素材（detail 为主体裁剪，已弃用）

experiments/
  link-exp/               档案站 ⇄ 工作台双向互链实验（L1）
  growthseq-exp/          生长发育序列搭建实验（未沉淀为技能）

history-builds/
  archive-v23/            v23 定版基线的源料、脚本与 history 快照
  planktontest-playground/  108 图构建的源料与台账

skills/
  plankton-playground/    档案站构建技能快照 v4.0.0
  larval-taxonomy/        幼体分类技能快照（含 S8 人在环+学习闭环）

archive-scripts/
  fetch_assets.py         把 CDN 外链图片取回本地
  relink_archive.py       把页面外链改写为仓库内路径，带 4 道校验
```

## 未纳入本仓库的内容

两个历史构建目录里的**派生图层**共 757MB 未纳入，因为它们可从外挂硬盘原图
用 `prep_assets.py` 重新生成：

- `archive-v23/stage_full/` — 487MB，110 张灯箱层
- `planktontest-playground/stage/` — 257MB，104 张显示层

原图（未压缩）存于作者本地外挂硬盘，不在任何仓库内。

工作台 `data/` 下的 `*.bak-*` 历史备份快照也已排除（`.gitignore` 覆盖）。

## 三层素材语义

| 层 | 尺寸 | 用途 |
|---|---|---|
| `thumb` | 400px 整幅 | 网格瓦片 |
| `full` | 1200px 整幅 | 检查器大图（当前内嵌进单文件） |
| `detail` | 640px 主体裁剪 | **已弃用** — 主体裁剪被作者否决 |

`detail` 被否决的原因：居中裁剪让生物不真实地充满画面、丢分辨率、丢黑水语境。
检查器一度误用 `detail` 导致严重裁剪感，改为内嵌 `full` 后**文件更小且显示正确**。

关联条带的焦点放大只用 `transform: scale`，**永不换源到 `r.full`** ——
`r.full` 是整幅图而非裁剪图（实测 2745×4117 比例 0.667 vs 裁剪 640×355 比例 1.803），
换源会重新引入错位与宽高比跳变。

## 反馈学习闭环

工作台内裁决（确认 / 更正 / 驳回 + 「你看漏了 X」批注）→ 导出 JSON
→ 放入 `workbench/data/decisions/` → 运行 `ingest_feedback.py`：

- claims 覆盖：**人工裁决永远压过 AI 草案**，`confirmed`/`human` 状态不可变
- revision_log 记录修订轨迹
- `error_book.json` 累积多标签失效模式
- `anchors.json` 按分类路径索引已确认图，供后续 SOP 预比对
- `accuracy_ledger.json` 批次级统计

摄取幂等，已处理文件归档到 `_ingested/`。
幼体分类技能的 S8 阶段已强制要求：**SOP 运行前必须先读 error_book / anchors / ledger**。

## 铁律（贯穿全项目）

- 绝不修改外挂硬盘上的原始照片
- v23 锁定为定版基线，任何改动必须保持其行为（morph=0 等价）
- 帧级零相交强制 —— 整个运动过程中不允许任何重叠或碰撞
- 一次只改一件事，合并前独立验证
- 任何不可逆的批处理，先出样本获批准
- 所有验证阈值必须与规模无关（适配图片数量与视口尺寸）
- 主体裁剪已否决，一律整幅显示
- **算法只召回，分组判定必须由人眼完成**
- 注入前必须 `node --check`
- 测试用真实鼠标手势，不用合成点击
- 定版后不主动新增测试或按自己意愿加功能
