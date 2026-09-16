# Strategy Lab

**配置策略，运行回测，检查收益与风险。** 一个可本地运行、可独立开源的日线策略研究工作台。真实行情采用 PostgreSQL 缓存，缺失或过期时按需从公开接口更新。

用界面组合 RSI、MACD、均线、动量等条件；选择 **Python（默认）** 或 **Go** 运行即可。两者只是可选的运行方式，各自独立实现；用户不需要比较语言。引擎不依赖聚宽、TA-Lib、pandas 或 NumPy；真实行情模式需要 PostgreSQL 和可选的 `psycopg` 驱动。

> 界面默认使用真实行情和 PostgreSQL 缓存。另有 **800 个合成工作日、3 个虚构资产** 的演示数据，只用于验证程序；不能用演示收益证明策略有效。

## 快速开始

默认的真实行情模式需要 Python 3.9+、Docker Desktop 和 PostgreSQL 驱动：

```sh
make setup-market
make run
```

打开 [http://127.0.0.1:8765](http://127.0.0.1:8765)。默认资产是 510300、518880、511010；首次回测会从公开日线接口抓取并写入 PostgreSQL，下一次相同区间优先查库。数据库及复权规则见 [真实行情说明](docs/DATA_SOURCES.md)。Docker 只提供数据库，界面和两套回测引擎仍在本机运行。

已有 PostgreSQL 时，可设置 `STRATEGYLAB_DATABASE_URL` 并安装 `pip install -e '.[market]'`。Go 作为可选回测引擎需要 Go 1.23+，选择它时才会编译；网页无需 Node.js。只想检查规则时可在页面把数据来源切为“合成演示”，该模式不需要数据库。服务仅监听 127.0.0.1。

## 可以做什么

- 可视化增删入场/退出条件，支持 AND、OR、指标相互比较、数值阈值、上穿/下穿。
- 调整周期、MACD 参数、持仓数、排名方向、资金、手续费、滑点、交易单位和入场仓位上限。
- JSON 导入/导出，支持嵌套 AND/OR/NOT；复杂表达式保留在 JSON 中，不会被界面悄悄扁平化。
- 默认从 PostgreSQL 读取真实沪深股票/ETF 日线，缺失或过期时先尝试东方财富公开接口，连接失败则使用腾讯公开接口；实际来源逐资产记录。也可导入本地多资产 OHLCV CSV。
- 默认使用 Python；可切换为 Go，每次只执行所选运行方式。
- 显示日净值、最大回撤及恢复天数、Sharpe、Calmar、成本、实际仓位、订单、拒单。
- 下载完整实验 JSON 与成交 CSV。完整实验包含策略快照、数据与策略指纹、每日目标及持仓。
- 自带 RSI + MACD、RSI 回落后上穿、21 日动量轮动、买入持有四个可编辑模板。

## 不编写策略代码

例如“RSI < 35 且收盘高于 MA60”可以直接在界面配置，也可以写成：

```json
{
  "all": [
    {"left": "rsi14", "op": "lt", "right": 35},
    {"left": "close", "op": "gt", "right": "sma60"}
  ]
}
```

指标定义：

```json
{
  "rsi14": {"kind": "rsi", "period": 14},
  "sma60": {"kind": "sma", "period": 60},
  "macd_hist": {"kind": "macd", "fast": 12, "slow": 26, "signal": 9, "output": "hist"}
}
```

支持 `sma / ema / rsi / macd / roc / momentum_score / atr / highest / lowest`，以及 OHLCV 原始字段。完整配置参见 [examples/trend.json](examples/trend.json) 和 [执行规范](docs/SEMANTICS.md)。

指标目录之外的新指标仍需要分别实现两种语言版本并增加一致性测试；不能把任意表达式字符串当代码执行。

## 独立命令行

Go：

```sh
go run ./cmd/strategy-lab -strategy examples/trend.json -data examples/demo.csv -out /tmp/go-result.json
```

Python（**这条命令完全不需要 Go**）：

```sh
PYTHONPATH=python python3 -B -m strategylab --strategy examples/trend.json --data examples/demo.csv --out /tmp/python-result.json
```

Go 程序可调用 `engine.ParseStrategy` 和 `engine.Run`。Python 程序可调用：

```python
import json
from pathlib import Path
from strategylab import run

strategy = json.loads(Path("examples/trend.json").read_text())
data = Path("examples/demo.csv").read_bytes().decode("utf-8")
report = run(strategy, data)
```

**现有依赖 `jqdata` 的 `.py` 或任意 Go 策略不会自动转换。** 当前跨语言接口是相同的策略配置与行情协议；平台不执行用户上传的源代码。原 B 策略中的跨资产轮动速度与状态机也没有在此自动移植，不能把“21 日动量轮动”模板当成 B 策略。

## 数据格式

```csv
date,symbol,open,high,low,close,volume
2024-01-02,510300,3.500,3.530,3.480,3.510,1000000
2024-01-03,510300,3.520,3.550,3.500,3.530,1100000
```

- 同一文件放多个资产；`symbol` 按文本读取，保留前导零。
- 可增加 `limit_up,limit_down`，单位为当日价格；缺省为 0，表示未提供涨跌停限制。
- `volume=0` 视为不可成交。日期必须为 `YYYY-MM-DD`，重复日期/资产、非有限数和不合理 OHLC 会直接拒绝。
- CSV 可以无序，引擎会排序。最多 100,000 行；网页上传小于 8 MB。
- 使用**同一种复权口径**；引擎不自动除权、派息或处理拆股。复权 OHLC 与原始涨跌停价不可混用。
- 为指标预热，CSV 应包含回测开始日以前的足够历史。资产池、基准代码需要真实存在于文件中。
- 实际日期来自输入行情，示例只排除周末，不模拟交易所节假日。研究真实策略必须使用真实交易日数据。

## 公平验证策略 A/B

选择一种运行方式即可；A/B 应比较策略条件的变化：

1. 固定数据、区间、池子、成本和执行规则，只改变要验证的策略条件，分别导出实验。
2. 比较完整日净值，检查最大回撤、恢复时间、Sharpe/Calmar、建仓数、拒单和实际仓位。
3. 预先划分训练/验证区间，冻结参数后再验证。没有自动寻优或自动授予“有效策略”的功能。

## 开发者测试

```sh
make test
make parity
```

开发测试才需要同时安装两种语言；跨语言核对仅用于维护实现一致性，不是用户回测流程。

测试包含手算成交/费用、持仓期间回撤、恢复天数、缺失行情、涨跌停、指标预热、历史前缀不变性，以及固定随机种子下多指标组合的跨语言对照。测试数据均为合成数据，不能作为投资结论。

## 项目结构

```text
cmd/strategy-lab/        Go 命令行
engine/                 独立 Go 指标、规则、回放与统计
python/strategylab/      独立 Python 引擎与对照器
web/                    无框架的可视化工作台
server.py               本地 HTTP 服务与固定引擎进程调度
compose.yaml             本机 PostgreSQL 17 服务
python/strategylab/market.py 公开行情、缓存与来源记录
compare.py              开发者实现一致性检查
examples/               JSON 模板、可重复生成的合成行情
schema/                 Strategy IR v1 JSON Schema
tests/                 Python 与跨语言测试
docs/                  指标口径、设计与验收记录
```

## 当前边界

当前支持日线、只做多、无杠杆、下一交易日开盘成交。没有实盘交易、分钟级撮合、盘口冲击模型、卖空、参数优化或多人账户。持仓上限在入场执行，已有持仓价格上涨后可以超过上限，不会隐式每日减仓。

本机服务不是面向公网的生产托管服务，没有用户认证；不要将端口直接暴露到公网。真实行情来自网页公开接口，并非有服务等级保证的交易所数据服务。固定引擎在独立子进程运行并有超时限制，但这不是运行任意用户 Python/Go 源码的安全沙箱。

## 开源与参考

采用 [MIT License](LICENSE)。项目可以作为独立仓库发布，已经包含贡献指南、测试工作流与协议说明；当前没有替用户创建或发布 GitHub 远程仓库。

产品思路参考本地 hackthon 的 `strategylab-mvp`：可视化条件 → 版本化 Strategy IR → 确定性验证。这里重新实现了真实资金/持仓回放，不复制其演示收益，不引入 DreamDEX/Somnia SDK 或钱包逻辑。参见 [NOTICE](NOTICE)。
