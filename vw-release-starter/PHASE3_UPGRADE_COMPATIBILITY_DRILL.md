# 第三阶段操作手册：真实客户端升级与恢复验证

更新：2026-09-10。第二阶段按用户确认已完成；第三阶段尚未执行。
本轮路线：**S0 1.35.1 → S1 1.37.2 → 恢复 S0**。版本和完整 RepoDigest 在开始时重新核对。
必测客户端：Windows Edge 扩展、Android App；精确版本需在实际设备上填写。

## 0. 本轮目标与执行约定

证明四件事：旧会话能够跨越升级；新登录与账号 TOTP 可用；Edge 与 Android 真正双向同步；旧镜像配套升级前完整数据能够恢复。
仅用第二阶段的虚构账号和数据，操作 vaultwarden-release-lab。它是逻辑上的候选环境，不是历史上装有生产副本的 vaultwarden-candidate。

| 执行位置 | 工作 |
|---|---|
| ECS root SSH | 本文所有 Bash 块 |
| DNS 控制台、NPM 网页 | 新建独立练习 HTTPS 入口 |
| Windows 浏览器 | 查看 GitHub workflow、填写结果 |
| 独立 Edge 配置文件、Android 测试账号 | 输入练习密码、TOTP，进行验收 |

路径：

- 练习：/root/data/docker_data/vaultwarden-release-lab
- 备份：/root/data/backups/vaultwarden-lab
- 生产禁区：/root/data/docker_data/vaultwarden（本轮仅只读核对）
- Windows 本地结果：F:\ai-vw\phase3-result.md（第 10 节有模板）

每次只执行一个完整代码块，核对通过条件再继续。圆括号内失败会退出子 Shell，避免关闭 SSH。不同块的变量不保留，不要在另一个会话并行操作练习环境。
开始或重连后先运行：

~~~bash
set +e
unset DOCKER_CONTEXT VW_LAB_IMAGE VW_LAB_DOMAIN VW_LAB_PROXY_NETWORK
export DOCKER_HOST=unix:///var/run/docker.sock
~~~

Docker 使用 ECS 本地服务，Compose 从 .env 取配置。
禁止生产 up/down/restart、docker system prune、开放公网 9011。数据库、备份、密码、token、TOTP seed、完整 inspect、HAR 不提交 GitHub。

## 1. 只读核对旧版和环境

~~~bash
set +e
(
set -Eeuo pipefail
cd /root/data/docker_data/vaultwarden-release-lab
docker inspect vaultwarden --format '{{.State.Status}} {{.State.Health.Status}} {{.State.StartedAt}}'
docker inspect vaultwarden-release-lab --format '{{.State.Status}} {{.Config.Image}}'
docker inspect vaultwarden-release-lab --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}'
docker compose --project-name vw-restore-lab -f docker-compose.lab.yml config --images
docker inspect npm --format '{{.State.Status}}{{println}}{{range $name, $settings := .NetworkSettings.Networks}}{{$name}}{{println}}{{end}}'
df -h /root/data
)
~~~

必须看到生产 running healthy，练习 /data 精确指向 .../vaultwarden-release-lab/data，练习为第二阶段恢复后的旧 digest，NPM 正常运行。
记录生产 StartedAt，后续比对。练习为 exited 可以接续，为 running 则核对后再停止。

第二阶段恢复后 TOTP 登录、before-backup、after-restore、损坏检测按本次用户确认记完成，补记完成时间即可。
历史好包 lab-20260908T144414Z 留存；本轮需要新备份，不能复用旧 ID。

## 2. 准备 Edge 与 Android 共用的 HTTPS 地址

### 2.1 先确定入口

Android 上 localhost 是手机自己。Windows SSH 转发与测试 CA 不能直接覆盖手机 App。
用你拥有的一个独立域名，例如 vw-release-lab.你的域名。示例不是可直接使用的地址。
不要使用生产域名或历史 Candidate 域名。正式旧会话建立前准备好入口，此后升级和恢复全程不换 URL。

连接方式：客户端 → HTTPS → NPM → 同机 Docker 网络内 HTTP → 练习容器。
NPM 使用两端信任的有效证书，只新建练习 Proxy Host，不编辑生产 Proxy Host。

### 2.2 保存入口配置，然后编辑练习文件（ECS）

~~~bash
set +e
(
set -Eeuo pipefail
umask 077
cd /root/data/docker_data/vaultwarden-release-lab
test "$(docker inspect vaultwarden-release-lab --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}')" = "$PWD/data"
test ! -e phase3-entry-before
install -d -m 700 phase3-entry-before
cp -a docker-compose.lab.yml .env phase3-entry-before/
docker stop vaultwarden-release-lab
test "$(docker inspect vaultwarden-release-lab --format '{{.State.Running}}')" = false
nano .env
)
~~~

目录已存在就停止核对，不删除后重跑。Nano 用 Ctrl+O、回车保存，Ctrl+X 退出。
保留原 VW_LAB_IMAGE= 整行不动，新增下面两行并替换示例：

~~~dotenv
VW_LAB_DOMAIN=https://你的独立练习域名
VW_LAB_PROXY_NETWORK=第1节核对的NPM用户自定义网络名
~~~

网络必须是 NPM 已加入的用户自定义网络，不要猜名字，不用 bridge/host/none。
多个网络时选择 NPM 代理上游使用的网络；没有合适网络就停在这里，提供网络名称输出后再定向配置。

用 nano /root/data/docker_data/vaultwarden-release-lab/docker-compose.lab.yml 完整替换练习 Compose：

~~~yaml
services:
  vaultwarden-lab:
    image: "${VW_LAB_IMAGE:?VW_LAB_IMAGE is required}"
    container_name: vaultwarden-release-lab
    restart: "no"
    environment:
      DOMAIN: "${VW_LAB_DOMAIN:?VW_LAB_DOMAIN is required}"
      SIGNUPS_ALLOWED: "false"
    volumes:
      - ./data:/data
    ports:
      - "127.0.0.1:9011:80"
    networks:
      lab-proxy:
        aliases:
          - vaultwarden-release-lab
networks:
  lab-proxy:
    external: true
    name: "${VW_LAB_PROXY_NETWORK:?VW_LAB_PROXY_NETWORK is required}"
~~~

这里有意移除练习 ROCKET_TLS 和证书挂载；原 tls 目录保留。HTTPS 由 NPM 处理。
以后 ECS 本机探测使用 http://127.0.0.1:9011/alive；客户端使用新 HTTPS 域名。
不开放公网 9011，不修改 NPM Compose 或重启整个 NPM。

### 2.3 检查配置并启动旧版

~~~bash
set +e
(
set -Eeuo pipefail
cd /root/data/docker_data/vaultwarden-release-lab
docker compose --project-name vw-restore-lab -f docker-compose.lab.yml config
docker compose --project-name vw-restore-lab -f docker-compose.lab.yml config --images
)
~~~

逐项核对：仅一个服务 vaultwarden-lab；容器名 vaultwarden-release-lab；旧完整 digest；新 HTTPS DOMAIN；注册 false；唯一数据挂载为本练习 data；127.0.0.1:9011:80；外部网络与 NPM 一致；没有 ROCKET_TLS、生产路径或额外服务。
这不是自动安全检查，任一不符就先修正，不进入启动块。

~~~bash
set +e
(
set -Eeuo pipefail
cd /root/data/docker_data/vaultwarden-release-lab
docker compose --project-name vw-restore-lab -f docker-compose.lab.yml up -d --no-deps --pull never vaultwarden-lab
docker inspect vaultwarden --format '{{.State.Status}} {{.State.Health.Status}} {{.State.StartedAt}}'
)
~~~

### 2.4 新建 DNS 与 NPM Proxy Host（网页）

1. 新增独立域名 A 记录到 ECS 公网 IPv4，不编辑生产记录。未配置 IPv6 不添加 AAAA。本轮优先 DNS 直连，避免引入 CDN 变量。
2. NPM 新建 Proxy Host：Domain Names 填独立域名；Scheme=http；Forward Hostname=vaultwarden-release-lab；Forward Port=80；开启 Websockets Support。
3. SSL 选择覆盖此域名的有效证书，或申请 Let's Encrypt，开启 Force SSL。申请失败先解决 DNS/证书，不绕过客户端证书校验。
4. 新入口设置按来源 IP 放行的 Access List，只允许当前电脑/手机出口 IP，拒绝其他地址。建议两端先使用同一 Wi-Fi。不加额外 HTTP Basic Auth，以免干扰 App。切蜂窝网络前核对允许的出口 IP。
5. 两端浏览器打开该 HTTPS 地址，确认无证书警告且出现练习登录页，生产网页仍正常。

403 先查 Access List；502 而本机 alive 成功时查 NPM 网络、名称解析、上游协议。
若重建后 NPM 缓存旧容器地址，先仅重新保存练习 Proxy Host 刷新解析，不重启整个 NPM。

原 localhost 会话因入口切换失效不属于服务端升级故障，正式旧会话在第 4 节建立。

## 3. 复用 GitHub 镜像同步 workflow

打开 [Actions](https://github.com/redmosec/vaultwarden-consistence/actions/workflows/sync-vaultwarden-stable.yml)，选择 Sync Vaultwarden stable to ACR。
已有 1.37.2 成功记录就复用；否则 Run workflow，version 明确填 1.37.2，不留空跟随 latest。

记录 run 链接、选定版本、ACR 完整仓库地址与 digest。
实际复制时看 Summary；目标已存在且复制 skipped 时，从 Check whether version already exists 日志的 imagetools inspect 读取。
历史 f309... 不直接当作实时值，被遮蔽的仓库地址不可用于配置。

核对 [1.37.2 发布说明](https://github.com/dani-garcia/vaultwarden/releases/tag/1.37.2)及中间版本迁移说明。
若发现必要的中间升级步骤或不适用配置，停止直接跳版本，重新确定路线。
workflow 只同步镜像到 ACR，不连接 ECS、不部署生产、不证明客户端兼容。本轮不修改它。

## 4. S0 上建立正式基线和旧会话

先运行第 7.1 节检查块，实际版本必须是 1.35.1，健康与探测通过。

1. Edge 建立独立练习配置文件，使用官方 Bitwarden 扩展，记下 Edge 和扩展精确版本。
2. Android 记录系统/App 精确版本。通过实装版本支持的添加/切换账号功能添加不同服务器的练习账号；不支持安全隔离时使用备用设备或已有隔离资料。不要卸载日常 App 或清除生产数据。
3. 两端服务器地址均设为第 2 节同一 HTTPS URL，登录 restore-lab@example.invalid，输入主密码及账号 TOTP。已有账号不需要重新开放注册。
4. Edge 创建 p3-edge-before，备注 S0-before-upgrade；Android 同步确认。Android 创建 p3-android-before，Edge 同步确认。
5. 记录旧版两端新登录、TOTP、双向同步结果。在用的附件、Send、自动填充用虚构内容加测；未使用项说明 N/A。
6. 两端测试账号保持已登录，可锁定，不退出、不删账号、不清缓存、不改 URL。

基线失败记 BASELINE_FAIL，不能归因于还没发生的升级。
客户端开始、结束都记录版本；若自动更新，需要重新确认受影响组合。
正式旧会话应来自 S0，不能在升级后重新登录再称为“旧会话”。

## 5. 创建本轮新冷备

暂停两端测试写入，但保持登录。
执行 [第二阶段手册](PHASE2_BACKUP_RESTORE_DRILL.md) **第 4 节两个代码块**，新建本轮 lab-时间 恢复包，记录新 DRILL_ID。

通过：容器停止；data、Compose、.env、image.txt 完整；manifest 全部 OK；SQLite [('ok',)]；完成标志存在。
不复用旧 ID，不执行第二阶段第 5 节 after-backup 修改。

新快照包含正式 HTTPS DOMAIN、网络配置、两端会话。
恢复依赖仍可用的 NPM 网络、DNS 和公共证书；这些外部资源不在本包内。本轮是同机应用恢复，不是整机灾备。

## 6. 准备与切换候选镜像

### 6.1 校验新备份、拉取候选、保存本轮记录

~~~bash
set +e
(
set -Eeuo pipefail
umask 077
cd /root/data/docker_data/vaultwarden-release-lab
read -r -p '输入第5节的新 DRILL_ID: ' DRILL_ID
[[ "$DRILL_ID" =~ ^lab-[0-9]{8}T[0-9]{6}Z$ ]]
BUNDLE="/root/data/backups/vaultwarden-lab/$DRILL_ID"
test -f "$BUNDLE/COMPLETE"
test "$(docker inspect vaultwarden-release-lab --format '{{.State.Running}}')" = false
test "$(docker inspect vaultwarden-release-lab --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}')" = "$PWD/data"
test "$(docker inspect vaultwarden --format '{{.State.Status}} {{.State.Health.Status}}')" = 'running healthy'
(cd "$BUNDLE" && sha256sum -c manifest.sha256)
cmp .env "$BUNDLE/compose/.env"
cmp docker-compose.lab.yml "$BUNDLE/compose/docker-compose.lab.yml"
OLD_IMAGE=$(cat "$BUNDLE/image.txt")
test "$(docker compose --project-name vw-restore-lab -f docker-compose.lab.yml config --images)" = "$OLD_IMAGE"
test "$(docker inspect vaultwarden-release-lab --format '{{.Image}}')" = "$(docker image inspect "$OLD_IMAGE" --format '{{.Id}}')"
read -r -p '输入候选完整 RepoDigest（仓库@sha256:64位）: ' NEW_IMAGE
[[ "$NEW_IMAGE" =~ ^[^[:space:]@]+@sha256:[0-9a-f]{64}$ ]]
test "${NEW_IMAGE%@sha256:*}" = "${OLD_IMAGE%@sha256:*}"
test "$NEW_IMAGE" != "$OLD_IMAGE"
test ! -e "phase3-$DRILL_ID"
docker pull "$NEW_IMAGE"
test "$(docker image inspect "$NEW_IMAGE" --format '{{.Os}}/{{.Architecture}}')" = linux/amd64
test "$(docker image inspect "$NEW_IMAGE" --format '{{index .Config.Labels "org.opencontainers.image.version"}}')" = 1.37.2
docker run --rm --network none --read-only --entrypoint /vaultwarden "$NEW_IMAGE" --version
install -d -m 700 "phase3-$DRILL_ID"
printf '%s\n' "$OLD_IMAGE" > "phase3-$DRILL_ID/old-image.txt"
printf '%s\n' "$NEW_IMAGE" > "phase3-$DRILL_ID/new-image.txt"
printf '记录目录：%s/phase3-%s\n' "$PWD" "$DRILL_ID"
)
~~~

通过：备份及比较无错误，候选版本输出 1.37.2，创建本轮记录目录。
ACR 登录失败按现有管理方式解决，不把密码写进命令参数或聊天。
版本查询临时容器没有绑定生产数据；--rm 会清理自身临时容器及匿名卷。
记录目录已存在就停止核对进度，不删除重做。该记录是人工辅助，不是自动事务状态。

### 6.2 修改镜像行并核对

用 nano /root/data/docker_data/vaultwarden-release-lab/.env，将唯一的 VW_LAB_IMAGE= 行替换成上述 new-image.txt 中的完整引用。
DOMAIN、网络和其他文件保持不变。然后运行：

~~~bash
set +e
(
set -Eeuo pipefail
cd /root/data/docker_data/vaultwarden-release-lab
read -r -p '再次输入本轮 DRILL_ID: ' DRILL_ID
[[ "$DRILL_ID" =~ ^lab-[0-9]{8}T[0-9]{6}Z$ ]]
BUNDLE="/root/data/backups/vaultwarden-lab/$DRILL_ID"
test "$(docker inspect vaultwarden-release-lab --format '{{.State.Running}}')" = false
test "$(docker compose --project-name vw-restore-lab -f docker-compose.lab.yml config --images)" = "$(cat "phase3-$DRILL_ID/new-image.txt")"
cmp docker-compose.lab.yml "$BUNDLE/compose/docker-compose.lab.yml"
python3 - "$BUNDLE/compose/.env" .env <<'PY_ENV'
from pathlib import Path
import sys
def other_lines(path):
    lines=Path(path).read_text().splitlines()
    if sum(line.startswith("VW_LAB_IMAGE=") for line in lines)!=1:
        raise SystemExit("VW_LAB_IMAGE 行必须唯一")
    return [line for line in lines if not line.startswith("VW_LAB_IMAGE=")]
if other_lines(sys.argv[1]) != other_lines(sys.argv[2]):
    raise SystemExit("镜像之外的 .env 内容改变，停止")
print("PASS: 仅镜像行改变")
PY_ENV
docker compose --project-name vw-restore-lab -f docker-compose.lab.yml config
)
~~~

必须 PASS，并再次人工核对第 2.3 节的配置边界。接着启动：

~~~bash
set +e
(
set -Eeuo pipefail
cd /root/data/docker_data/vaultwarden-release-lab
docker compose --project-name vw-restore-lab -f docker-compose.lab.yml up -d --no-deps --pull never vaultwarden-lab
)
~~~

候选可能迁移数据库。之后回旧版必须一起恢复旧数据，不能只改回镜像行。

## 7. 机器检查与真实客户端验收

### 7.1 通用检查块（旧版、升级后、恢复后可用）

~~~bash
set +e
(
set -Eeuo pipefail
cd /root/data/docker_data/vaultwarden-release-lab
docker inspect vaultwarden-release-lab --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}} {{.Config.Image}}'
EXPECTED=$(docker compose --project-name vw-restore-lab -f docker-compose.lab.yml config --images)
test "$(docker inspect vaultwarden-release-lab --format '{{.Image}}')" = "$(docker image inspect "$EXPECTED" --format '{{.Id}}')"
docker exec vaultwarden-release-lab /vaultwarden --version
curl --fail --silent --show-error --max-time 10 http://127.0.0.1:9011/alive
docker inspect vaultwarden --format '{{.State.Status}} {{.State.Health.Status}} {{.State.StartedAt}}'
)
~~~

要求练习最终 running healthy、版本正确、image ID 一致、alive 成功；生产健康和 StartedAt 不变。
starting/瞬时 EOF 时等数秒重试本块，不反复 up。两分钟仍不健康就按第 9 节处理。
外部 HTTPS 必须两端各自验证，内部 alive 不覆盖 DNS、证书与 NPM。

### 7.2 必须先旧会话，后新登录

| 顺序 | 操作 | 通过条件 |
|---|---|---|
| A | 不退出两端旧会话，解锁并手动同步 | 真正连接服务器，不能只看缓存 |
| B | Edge 创建 p3-edge-after，Android 同步；Android 创建 p3-android-after，Edge 同步 | 两端都收到对端新条目 |
| C | 保持旧会话，观察令牌刷新，再同步 | 有刷新成功证据及之后同步成功 |
| D | A/B/C 记录完后，两端退出测试账号再登录 | 主密码及账号 TOTP 通过；锁定解锁不算新登录 |
| E | 新无痕窗口打开 Web Vault | 新网页资源下新登录、TOTP、同步通过 |
| F | 验证在用附件、Send、自动填充 | 逐项通过；未使用项记有理由的 N/A |

刷新不猜固定等待时长。Edge 扩展开发者工具 Network 可在本地查看 /identity/connect/token，核对 grant_type=refresh_token 与成功响应；不复制请求体、响应体或 HAR。
Android 无可观察的刷新诊断时，不做证书绕过或抓包解密。记录会话保留时间和同步结果，“刷新已证明”单列 NOT_TESTED，补齐合适的观察证据再关闭；一次手动同步不代表一定发生刷新。必要时在 S0 重新建立会话做专项补测。

旧会话失败但重新登录成功分别记 FAIL/PASS，不可用清缓存后的成功覆盖旧会话失败。
没有验证写 NOT_TESTED，网络/设备条件限制写 BLOCKED，均不是总 PASS。
本轮先固定现有客户端验证服务端升级；以后客户端 C1 更新，另行记录 S1 下客户端原地升级及旧会话验证。前后都记录实装版本。

## 8. 完整恢复演练

即使候选通过也要做一次。先保存第 7 节结果，两端暂停写入；回滚会丢弃本轮升级后虚构条目。

1. 执行第二阶段手册第 4 节的**第一个代码块**，仅停止练习容器。
2. 执行第二阶段第 6 节“保留现场并恢复到新目录”块，输入**本轮第 5 节新 DRILL_ID**。升级后的 data/配置留在 failed 目录，旧快照恢复到原位置。已有目标目录时停止，不删除绕过。
3. 执行第二阶段第 6 节“核对恢复镜像”块，同一个本轮 ID，必须是旧镜像。
4. **跳过第二阶段随后含 localhost HTTPS curl 的启动块。**使用本手册第 6.2 节最后的启动块，再执行第 7.1 节检查；实际版本回到 1.35.1，内部 HTTP alive 成功，生产正常。
5. 保持本轮 NPM/DNS/DOMAIN 不变，不恢复 phase3-entry-before 的 localhost 配置。它只用于入口准备失败时单独复原。
6. 两端先退出练习账号，避免升级后的缓存或待同步写入污染恢复结果；先用新无痕 Web Vault 登录，确认 p3-edge-before、p3-android-before 存在，两个 p3-*-after 不存在。然后两端新登录、账号 TOTP 验证。生产账号不退出、不清数据。
7. 新建 p3-after-rollback，验证 Edge ↔ Android 双向同步与必要附件。若客户端此时已更新且不兼容 S0，记录恢复路径 FAIL，不能仅凭容器健康通过。

最后停止练习并在 NPM **仅禁用本轮练习 Proxy Host**。DNS/证书保留，旧 Candidate 清理不是本轮步骤。
保留好包、坏包、failed-data、phase3 记录，不删除现场。

~~~bash
set +e
(
set -Eeuo pipefail
docker stop vaultwarden-release-lab
test "$(docker inspect vaultwarden-release-lab --format '{{.State.Running}}')" = false
docker inspect vaultwarden --format '{{.State.Status}} {{.State.Health.Status}} {{.State.StartedAt}}'
)
~~~

## 9. 失败或中断时怎么处理

| 情况 | 操作 |
|---|---|
| 入口/证书不通 | 停在第 2 节，解决后才建立基线 |
| 备份/SQLite/镜像核对失败 | 保持停止，不启动候选，保留 partial |
| 已修改 .env，未启动候选 | 检查实际镜像、记录目录和 .env，不重跑整套切换 |
| 候选健康或客户端失败 | 记录失败，停止练习，按第 8 节恢复 |
| SSH 在启动附近断开 | 重连后先跑第 7.1 节，识别现场，不假定已经成功或自动回滚 |
| 恢复中断，data/failed-data/data.restore 不完整 | 保持停止，只提供目录名、镜像和 ID，逐步核查；不整块重复恢复 |
| 生产健康或 StartedAt 意外改变 | 暂停练习调查，不顺手操作生产 |

第二阶段恢复是人工单次流程，不具备中断续跑。本手册不承诺自动恢复。
如果仅放弃入口准备，先停练习、禁用新 Proxy Host，核对旧 TLS 证书有效后单独还原 phase3-entry-before 的配置。
候选启动后放弃升级，应使用第 8 节完整数据恢复，不能仅还原入口配置。

## 10. 本地结果模板及下一步

复制下表至 F:\ai-vw\phase3-result.md，逐项填事实。不写密码或秘密，公开前脱敏。

| 项目 | 结果 |
|---|---|
| 日期、操作者、第二阶段完成时间 | 待填 |
| S0 版本及完整 digest | 待填 |
| S1 版本及完整 digest、workflow run 链接 | 待填 |
| 固定练习 URL、NPM 网络 | 待填 |
| Edge/扩展版本（开始、结束） | 待填 |
| Android/App 版本（开始、结束） | 待填 |
| 本轮新 DRILL_ID | 待填 |
| S0 两端新登录、TOTP、双向同步 | 分项待填 |
| S1 Edge 旧会话、刷新、新登录、TOTP | 分项待填 |
| S1 Android 旧会话、刷新、新登录、TOTP | 分项待填 |
| S1 双向同步、Web Vault | 待填 |
| 附件/Send/自动填充 | 分项 PASS/FAIL/有理由的 N/A |
| S0 恢复后数据边界、两端 TOTP、同步 | 分项待填 |
| 生产健康、StartedAt 前后对比 | 待填 |
| 最终练习停止、新入口 Disabled | 待填 |
| 失败、未覆盖范围与限制 | 待填 |
| 总判定 | NOT_TESTED；必测项全部通过才改 PASS |

通过后进入第四阶段：实现 stage/deploy/rollback、单机锁、持久事务记录、中断/过期 ID 测试。
当前 vw_release.py 只有 status，采集 vaultwarden 和 vaultwarden-candidate，不采集本轮 lab，compatibility 不会自动变为 PASS。
本轮 DRILL_ID 不是未来生产 RELEASE_ID。

## 依据

- [现有镜像同步 workflow](../.github/workflows/sync-vaultwarden-stable.yml)：指定版本同步到 ACR，已存在则跳过复制。
- [Compose config](https://docs.docker.com/reference/cli/docker/compose/config/)与[up](https://docs.docker.com/reference/cli/docker/compose/up/)。
- [NPM Docker 网络](https://nginxproxymanager.com/advanced-config/#best-practice-use-a-docker-network)：同网络按唯一名称访问上游。
- [Bitwarden 自托管客户端设置](https://bitwarden.com/help/change-client-environment/)：界面以实际安装版本为准。
- [Vaultwarden 备份恢复](https://github.com/dani-garcia/vaultwarden/wiki/Backing-up-your-vault)：停止服务，保留原数据，匹配恢复数据库与 WAL。
