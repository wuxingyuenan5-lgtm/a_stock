# 申万行业每日跟踪

第一版只跟踪申万一级、二级行业指数的以下数据：

- 收盘价
- 成交额
- 日收益率
- 20 日滚动年化波动率

二级行业会保留对应的申万一级行业名称和代码，便于按一级行业查看各细分板块。

## 数据口径

数据通过 AKShare 获取：

- `sw_index_first_info()`：申万一级行业清单
- `sw_index_second_info()`：申万二级行业及上级行业映射
- `index_hist_sw()`：申万行业指数日线历史数据

日收益率采用简单收益率：

```text
R_t = Close_t / Close_(t-1) - 1
```

20 日年化波动率：

```text
Vol_20,t = Std.S(R_(t-19):R_t) × sqrt(252)
```

因此计算 20 个日收益率至少需要 21 个收盘价。

`index_hist_sw()` 文档没有明确标注历史成交额的单位，本项目第一版保留接口返回的原始数值，不自行缩放，避免错误换算。

## 本地运行

需要 Python 3.11 或以上版本。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python update_sw_industry.py
```

Windows 激活虚拟环境：

```powershell
.venv\Scripts\activate
```

默认每个指数保留最近 260 个交易日。也可以修改：

```bash
python update_sw_industry.py --history-rows 500
```

## 输出文件

运行后生成：

```text
data/sw_industry_history.csv
```

历史长表，字段包括日期、行业层级、一级行业、指数代码、指数名称、收盘价、成交额、日收益率和 20 日年化波动率。

```text
data/sw_industry_latest.csv
```

每个一级、二级行业的最新交易日截面。

若部分指数请求失败，会生成：

```text
data/sw_industry_failures.csv
```

失败指数会优先沿用仓库中已有的历史数据，不会用空值覆盖旧数据。

CSV 使用 UTF-8 BOM 编码，可直接用 Excel 打开。

## 自动更新

GitHub Actions 在每个工作日北京时间 16:30 自动运行，也支持在 Actions 页面手动执行。

若当天是休市日，最新交易日不会变化，通常也不会产生新的数据提交。
