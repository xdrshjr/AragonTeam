# AragonTeam

**AI 时代的团队协作与研发管理平台。** 与 Jira / 禅道最本质的区别是：**Agent 是一等公民的执行者**——
需求单与 BUG 单既可以指派给人，也可以指派给 AI Agent（dev-agent / qa-agent…），由 Agent 自己认领、
推进、交接，并留下与人类完全同构的协作轨迹。

---

## 核心能力

- **需求 / BUG 全生命周期**：新建 → 指派 → 开发 → 测试 → 审批 → 完成；需求可一键转 BUG。
  所有状态迁移由后端状态机裁决，非法迁移一律 409。
- **看板拖拽**：拖动即迁移，前端乐观更新、失败自动回滚。
- **Agent 自主协作**：Agent 可自动认领工单、连续推进、dev→qa 自动交接，支持「一键运行整支 AI 团队一轮」。
  配置 `AGENT_LLM_*` 后由真实大模型产出工作产物；不配置则退回确定性文案，开箱即用。
- **文档管理**：需求 / BUG 全流程可上传、预览、在线编辑、版本对比与回滚文档；
  文档是可复用的一等资源（多对多绑定），内容寻址存储 + 去重，支持软删与回收站。
- **协作与治理**：评论 / @提及 / 通知中心、全局搜索与过滤、项目维度作用域、批量操作、
  行级 RBAC、成员停用、项目归档、审计时间线。

---

## 技术栈

| 层 | 选型 |
|---|---|
| 前端 | Next.js 14（App Router）+ React 18 + TypeScript + Tailwind CSS + @dnd-kit + SWR |
| 后端 | Flask + SQLAlchemy 2 + Flask-JWT-Extended + Flask-CORS |
| 存储 | SQLite（WAL），首次启动自动建表并写入示例数据 |
| 设计 | 暖色浅色风（ivory + clay/coral + 衬线标题），左导航 + 顶栏 + 主内容三段式 |

---

## 快速开始

> Windows PowerShell 5.1 下命令请**分开执行**，不要用 `&&` 链接。

### 后端（:5000）

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

首次启动自动创建 `backend/aragon.db`。健康检查：`GET http://localhost:5000/api/health`。

### 前端（:3000）

```powershell
cd frontend
npm install
copy .env.local.example .env.local
npm run dev
```

打开 <http://localhost:3000>。默认账号来自后端配置 `ROOT_ADMIN_*`，开发默认值是
**`admin` / `admin123`**——这个账号是**根管理员**：它不可被降级 / 停用 / 被他人重置密码，
也是「所有管理员都进不来」时唯一的破窗入口（改配置 + 重启）。**生产必须覆盖
`ROOT_ADMIN_PASSWORD`。**

新同事无需管理员代建账号：访问 <http://localhost:3000/register>，填对邀请码（默认 `aragon`）
即可自助注册并直接登录。邀请码、注册开关与新用户默认角色由根管理员在「设置 → 注册配置」里管理；
邀请码还可以设**有效期**与**名额上限**（留空 = 永不过期，`0` = 不限），设置页实时显示已用名额与状态，
「重新生成」会让旧码立即失效并把已用名额归零。根管理员在侧栏还有一个「审计」页，
可按实体 / 动作 / 施动者 / 时间筛选查看全站的账号与配置变更记录（含账号锁定 / 解锁）。

示例数据每类只有一条（1 账号 / 1 Agent / 1 项目 / 1 需求 / 1 BUG / 1 评论 / 1 审计 / 1 通知）。
其余成员在「团队」页创建，需要 dev→qa 演示时在「Agents」页新建一个 `qa` Agent 即可。

---

## 目录结构

```
AragonTeam/
├─ backend/          Flask REST 后端
│  ├─ models/        User / Agent / Project / Requirement / Bug / Document / ...
│  ├─ services/      workflow（状态机）/ agent_runner / agent_autopilot / documents / ...
│  ├─ routes/        auth / users / agents / projects / requirements / bugs / board / documents / stats
│  └─ tools/         一次性维护 CLI（示例数据清理、孤儿 blob 回收、回收站清理）
├─ frontend/         Next.js 前端（app / components / hooks / lib）
├─ ops/              Linux 一键部署工具箱（systemd + Nginx + 看门狗）
└─ docs/             plans/ 各轮 spec、iterations.md 详细迭代记录
```

---

## 常用配置

后端全部配置项都有开发默认值，开箱即用；生产环境至少覆盖前两项。

| 变量 | 默认值 | 说明 |
|---|---|---|
| `SECRET_KEY` / `JWT_SECRET_KEY` | 开发用占位串 | **生产务必覆盖** |
| `DATABASE_URL` | `sqlite:///<repo>/backend/aragon.db` | 自定义时**请写绝对路径** |
| `CORS_ORIGINS` | `http://localhost:3000` | 允许的前端 origin（逗号分隔） |
| `AGENT_LLM_PROVIDER` / `AGENT_LLM_API_KEY` | `none` / 空 | 设置后 Agent 由真实大模型驱动；留空即离线模式 |
| `UPLOAD_DIR` | `<repo>/backend/var/uploads` | 文档 blob 根目录，**多机部署必须共享存储** |
| `ROOT_ADMIN_USERNAME` / `ROOT_ADMIN_PASSWORD` | `admin` / `admin123` | 根管理员账号。**生产必须覆盖密码**；仍用默认值时启动日志会持续告警 |
| `ROOT_ADMIN_EMAIL` / `ROOT_ADMIN_DISPLAY_NAME` | `admin@aragon.dev` / `Ada（管理员）` | 根管理员的展示信息 |
| `ROOT_ADMIN_BOOTSTRAP` | `true` | 启动时幂等保障根管理员存在且归位。**运维 CLI 与测试环境必须关** |
| `ROOT_ADMIN_SYNC_PASSWORD` | `false` | 忘密码时的恢复开关，见下方四步流程。**平时必须为 false** |
| `REGISTRATION_ENABLED` / `REGISTRATION_INVITE_CODE` | `true` / `aragon` | 自助注册的**兜底默认值**；库内 `app_settings` 有值时以库为准 |
| `REGISTRATION_DEFAULT_ROLE` | `member` | 新注册用户的角色。**恒过 `member`/`pm` 白名单**，设成 `admin` 会被回落并告警 |
| `SIGNUP_MAX_ATTEMPTS` | `10` | 单客户端 5 分钟内的注册尝试上限（成功也计数） |
| `TRUST_PROXY_COUNT` | `0` | 信任几层反代的 `X-Forwarded-For`。**走 nginx 反代时必须置 1**，否则 `remote_addr` 恒为 `127.0.0.1`，注册限流退化成**全站单桶**（一个人手滑几次就把所有人挡在门外）。默认 0 = 不信任任何转发头，防伪造 |
| `PASSWORD_MIN_LENGTH` / `PASSWORD_MIN_CHAR_CLASSES` | `8` / `2` | 全站口令策略的两个旋钮，作用于**所有**设置口令的路径。取值会被钳到 `[6,128]` / `[1,4]`：`0` 等于没有策略，`999` 会让**所有人（含根管理员）都改不了密码**且产品内无恢复路径 |
| `TEMP_PASSWORD_LENGTH` | `16` | 服务端生成的一次性口令长度；仍会被策略的上下界二次钳位 |
| `RESERVED_USERNAMES` | 空 | 追加保留用户名（逗号分隔）。与内置表和 `ROOT_ADMIN_USERNAME` 取并集，**只作用于建号那一刻，不追溯存量账号** |
| `FORCE_PASSWORD_CHANGE` | `true` | 强制改密闸门。置 `false` **只关硬拦、不关标记**——它是升级当天发现闸门误伤了某个集成脚本时的止血阀，不是长期形态 |
| `LOGIN_MAX_ATTEMPTS` | `10` | 内存 IP 限流：同一 `(ip, username)` 在 5 分钟窗口内失败达此数即 429。重启即清空、多副本不共享 |
| `LOGIN_LOCK_THRESHOLD` | `8` | **账号级**登录锁定：同一账号**连续**失败达此数即临时锁定（落库、跨重启有效，拦得住换 IP 的慢速撞库）。取值钳到 `[3,100]`。**必须 < `LOGIN_MAX_ATTEMPTS`**——否则 IP 限流会先把请求挡光，账号锁定在该部署下**永远不可能触发**（默认 8 < 10 是刻意的）。根管理员永不被锁 |
| `LOGIN_LOCK_MINUTES` | `15` | 锁定时长（分钟），自然到期无需任何后台任务。钳到 `[1,1440]`；更长的封禁应改用「停用」这个有审计的动作 |
| `LOGIN_LOCK_NOTIFY_COOLDOWN_MINUTES` | `1440` | 同一账号在此窗口内已通知过管理员就只写审计、不再重复扇出通知（防换 IP 反复触发的通知放大）。钳到 `[0,10080]`，`0` = 每次锁定都通知 |

前端：`NEXT_PUBLIC_API_BASE`（默认 `http://localhost:5000/api`）。

### 根管理员忘记密码怎么办

唯一的恢复路径，**四步顺序不可换**：

1. 设 `ROOT_ADMIN_SYNC_PASSWORD=true`；
2. 重启（此刻库内口令被重置为 `ROOT_ADMIN_PASSWORD` 的值）；
3. 用该口令登录；
4. **先把 flag 设回 `false` 并再重启一次**，之后才去「设置」页改新密码。

把第 4 步的两半颠倒（先改密码、后关 flag），新密码会在下一次重启时被静默改回配置里的旧值。
该 flag 为真时每次启动都会打一条 warning，就是为了让人不会忘记关掉它。

### 口令策略

**一份策略，作用于所有会设置口令的路径**：自助注册、管理员建号、管理员重置、成员自助改密。
规则由 `PASSWORD_MIN_LENGTH` / `PASSWORD_MIN_CHAR_CLASSES` 两个旋钮决定，经
`GET /api/auth/registration-meta` 下发给前端——注册页、设置页、建号弹窗读到的规则清单
与后端判据**恒为同一份**，不会出现「界面说没问题、提交却 400」。

> ⚠️ **破坏性变更（本轮唯一一次，有意为之）**：`POST /api/users` 与
> `POST /api/auth/register` 此前**零口令约束**，一个字符的口令也能建号成功；现在弱口令
> 一律 **400**。`POST /api/me/password` 的下限也从 6 位提到策略值（默认 8），其错误串
> 由 `new password must be 6..128 chars` 变为 `password must be 8..128 chars`。
> **登录路径永不重新校验口令**，故存量的弱口令用户不会被锁在门外。

保留用户名（`admin`/`root`/`system`/`api`/… ∪ `RESERVED_USERNAMES` ∪ `ROOT_ADMIN_USERNAME`）
**只在新建账号那一刻判定，不追溯任何存量行**——升级后不需要去改数据，一个叫 `system`
的既有账号继续正常登录、正常被改资料。

### 忘记密码 / 重置流程

普通成员忘记密码**不再需要改配置重启**：

1. 管理员在「团队 → 重置密码」点一下（默认「自动生成一次性密码」）；
2. 系统生成一个一次性口令并**只显示这一次**，管理员把它发给本人；
3. 本人用它登录，会被**强制**送到 `/force-password`——在改掉口令之前，除了「读我是谁」
   与「改密码」以外的所有 `/api/*` 一律 403（这是服务端的硬约束，不是前端的善意提示）；
4. 改完即自动进入工作台，标记清除，审计里留下一条记录。

管理员因此**不需要也不应该**知道同事的长期口令。根管理员是唯一的例外：他的口令只有他
本人能改（他人重置一律 409，**包括空 body 的重置**），忘记时仍走上面那条四步恢复流程。

完整变量表见 [`docs/iterations.md`](docs/iterations.md)。

---

## 质量门禁

```powershell
cd backend
python -m pytest -q      # 要求零失败，且用例总数不低于开工基线

cd frontend
npm run typecheck        # tsc --noEmit → 0 error
npm run build            # next build → 成功
```

---

## 部署

`ops/` 提供 Linux 服务器一键部署工具箱（systemd 服务 + Nginx 反代 + 健康看门狗 + 日志轮转）：

```bash
sudo ./ops/provision.sh       # 装依赖、建服务账号、生成密钥
sudo ./ops/install.sh         # 安装 systemd 服务与 Nginx 站点
sudo ./ops/deploy.sh          # 更新代码后重新部署
./ops/status.sh               # 查看运行状态
```

部署参数在 `ops/config.env`，细节见 [`ops/README.md`](ops/README.md)。

---

## 更多文档

- [`docs/iterations.md`](docs/iterations.md) —— 逐轮迭代记录：设计取舍、接口语义变更、验收结论。
- [`docs/plans/`](docs/plans/) —— 每轮功能的完整 spec 与验收标准。
- [`CLAUDE.md`](CLAUDE.md) —— 代码规范与 AI 协作约定（状态机不可绕过、加列需登记等硬约束）。
