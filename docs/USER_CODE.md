# 自写策略与 Agent

## 决策接口

在“策略输入”页选择 Python 或 Go，编写 `decide` 函数。它在每个交易日收盘后调用一次，返回**下一交易日想持有的资产代码列表**；返回空列表表示转为现金。引擎仍在下一交易日开盘按手续费、滑点、可用资金、持仓上限和成交限制执行。策略代码不负责直接下单，也不能调用聚宽的 `jqdata`。

Python：`def decide(ctx): return ['510300']`。`ctx` 是字典，含 `date`、`history`、`positions`、`cash`、`equity`。`history[code]` 是截至信号日的 OHLCV 字典列表，包含 `date/open/high/low/close/volume/limit_up/limit_down`。可从 `strategylab.engine` 导入 `indicator` 计算 `rsi/macd/sma` 等指标。

Go：`func Decide(ctx engine.Context) []string`，源文件使用 `package main` 并导入 `strategylab/engine`。`Context` 含 `Date`、`History map[string][]engine.Bar`、`Positions map[string]int`、`Cash`、`Equity`。`engine.Calculate` 返回指标序列；预热前的值为 `NaN`，应先用 `math.IsNaN` 检查。仓位代码必须在配置的资产池中，不得重复，数量不能超过最大持仓数。

可以从 [Python RSI 示例](../examples/custom_rsi.py) 或 [Go RSI 示例](../examples/custom_rsi.go) 开始。上传文件或在编辑器粘贴代码后，选择相应语言和行情，运行回测。完整报告保留代码和 SHA256 指纹，历史记录可重新打开。代码策略不会自动从聚宽源文件迁移。

## Agent 生成代码

选择 DeepSeek、GPT / OpenAI、MiniMax、GLM 或 Kimi，选择官方模型 ID，也可以选“自定义模型 ID”输入供应商提供的 ID。填写该服务的 API Key 和自然语言策略描述。系统只向该服务发送当前策略描述与 `decide` 接口说明，返回的代码进入编辑器供人工检查；**生成动作不自动运行代码或回测**。API Key 不写入数据库、日志或下载的报告。当前固定使用各家的官方 Chat Completions 地址，不接受自定义转发 URL。

生成提示现在使用项目内的 [strategy-lab-script Skill](../.agents/skills/strategy-lab-script/SKILL.md)。网页把当前资产池、基准和最大持仓数一并提交给本机服务；服务端从 Skill 文件读取决策接口、因果性和日线执行约束，再通过 HTTPS 请求所选模型，并先检查返回代码的入口函数与基本语法。响应带有 Skill 名称和内容指纹，便于确认使用的是哪版提示。该 Skill 也可在本项目的 Codex 工作目录中复用。用户的 API Key 不写进 Skill、代码仓库或历史记录。

模型建议（2026-09-17 核对；这里使用 API 模型 ID，排行榜展示名不可直接复制）：

| 服务 | 默认 ID | 其他选项 | 密钥来源与接口 |
| --- | --- | --- | --- |
| DeepSeek | `deepseek-flash`（V4.1 Flash） | 自定义 | [官方 API](https://api-docs.deepseek.com/updates/) |
| GPT / OpenAI | `gpt-5.6-sol` | `gpt-5.6-terra`、`gpt-5.6-luna`、`gpt-5.1` | [OpenAI API](https://developers.openai.com/api/docs/models/gpt-5.6-sol)；ChatGPT Pro 订阅不含 API 用量 |
| MiniMax | `MiniMax-M3` | `MiniMax-M2.7` | [MiniMax OpenAI 兼容 API](https://platform.minimax.io/docs/api-reference/text-openai-api) |
| GLM / Z.ai 国际站 | `glm-5.3` | `glm-5.2` | [Z.ai API](https://docs.z.ai/guides/llm/glm-5.3) 与国际站密钥 |
| GLM / 智谱国内站 | `glm-5.2` | 自定义 | `open.bigmodel.cn` 与国内站密钥 |
| Kimi 国际站 | `kimi-k3` | `kimi-k2.7-code`、`kimi-k2.6` | [Kimi K3 API](https://platform.kimi.ai/docs/guide/kimi-k3-quickstart) 与国际站密钥 |
| Kimi 国内站 | `kimi-k2.6` | 自定义 | [Kimi 国内站 API](https://platform.kimi.com/docs/api/chat) 与国内站密钥 |

国内站与国际站不能混用 API Key。模型供应商可能调整 ID、配额及价格；自定义 ID 仅用于同一服务对应的官方接口。项目不提供模型额度，也不使用你的 ChatGPT 订阅额度。

## 执行边界

网页服务只负责数据、记录和展示，自写代码由 `compose.deploy.yaml` 中的独立 worker 容器执行。worker 不接入网络，不接收数据库或模型密钥；容器只挂载任务卷，根文件系统只读，并限制进程与内存。部署仍应只供管理员使用；容器隔离不是可向不可信公众开放的多租户沙箱。本机仅运行 `make run` 时，代码模式会提示启动完整 Compose 部署。

回测记录保存策略配置、用户代码和结果，因此 PostgreSQL 的备份也包含策略代码。请勿把密钥写进策略源文件。历史记录目前保留最近 100 条列表，但数据库不自动删除旧记录；容量规划和备份由部署者负责。
