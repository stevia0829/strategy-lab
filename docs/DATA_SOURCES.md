# 真实行情与 PostgreSQL 缓存

## 启动

真实行情模式需要 Python 3.9+、Docker Desktop（或现成 PostgreSQL）和项目的可选驱动：

```sh
make setup-market
make run
```

`setup-market` 创建 `.venv`、安装 `psycopg[binary]`，并用 `compose.yaml` 启动 PostgreSQL 17。数据库只映射到本机 `127.0.0.1:55432`；数据位于 Docker 命名卷 `strategy-lab_strategy_lab_postgres`，`make db-down` **不会删除卷**。需要改密码或连接现有 PostgreSQL 时，设置 `STRATEGYLAB_DATABASE_URL` 并相应修改 Compose 环境变量。样例密码仅用于本机开发，不能照搬到公网部署。服务本身仍只绑定本机 127.0.0.1。

如果已有数据库，可以只装驱动并运行服务：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -e '.[market]'
export STRATEGYLAB_DATABASE_URL='postgresql://USER:PASSWORD@HOST:PORT/DBNAME'
make run
```

浏览器默认打开“真实行情 · 数据库”。策略模板在首次启动时把演示资产映射为 `510300`、`518880`、`511010`，基准为沪深300指数 `000300`，日期默认取北京时间前一日至往前两年；这些代码和日期都可编辑。只有首次/缓存过期/请求区间扩展时才访问公开接口。也可以切回“合成演示”或导入本地 CSV。

## 实际数据流

1. 配置中的股票/ETF 代码须为六位沪深代码；最多 50 只。基准额外支持 `000300`（沪深300指数，非可交易 ETF）。页面使用公开日线，股票/ETF 采用**前复权（qfq）**，指数本身没有分红复权口径。单次回测仅执行选定的 Python 或 Go 引擎，两者读取同一份 PostgreSQL 导出的 CSV。
2. 根据指标最长周期把请求开始日提前，用于预热。数据库 `market_coverage` 记录每个代码已完整请求过的日期范围与抓取时刻，`market_bars` 按 `来源 + 复权口径 + 代码 + 日期` 去重存储 OHLCV。
3. 若任一数据源的覆盖范围包含目标且抓取时间不到 24 小时，就直接读取数据库。否则优先尝试东方财富；连接或数据质量错误时尝试腾讯。每只资产本次只使用一个来源，行情与覆盖范围按来源分别保存；前复权历史可能因后续分红而重算，所以刷新时重新写入该来源的历史价格。按代码持有数据库事务锁，避免并发重复抓取。
4. 返回结果保留 `source=market`、`source_meta`（逐资产提供方、复权口径、查询区间、缓存命中和更新代码、条数、查询时刻）与引擎使用的 CSV SHA256。两个公开接口、数据库或数据质量都失败时会直接显示错误，不会悄悄改用演示数据。

页面上的 `source_meta.fetched_symbols` 只说明该次从接口更新过，不表示首次入库。`cached_symbols` 表示该次未请求公网，全部来自数据库。完整实验 JSON 可用于核对。

## 上游口径与限制

- 接口：东方财富 `push2his.eastmoney.com/api/qt/stock/kline/get`，固定域名和日线参数 `klt=101`、前复权 `fqt=1`。字段按日期、开、高、低、收、成交量解析；不会执行外部返回的代码。这里使用网页公开行情接口，它不是有服务等级保证的正式数据合同，可能限流、改版或停止服务。接口口径参考 [AKShare 官方 ETF 日线文档](https://github.com/akfamily/akshare/blob/main/docs/data/fund/fund_public.md) 与 [A 股实现](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hist_em.py)。
- 备用接口：腾讯 `proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get`，逐年请求前复权日线，避免单次 640 根 K 线限制。接口与字段口径参考 [AKShare 腾讯日线实现](https://github.com/akfamily/akshare/blob/master/akshare/stock_feature/stock_hist_tx.py)。这同样是非正式公开接口；结果中的 `source_meta.symbol_providers` 会列出逐资产实际来源。
- 只在所选日期已有收盘数据后回测；不将当日尚未完成的 K 线当成历史。接口文档说明当日收盘价需在收盘后取得。数据质量与停牌、节假日、上市时间须由使用者核验。
- 前复权可以帮助技术指标保持连续，但历史价格会随未来分红调整；这不是严格时点复原的历史数据。旧请求超过 24 小时会刷新缓存，降低不同复权基准混用的风险。
- 接口未提供价格涨跌停价，本模式无法执行涨跌停拒单模拟；成交量仅用于识别零量日，没有容量或冲击成本模型。分红现金流、退市、幸存者偏差与成分股历史不在这个数据源中建模。
- 没有足够的指标预热期时，早期信号可能不可用；接口返回空或缺资产会报错。数据库不记录仓位、用户账户或 API 密钥。

## 验证

```sh
make test
make parity
make test-market
```

`test-market` 在独立临时 schema 中做数据库读写与缓存测试，不清理真实行情表。真正的端到端检查应先用较短的真实 ETF 区间运行一次，再原样运行第二次确认 `source_meta.cached_symbols` 命中；扩大结束日期可确认增量请求会更新缓存。
