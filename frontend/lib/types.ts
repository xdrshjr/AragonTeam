// 全量 TS 类型（§3.3 lib/types.ts）。前后端 status key 契约必须逐字一致。

export type Role = "admin" | "pm" | "member";
export type AgentKind = "dev" | "qa" | "generic";
export type AgentStatus = "idle" | "busy" | "offline";

export type Priority = "low" | "medium" | "high" | "urgent";
export type Severity = "trivial" | "minor" | "major" | "critical";

// 需求 7 态 / BUG 5 态（§2.3，与后端 workflow.py 邻接表逐字一致）。
export type RequirementStatus =
  | "new"
  | "assigned"
  | "in_development"
  | "testing"
  | "reviewing"
  | "bug_fixing"
  | "done";

export type BugStatus = "open" | "assigned" | "fixing" | "verifying" | "closed";

export type AssigneeType = "user" | "agent";

// to_dict 里 join 出的 assignee 概要对象。
export interface AssigneeSummary {
  type: AssigneeType;
  id: number;
  name: string;
  avatar_color?: string | null; // user
  kind?: AgentKind;             // agent
}

export interface User {
  id: number;
  username: string;
  email: string | null;
  role: Role;
  display_name: string;
  avatar_color: string | null;
  created_at: string;
  updated_at: string;
}

export interface Agent {
  id: number;
  name: string;
  kind: AgentKind;
  status: AgentStatus;
  description: string | null;
  created_at: string;
  updated_at: string;
}

export interface Project {
  id: number;
  name: string;
  key: string;
  description: string | null;
  owner_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface Requirement {
  id: number;
  project_id: number | null;
  title: string;
  description: string | null;
  priority: Priority;
  status: RequirementStatus;
  assignee_type: AssigneeType | null;
  assignee_id: number | null;
  assignee: AssigneeSummary | null;
  reporter_id: number | null;
  position: number;
  created_at: string;
  updated_at: string;
}

export interface Bug {
  id: number;
  project_id: number | null;
  title: string;
  description: string | null;
  severity: Severity;
  status: BugStatus;
  assignee_type: AssigneeType | null;
  assignee_id: number | null;
  assignee: AssigneeSummary | null;
  reporter_id: number | null;
  related_requirement_id: number | null;
  position: number;
  created_at: string;
  updated_at: string;
}

export interface Activity {
  id: number;
  entity_type: "requirement" | "bug";
  entity_id: number;
  action: string;
  from_status: string | null;
  to_status: string | null;
  actor_type: "user" | "agent" | "system" | null;
  actor_id: number | null;
  message: string | null;
  created_at: string;
}

// —— Phase-2：评论、合并 feed、Agent 推进结果 ——

export type AuthorType = "user" | "agent" | "system";

// to_dict 里 join 出的作者概要（user/agent/system 三态；已删除降级为占位）。
export interface AuthorSummary {
  type: AuthorType;
  id?: number | null;
  name: string;
  avatar_color?: string | null; // user
  kind?: AgentKind;             // agent
}

export interface Comment {
  id: number;
  entity_type: "requirement" | "bug";
  entity_id: number;
  author_type: AuthorType;
  author_id: number | null;
  author: AuthorSummary;
  body: string;
  created_at: string;
}

// 合并 feed 的两种元素，以 kind 判别（后端已合并排序，前端只渲染）。
export interface FeedActivityItem {
  kind: "activity";
  id: number;
  action: string;
  from_status: string | null;
  to_status: string | null;
  actor: AuthorSummary | null;
  message: string | null;
  created_at: string;
}
export interface FeedCommentItem extends Comment {
  kind: "comment";
}
export type FeedItem = FeedActivityItem | FeedCommentItem;

export interface Feed {
  items: FeedItem[];
}

// POST /:entity/:id/agent-advance（单步）返回。
export interface AgentAdvanceResult {
  ticket: Requirement | Bug;
  comment: Comment;
  agent: Agent;
}

// 看板列。
export interface BoardColumn<T> {
  key: string;
  title: string;
  items: T[];
}
export interface Board<T> {
  columns: BoardColumn<T>[];
}

export interface Stats {
  requirements: { total: number; by_status: Record<string, number> };
  bugs: { total: number; by_status: Record<string, number> };
  agents: {
    total: number;
    idle: number;
    busy: number;
    offline: number;
    utilization: number; // busy / total（0..1）
  };
  members: number;
  activities_this_week: number;
  recent_activities: Activity[];
}

// 任何卡片实体（需求 | BUG）的公共形状，看板通用组件用。
export type Card = Requirement | Bug;

// —— Phase-3：通知中心 ——

export type NotificationType =
  | "assigned"
  | "commented"
  | "mentioned"
  | "status_changed"
  | "agent_advanced"
  | "converted";

export interface Notification {
  id: number;
  type: NotificationType;
  entity_type: "requirement" | "bug" | null;
  entity_id: number | null;
  actor_type: "user" | "agent" | "system" | null;
  actor_id: number | null;
  actor: AuthorSummary | null;
  message: string;
  is_read: boolean;
  created_at: string;
}

// —— Phase-3：Agent 自主编排结果 ——

export interface AutopilotAdvanced {
  entity: "requirement" | "bug";
  id: number;
  from: string;
  to: string;
  message: string;
}
export interface AutopilotSkipped {
  entity?: "requirement" | "bug";
  id?: number;
  reason: string; // no-action | terminal | cap | busy
}
export interface AutopilotClaimed {
  entity: "requirement" | "bug";
  id: number;
  status: string;
}

// POST /agents/:id/claim-next
export interface ClaimResult {
  claimed: Requirement | Bug | null;
}
// POST /agents/:id/autorun
export interface AutorunResult {
  agent: Agent;
  advanced: AutopilotAdvanced[];
  skipped: AutopilotSkipped[];
}
// POST /agents/:id/tick
export interface TickResult {
  agent: Agent;
  claimed: AutopilotClaimed[];
  advanced: AutopilotAdvanced[];
  skipped: AutopilotSkipped[];
}
// POST /agents/autorun-all
export interface AutorunAllResult {
  runs: {
    agent: Agent;
    claimed: AutopilotClaimed[];
    advanced: AutopilotAdvanced[];
    skipped: AutopilotSkipped[];
  }[];
}

// —— Phase-3：「我的工作」聚合（GET /me/work）——
export interface MeWork {
  assigned: { requirements: Requirement[]; bugs: Bug[] };
  reported: { requirements: Requirement[]; bugs: Bug[] };
}

// —— account-settings：账号自助中心 ——

// 6 类通知的开关映射（GET/PATCH /me/notification-preferences 的 preferences 信封内容）。
export type NotificationPreferences = Record<NotificationType, boolean>;

// PATCH /me/profile 载荷（键均可选，仅提供的键才更新；username/role 后端恒忽略）。
export interface ProfileUpdate {
  display_name?: string;
  email?: string;
  avatar_color?: string;
}

// —— global-search：统一搜索（GET /api/search 响应）——
export interface SearchResults {
  query: string;
  requirements: Requirement[];
  bugs: Bug[];
  counts: { requirements: number; bugs: number };
}

// —— admin-console：管理台写操作载荷型 ——
// 薄载荷型，供三态弹窗 props 与 api 调用；键集合与后端受理字段逐一对齐。

// POST /api/users（admin）——建成员。
export interface UserCreate {
  username: string;
  password: string;
  role: Role;
  display_name?: string;
  email?: string;
}

// PATCH /api/users/:id（admin）——改资料 / 角色 / 重置密码；仅提供的键才更新。
export interface UserUpdate {
  display_name?: string;
  email?: string;
  role?: Role;
  password?: string;
}

// POST /api/agents（新建）与 PATCH /api/agents/:id（编辑）共用；键均可选，按模式取子集。
export interface AgentInput {
  name?: string;
  kind?: AgentKind;
  status?: AgentStatus;
  description?: string;
}

// POST /api/projects（pm/admin）——新建项目。
export interface ProjectCreate {
  name: string;
  key: string;
  description?: string;
}
