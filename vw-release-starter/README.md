# vw-release：只读状态检查

当前增量只实现 `status`，用于采集 ECS 本机两个固定容器的非秘密元数据。备份、`stage`、`deploy` 和 `rollback` 尚未实现；不应将采集成功视为允许发布。

代码只使用 Python 标准库和已有 Docker CLI。本地在 Python 3.10.12 上运行了 6 项离线测试。

## 本地验证

进入本仓库的 `vw-release-starter` 目录：

```bash
cd vaultwarden-consistence/vw-release-starter
python3 -m unittest -v
python3 vw_release.py --help
```

预期测试输出 `Ran 6 tests` 和 `OK`，帮助只列出 `status`。Windows 原生 Python 可使用 `python` 替代 `python3`。

测试模拟 Docker 返回值，不需要安装 Docker，也不连接 ECS。覆盖读取失败不误报缺失、敏感错误信息不输出、容器停止不等于兼容 PASS、不完整响应拒绝，以及未实现的部署命令无法调用 Docker。

## 在 ECS 上运行

通过已有、已验证服务器身份的 SSH/SFTP 管理连接执行。程序假设：

- Linux 本机 rootful Docker，socket 为 `unix:///var/run/docker.sock`；
- 生产容器名 `vaultwarden`，Candidate 容器名 `vaultwarden-candidate`；
- 当前管理用户已有读取 Docker 的权限。

先检查环境：

```bash
python3 --version
docker --host unix:///var/run/docker.sock version --format '{{.Server.Version}}'
```

不要为此替换系统 Python 或修改生产 Compose。若 socket、容器名不同，先对代码做定向调整。

创建独立工具目录，然后通过现有 SFTP 上传 `vw_release.py`：

```bash
mkdir -p /root/vw-release-lab
```

上传后的路径为 `/root/vw-release-lab/vw_release.py`。执行：

```bash
python3 /root/vw-release-lab/vw_release.py status
```

程序只调用容器列表和格式化 inspect，不启停容器、不读取密码库或完整环境变量。Docker 读取错误不会转发原始 stderr。分享结果时检查是否需要遮蔽主机名、镜像仓库地址和内部路径；不要把现场输出提交到公开仓库。

## 怎样理解结果

| 字段 | 含义与限制 |
|---|---|
| read_ok | 成功采集且找到预期生产容器；不是健康或发布判定 |
| observed_at / host | UTC 观测时间与脚本运行主机 |
| exists | 成功列出容器后，是否找到这个精确名称 |
| image_ref | 容器创建时指定的镜像引用；不是当前 Compose 文件内容 |
| image_id | 容器实际使用的本地镜像 ID，不等同 registry manifest digest |
| image_reference_uses_digest | 引用是否使用完整 @sha256 格式；不证明来源或可重新拉取 |
| state / health | Docker 保存的状态；停止容器附带的 health 不能视为当前在线探测结果 |
| data_mounts | 目的地为 /data 的挂载，不读取其中内容 |
| ports_configured | 配置的主机端口映射，不证明公网可达性 |
| compatibility | 固定 NOT_TESTED，需要另做真实客户端验证 |

退出码：0 表示采集完成且找到生产容器；1 表示读取失败或生产容器缺失；2 表示用法不支持。停止的容器仍可能返回 0；Candidate 缺失不会自动创建。

若 `image_ref` 是 `:latest`，不能直接断定当前 Compose 未固定 digest：可能文件已经修改，但运行容器尚未重建。下一步应只读比对实际 Compose 的 `config --images` 输出，以及运行镜像的 `RepoDigests`。本地记录有 digest 也不证明远端仍可拉取。不要为核对状态直接执行 pull、up 或重建容器。

## 与现有 workflow 的关系

复用仓库原有 [stable → ACR 镜像同步 workflow](../.github/workflows/sync-vaultwarden-stable.yml)。它负责同步候选镜像；本工具负责读取 ECS 现场，两者职责独立。本增量不修改 workflow，不让 GitHub Actions 连接 ECS。

现有 workflow 只有手动和定时触发，不运行 Python 单元测试。上面的测试应在提交前本地执行，不能把镜像同步成功当作代码或客户端测试成功。

## 后续第一版范围

第二阶段人工操作见 [完整备份与恢复演练手册](PHASE2_BACKUP_RESTORE_DRILL.md)。先按手册证明恢复链路，再把这些动作编码进 `vw-release`。

第二阶段完成后，按 [第三阶段：真实客户端升级与恢复验证](PHASE3_UPGRADE_COMPATIBILITY_DRILL.md) 验证 Edge 扩展与 Android App。阶段、分工及生产发布边界见 [完整流程说明](完整流程说明.md)。手册已提供不代表升级测试或生产发布已经完成。

沿用四个公共接口：`status`、`stage`、`deploy RELEASE_ID`、`rollback RELEASE_ID`；当前只有第一个可用。

1. 根据现场事实补齐状态核对。
2. 在独立虚构测试数据上实现完整备份与恢复，验证恢复到新目录后配套旧镜像及数据可用。
3. 在同一 Candidate URL、测试数据和自有密钥上验证真实升级路径，分开记录旧会话/令牌刷新、新登录/2FA和跨端同步。
4. 加入串行锁、最小持久记录、当前事务校验和人工验收等待；演练备份中断、启动失败、恢复中断和过期 release_id。
5. 演练通过后进行一次人工启动的生产发布。正常写入暂停到验收完成；恢复日常使用后，旧备份不能再作为常规回滚直接覆盖新数据。

参考：[Docker 容器列表](https://docs.docker.com/reference/cli/docker/container/ls/)、[Docker inspect](https://docs.docker.com/reference/cli/docker/inspect/)、[Compose config](https://docs.docker.com/reference/cli/docker/compose/config/)、[Vaultwarden 备份与恢复](https://github.com/dani-garcia/vaultwarden/wiki/Backing-up-your-vault)。
