# 浮游生物研究工作台 · Homoplankton

claim-centric 研究工具的第一版：**外壳 + 图库模式**。数据模型先于界面建立，
后续表格模式与分类关系树作为视图增量加入，不需要改模型。

## 它回答什么

不是「把数据填进去」，而是「这个问题我知道多少、凭什么知道、哪些被推翻过」。
每个值带三个属性：`asserted_by`（谁说的）、`status`（可信到什么程度）、
`evidence`（凭什么）+ `superseded_by`（被谁推翻）。

## 打开方式

直接双击 `workbench.html`（自包含单文件，16 MB，含 108 张内嵌缩略图与检查器大图）。
日常使用**不依赖外置盘、不依赖网络**。

键盘流（3108 张靠鼠标点选不可能完成）：
`J`/`K` 移动 · `1` 认可 · `2` 修改 · `3` 否决 · `Enter` 确认并下一条 ·
`Space` 放大主体 · `/` 搜索 · `⌘S` 保存

## 保存机制（两级回退）

1. 批注即时写入浏览器 localStorage（覆盖层，不改动原始断言）
2. `⌘S` 或「保存」按钮：Chrome/Edge 用 File System Access API 直接写本地 JSON；
   不支持的浏览器回退为下载 JSON
3. 「打开」按钮可载入之前导出的批注文件
4. 导出的覆盖层写明：`verdict=confirm` 可写入 confirmed 库；
   `no_sequence=true` 排除出序列装配；`taxonomy_path/stage_label` 为人工修订值，
   落库时应生成新的 human 断言并把被替换的 ai 断言标 superseded_by

## 构建管线（外置盘挂载时才能重跑前两步）

```
scripts/build_assets.py      外置盘原图 → 缩略图/主体裁剪/三分类色彩/EXIF  → assets/derived.json
scripts/build_claims.py      derived + v5 标注 → claim 数据库               → data/claims.json
scripts/build_workbench.py   claims + 内嵌图 → 单文件页面（--embed-detail 自包含）
scripts/test_cdp.mjs         真实浏览器交互测试（22 项，含键盘流/队列/筛选/导出）
```

重跑顺序：assets → claims → workbench → test。

## 数据事实（108 张实测，勿凭印象引用）

- **EXIF**：DateTimeOriginal / 曝光 / 光圈 / ISO = 108/108；等效焦距 88/108；
  镜头型号与 GPS 缺失（Lightroom 剥离）。DateTime 是导出时间，≠ 拍摄时间。
  （曾误报全缺，根因：exif_transpose() 返回对象无 _getexif 方法。见修正链 r5）
- **潜次**：由 DateTimeOriginal 推断 44 个潜次 / 7 个航次（同日 >40min 断点切分）。
  Lightroom 导出批次仅 5 组，不能当潜次用。
- **主体框**：105/108 有归一化 box；3 张全暗帧按整幅处理并如实标注 full_frame。
- **色彩**：三分类 water/tissue/pigment。色素只认暖色相（hue≤32 或 ≥330）且
  占组织比 ≥2%，否则报「未检出显著色素」，不硬给色值。（单一主色调曾把 15% 的水
  当成主体色，见修正链 r6）
- **文献**：34 条唯一书目 / 38 次引用出现。核验层级 opened 7 · bibliographic 5 ·
  link_only 26；可达性 opens_now 18 · bot_walled 18 · unreachable 2。
- **争议**：2 张真争议（DSC_3058、_Y3A0153，栉水母术语之争）。
  DSC_0933 是确定结论（单细胞，无后生动物序列），**不是**争议——
  关键词扫描曾把它误判为争议，故改为显式登记。

## 设计决策留痕

- **配色纪律**：4 色相（slate/amber/green/rust）+ 实色/虚线两种处理法表达状态。
  黑底上饱和色泛光晕（Tool 1「海洋雪像脏点」同因），故深色外框 + 中性工作面，
  并提供浅色模式供长时间核验；图像瓦片保持黑底（黑水照片本就需要黑底）。
- **为什么不用关键词自动判争议**：会把确定结论误标成争议，稀释争议板可信度。
- **为什么检查器大图内嵌**：相对路径版本单独发送时会降级为 400px 缩略图——
  而低分辨率误判正是把船蛸看成鱼的那次事故的根因。诊断特征必须看得清。
- **单文件体积**：16 MB。若只要轻量版，去掉 --embed-detail 得 1.6 MB
  （大图走相对路径，需与 assets/ 同目录）。

## 后续增量（数据层已就绪，只加视图）

表格模式（跨图比较查询原生）、分类关系树（D3 cluster，节点虚实表置信度）、
潜次批量填面板、成体文献对照、原位姿态差异登记、分期缺口图。
