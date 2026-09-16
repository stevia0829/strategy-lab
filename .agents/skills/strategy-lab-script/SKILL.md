---
name: strategy-lab-script
description: 根据自然语言生成或修改 Strategy Lab 的 Python／Go 日线 decide 策略脚本；用于平台 Agent 草稿和该项目内的策略代码请求。
---

# Strategy Lab 策略脚本

把用户描述变成可审阅、可回测的完整源文件。优先遵守用户明确给出的资产池、指标周期、入退场和风险条件；条件不足时在代码注释中写明少量必要假设，不暗自声称策略有效。

- 策略在每个交易日收盘后收到 `ctx`，只能读取 `ctx.history` 中截至当天的行情，返回下一交易日希望持有的资产代码列表。空列表表示现金。引擎负责下一交易日开盘成交、现金、仓位上限、整手、手续费、滑点与拒单；脚本不直接下单，也不实现盘中交易。
- 目标只能来自本次资产池，不能重复，数量不能超过 `max_positions`。指标预热不足或缺数据时要明确处理；不能用未来行情、`jqdata`、网络、文件读写、环境变量或密钥。不要把用户的 API Key 写进生成代码。
- Python 输出完整 `.py` 源码，提供顶层 `def decide(ctx):`。`ctx` 是字典，含 `date`、`history`、`positions`、`cash`、`equity`；`history[code]` 是截至信号日的 OHLCV 字典列表。可用 `from strategylab.engine import indicator`，调用 `indicator(bars, {'kind': 'rsi', 'period': 14})`；预热值为 `None`。
- Go 输出完整 `package main` 源码，提供 `func Decide(ctx engine.Context) []string`，导入 `strategylab/engine`。`ctx.History` 是 `map[string][]engine.Bar`；`engine.Calculate(bars, engine.Indicator{Kind: "rsi", Period: 14})` 计算指标，预热值为 `NaN`，需用 `math.IsNaN` 判断。
- 仅在日线可执行的信号上做风控。需要止损或减仓时，把它表述为收盘信号和次日开盘目标，不能承诺盘中价格触发或保证成交。

如果是平台的 Agent 草稿请求，只返回源代码，不加 Markdown 围栏或收益承诺；草稿不会自动运行。若在有工具的开发环境里直接交付脚本，先做语法检查与一组小规模合成数据回测，并明确合成结果只验证执行链路。
