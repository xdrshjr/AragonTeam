# AragonTeam

**AI 时代的团队协作与研发管理平台** —— 与传统研发管理工具（Jira / 禅道）最本质的区别是：
**Agent 是一等公民的执行者**。需求单与 BUG 单不仅可以指派给人类成员，也可以指派给 AI Agent
（dev-agent / qa-agent 等）。平台记录人类与 Agent 混合协作的完整流转轨迹，为「Agent 自动认领需求、
自动开发、自动修 BUG」预留数据结构与接口位。

本仓库为 **MVP 骨架**：前后端可启动、可登录、可创建 / 指派 / 流转需求与 BUG、看板可拖拽、数据可持久化。

---

## 技术栈

- **前端**：Next.js 14（App Router）+ React 18 + TypeScript + Tailwind CSS + @dnd-kit（拖拽）+ SWR
- **后端**：Python Flask + SQLAlchemy 2 + Flask-JWT-Extended（JWT 鉴权）+ Flask-CORS
- **持久化**：SQLite（`backend/aragon.db`，首次启动自动建表并 seed mock 数据）
- **设计**：Anthropic 暖色浅色风（ivory 背景 + clay/coral 强调 + 衬线标题），仅浅色模式

三段式布局：**左侧竖向功能导航 + 顶部 Header + 右侧主内容区**。

---

## 目录结构

```
AragonTeam/
├─ backend/            Flask REST 后端
│  ├─ app.py           create_app 工厂 + 启动入口（:5000）
│  ├─ config.py        配置（密钥 / SQLite / CORS）
│  ├─ extensions.py    db / jwt 实例
│  ├─ errors.py        全局 JSON 错误契约 + JWT loaders
│  ├─ seed.py          幂等 mock 数据
│  ├─ models/          User / Agent / Project / Requirement / Bug / Activity
│  ├─ services/        workflow（状态机）/ auth_helpers（鉴权）
│  └─ routes/          auth / users / agents / projects / requirements / bugs / board / stats
└─ frontend/           Next.js 前端
   ├─ app/             login / (app){dashboard,requirements(+board),bugs(+board),agents,team,settings}
   ├─ components/      layout / kanban / ui / requirements / bugs / AssigneePicker
   ├─ lib/             types / constants / api / auth / toast
   └─ hooks/           useBoard（看板拉取 + 乐观移动 + 回滚）
```

---

## 启动步骤

> Windows 下命令分开执行，**不要**用 `&&` 链式（PowerShell 5.1 不支持）。

### 1. 后端（端口 5000）

PowerShell：
```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

cmd：
```bat
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

首次启动会自动创建 `aragon.db` 并写入 mock 数据。后端地址：`http://localhost:5000`
（健康检查：`GET /api/health`）。

### 2. 前端（端口 3000）

PowerShell / cmd：
```
cd frontend
npm install
copy .env.local.example .env.local
npm run dev
```

打开 `http://localhost:3000`。前端通过 `NEXT_PUBLIC_API_BASE`（默认 `http://localhost:5000/api`）
访问后端。

---

## 默认账号（seed）

| 用户名 | 密码 | 角色 |
|---|---|---|
| `admin` | `admin123` | 管理员 |
| `pm` | `pm123` | 项目经理 |
| `alice` | `alice123` | 成员 |
| `bob` | `bob123` | 成员 |

内置 Agent：`dev-agent`（开发）、`qa-agent`（测试）。

---

## 核心业务闭环

- **需求生命周期**：新建 → 指派（人 / Agent）→ 开发中 → 测试中 → 审批中 → 完成；
  审批不通过或发现缺陷可**一键转 BUG**（源需求转入「修复中」）。
- **BUG 生命周期**：新建 → 指派 → 修复中 → 验证中 → 关闭。
- **看板拖拽**：拖动卡片触发状态迁移，合法性由后端状态机（邻接表）裁决；
  非法迁移返回 409，前端乐观更新回滚并提示。
- **审计时间线**：每次创建 / 指派 / 流转 / 转 BUG 都写入 `activities`，记录人 / Agent 混合协作轨迹。

设计与验收细节见 [`docs/plans/aragonteam-mvp/spec.md`](docs/plans/aragonteam-mvp/spec.md)。
