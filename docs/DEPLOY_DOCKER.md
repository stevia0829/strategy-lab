# 在一台服务器上部署 Strategy Lab

`compose.deploy.yaml` 在同一台服务器上运行网页应用、PostgreSQL 和无网络的代码 worker。应用镜像同时包含 Python 引擎和预编译的 Go 引擎；每次回测只运行页面选中的一种。自写代码仅由 worker 执行。行情首次按需从公开接口获取，此后保存在 PostgreSQL 命名卷中。

## 准备

服务器需要可联网的 Linux、Docker Engine 和 Docker Compose 插件，并允许应用容器访问东方财富或腾讯的公开行情接口；代码 worker 不联网。部署时需要能连接 Docker 镜像仓库，以拉取 Python、Go、PostgreSQL 基础镜像。建议至少 4 GB 内存和足够容纳历史行情、回测记录的磁盘空间。使用模型生成代码时，应用容器还需要访问所选模型服务。

```sh
git clone https://github.com/stevia0829/strategy-lab.git
cd strategy-lab
umask 077
printf 'STRATEGYLAB_DB_PASSWORD=%s\nSTRATEGYLAB_APP_PASSWORD=%s\nSTRATEGYLAB_PORT=8765\n' "$(openssl rand -hex 24)" "$(openssl rand -hex 24)" > .env.deploy
docker compose --env-file .env.deploy -f compose.deploy.yaml up -d --build --wait
docker compose --env-file .env.deploy -f compose.deploy.yaml ps
curl -fsS http://127.0.0.1:8765/api/market/status
```

最后一个命令应返回 `"ready": true`。`.env.deploy` 包含数据库密码，已被 Git 忽略；请勿提交或发送给他人。修改密码时不能只改此文件：已有数据库卷内的密码不会随 `POSTGRES_PASSWORD` 自动改变，需先在数据库中更改账户密码，再更新环境文件并重建应用容器。

默认只映射服务器本机 `127.0.0.1:8765`；PostgreSQL 没有宿主机端口映射。电脑上运行以下命令建立 SSH 隧道：

```sh
ssh -N -L 8766:127.0.0.1:8765 USER@SERVER
```

然后在电脑浏览器打开 [http://127.0.0.1:8766](http://127.0.0.1:8766)。浏览器会要求输入账号密码：账号为 `admin`，密码为 `.env.deploy` 中的 `STRATEGYLAB_APP_PASSWORD`。将 `USER@SERVER` 替换为服务器登录名和地址。电脑若已有程序占用 8766，换一个空闲的本地端口即可。若要让其他人从公网访问，还需在服务器上配置 HTTPS 反向代理；应用内只有单一管理员密码，没有多用户权限体系。

## 日常维护

所有命令都在仓库目录运行：

```sh
# 查看状态和最近日志
docker compose --env-file .env.deploy -f compose.deploy.yaml ps
docker compose --env-file .env.deploy -f compose.deploy.yaml logs --tail=100 app postgres

# 拉取代码并升级；数据库卷保留
git pull --ff-only
docker compose --env-file .env.deploy -f compose.deploy.yaml up -d --build --wait

# 备份历史行情（备份文件仍在服务器上，需另行复制到安全位置）
mkdir -p backups
docker compose --env-file .env.deploy -f compose.deploy.yaml exec -T postgres \
  pg_dump -U strategy_lab -d strategy_lab -Fc > "backups/strategy_lab_$(date +%Y%m%d_%H%M%S).dump"

# 停止服务，不删除数据库卷
docker compose --env-file .env.deploy -f compose.deploy.yaml down
```

不要对该部署运行 `down -v`：它会删除 PostgreSQL 历史数据卷。备份恢复可以在空数据库中用 `pg_restore -U strategy_lab -d strategy_lab --clean --if-exists` 导入；恢复前先单独保存现有卷和备份文件。数据库卷属于 `strategy-lab-server` Compose 项目，与本机开发用的 `compose.yaml` 数据卷相互独立；从本机迁移已有行情时需要另行导出和导入。

## 验证

在网页选择“合成演示”分别运行 Python 和 Go，以确认两个引擎都能工作；此模式不能用于验证策略收益。再选短区间的真实 ETF，连续运行相同配置两次，在下载的实验 JSON 中检查第二次的 `source_meta.cached_symbols`。若真实行情失败，先查看应用日志和服务器对公开数据接口的网络连通性；接口并无可用性保证，失败时系统不会用演示数据替代真实行情。

自写代码由无网络、无数据库密钥的隔离 worker 容器执行；应用容器使用管理员密码，历史记录保存在 PostgreSQL。管理员应仅运行自己信任的策略代码，隔离容器并不是面向陌生用户的多租户代码沙箱。此部署不提供自动备份或公网 HTTPS，这些能力应按实际使用场景在服务器基础设施中补齐。
