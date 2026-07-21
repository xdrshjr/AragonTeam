# AragonTeam 测试环境运维手册

## 环境

- 服务器：`120.26.57.40`
- 部署目录：`/opt/aragonteam`
- 服务账号：`aragonteam`
- 后端：Flask + Gunicorn，`127.0.0.1:5000`
- 前端：Next.js，`127.0.0.1:3000`
- 入口：Nginx HTTP，`http://120.26.57.40`
- 后端健康检查：`http://127.0.0.1:5000/api/health`

## 首次安装

以下命令在服务器的 `/opt/aragonteam` 目录执行：

```bash
sudo ./ops/provision.sh
sudo -u aragonteam ./ops/install-deps.sh --skip-system
sudo -u aragonteam env HOME=/var/lib/aragonteam npm --prefix frontend run build
sudo ./ops/install.sh
```

`provision.sh` 会安装 Python/Node.js/Nginx，创建专用服务账号，并在
`/etc/aragonteam/aragonteam.env` 生成权限为 `0640` 的随机应用密钥。重复执行时不会覆盖
已有密钥或数据库。

## 常用命令

```bash
./ops/status.sh
./ops/logs.sh all -n 100
./ops/logs.sh backend -f
sudo ./ops/deploy.sh
sudo ./ops/uninstall.sh
```

部署前备份位于 `/opt/aragonteam/.deploy-backups/`。`uninstall.sh` 只移除服务、Nginx
站点和 watchdog 配置，不删除源码、SQLite 数据库、上传文件或密钥。
