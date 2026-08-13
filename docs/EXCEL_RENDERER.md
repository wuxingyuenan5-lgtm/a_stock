# A股每日市场监控｜Web 生产链路 v1.4

## 目标

正式生产链：

```text
上一交易日正式验证工作簿
+ 当日 GitHub 自包含 render bundle
→ 原表增量更新
→ 原图表只更新数据序列
→ workbook validator
→ A股每日市场监控_YYYYMMDD.xlsx
→ 该正式输出成为下一交易日滚动母表
```

GitHub 是数据、规则、版本和 render bundle 的唯一生产源；网页 ChatGPT 只负责使用 `artifact_tool` 消费固定输入并生成 Excel，不重新研究、不重新定义字段、不自由重建工作簿。

## v1.4 核心修复

1. **母表从固定模板改为滚动母表。** 固定 2026-08-10 模板只用于首次 bootstrap。正常生产必须以上一交易日正式验证输出为母表。滚动母表不再因为 SHA256 与 bootstrap 不同而被拒绝；改为校验 9 个工作表和固定图表结构。
2. **禁止每日重新创建图表。** 每日 Renderer 不允许 `delete_all_drawings()`，也不允许新增图表对象。只更新原图表 series 的 categories / values。导出前后比较图表数量、锚点位置和 series identity，结构变化直接 FAIL。
3. **01 和 06 纳入正式 Renderer。** `01_申万行业` 由 `sw_industry_latest.csv` 更新；`06_综合拥挤度_辅助` 使用同一份申万快照和 02 同日全 A 成交额分母增量更新。
4. **04 行业矩阵不再丢行业。** 最多展示 13 个命名行业，其余归入“其他行业汇总”。当日矩阵合计必须等于当日百亿成交股数量。
5. **05 同日推导成交额。** 申万官方给出成交额占比/换手率但 `amount_100m` 为空时，使用 02 同日全部 A 股成交额推导，不跨日期、不跨来源。
6. **07 继续单一历史源。** `innovation_history_selected.csv` 是唯一渲染历史输入，源切换必须整段历史重写。

## GitHub 每日生产链

`daily_market_monitor.yml` 人工触发后执行：

1. 语法检查和单元测试；
2. 刷新申万四行业拥挤度缓存；
3. 刷新申万一级/二级行业快照；
4. 生成标准化 `daily_payload.json`；
5. 生成自包含 render bundle；
6. 写入 `data/latest_bundle_pointer.json`；
7. 上传单一 workflow artifact；
8. 持久化历史、缓存、申万快照及 JSON 归档。

`data/latest_bundle_pointer.json` 是网页生产的唯一 GitHub 导航入口。网页不再搜索大量仓库文件，只需读取 pointer，即可知道目标日期、workflow run id、artifact 名称、Renderer 版本和预期母表文件名。

## 自包含 render bundle

workflow artifact 必须包含：

- `daily_payload.json`
- `validation.json`
- `source_manifest.json`
- `hot_stocks.csv`
- `innovation_history_selected.csv`
- `sw_industry_latest.csv`
- `render_bundle_manifest.json`
- `web_production_manifest.json`
- `renderer_runtime/run_excel_renderer_v14.py`
- `renderer_runtime/excel_renderer_artifact.py`
- `renderer_runtime/excel_renderer.json`

因此网页端只下载 **一个 artifact**，不再逐个读取 GitHub 程序和配置。

## 网页端标准执行

用户只需说：

> 生成今天的 A 股每日市场监控

网页端严格执行：

1. 读取 `data/latest_bundle_pointer.json`；
2. 下载 pointer 指向的单一 artifact；
3. 根据 `expected_mother_filename` 定位上一交易日正式工作簿；
4. 若母表原始 xlsx 已在当前运行时，直接使用；若只能看到 File Library 引用、无法获得原始二进制，只允许用户选择/附加该文件一次，**不得自由重建**；
5. 执行 artifact 自带 Renderer：

```bash
python renderer_runtime/run_excel_renderer_v14.py \
  --template <mother.xlsx> \
  --bundle-dir . \
  --config renderer_runtime/excel_renderer.json \
  --output A股每日市场监控_YYYYMMDD.xlsx
```

6. Renderer validator PASS/WARN 后交付；FAIL 时停止，不得退回手写 Excel。

## 工作表规则

### 01_申万行业
- Header 第 6 行，数据第 7 行；
- 输入 bundle 中 `sw_industry_latest.csv`；
- 全量刷新当前快照；
- 单个长期停更指数保留接口最近有效值，不跨源替换。

### 02_统一历史数据
- 新日期插入第 6 行；
- A:O、T 来自 payload / 原有历史；P:S 为固定公式；
- 新日期指数抓取失败保持空白；
- 同日重跑时 payload 空值不得覆盖母表已验证非空值。

### 03_市场宽度图
- 只读 02；
- 图表时间升序；
- 三张既有图表只更新 series；
- 不删除、不新建图表。

### 04_百亿成交历史
- 长表最新日期在上，同日排名升序；
- 最近 6 个有记录交易日进入矩阵；
- 13 个命名行业 + 1 个“其他行业汇总”；
- 矩阵当日合计 = 长表当日行数 = 02 百亿成交股数。

### 05_申万行业资金拥挤度
- 四个目标行业必须完整同日；
- 官方值未发布时不新增空白日期；
- 成交额缺失但同日占比存在时，用 02 同日全 A 分母推导；
- 四张既有图表只更新 series。

### 06_综合拥挤度_辅助
- 使用 01 同源的四个目标二级行业；
- 只在四个目标均为同一有效日且 02 有同日全 A 成交额时新增；
- 仍为辅助模块，不进入核心评分。

### 07_创新药交易拥挤度
- 独立主题；
- 完整 selected history 重写；
- 不混用东方财富与同花顺；
- 两张既有图表只更新 series。

### 99_口径与质量
必须记录目标日期、payload validation、Renderer v1.4、输入滚动母表 SHA256、各模块最新有效日、缺失模块和图表结构校验结果。

## 硬校验

正式导出前必须满足：

1. 02 第 6 行为目标交易日；
2. 市场宽度公式正确；
3. 百亿成交集中度正确；
4. 04 当日长表行数与 02 一致；
5. 04 当日矩阵合计与 02 一致；
6. 00 核心 KPI 与 02 一致；
7. 03 最新日期为目标日；
8. 东方财富创新药当日换手率不为空；
9. 导出前后 00/03/05/07 的图表数量、锚点和 series identity 完全一致；
10. 全工作簿无 `#REF!/#DIV0!/#VALUE!/#NAME?/#N/A`。

任何硬校验失败：**停止交付，不自由重建。**

## 效率目标

网页日常运行收敛为：

```text
1 次读取 latest pointer
+ 1 次下载 artifact
+ 1 次获得母表
+ 1 次 Renderer
+ 1 次 validator
= 直接交付
```

不再重复搜索多个 GitHub 文件、临时推断版式、重新创建图表、手工重算生产包已有数据，或在错误母表上连续修补。
