# A股每日监控生产链路 v1

## 目标

把每日更新从“临时抓数据 + 手工改 Excel”变成固定的数据生产接口。

正式链路：

```text
Data Collector
  -> Normalizer
  -> daily_payload.json
  -> Validator
  -> Excel Renderer
```

v1 已实现前四步。Excel Renderer 将以冻结母表为模板消费 `daily_payload.json`，不再负责研究或重新定义口径。

## 一键运行

```bash
python run_daily.py --target-date 2026-08-10
```

日更入口只允许生产中国时区“当天”收盘快照；历史回填继续走专用 backfill 流程，避免把当前行情误标成历史日期。

输出：

```text
output/2026-08-10/
  daily_payload.json
  validation.json
  source_manifest.json
  hot_stocks.csv
  all_a_snapshot.csv
  sw_analysis_daily_second.csv
```

## 每日增量原则

- 全 A 市场历史只追加当天一行：`data/history/market_core.csv`
- 创新药历史只请求上次有效日附近到目标日，之后去重追加
- 申万个股行业映射从每日链路拆出，由每周任务刷新到 `data/cache/sw_stock_mapping.csv`
- 正常日不重新跑 1 月至今的全市场历史
- 单个指数、申万或创新药上游失败时降级为 WARN，不让已成功的核心市场数据重跑

## payload 契约

`daily_payload.json` 是所有展示端的唯一输入，主要包含：

- `market`: 上涨/下跌/平盘、涨跌停、全 A 成交额、市场宽度
- `indices`: 上证50、Choice微盘、中证全指
- `hot_stocks`: 成交额 >= 100 亿元个股及申万行业映射
- `sw_crowding`: 通信设备、计算机设备、元件、半导体
- `innovation_drug`: 独立创新药主题
- `rendering`: 表格倒序、图表正序

## 申万拥挤度

申万日度分析接口直接提供换手率和成交额占比，二者都按百分数点返回，生产层统一转换成 0-1 小数。

若申万最新有效日落后于市场目标日：

- 保留申万最新有效日期
- 成交额占比使用申万官方字段
- 不用目标日全 A 成交额反推滞后日行业成交额
- 缺少同日分母时，行业成交额保持空值，而不是伪造 0

## 创新药

创新药不并入申万 05，独立作为主题页。

正式生产口径统一切换为东方财富“创新药”概念板块：

- 历史接口直接提供收盘、成交量、成交额、涨跌幅和换手率
- 换手率直接使用供应商历史字段，不再用流通股本倒算
- 成交额统一从元转换为亿元
- 成交额占全 A 仍使用同日 `market_core.csv` 的全 A 成交额作为分母
- 若历史日线尚未更新到当天，则使用同一东方财富概念板块实时接口补当天成交额、涨跌幅和换手率
- `20日成交量活跃度代理`继续保留为辅助指标，但不再替代换手率

## GitHub Actions

`.github/workflows/daily_market_monitor.yml`

- 工作日北京时间 16:40 自动执行
- 支持手工运行当天任务
- PR 会跑单元测试和一次真实数据 dry-run，但不会写回历史数据
- 只持久化增量 history/cache 和 JSON 归档
- 大体量股票快照只放 Action artifact，避免仓库膨胀

`.github/workflows/refresh_sw_mapping.yml`

- 每周一北京时间 08:00 刷新申万个股到二级行业映射
- 把慢速行业成分请求从每日生产链路移除

## 下一阶段：Excel Renderer

冻结一份正式母表后，Renderer 只做三件事：

1. 读取 `daily_payload.json`
2. 把当天数据写入固定表位，并刷新图表数据源
3. 运行 workbook validator 后导出 `A股每日市场监控_YYYYMMDD.xlsx`

Renderer 不再访问外部行情 API，也不重新计算业务口径。
