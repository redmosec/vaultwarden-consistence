# Vaultwarden Consistence

一套小型、可复现的 Vaultwarden 升级模式：GitHub Actions 只把官方 stable 镜像同步到私有镜像仓库，生产服务器固定镜像 digest，并在人工授权的维护窗口内完成冷备、升级和真实客户端验收。

本项目解决的问题是：Bitwarden 客户端可能先于自托管 Vaultwarden 更新，旧服务端随后无法登录或同步。这里采用“服务端 stable 优先、镜像供应与生产部署分离”的方式缩短版本差距，同时保留可恢复性。

## 工作方式

```text
Vaultwarden stable 发布
        ↓
GitHub Actions 每日检查，也可手动触发
        ↓
验证 amd64 / Debian / 版本标签，按版本号同步到 registry
        ↓
人工核对目标 digest 和生产现场
        ↓
暂停写入 → 停服务 → 完整冷备 → 只升级 Vaultwarden
        ↓
机器检查 → 当前 Edge/Android 登录与双向同步验收
        ↓
通过后恢复写入；失败则用旧镜像和匹配的旧数据一起恢复
```

自动化边界很明确：workflow 不连接生产服务器、不自动部署、不监测 Bitwarden 客户端版本，也不把 HTTP 200 当作兼容性通过。

## 仓库内容

```text
.
├── .github/workflows/sync-vaultwarden-stable.yml
├── .gitignore
├── LICENSE
└── README.md
```

## 前提

- 一个 GitHub 仓库；
- 一个支持 Docker Registry API 的私有镜像仓库，例如阿里云 ACR；
- 一台 `linux/amd64`、使用 Docker Compose 的生产服务器；
- Vaultwarden 数据通过 bind mount 或 volume 持久化；
- 已配置有效 HTTPS；
- 维护者能够暂停写入，并在机器检查后完成客户端验收。

本文命令以 Docker Compose、SQLite、服务名 `vaultwarden` 和目录 `/opt/vaultwarden` 为例。请先替换路径和服务名。MySQL/PostgreSQL 必须使用对应数据库的一致性备份方法，不能照搬 SQLite 文件备份。

## 1. 配置镜像同步

Fork 或复制本仓库，然后在 GitHub 仓库设置中创建：

| 类型 | 名称 | 示例 |
|---|---|---|
| Repository variable | `ACR_REGISTRY` | `registry.example.com` |
| Repository variable | `ACR_IMAGE` | `namespace/vaultwarden` |
| Repository secret | `ACR_USERNAME` | 镜像仓库用户名 |
| Repository secret | `ACR_PASSWORD` | 镜像仓库密码或最小权限 token |

凭据只需要目标 repository 的拉取和推送权限。不要把密码写进 workflow、Compose 或提交记录。

workflow 默认每天 UTC 03:23 检查一次，即北京时间 11:23。也可以在 **Actions → Sync Vaultwarden stable to registry → Run workflow** 手动执行；留空使用官方最新 stable，填写 `1.37.2` 这类版本号则同步指定 stable。

同步会读取 Vaultwarden 官方 `releases/latest`，拒绝不符合 `x.y.z` 的版本号，验证镜像版本、平台与 Debian 基础系统。目标版本标签已存在时不会覆盖；无该标签时才从 GHCR 同步。无论哪种情况，job summary 都会输出目标 digest。

同步成功只代表候选镜像可用，不代表生产已经升级或客户端兼容。

## 2. 固定生产镜像

先从成功的 Actions summary 或 registry 获取 digest：

```bash
docker buildx imagetools inspect \
  registry.example.com/namespace/vaultwarden:1.37.2
```

生产 Compose 使用完整 digest，不使用 `latest`：

```yaml
services:
  vaultwarden:
    image: registry.example.com/namespace/vaultwarden@sha256:REPLACE_WITH_DIGEST
    restart: unless-stopped
    volumes:
      - ./data:/data
    ports:
      - "127.0.0.1:8000:80"
```

反向代理继续指向现有 Vaultwarden 上游。升级时不要同时修改域名、TLS、数据库后端或代理拓扑，以免无法判断失败原因。

## 3. 升级前只读核对

```bash
cd /opt/vaultwarden
docker compose config
docker compose ps
docker inspect vaultwarden \
  --format 'image={{.Image}} ref={{.Config.Image}} health={{if .State.Health}}{{.State.Health.Status}}{{end}}'
docker inspect vaultwarden \
  --format '{{range .Mounts}}{{println .Source "->" .Destination}}{{end}}'
df -h .
```

核验后才安排维护窗口：

- 没有另一位维护者或自动任务正在发布；
- 当前 Compose、运行镜像和 `/data` 挂载已经确认；
- 新镜像完整 digest 已知且可以拉取；
- 备份空间充足，HTTPS 确实指向该容器；
- 用户能够暂停写入并在机器检查后立即验收；
- 已写明最长中断时间和恢复路径。

## 4. 每次升级都做新的冷备

先替换版本和路径，不要运行未替换的占位值。

```bash
set -euo pipefail
umask 077
cd /opt/vaultwarden

release_id="$(date -u +%Y%m%dT%H%M%SZ)"
backup_dir="/opt/backups/vaultwarden/$release_id"
new_image="registry.example.com/namespace/vaultwarden@sha256:REPLACE_WITH_DIGEST"

mkdir -p "$backup_dir"
docker pull "$new_image"
docker image inspect "$new_image" --format '{{.Id}} {{.Os}}/{{.Architecture}}'

cp docker-compose.yml "$backup_dir/docker-compose.yml"
[ ! -f .env ] || cp .env "$backup_dir/.env"
docker inspect vaultwarden > "$backup_dir/container-before.json"
old_image_id="$(docker inspect vaultwarden --format '{{.Image}}')"

docker compose stop vaultwarden
tar --acls --xattrs -cpf "$backup_dir/data.tar" data
docker image save "$old_image_id" -o "$backup_dir/old-image.tar"
sha256sum "$backup_dir/data.tar" "$backup_dir/old-image.tar" \
  > "$backup_dir/SHA256SUMS"
sha256sum -c "$backup_dir/SHA256SUMS"
tar -tf "$backup_dir/data.tar" >/dev/null
sqlite3 data/db.sqlite3 'PRAGMA integrity_check;'
```

只有哈希校验、tar 可读性和 SQLite `integrity_check` 都通过，才修改 Compose 的镜像 digest。任何一步失败都停止升级，并用原 Compose 启动原服务。

## 5. 只升级 Vaultwarden

将 Compose 的 `image:` 改为已经核对的完整 digest，然后执行：

```bash
cd /opt/vaultwarden
docker compose config >/dev/null
docker compose up -d --no-deps --pull never vaultwarden
docker compose ps vaultwarden
docker inspect vaultwarden \
  --format 'image={{.Image}} health={{if .State.Health}}{{.State.Health.Status}}{{end}}'
docker logs --since 10m vaultwarden
curl --fail --silent --show-error https://vault.example.com/alive
sqlite3 data/db.sqlite3 'PRAGMA quick_check;'
```

机器检查标准：

- 容器持续运行且健康检查通过；
- 运行 image ID 对应目标 digest；
- `/data` 仍指向原生产数据；
- 数据库检查返回 `ok`；
- 日志没有 migration panic、database error 或启动循环；
- 原 HTTPS 地址 `/alive` 成功且证书验证正常；
- 未意外重建数据库、反向代理或其他服务。

## 6. 验收当前客户端

机器检查通过后，只验证当前实际使用的客户端：

1. 记录 Edge 扩展和 Android Password Manager 的实际版本；
2. 已有会话解锁并同步；
3. 保存未同步数据后，退出账号并使用原自托管 URL 重新登录；
4. 打开并解密测试条目，锁定后再次解锁；
5. Edge 新建无秘密测试条目，Android 同步后可见；
6. Android 修改该条目，Edge 同步后可见；
7. 账号启用了 2FA 才验证 2FA；未启用记 `N/A`；
8. 只有实际观察到 token refresh 才记为通过，否则保留 `NOT_TESTED`。

机器健康与 HTTPS 成功不能替代这一步。结果只适用于当前“Vaultwarden + Edge + Android + 配置”组合。

## 7. 失败恢复

机器检查失败时，在维护窗口内恢复。旧镜像必须和升级前的数据一起恢复，不能让旧程序读取已经迁移的新数据库。

```bash
set -euo pipefail
umask 077
cd /opt/vaultwarden

backup_dir="/opt/backups/vaultwarden/REPLACE_WITH_RELEASE_ID"
failed_dir="/opt/backups/vaultwarden/failed-$(date -u +%Y%m%dT%H%M%SZ)"

docker compose stop vaultwarden || true
mkdir -p "$failed_dir"
tar --acls --xattrs -cpf "$failed_dir/data-after-failure.tar" data

sha256sum -c "$backup_dir/SHA256SUMS"
mv data "data.failed-$(date -u +%Y%m%dT%H%M%SZ)"
tar --acls --xattrs -xpf "$backup_dir/data.tar"
cp "$backup_dir/docker-compose.yml" docker-compose.yml
[ ! -f "$backup_dir/.env" ] || cp "$backup_dir/.env" .env
docker load -i "$backup_dir/old-image.tar"
sqlite3 data/db.sqlite3 'PRAGMA integrity_check;'
docker compose up -d --no-deps --pull never vaultwarden
```

恢复后重新检查容器、数据库、HTTPS 和已知可用范围。旧服务端可能仍无法兼容已经更新的 Bitwarden 客户端，因此“恢复成功”和“新客户端可以登录”是两个不同结论。

一旦恢复日常写入，就禁止直接用升级前快照覆盖当前数据。此后应先保存新增数据和现场，再制定新的修复方案。

## Bitwarden 客户端先更新时

本仓库的 workflow 只监测 Vaultwarden stable，不监测 Edge Add-ons 或 Google Play。发现客户端更新后：

1. 记录设备实际版本；
2. 阅读 Vaultwarden 与 Bitwarden 的相关 release notes；
3. 若当前服务端仍在支持范围，只重测受影响客户端和双向同步；
4. 若需要新版服务端，等待 stable 镜像同步到 registry，再走上述冷备升级；
5. 若兼容修复尚未发布，明确记录 `BLOCKED`，不要默认切换 prerelease 或关闭认证保护。

## 安全规则

不要向 GitHub 提交 `.env`、registry 凭据、SSH 私钥、Vaultwarden `/data`、数据库、附件、RSA 私钥、完整 inspect、HAR、访问日志、真实域名/IP、测试秘密或恢复码。

公开仓库只保存方法和自动化模板。每个部署自己的版本台账、digest、备份位置和验收证据应保存在私有位置。

## 限制

- workflow 同步官方 amd64 Debian 镜像；ARM 主机需要调整平台并重新验证。
- 版本标签已存在时不会覆盖，部署前仍须核对远端 digest。
- 本项目不验证上游镜像签名，也不提供无人值守生产部署。
- 示例备份流程面向 SQLite；外部数据库需要数据库原生方案。
- 本项目不是 Vaultwarden 或 Bitwarden 官方项目。

## License

[AGPLV3.0](LICENSE)
