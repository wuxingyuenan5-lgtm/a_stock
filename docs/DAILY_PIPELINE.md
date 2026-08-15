# A股每日市场监控｜生产链路 v3.0

## 1. 正式架构

HTML 是每日正式展示成品，Excel 不再是 HTML 的中间母表。

```text
历史完整性预检 / 定点回填
→ 当日数据采集
→ 申万缓存/快照更新
→ report_data.json
→ 单文件 HTML Renderer
→ HTML Validator
→ HTML + report_data + validation 单 artifact
→ GitHub 归档
```

唯一网页运行入口：`config/html_production_runtime.json`。

旧 `config/web_production_runtime.json` 与 Excel Renderer v1.5 暂时保留，只作为兼容/历史路径，不属于 HTML 日常关键路径。

## 2. 每日生产顺序

`.github/workflows/daily_market_monitor.yml` 正常日依次执行：

1. 安装依赖与快速语法检查；
2. `run_history_preflight.py` 扫描历史关键字段，并对可恢复指数历史缺口做历史 K 线回填；
3. 刷新申万四行业拥挤度缓存；
4. `run_daily.py` 获取当天市场数据，并持久化指数历史和百亿成交个股历史；
5. `update_sw_industry_fast.py` 批量更新申万一级/二级行业快照；
6. `build_report_data.py` 生成唯一展示数据合同 `report_data.json`；
7. `render_market_monitor_html.py` 生成自包含 HTML；
8. `validate_market_monitor_html.py` 执行结构和数据一致性校验；
9. 写 `data/latest_bundle_pointer.json`；
10. 上传一个 `a-share-monitor-html-YYYY-MM-DD` artifact；
11. 归档历史、JSON 和 HTML。

完整单元测试只在 PR/code review 跑，普通日不重复执行。

## 3. 历史预检

每日生产不是简单“昨日状态 + 今日增量”，而是先做低成本历史完整性扫描。

关键检查：

- 上证50、Choice微盘、中证全指：收盘、涨跌幅、成交额；
- 全A：成交额、涨跌家数、涨跌停、市场宽度；
- 百亿成交：每日数量与明细；
- 创新药：成交额、成交额占全A、供应商直接换手率；
- 申万行业与四行业拥挤度最新有效日。

规则：

- 指数历史缺口只能用历史 K 线补，不得使用当前报价倒填；
- 大面积指数历史初始化使用“每个指数一次日期区间请求”，避免日期×指数的大量网络请求；
- 单个零散日期再做定点补抓；
- 创新药成交额占比只允许 `同日创新药成交额 / 同日全部A股成交额`；
- 创新药换手率只接受供应商直接板块换手率；
- 新的空值不得覆盖已验证历史非空值；
- 没有同定义可靠来源的数据继续留空，并在质量区明确 WARN，禁止造值。

## 4. 标准化数据合同

`report_data.json` 是 HTML 唯一数据输入，至少包含：

- `meta`
- `market_history`
- `indices_history`
- `sw_industry_latest`
- `hot_stock_matrix`
- `hot_stocks_latest`
- `sw_crowding_history`
- `innovation_history`
- `quality`

Renderer 不联网、不重新定义业务口径、不读取 Excel。

## 5. HTML 展示规则

正式 HTML 必须：

- 单文件离线可打开；
- 不引用 CDN、远程 JS/CSS/图片；
- 表格按真实记录数动态增长；
- 百亿成交最新日完整显示全部个股，不设 7 行上限；
- 市场涨跌结构使用完整历史数组，最新点必须等于报告日；
- 图表右侧预留安全边距，最后日期不得与右轴重叠；
- 申万行业支持页面内搜索/层级筛选；
- 申万四行业显示真实“最新官方有效日”；
- 创新药只展示真实换手率，不存在“20日成交量活跃度代理”。

## 6. Validator

结构性错误必须 FAIL，包括：

1. 报告日不等于市场历史最新日；
2. 最新市场结构缺上涨/下跌/涨停/跌停；
3. 百亿成交完整明细数量与 `hot_count` 不一致；
4. 最近日期矩阵当日合计与 `hot_count` 不一致；
5. HTML 没有最新报告日的市场图数据；
6. HTML 存在外部依赖；
7. 创新药出现代理活跃度字段；
8. 同日全A分母已经存在但创新药成交占比仍空白。

数据源暂时不可得且无法在同定义下安全恢复时为 WARN，不允许为了 PASS 伪填数据。

## 7. 百亿成交历史

`data/history/hot_stocks.csv` 保存验证过的百亿成交完整历史。每日当天数据按日期整体 upsert，历史其他日期不动。

HTML 首页不再存在固定行号。最近日期矩阵与最新日期完整个股明细都由同一历史数据生成，因此 7、12、23、30 只均可自然展示。

## 8. 申万数据

- 日常行业快照继续由 `update_sw_industry_fast.py` 批量增量更新；
- 慢速逐指数历史刷新仅用于 bootstrap/缓存修复；
- 四行业拥挤度以申万官方最新有效发布日期为准；
- 如果官方只到 T-1，HTML 明确显示 T-1，不伪装成报告日。

## 9. 网页端标准动作

用户只需要：

> 更新一下今天的

网页端正常只需：

```text
读 config/html_production_runtime.json
→ 读 data/latest_bundle_pointer.json
→ 下载一个 a-share-monitor-html-* artifact
→ 检查 html_validation.json
→ 交付 A股每日市场监控_YYYYMMDD.html
```

不需要寻找 Excel 母表，不需要网页端重新修改图表对象或复制单元格格式。

## 10. Excel 定位

现有复杂 Excel 版本保留为历史参考，不再作为 HTML 正式生产依赖。

如后续需要 Excel，则另行生成“简化数据底表”，并与 HTML 一样只消费 `report_data.json`，不再由 Excel 反向驱动 HTML。
