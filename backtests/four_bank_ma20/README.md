# 四大行 MA20 组合回测数据

本目录为以下策略准备可审计的日频数据：

- 信号：上证指数收盘价相对 20 日均线的跌破与上穿；
- 持仓：中国银行、工商银行、建设银行、农业银行；
- 组合：开仓时四只股票等权配置；
- 成交：信号确认后的下一交易日开盘价；
- 公司行为：使用不复权价格成交，现金分红、送股和转增单独记账。

## 标的

| 标准代码 | 名称 | 用途 |
|---|---|---|
| `sh.000001` | 上证指数 | 择时信号 |
| `sh.601988` | 中国银行 | 组合持仓 |
| `sh.601398` | 工商银行 | 组合持仓 |
| `sh.601939` | 建设银行 | 组合持仓 |
| `sh.601288` | 农业银行 | 组合持仓 |

默认下载区间从 `2011-01-01` 至运行当日。

## 数据源

行情数据直接通过东方财富公开 HTTPS 日线接口获取，参数 `fqt=0`，即不复权价格。固定使用已知的上海市场 `secid`，避免先调用全市场代码映射接口。

公司行为通过 AKShare 的 `stock_fhps_detail_em()` 获取，其底层为东方财富分红送配详情数据。接口返回的现金分红、送股和转股比例按每 10 股口径转换为每股口径。

下载失败时工作流直接报错，不会静默使用调整价或其他数据覆盖。

## 输出文件

运行后写入 `data/four_bank_ma20/`：

- `daily_prices_unadjusted.csv`：五个标的的长表日线；
- `corporate_actions.csv`：四只银行股的现金分红、送股、转增及相关日期；
- `open_prices_wide.csv`：开盘价宽表，便于回测撮合；
- `close_prices_wide.csv`：收盘价宽表，便于信号和每日估值；
- `manifest.json`：生成时间、数据区间、行数和各标的覆盖范围。

CSV 使用 UTF-8 BOM，可直接用 Excel 打开。

## 核心字段

`daily_prices_unadjusted.csv`：

- `date`：交易日；
- `code`：标准代码；
- `open/high/low/close/preclose`：不复权价格；
- `volume_raw`：数据源原始成交量字段，不自行改变单位；
- `amount`：成交额；
- `amplitude_pct`、`pct_change_pct`、`turnover_pct`：百分比口径字段；
- `trade_status`：返回日均记为可交易日；
- `source`：实际数据源。

`corporate_actions.csv`：

- `report_date`：分红方案对应报告期；
- `record_date`：股权登记日；
- `ex_date`：除权除息日；
- `cash_before_tax_per_share`：每股税前现金股利；
- `stock_dividend_per_share`：每股送股数量；
- `capitalisation_issue_per_share`：每股转增数量；
- `plan_status`、`plan_description`：方案状态和原始描述。

东方财富详情接口没有稳定提供实际派息到账日，因此 `payment_date` 暂为空。回测引擎应在除权除息日同步计入应收股利，避免不复权价格除息下跌造成虚假损失。

## 本地运行

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python backtests/four_bank_ma20/download_data.py
```

指定区间：

```bash
python backtests/four_bank_ma20/download_data.py \
  --start-date 2011-01-01 \
  --end-date 2026-07-31
```

脚本会检查：

- `date + code` 是否重复；
- OHLC 关系是否有效；
- 每个标的历史行数是否明显不足；
- 最新交易日是否与请求截止日相距过久；
- 四只银行股是否均有公司行为记录。
