# 自写策略与 Agent

## 决策接口

在“策略输入”页选择 Python 或 Go，编写 `decide` 函数。它在每个交易日收盘后调用一次，返回**下一交易日想持有的资产代码列表**；返回空列表表示转为现金。引擎仍在下一交易日开盘按手续费、滑点、可用资金、持仓上限和成交限制执行。策略代码不负责直接下单，也不能调用聚宽的 `jqdata`。

Python：`def decide(ctx): return ['510300']`。`ctx` 是字典，含 `date`、`history`、`positions`、`cash`、`equity`。`history[code]` 是截至信号日的 OHLCV 字典列表，包含 `date/open/high/low/close/volume/limit_up/limit_down`。可从 `strategylab.engine` 导入 `indicator` 计算 `rsi/macd/sma` 等指标。

Go：`func Decide(ctx engine.Context) []string`，源文件使用 `package main` 并导入 `strategylab/engine`。`Context` 含 `Date`、`History map[string][]engine.Bar`、`Positions map[string]int`、`Cash`、`Equity`。`engine.Calculate` 返回指标序列；预热前的值为 `NaN`，应先用 `math.IsNaN` 检查。仓位代码必须在配置的资产池中，不得重复，数量不能超过最大持仓数。

可以从 [Python RSI 示例](../examples/custom_rsi.py) 或 [Go RSI 示例](../examples/custom_rsi.go) 开始。上传文件或在编辑器粘贴代码后，选择相应语言和行情，运行回测。完整报告保留代码和 SHA256 指纹，历史记录可重新打开。代码策略不会自动从聚宽源文件迁移。

## Agent 生成代码

选择 DeepSeek、GPT / OpenAI、MiniMax、GLM / 智谱或 Kimi，输入该服务的模型 ID、API Key 和自然语言策略描述。系统只向该服务发送当前策略描述与 `decide` 接口说明，返回的代码进入编辑器供人工检查；**生成动作不自动运行代码或回测**。API Key 不写入数据库、日志或下载的报告。当前固定使用各家的官方 Chat Completions 地址，不接受自定义转发 URL。

各家模型 ID 会变化，界面给出默认值，也允许修改。官方文档：[DeepSeek](https://api-docs.deepseek.com/api/create-chat-completion/)、[OpenAI](https://platform.openai.com/docs/api-reference/introduction)、[MiniMax](https://platform.minimax.io/docs/api-reference/text-chat-openai)、[GLM](https://docs.bigmodel.cn/api-reference/%E6%A8%A1%E5%9E%8B-api/%E5%AF%B9%E8%AF%9D%E8%A1%A5%E5%85%A8)、[Kimi](https://platform.kimi.com/docs/api/chat)。接口调用可能按供应商价格计费；需要用户自己的 Key，项目不提供模型额度。

## 执行边界

网页服务只负责数据、记录和展示，自写代码由 `compose.deploy.yaml` 中的独立 worker 容器执行。worker 不接入网络，不接收数据库或模型密钥；容器只挂载任务卷，根文件系统只读，并限制进程与内存。部署仍应只供管理员使用；容器隔离不是可向不可信公众开放的多租户沙箱。本机仅运行 `make run` 时，代码模式会提示启动完整 Compose 部署。

回测记录保存策略配置、用户代码和结果，因此 PostgreSQL 的备份也包含策略代码。请勿把密钥写进策略源文件。历史记录目前保留最近 100 条列表，但数据库不自动删除旧记录；容量规划和备份由部署者负责。
