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
- 申万个股行业映射最多每 7 天刷新一次，缓存到 `data/cache/sw_stock_mapping.csv`
- 正常日不重新跑 1 月至今的全市场历史
- 某个上游失败由该 collector 自己重试，不触发已成功模块重复抓取

## payload 契约

`daily_payload.json` 是所有展示端的唯一输入，主要包含：

- `market`: 上涨/下跌/平盘、涨跌停、全 A 成交额、市场宽度
- `indices`: 上证50、Choice微盘、中证全指
- `hot_stocks`: 成交额 >= 100 亿元个股及申万行业映射
- `sw_crowding`: 通信设备、计算机设备、元件、半导体
- `innovation_drug`: 独立创新药主题
- `rendering`: 表格倒序、图表正序

## 创新药

创新药不并入申万 05。

当前采用同花顺创新药概念指数 886015：

- 成交额、成交量、指数收益可历史增量更新
- 成交额占全 A 由同日全 A 成交额作为分母
- 历史板块总换手率暂不伪造
- `20日成交量活跃度代理`独立保留，明确不等同于换手率

## GitHub Actions

`.github/workflows/daily_market_monitor.yml`

- 工作日北京时间 16:40 自动执行
- 支持手工输入目标日期
- 只持久化增量 history/cache 和 JSON 归档
- 大体量股票快照只放 Action artifact，避免仓库膨胀

## 下一阶段：Excel Renderer

冻结一份正式母表后，Renderer 只做三件事：

1. 读取 `daily_payload.json`
2. 把当天数据写入固定表位，并刷新图表数据源
3. 运行 workbook validator 后导出 `A股每日市场监控_YYYYMMDD.xlsx`

Renderer 不再访问外部行情 API，也不重新计算业务口径。
