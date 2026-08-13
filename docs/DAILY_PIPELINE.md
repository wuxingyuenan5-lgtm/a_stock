# A股每日市场监控｜生产链路 v2.0

## 1. 目标

日常生产必须是可重复、可停止、不可自由发挥的固定流水线：

```text
GitHub 数据生产
→ 标准化 payload + validation
→ 自包含 render bundle
→ latest bundle pointer
→ 网页 ChatGPT 读取唯一 runtime manifest
→ 上一交易日已验证滚动母表
→ Renderer v1.4 原表增量更新
→ workbook validator
→ 今日 XLSX
→ 今日 XLSX 成为下一交易日母表
```

GitHub 负责数据、规则、版本和 bundle；网页端只负责执行固定 Renderer 和交付 Excel。

---

## 2. 唯一入口

网页端每天首先只读取：

`config/web_production_runtime.json`

随后只读取：

`data/latest_bundle_pointer.json`

正常日禁止仓库全局搜索、禁止重新理解版式、禁止人工重算 bundle 已有业务数据。

---

## 3. GitHub 每日关键路径

`.github/workflows/daily_market_monitor.yml` 手工触发。

正常生产路径：

1. 安装依赖；
2. 快速语法预检；
3. 刷新 05 所需申万四行业拥挤度缓存；
4. `run_daily.py` 生成当天标准化市场 payload；
5. 使用 `update_sw_industry_fast.py` 两次批量申万实时接口增量更新 01/06 所需行业快照；
6. `prepare_render_bundle.py` 生成自包含 bundle；
7. 写 `data/latest_bundle_pointer.json`；
8. 上传一个 `a-share-monitor-YYYY-MM-DD` artifact；
9. 持久化增量历史、缓存和 JSON 状态。

完整单元测试只在 PR/code review 跑，不再占用正常日生产时间。

### 申万行业刷新分层

- **日常快速模式**：`update_sw_industry_fast.py`
  - 只做一级行业 + 二级行业两次批量请求；
  - 在已有 `sw_industry_history.csv` 上 upsert 当天；
  - 重算 20 日波动率；
  - 保留 260 日滚动历史；
  - 覆盖率低于 90% 时失败并沿用上一次已验证缓存。
- **完整刷新模式**：`update_sw_industry.py`
  - 仅 bootstrap、接口结构变化、缓存损坏或人工选择 `full_refresh_sw_industry=true` 时执行；
  - 不再进入普通日关键路径。

历史目标日不得使用实时批量接口伪装历史值；非当天目标日直接沿用已验证缓存。

---

## 4. 标准化数据层

`run_daily.py` 是业务数据生产入口，生成：

- `daily_payload.json`
- `validation.json`
- `source_manifest.json`
- `hot_stocks.csv`
- `all_a_snapshot.csv`
- `sw_analysis_daily_second.csv`

并维护：

- `data/history/market_core.csv`
- 创新药主/备独立历史
- 申万个股二级行业映射缓存

原则：

- 同一字段优先一个稳定接口一次获取；
- 缺失不写 0；
- 不跨源补值；
- 新交易日接口失败则该字段留空并 WARN；
- 同日重跑不得用空值覆盖母表中已验证非空值。

---

## 5. Render bundle

`prepare_render_bundle.py` 将网页端需要的输入封装为一个 artifact。

至少包含：

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

网页端不再逐个拉取 GitHub 程序和配置。

`data/latest_bundle_pointer.json` 记录：

- 目标日期；
- workflow run id；
- artifact 名称；
- Renderer 版本；
- 预期上一交易日母表日期与文件名；
- runtime manifest 路径。

---

## 6. 滚动母表

正常生产只接受：

`上一交易日正式验证输出.xlsx`

作为今日母表。

固定 `A股每日市场监控_优化版_20260810.xlsx` 只用于首次 bootstrap。

如果预期母表存在但网页运行时无法取得原始 xlsx 二进制：

**立即停止并要求用户附加/选择该文件。**

禁止：

- 用更旧母表替代；
- 根据解析文本重建；
- 新建工作簿模仿版式；
- 重新创建图表。

成功输出自动成为下一交易日母表。

---

## 7. Renderer v1.4

入口：

`run_excel_renderer.py -> run_excel_renderer_v14.py`

职责：

- 01：更新申万一级/二级快照；
- 02：目标日 upsert；
- 03：从 02 刷新原图表 series；
- 04：新增百亿成交明细并重算最近 6 日矩阵；
- 05：更新四行业官方拥挤度；
- 06：在同日四行业 + 同日全 A 分母齐全时增量更新；
- 07：使用完整单一来源 selected history；
- 00：同步 KPI/摘要与已有图表 series；
- 99：记录数据质量、母表 SHA、Renderer 版本和缺失模块。

### 图表铁律

每日生产只允许修改已有图表的：

- categories
- values
- 必要的标题文字

禁止：

- `delete_all_drawings()`
- 新增 chart object
- 移动 anchor
- 改变 series identity

00 / 03 / 05 / 07 导出前后图表数量、锚点、series identity 必须完全一致。

---

## 8. Validator

硬校验至少包括：

1. 02 第 6 行 = 目标日期；
2. 市场宽度公式正确；
3. 百亿成交集中度正确；
4. 04 当日长表行数 = 02 百亿股数；
5. 04 当日矩阵合计 = 02 百亿股数；
6. 00 核心 KPI = 02；
7. 03 最新日期 = 目标日；
8. 东方财富创新药当日有真实换手率；
9. 图表结构完全保持；
10. 全工作簿无 `#REF!/#DIV0!/#VALUE!/#NAME?/#N/A`。

FAIL：不交付。
WARN：允许交付，但 99 页必须写明缺失项。

---

## 9. 历史数据缺口与日常生产隔离

历史百亿成交等存量缺口属于一次性 backfill/data-debt 项目，不允许每天重新回补，也不能拖慢每日生产。

日常链路只做：

`昨日已验证状态 + 今日增量`

历史回填单独运行、单独验证、验证通过后再并入母表。

---

## 10. 网页端明日标准动作

用户只需：

> 生成今天的A股每日市场监控

网页端执行：

```text
读 web_production_runtime.json
→ 读 latest_bundle_pointer.json
→ 下载一个 artifact
→ 找 expected_mother_filename
→ 运行一次 Renderer
→ 运行一次 validator
→ 交付
```

如果母表原始文件无法取得，只问一次用户附加母表；不再进入任何自由重建路径。
