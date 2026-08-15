# A股每日市场监控｜生产链路 v3.1

## 1. 正式架构

HTML 是每日正式展示成品，Excel 不再是 HTML 的中间母表。

```text
历史完整性预检 / 定点回填
→ Raw / Stage 当日采集
→ Canonical 候选标准化
→ Canonical Validator
→ 通过后 Promote 到正式历史 CSV
→ report_data.json
→ HTML v1.1 Renderer
→ HTML Validator
→ HTML + report_data + Canonical/HTML validation 单 artifact
→ GitHub 归档
```

唯一网页运行入口：`config/html_production_runtime.json`。

旧 Excel Renderer v1.5 暂时保留为兼容/历史路径，不属于 HTML 日常关键路径。

## 2. Raw 与 Canonical 的职责

Raw/Stage 保存当天接口直接结果、来源、抓取状态和失败信息，不直接驱动 HTML。

Canonical 是正式历史母表。当前继续使用 GitHub CSV，不引入数据库，但所有正式历史必须经过 Canonical gate。核心表至少包括：

- `market_core.csv`
- `indices_history.csv`
- `hot_stocks.csv`
- `innovation_drug_eastmoney.csv`
- `sw_analysis_daily_second.csv`
- `sw_industry_history.csv`

`report_data.json` 只读取通过验证的 Canonical 数据，不读取 Raw。

Canonical gate 检查：

- 主键唯一；
- 完全重复行可以规范化去重，冲突重复键 FAIL；
- 已验证非空历史不得被空值覆盖；
- 历史非报告日修改必须记录；
- 大规模历史删除、唯一业务键数量异常下降、最新日期倒退 FAIL；
- `上涨 + 下跌 + 平盘 = 有效股票数`；
- 市场宽度公式复核；
- 百亿成交额不得大于全A成交额；
- 占比/换手率等字段做范围与异常跳变检查；
- 每次输出 `canonical_validation.json` 与 `canonical_manifest.json`，manifest 记录各表 SHA256、行数、最新日期及历史变更。

Canonical Validator 为 FAIL 时，不允许生成正式 `report_data.json` 和 HTML。

## 3. 每日生产顺序

`.github/workflows/daily_market_monitor.yml` 正常日依次执行：

1. 安装依赖与快速语法检查；
2. `run_history_preflight.py` 扫描历史关键字段并定点修复可恢复缺口；
3. `run_daily.py` 在 staging 中完成当日市场、指数、百亿成交、申万与创新药采集/更新；
4. `validate_canonical_data.py` 对候选 Canonical 做结构、历史和数学一致性验证；
5. 仅在 Canonical 非 FAIL 时更新正式历史；
6. `build_report_data.py` 从 Canonical 生成唯一展示数据合同；
7. `render_market_monitor_html.py` 生成 HTML v1.1 单文件报告；
8. `validate_market_monitor_html.py` 执行展示层一致性校验；
9. 写 `data/latest_bundle_pointer.json`；
10. 上传一个 `a-share-monitor-html-YYYY-MM-DD` artifact；
11. 归档历史、manifest、validation、JSON 和 HTML。

完整单元测试只在 PR/code review 跑，普通日不重复执行。

## 4. 历史缺口预检

关键检查包括：

- 上证50、Choice微盘、中证全指：历史涨跌幅与成交额；
- 全A：成交额、涨跌家数、涨跌停、市场宽度；
- 百亿成交：每日数量与完整个股明细；
- 创新药：成交额、成交额占全A、供应商直接换手率；
- 申万行业与四行业拥挤度最新有效日。

规则：

- 指数历史只能使用历史 K 线补，不用当前报价倒填；
- 大面积初始化使用每指数一次日期区间请求，零散缺口再定点补抓；
- 创新药成交额占比只允许 `同日创新药成交额 / 同日全部A股成交额`；
- 创新药换手率只接受供应商直接板块换手率；
- 新空值不得覆盖已验证历史非空值；
- 无同定义可靠来源的数据继续留空并 WARN，禁止为了 PASS 伪填。

## 5. `report_data.json`

它是 HTML 的唯一业务数据输入，至少包含：

- `meta`
- `market_history`
- `indices_history`
- `sw_industry_latest`
- `hot_stocks_history`：截至报告日的全部 Canonical 百亿成交明细历史
- `hot_stock_matrix`：最近 10 个有记录交易日的展示矩阵
- `hot_stocks_latest`
- `sw_crowding_history`
- `innovation_history`
- `quality`

展示窗口不得反向截断 Canonical 历史。

## 6. HTML v1.1 展示与交互

### 所有时间序列图

- 单文件内嵌 JavaScript/SVG，不引用 CDN、外部 JS/CSS；
- 默认展示全历史；
- 每图提供开始/结束两个时间范围控制和“全部”恢复；
- 时间范围改变后重新计算可见区 y 轴，不只是裁切；
- tooltip 显示日期、指标、数值与单位；
- 图例明确标识每条序列，并可隐藏/恢复序列；
- 市场涨跌结构：上涨/下跌家数左轴，涨停/跌停家数右轴。

### 01｜申万行业

保留搜索和一级/二级筛选；以下列支持三态排序：

- 成交额
- 日收益率
- 20日年化波动率

点击循环：`原始顺序 → 降序 → 升序 → 原始顺序`。原始顺序使用 Canonical 快照中的不可变业务顺序。

### 04｜百亿成交

- Canonical `hot_stocks.csv` 保存全部已验证历史；
- HTML 矩阵默认最近 10 个有记录交易日；
- 最新日期放最左，历史日期向右；
- 报告日完整个股明细不设行数上限。

### 05｜申万四行业资金拥挤度

- 最新摘要只显示四行业本身，不显示“四行业成交额合计”表；
- `四行业成交额占全A` 使用四条半透明面积序列；
- `四行业换手率` 使用四条折线；
- 标题、图例、单位和 tooltip 明确说明通信设备、计算机设备、元件、半导体。

### 06｜创新药交易拥挤度

- `创新药成交额占全A` 使用面积图；
- `创新药换手率` 使用折线图；
- 换手率只接受供应商直接板块字段；
- `20日成交量活跃度代理` 永久禁止进入 Canonical、report_data 或 HTML。

## 7. 双层 Validator

### Canonical Validator

负责判断历史数据是否足以进入正式展示链。FAIL 时停止生产。

### HTML Validator

负责：

1. 报告日等于市场历史最新日；
2. 最新市场结构四项完整；
3. 百亿成交明细数量等于 `hot_count`；
4. 百亿成交矩阵报告日合计等于 `hot_count`；
5. 市场图包含最新报告日数据 marker；
6. HTML 无外部运行依赖；
7. 创新药不存在代理活跃度字段；
8. 已存在同日全A分母时，创新药占比不得继续为空。

无法同定义安全恢复的数据源缺口为 WARN，不允许伪填。

## 8. 网页端标准动作

用户只需：

> 更新一下今天的

网页端执行：

```text
读 config/html_production_runtime.json
→ 读 data/latest_bundle_pointer.json
→ 下载唯一 a-share-monitor-html-* artifact
→ 检查 canonical_validation.json
→ 检查 html_validation.json
→ 交付 A股每日市场监控_YYYYMMDD.html
```

不再寻找 Excel 母表，不再由网页端修改 Excel 图表对象或复制单元格格式。

## 9. Excel 定位

现有复杂 Excel 版本保留为历史参考，不再作为 HTML 正式生产依赖。

如未来需要 Excel，只生成简化数据底表，并与 HTML 一样消费 Canonical/report_data，不反向驱动 HTML。
