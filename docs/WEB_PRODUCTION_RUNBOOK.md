# 网页生成 A股每日市场监控｜最短执行清单

用户指令：`生成今天的 A 股每日市场监控`

网页端只执行以下动作：

1. GitHub 读取 `data/latest_bundle_pointer.json`。
2. 按 pointer 的 `run_id + artifact_name` 下载一个 workflow artifact。
3. 读取 artifact 内 `web_production_manifest.json`。
4. 定位 `expected_mother_filename` 指向的上一交易日正式工作簿。
5. 不修改母表图表对象；直接执行 bundle 自带 `run_excel_renderer_v14.py`。
6. 读取 `.renderer_validation.json`：
   - PASS：交付；
   - WARN：说明缺失项后交付；
   - FAIL：停止。
7. 输出文件名严格为 `A股每日市场监控_YYYYMMDD.xlsx`。

禁止：
- 找不到母表时自己重建；
- 手工重新设计首页；
- 删除/新增图表；
- 跨源补空值；
- 把 GitHub artifact 当成最终 Excel 附件；
- Renderer FAIL 后退回自由生成。

母表二进制如果无法从 File Library 直接 materialize 到当前运行时，只允许用户补一次“选择/附加上一交易日正式表”，然后继续执行；不再进行其他人工步骤。
