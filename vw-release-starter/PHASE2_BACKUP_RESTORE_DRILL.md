# 第二阶段操作手册：隔离环境完整备份与恢复演练

本阶段只操作新建的练习环境，不停止、不重建、不修改生产容器。

这是人工演练手册，不是自动化脚本。每次只执行一个代码块，核对紧随其后的通过条件后再继续。所有 `REPLACE_WITH_...` 内容必须替换成实际值，不能原样执行。命令默认由 ECS 的 root 管理会话运行。

## 通过标准与禁区

演练通过必须证明：完整保存练习数据、Compose 和固定镜像；修改数据后保留现场；恢复到新目录；应用启动后能看到备份时的虚构条目。只有压缩包、哈希或容器健康不算恢复成功。

生产目录是 /root/data/docker_data/vaultwarden。以下对象禁止用于破坏性练习：

- /root/data/docker_data/vaultwarden/data
- /root/data/docker_data/vaultwarden/candidate-data-1.37.2-20260902_160514
- 生产 docker-compose.yml、release-state.env 和现有 vw_backup_*.tar.gz

现有 db_*.sqlite3 只是数据库备份，不包含附件、Send、配置和 RSA 密钥。现有 tar.gz 在实际恢复前也不能视为已验证回滚点。

本手册只新建：

~~~text
/root/data/docker_data/vaultwarden-release-lab
/root/data/backups/vaultwarden-lab
~~~

禁止使用 docker system prune、vaultwarden* 通配符、生产 up/down/restart，以及任何 0.0.0.0 端口绑定。当前目录不符时先运行 pwd。

## 1. 开始前只读检查

~~~bash
pwd
docker inspect vaultwarden --format '{{.State.Status}} {{.State.Health.Status}}'
docker inspect vaultwarden --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}'
docker container ls --all --format '{{.Names}}'
ss -H -ltn 'sport = :9011'
df -h /root/data
~~~

必须确认：生产为 running healthy；生产 /data 来源正确；容器列表中没有 vaultwarden-release-lab；9011 查询没有输出；/root/data 有足够空间。任一不符就停止。不要把 Docker 读取失败解释成“容器不存在”。

## 2. 创建练习环境

~~~bash
umask 077
set -Eeuo pipefail
install -d -m 700 /root/data/docker_data/vaultwarden-release-lab/data
install -d -m 700 /root/data/backups/vaultwarden-lab
cd /root/data/docker_data/vaultwarden-release-lab
pwd
~~~

pwd 必须显示 /root/data/docker_data/vaultwarden-release-lab。

创建 .env：

~~~bash
nano /root/data/docker_data/vaultwarden-release-lab/.env
~~~

写入：

~~~dotenv
VW_LAB_IMAGE=REPLACE_WITH_FULL_PRODUCTION_REPODIGEST
~~~

替换占位符，使用已经核对的 RepoDigest，不得使用 latest。然后：

~~~bash
chmod 600 /root/data/docker_data/vaultwarden-release-lab/.env
install -d -m 700 /root/data/docker_data/vaultwarden-release-lab/tls
cd /root/data/docker_data/vaultwarden-release-lab/tls
openssl genpkey -algorithm RSA -out lab-ca.key -pkeyopt rsa_keygen_bits:2048
openssl req -x509 -new -sha256 -days 30 \
  -key lab-ca.key -out lab-ca.crt \
  -subj '/CN=vw-release-lab-local-CA' \
  -addext 'basicConstraints=critical,CA:TRUE,pathlen:0' \
  -addext 'keyUsage=critical,keyCertSign,cRLSign'
openssl genpkey -algorithm RSA -out localhost.key -pkeyopt rsa_keygen_bits:2048
openssl req -new -key localhost.key -out localhost.csr -subj '/CN=localhost'
printf '%s\n' \
  'authorityKeyIdentifier=keyid,issuer' \
  'basicConstraints=critical,CA:FALSE' \
  'keyUsage=critical,digitalSignature,keyEncipherment' \
  'extendedKeyUsage=serverAuth' \
  'subjectAltName=DNS:localhost,IP:127.0.0.1' > localhost.ext
openssl x509 -req -in localhost.csr \
  -CA lab-ca.crt -CAkey lab-ca.key -CAcreateserial \
  -out localhost.crt -days 7 -sha256 -extfile localhost.ext
openssl verify -CAfile lab-ca.crt localhost.crt
chmod 600 lab-ca.key localhost.key
cd /root/data/docker_data/vaultwarden-release-lab
nano /root/data/docker_data/vaultwarden-release-lab/docker-compose.lab.yml
~~~

这是只给本次隔离演练使用的短期 RSA 测试证书。验证必须输出 `localhost.crt: OK`。两个私钥必须留在 ECS，不要下载或提交到 Git。

Compose 内容：

~~~yaml
services:
  vaultwarden-lab:
    image: "${VW_LAB_IMAGE:?VW_LAB_IMAGE is required}"
    container_name: vaultwarden-release-lab
    restart: "no"
    environment:
      DOMAIN: "https://localhost:9011"
      ROCKET_TLS: '{certs="/ssl/localhost.crt",key="/ssl/localhost.key"}'
      SIGNUPS_ALLOWED: "true"
    volumes:
      - ./data:/data
      - ./tls/localhost.crt:/ssl/localhost.crt:ro
      - ./tls/localhost.key:/ssl/localhost.key:ro
    ports:
      - "127.0.0.1:9011:80"
~~~

检查：

~~~bash
cd /root/data/docker_data/vaultwarden-release-lab
docker compose --project-name vw-restore-lab -f docker-compose.lab.yml config --images
docker compose --project-name vw-restore-lab -f docker-compose.lab.yml config
~~~

必须看到固定 digest、练习 data、两个只读 tls 文件挂载、容器名 vaultwarden-release-lab 和 127.0.0.1:9011。若出现生产目录、生产容器名或 0.0.0.0，停止。

启动：

~~~bash
docker compose --project-name vw-restore-lab -f docker-compose.lab.yml up -d
docker inspect vaultwarden-release-lab --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}'
curl --fail --silent --show-error --cacert tls/lab-ca.crt https://localhost:9011/alive
docker inspect vaultwarden --format '{{.State.Status}} {{.State.Health.Status}}'
~~~

练习容器应运行，alive 成功，生产仍为 running healthy。

## 3. 创建虚构数据

在 SSH 客户端建立本地端口转发：本机 9011 → ECS 的 127.0.0.1:9011。只把 tls/lab-ca.crt 下载到 Windows，两个私钥必须留在 ECS。在 Windows 当前用户的“受信任的根证书颁发机构”中导入 lab-ca.crt，完全退出并重开 Chrome 或 Edge，再打开 https://localhost:9011。这个端口只绑定 ECS loopback，不要在安全组中开放 9011。

Vaultwarden 1.37.2 的 Web Vault 拒绝 HTTP，包括 localhost；看到 `Insecure URL not allowed` 表示浏览器仍在使用 http://，或者测试CA 证书尚未受信任。不要使用浏览器的“继续访问不安全页面”绕过证书错误。

只创建练习账号：

- 邮箱 restore-lab@example.invalid
- 使用新的练习主密码
- 创建条目 vw-release-restore-drill
- 备注写 before-backup
- 为练习账号启用新的测试 TOTP；seed 和验证码只留在你的测试设备，不写入文档
- 若日常使用附件，再加入一个无隐私小文本附件

同步、退出并使用测试 TOTP 重新登录，确认 before-backup 存在。随后编辑 Compose，把 SIGNUPS_ALLOWED 改为 false，并只重建练习容器：

~~~bash
cd /root/data/docker_data/vaultwarden-release-lab
nano docker-compose.lab.yml
docker compose --project-name vw-restore-lab -f docker-compose.lab.yml up -d
curl --fail --silent --show-error --cacert tls/lab-ca.crt https://localhost:9011/alive
~~~

## 4. 创建完整恢复包

停止且只停止练习容器：

~~~bash
cd /root/data/docker_data/vaultwarden-release-lab
docker compose --project-name vw-restore-lab -f docker-compose.lab.yml stop
docker inspect vaultwarden-release-lab --format '{{.State.Running}}'
docker inspect vaultwarden --format '{{.State.Status}} {{.State.Health.Status}}'
~~~

期望为 false，以及生产 running healthy。

在同一个 SSH 会话中整块执行：

~~~bash
umask 077
set -Eeuo pipefail
LAB_ROOT=/root/data/docker_data/vaultwarden-release-lab
BACKUP_ROOT=/root/data/backups/vaultwarden-lab
DRILL_ID="lab-$(date -u +%Y%m%dT%H%M%SZ)"
PARTIAL="$BACKUP_ROOT/$DRILL_ID.partial"
FINAL="$BACKUP_ROOT/$DRILL_ID"

test ! -e "$PARTIAL"
test ! -e "$FINAL"
install -d -m 700 "$PARTIAL/data" "$PARTIAL/compose"
cp -a "$LAB_ROOT/data/." "$PARTIAL/data/"
cp -a "$LAB_ROOT/docker-compose.lab.yml" "$LAB_ROOT/.env" "$PARTIAL/compose/"
docker compose --project-name vw-restore-lab -f "$LAB_ROOT/docker-compose.lab.yml" config --images > "$PARTIAL/image.txt"

cd "$PARTIAL"
find data compose image.txt -type f -print0 | sort -z | xargs -0 sha256sum > manifest.sha256
sha256sum -c manifest.sha256
python3 -c 'import sqlite3,sys; print(sqlite3.connect("file:"+sys.argv[1]+"?mode=ro",uri=True).execute("PRAGMA quick_check").fetchone()[0])' "$PARTIAL/data/db.sqlite3"

touch COMPLETE
sync
mv "$PARTIAL" "$FINAL"
printf 'DRILL_ID=%s\n' "$DRILL_ID"
test -f "$FINAL/COMPLETE"
~~~

通过条件：manifest 全部 OK，SQLite 输出 ok，并记下 DRILL_ID。任一步失败都不要手工补建 COMPLETE，也不要把 .partial 改名。

## 5. 制造备份后的变化

~~~bash
cd /root/data/docker_data/vaultwarden-release-lab
docker compose --project-name vw-restore-lab -f docker-compose.lab.yml up -d
curl --fail --silent --show-error --cacert tls/lab-ca.crt https://localhost:9011/alive
~~~

登录练习账号，把备注改成 after-backup，同步并刷新确认。再次停止：

~~~bash
docker compose --project-name vw-restore-lab -f docker-compose.lab.yml stop
docker inspect vaultwarden-release-lab --format '{{.State.Running}}'
docker inspect vaultwarden --format '{{.State.Status}} {{.State.Health.Status}}'
~~~

## 6. 保留现场并恢复到新目录

把 DRILL_ID 换成第 4 步实际值，不得猜“最新目录”：

~~~bash
umask 077
set -Eeuo pipefail
LAB_ROOT=/root/data/docker_data/vaultwarden-release-lab
BACKUP_ROOT=/root/data/backups/vaultwarden-lab
DRILL_ID='REPLACE_WITH_EXACT_DRILL_ID'
test "$DRILL_ID" != REPLACE_WITH_EXACT_DRILL_ID
BUNDLE="$BACKUP_ROOT/$DRILL_ID"
FAILED_DATA="$LAB_ROOT/failed-data-$DRILL_ID"
RESTORED_DATA="$LAB_ROOT/data.restore-$DRILL_ID"
FAILED_COMPOSE="$LAB_ROOT/failed-compose-$DRILL_ID"

test -f "$BUNDLE/COMPLETE"
test ! -e "$FAILED_DATA"
test ! -e "$RESTORED_DATA"
test ! -e "$FAILED_COMPOSE"

cd "$BUNDLE"
sha256sum -c manifest.sha256
python3 -c 'import sqlite3,sys; print(sqlite3.connect("file:"+sys.argv[1]+"?mode=ro",uri=True).execute("PRAGMA quick_check").fetchone()[0])' "$BUNDLE/data/db.sqlite3"

mv "$LAB_ROOT/data" "$FAILED_DATA"
install -d -m 700 "$RESTORED_DATA"
cp -a "$BUNDLE/data/." "$RESTORED_DATA/"
diff -qr "$BUNDLE/data" "$RESTORED_DATA"
python3 -c 'import sqlite3,sys; print(sqlite3.connect("file:"+sys.argv[1]+"?mode=ro",uri=True).execute("PRAGMA quick_check").fetchone()[0])' "$RESTORED_DATA/db.sqlite3"

install -d -m 700 "$FAILED_COMPOSE"
mv "$LAB_ROOT/docker-compose.lab.yml" "$LAB_ROOT/.env" "$FAILED_COMPOSE/"
cp -a "$BUNDLE/compose/." "$LAB_ROOT/"
mv "$RESTORED_DATA" "$LAB_ROOT/data"
~~~

COMPLETE 缺失、manifest 失败、SQLite 不是 ok、diff 有输出或目标目录已存在时，必须停止。

核对恢复镜像：

~~~bash
cd /root/data/docker_data/vaultwarden-release-lab
BACKUP_ROOT=/root/data/backups/vaultwarden-lab
DRILL_ID='REPLACE_WITH_EXACT_DRILL_ID'
test "$DRILL_ID" != REPLACE_WITH_EXACT_DRILL_ID
docker compose --project-name vw-restore-lab -f docker-compose.lab.yml config --images
cat "$BACKUP_ROOT/$DRILL_ID/image.txt"
~~~

两者必须一致。随后：

~~~bash
docker compose --project-name vw-restore-lab -f docker-compose.lab.yml up -d
curl --fail --silent --show-error --cacert tls/lab-ca.crt https://localhost:9011/alive
docker inspect vaultwarden --format '{{.State.Status}} {{.State.Health.Status}}'
~~~

通过 Web Vault 确认：

- 使用测试 TOTP 可以登录。
- 备注为 before-backup，不是 after-backup。
- 备份前的附件可下载。
- 新建 after-restore 条目并同步成功。

此时才记录“隔离环境完整恢复通过”。

## 7. 验证损坏包会被拒绝

不要损坏好包：

~~~bash
BACKUP_ROOT=/root/data/backups/vaultwarden-lab
DRILL_ID='REPLACE_WITH_EXACT_DRILL_ID'
test "$DRILL_ID" != REPLACE_WITH_EXACT_DRILL_ID
BAD="$BACKUP_ROOT/$DRILL_ID-corrupt"

test ! -e "$BAD"
cp -a "$BACKUP_ROOT/$DRILL_ID" "$BAD"
printf '\ncorrupt-test\n' >> "$BAD/data/db.sqlite3"

cd "$BAD"
if sha256sum -c manifest.sha256; then
  echo 'FAIL: 损坏未被发现'
else
  echo 'PASS: manifest 已拒绝损坏恢复包'
fi
~~~

期望至少一个 FAILED，最后显示 PASS。不得启动坏包。过期 release ID 和恢复中断要等执行器具有事务状态后再测。

## 8. 结束状态

首次先保留恢复后的 data、failed-data、failed-compose、好恢复包和坏包，不清理。保持练习容器停止：

~~~bash
cd /root/data/docker_data/vaultwarden-release-lab
docker compose --project-name vw-restore-lab -f docker-compose.lab.yml stop
docker inspect vaultwarden-release-lab --format '{{.State.Running}}'
docker inspect vaultwarden --format '{{.State.Status}} {{.State.Health.Status}}'
~~~

期望为 false，以及生产 running healthy。清理是后续单独动作。演练资料不再需要后，从 Windows 当前用户的“受信任的根证书颁发机构”中删除主题为 `CN=vw-release-lab-local-CA` 的测试 CA 证书。

## 9. 单独清理旧 Candidate 生产副本（用户已授权）

这一节与恢复演练无依赖，建议在演练结束后执行；如果第 1 节发现磁盘空间不足，可以先执行本节，再返回第 2 节。它会永久删除旧 Candidate 数据，因此先移到一个精确的隔离名称，复核生产正常，再删除。不要删除 docker-compose.candidate.yml、release-state.env 或 release-state.env.before-candidate-verified；它们保留历史记录，但 release-state.env 中的 Candidate 路径会成为历史值，不能再当作可运行现场。

先在 NPM 管理界面确认 vw2candidate.qg778.com 的入口仍为 Disabled。然后只读核对：

~~~bash
docker inspect vaultwarden-candidate --format '{{.State.Running}}'
docker inspect vaultwarden-candidate --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}'
docker inspect vaultwarden --format '{{.State.Status}} {{.State.Health.Status}}'
~~~

必须依次看到 false、精确路径 /root/data/docker_data/vaultwarden/candidate-data-1.37.2-20260902_160514，以及生产 running healthy。任何结果不同都停止。

删除已停止的旧 Candidate 容器，再把敏感数据目录改名隔离：

~~~bash
umask 077
set -Eeuo pipefail
CANDIDATE=/root/data/docker_data/vaultwarden/candidate-data-1.37.2-20260902_160514
RETIRED=/root/data/docker_data/vaultwarden/candidate-retired-1.37.2-20260902_160514

test "$(realpath -- "$CANDIDATE")" = "$CANDIDATE"
test -d "$CANDIDATE"
test ! -L "$CANDIDATE"
test ! -e "$RETIRED"
docker rm vaultwarden-candidate
mv -- "$CANDIDATE" "$RETIRED"
docker inspect vaultwarden --format '{{.State.Status}} {{.State.Health.Status}}'
du -sh -- "$RETIRED"
~~~

生产仍必须为 running healthy。此时目录还能通过反向 mv 恢复；先不要继续，重新运行 vw_release.py status，确认 production 正常且 candidate.exists 为 false。

确认无误后，才永久删除这个精确隔离目录：

~~~bash
set -Eeuo pipefail
RETIRED=/root/data/docker_data/vaultwarden/candidate-retired-1.37.2-20260902_160514
test "$RETIRED" = /root/data/docker_data/vaultwarden/candidate-retired-1.37.2-20260902_160514
test -d "$RETIRED"
test ! -L "$RETIRED"
rm -rf --one-file-system -- "$RETIRED"
test ! -e "$RETIRED"
docker inspect vaultwarden --format '{{.State.Status}} {{.State.Health.Status}}'
~~~

最后必须再次看到生产 running healthy。该删除不可恢复；不要使用变量为空、通配符或缩短后的父目录执行 rm。

## 依据与实现原则

Vaultwarden 官方说明：SQLite 在线时优先使用 Online Backup API 或内置 backup；服务停止后可以复制主数据库及匹配的 WAL。附件、配置和 RSA 密钥位于数据库之外，也要按实际用途备份。恢复时必须停止服务，数据库单文件备份不能搭配旧 WAL，并应定期实际演练恢复：

https://github.com/dani-garcia/vaultwarden/wiki/Backing-up-your-vault

Vaultwarden 官方 HTTPS 说明：Web Vault 依赖 HTTPS；内置 Rocket TLS 不建议用于生产，但可用于本机端口转发下的隔离演练。Rocket TLS 需要 RSA 证书和容器内可见的证书路径：

https://github.com/dani-garcia/vaultwarden/wiki/Enabling-HTTPS

本演练选择“停止练习容器后完整复制整个 data”，先用最少机制证明恢复链路。通过后再把已验证动作编码进 vw-release。
