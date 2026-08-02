# 四大行 MA20 组合回测

本目录包含数据下载脚本、完整回测引擎、单元测试和 GitHub Actions。

## 默认策略

- 择时标的：上证指数 `sh.000001`；
- 均线：20 个交易日简单移动平均线；
- 开仓：上证指数收盘价由上向下跌破 MA20，在下一可交易日开盘买入；
- 平仓：上证指数收盘价由下向上突破 MA20，在下一可交易日开盘卖出；
- 持仓：中国银行、工商银行、建设银行、农业银行；
- 配置：四只股票等权，按 100 股整数手买入，持有期间不再平衡；
- 价格：使用不复权开盘价成交、不复权收盘价估值；
- 公司行为：在除权除息日、当日开盘成交前，显式计入现金分红、送股和转增；
- 样本末仍持仓时按最后收盘价估值，不伪造下一交易日开盘价强制平仓。

信号模式可以切换为趋势跟随：上穿 MA20 买入、下穿 MA20 卖出。

## 默认成本参数

| 参数 | 默认值 |
|---|---:|
| 初始资金 | 1,000,000 元 |
| 佣金率 | 0.03% |
| 单笔最低佣金 | 5 元 |
| 滑点 | 0 bps |
| 股息税率 | 0% |
| 卖出印花税 | 历史口径 |

历史印花税口径：2023-08-28 以前按卖出金额的 0.1%，此后按 0.05%。所有参数均可通过命令行修改。

## 数据标的

| 标准代码 | 名称 | 用途 |
|---|---|---|
| `sh.000001` | 上证指数 | MA20 信号 |
| `sh.601988` | 中国银行 | 组合持仓 |
| `sh.601398` | 工商银行 | 组合持仓 |
| `sh.601939` | 建设银行 | 组合持仓 |
| `sh.601288` | 农业银行 | 组合持仓 |

## 数据文件

`download_data.py` 生成：

```text
data/four_bank_ma20/
├── daily_prices_unadjusted.csv
├── corporate_actions.csv
├── open_prices_wide.csv
├── close_prices_wide.csv
└── manifest.json
```

行情通过腾讯证券公开 HTTPS 日线接口按两年区间下载。公司行为通过 AKShare 的 `stock_fhps_detail_em()` 获取。

若源数据的最高价或最低价不能包络开盘价、收盘价，脚本会保留 `high_raw/low_raw`，确定性修复可用 `high/low`，并写入 `quality_flag=ohlc_bounds_repaired`；修复记录超过阈值时直接终止。

## 回测输出

`backtest.py` 默认写入：

```text
results/four_bank_ma20/
├── summary.json
├── report.md
├── equity_curve.csv
├── annual_returns.csv
├── trades.csv
├── fills.csv
├── signal_ledger.csv
├── corporate_action_ledger.csv
└── signals.csv
```

其中：

- `report.md`：核心绩效、交易统计、年度收益和口径说明；
- `summary.json`：结构化汇总；
- `equity_curve.csv`：策略、四大行买入持有和上证指数价格基准的每日净值；
- `trades.csv`：每轮完整交易；
- `fills.csv`：四只股票逐笔成交、佣金和印花税；
- `signal_ledger.csv`：信号是否被执行或忽略；
- `corporate_action_ledger.csv`：持仓期间实际计入的现金分红和送转；
- `signals.csv`：指数、MA、交叉方向和原始信号。

## Windows 本地运行

在仓库根目录打开 PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python backtests/four_bank_ma20/backtest.py
```

测试：

```powershell
python -m unittest discover -s backtests/four_bank_ma20 -p "test_*.py" -v
```

若需要重新下载数据：

```powershell
python backtests/four_bank_ma20/download_data.py --start-date 2011-01-01
```

## 常用参数

均值回归默认版本：

```powershell
python backtests/four_bank_ma20/backtest.py `
  --initial-capital 1000000 `
  --ma-window 20 `
  --signal-mode mean_reversion `
  --commission-rate 0.0003 `
  --minimum-commission 5 `
  --slippage-bps 0 `
  --dividend-tax-rate 0 `
  --stamp-duty-mode historical
```

加入 5 bps 单边滑点：

```powershell
python backtests/four_bank_ma20/backtest.py --slippage-bps 5
```

切换为趋势跟随：

```powershell
python backtests/four_bank_ma20/backtest.py --signal-mode trend_following
```

固定印花税或完全忽略印花税：

```powershell
python backtests/four_bank_ma20/backtest.py --stamp-duty-mode fixed --fixed-stamp-duty-rate 0.0005
python backtests/four_bank_ma20/backtest.py --stamp-duty-mode none
```

## 无未来函数约束

- MA 与交叉信号只使用当日及此前收盘价；
- 信号必须到当日收盘后才确认；
- 买卖价格严格取下一可交易日开盘价；
- 不能取得下一交易日开盘价时，不执行该信号；
- 公司行为在除权除息日开盘前处理，避免买入除权日股票却错误取得股息。

## 自动运行

`.github/workflows/run_four_bank_ma20_backtest.yml` 会自动：

1. 安装依赖；
2. 编译检查；
3. 运行单元测试；
4. 执行默认回测；
5. 上传完整结果；
6. 在分支 push 事件中将结果提交回当前分支。
