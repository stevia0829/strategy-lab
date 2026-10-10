# 自写策略与 Agent

## 决策接口

在“策略输入”页选择 Python 或 Go，编写 `decide` 函数。它在每个交易日收盘后调用一次，返回**下一交易日想持有的资产代码列表**；返回空列表表示转为现金。引擎仍在下一交易日开盘按手续费、滑点、可用资金、持仓上限和成交限制执行。策略代码不负责直接下单，也不能调用聚宽的 `jqdata`。

Python：`def decide(ctx): return ['510300']`。`ctx` 是字典，含 `date`、`history`、`positions`、`cash`、`equity`。`history[code]` 是截至信号日的 OHLCV 字典列表，包含 `date/open/high/low/close/volume/limit_up/limit_down`。可从 `strategylab.engine` 导入 `indicator` 计算 `rsi/macd/sma` 等指标。

Go：`func Decide(ctx engine.Context) []string`，源文件使用 `package main` 并导入 `strategylab/engine`。`Context` 含 `Date`、`History map[string][]engine.Bar`、`Positions map[string]int`、`Cash`、`Equity`。`engine.Calculate` 返回指标序列；预热前的值为 `NaN`，应先用 `math.IsNaN` 检查。仓位代码必须在配置的资产池中，不得重复，数量不能超过最大持仓数。

可以从 [Python RSI 示例](../examples/custom_rsi.py) 或 [Go RSI 示例](../examples/custom_rsi.go) 开始。真实行情模式中，代码里明确写出的六位沪深股票或 ETF 字符串会自动补入本次资产池，再按需拉取行情；动态遍历 `ctx.history` 的策略仍以手动填写的资产池为范围。比较基准单独配置。单次公开行情查询最多 100 个代码（含基准），不影响分次研究不同 A 股。上传文件或在编辑器粘贴代码后，选择相应语言和行情，运行回测。完整报告保留代码和 SHA256 指纹，历史记录可重新打开。代码策略不会自动从聚宽源文件迁移。

回测报告顶部的“查看策略详情”展示该次回测的实际资产池、仓位与费用参数，以及保存的完整源代码；这是历史快照，不受后续编辑影响。代码策略还可点“基于此策略继续优化”：页面会载入当时的代码和已保存的生成会话，并显示本轮将引用的回测反馈。反馈包含区间、数据类型、收益与风险指标、成交笔数、拒单原因及缺失行情天数；Agent 会结合本轮修改要求使用这些信息。早期记录没有会话文本时仍可从当时的代码继续。用户可移除反馈；编辑代码、切换语言或生成新版代码后，旧反馈自动移除，需重新回测才能评价新版代码。

## Agent 生成代码

选择 DeepSeek、GPT / OpenAI、MiniMax、GLM 或 Kimi，选择官方模型 ID，也可以选“自定义模型 ID”输入供应商提供的 ID。填写该服务的 API Key 和自然语言策略描述。系统只向该服务发送当前策略描述与 `decide` 接口说明，返回的代码进入编辑器供人工检查；**生成动作不自动运行代码或回测**。API Key 不写入数据库、日志或下载的报告。当前固定使用各家的官方 Chat Completions 地址，不接受自定义转发 URL。

生成提示现在使用项目内的 [strategy-lab-script Skill](../.agents/skills/strategy-lab-script/SKILL.md)。网页把当前资产池、基准和最大持仓数一并提交给本机服务；服务端从 Skill 文件读取决策接口、因果性和日线执行约束，再通过 HTTPS 请求所选模型，并先检查返回代码的入口函数与基本语法。响应带有 Skill 名称和内容指纹，便于确认使用的是哪版提示。该 Skill 也可在本项目的 Codex 工作目录中复用。用户的 API Key 不写进 Skill、代码仓库或历史记录。

Skill 要求生成代码在文件开头交代实际资产池、资产用途、决策流程与执行时点，并为指标、预热、入退场和防守等关键代码段写中文原理与流程注释。后续会话以右侧当前代码为基线，并携带最近的生成轮次；未明确要求的规则尽量保留。浏览器本地保存当前代码、配置、数据来源和最近会话供刷新后继续；运行回测后，这些会话也进入对应的 PostgreSQL 历史记录。导入的 CSV 内容不会写入浏览器会话或回测记录，刷新或重新打开该类历史报告后需重新导入相同 CSV 才能再回测。历史记录与浏览器均不保存 API Key，模型推理分段也不保存。不要在策略描述中输入密钥。

生成面板会通过 SSE 展示输入校验、模型连接、服务商返回的推理分段、代码分段和语法校验。DeepSeek 生成请求启用 thinking 模式时，若接口返回 `reasoning_content`，页面逐段展示；其他模型未返回推理内容时只展示实际执行节点和代码流。推理文本不会写入回测记录。生成过程中可停止请求、修改描述并重新生成；若描述在生成期间改变，旧请求的草稿不会覆盖编辑器。

模型建议（2026-09-23 核对；下拉框展示名会映射到官方 API 模型 ID，排行榜展示名不可直接复制）：

| 服务 | 默认 ID | 其他选项 | 密钥来源与接口 |
| --- | --- | --- | --- |
| DeepSeek | `deepseek-flash`（V4.1 Flash） | `deepseek-v4-pro`、自定义 | [官方 API](https://api-docs.deepseek.com/quick_start/pricing/) |
| GPT / OpenAI | `gpt-6-sol` | `gpt-6-astra`、`gpt-6-luna`、`gpt-5.6-sol`、`gpt-5.6-terra`、`gpt-5.6-luna`、`gpt-5.5`、`gpt-5.4` | [OpenAI API](https://developers.openai.com/api/docs/models)；ChatGPT Pro 订阅不含 API 用量 |
| MiniMax | `MiniMax-M3` | `MiniMax-M2.7` | [MiniMax OpenAI 兼容 API](https://platform.minimax.io/docs/api-reference/text-openai-api) |
| GLM / Z.ai 国际站 | `glm-5.3` | `glm-5.2` | [Z.ai API](https://docs.z.ai/guides/llm/glm-5.3) 与国际站密钥 |
| GLM / 智谱国内站 | `glm-5.2` | 自定义 | `open.bigmodel.cn` 与国内站密钥 |
| Kimi 国际站 | `kimi-k3` | `kimi-k2.7-code`、`kimi-k2.6` | [Kimi K3 API](https://platform.kimi.ai/docs/guide/kimi-k3-quickstart) 与国际站密钥 |
| Kimi 国内站 | `kimi-k2.6` | 自定义 | [Kimi 国内站 API](https://platform.kimi.com/docs/api/chat) 与国内站密钥 |

国内站与国际站不能混用 API Key。模型供应商可能调整 ID、配额及价格；自定义 ID 仅用于同一服务对应的官方接口。项目不提供模型额度，也不使用你的 ChatGPT 订阅额度。

## 执行边界

网页服务只负责数据、记录和展示，自写代码由独立 worker 容器执行；本机运行 `make setup-market` 启动 worker，服务器部署使用 `compose.deploy.yaml`。worker 不接入网络，不接收数据库或模型密钥；容器只挂载任务卷，根文件系统只读，并限制进程与内存。部署仍应只供管理员使用；容器隔离不是可向不可信公众开放的多租户沙箱。若只运行 `make run` 而未启动 worker，代码模式会提示先运行 `make setup-market`。

回测记录保存策略配置、用户代码、生成会话和结果，因此 PostgreSQL 的备份也包含策略代码与策略描述。请勿把密钥写进策略源文件或描述。历史记录目前保留最近 100 条列表，但数据库不自动删除旧记录；容量规划和备份由部署者负责。

Agent 使用 LangGraph 的准备 → 模型生成 → 代码校验节点。网页通过本地 SSE 显示图节点、模型实际返回的推理片段和代码片段；只有代码校验通过后才放入编辑器。模型未提供推理片段时，只显示流程节点。单次流式读取超时为 180 秒，用户可中止请求、修改描述后重试。API Key 只在本次请求的内存中使用，不进入图事件、历史回测或日志。
