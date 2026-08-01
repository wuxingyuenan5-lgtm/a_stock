# 四大行 MA20 组合回测数据

本目录为以下策略准备可审计的日频数据：

- 信号：上证指数收盘价相对 20 日均线的跌破与上穿；
- 持仓：中国银行、工商银行、建设银行、农业银行；
- 组合：开仓时四只股票等权配置；
- 成交：信号确认后的下一交易日开盘价；
- 公司行为：使用不复权价格成交，现金分红、送股和转增单独记账。

## 标的

| BaoStock 代码 | 名称 | 用途 |
|---|---|---|
| `sh.000001` | 上证指数 | 择时信号 |
| `sh.601988` | 中国银行 | 组合持仓 |
| `sh.601398` | 工商银行 | 组合持仓 |
| `sh.601939` | 建设银行 | 组合持仓 |
| `sh.601288` | 农业银行 | 组合持仓 |

默认下载区间从 `2011-01-01` 至运行当日。

## 数据源与降级规则

主数据源为 BaoStock：

- `query_history_k_data_plus(..., frequency="d", adjustflag="3")`：不复权日线；
- `query_dividend_data(..., yearType="operate")`：按除权除息年度查询公司行为。

若某项 BaoStock 请求失败，脚本仅对该项降级使用 AKShare，并在每行的 `source` 字段及 `manifest.json` 中明确记录，不会静默混用。

## 输出文件

运行后写入 `data/four_bank_ma20/`：

- `daily_prices_unadjusted.csv`：五个标的的长表日线；
- `corporate_actions.csv`：四只银行股的现金分红、送股、转增及相关日期；
- `open_prices_wide.csv`：开盘价宽表，便于回测撮合；
- `close_prices_wide.csv`：收盘价宽表，便于信号和每日估值；
- `manifest.json`：生成时间、数据区间、行数、各标的实际数据源。

CSV 使用 UTF-8 BOM，可直接用 Excel 打开。

## 核心字段

`daily_prices_unadjusted.csv`：

- `date`：交易日；
- `code`：标准代码；
- `open/high/low/close/preclose`：不复权价格；
- `volume`：成交量；
- `amount`：成交额；
- `trade_status`：交易状态；
- `pct_change_pct`：数据源返回的百分比涨跌幅；
- `source`：实际数据源。

`corporate_actions.csv`：

- `record_date`：股权登记日；
- `ex_date`：除权除息日；
- `payment_date`：派息日；
- `cash_before_tax_per_share`：每股税前现金股利；
- `stock_dividend_per_share`：每股送股数量；
- `capitalisation_issue_per_share`：每股转增数量。

回测时不应使用前复权价格下单。正确处理方式是：持仓跨越权益登记条件时，在相应公司行为日期增加现金或调整持股数量。

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
- 最新交易日是否与请求截止日相距过久。
