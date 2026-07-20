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
  /** 人类成员是否仍在职（false = 已停用；lifecycle-and-governance §2.5）。 */
  is_active?: boolean;
  /** 指向已删除目标的占位（§2.7）——**不是** null，否则 UI 会把它显示成「未指派」。 */
  deleted?: boolean;
}

export interface User {
  id: number;
  username: string;
  email: string | null;
  role: Role;
  display_name: string;
  avatar_color: string | null;
  /** false = 已停用：不能登录、既有 token 立即失效、不出现在指派选择器（§2.5）。 */
  is_active: boolean;
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
  /** true = 已归档：不出现在项目列表默认结果与全局切换器；既有工单不受影响（§2.6）。 */
  archived: boolean;
  archived_at: string | null;
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
  /** 绑定的文档数（ticket-document-management §4.3，additive）。看板 / 列表据此渲染
   *  回形针徽章。旧响应缺省时为 undefined，渲染方须按 0 处理。 */
  document_count?: number;
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
  /** 绑定的文档数（ticket-document-management §4.3，additive）。看板 / 列表据此渲染
   *  回形针徽章。旧响应缺省时为 undefined，渲染方须按 0 处理。 */
  document_count?: number;
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
  /** 该列的**真实**总数（可能大于 items.length；§2.8）。 */
  total: number;
  /** items 是否被每列上限截断——为真时列头必须诚实写出「显示 x / 共 y」。 */
  truncated: boolean;
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
  | "converted"
  | "document_added";

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
  /** 停用 / 启用成员（§2.5）；停用最后一位有效管理员 → 409。 */
  is_active?: boolean;
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

// —— bulk-operations：需求 / BUG 批量操作 ——
// 与后端 services/bulk_ops.py 的契约逐字对齐；该模块的 docstring 是唯一真相。

/** 批量动作。`priority` 只对需求合法、`severity` 只对 BUG 合法，错配即 400。 */
export type BulkAction =
  | "move"
  | "assign"
  | "unassign"
  | "priority"
  | "severity"
  | "delete";

/** POST /api/{requirements|bugs}/bulk 请求体；动作参数按 action 取子集。 */
export interface BulkRequest {
  ids: number[];
  action: BulkAction;
  /** action=move：目标状态。 */
  status?: string;
  /** action=assign：指派目标。 */
  assignee_type?: AssigneeType;
  assignee_id?: number;
  /** action=priority|severity：目标级别。 */
  value?: string;
}

/** 逐项失败。`error` 与单条端点的错误串一致，`detail` 形状随 error 而变。 */
export interface BulkFailure {
  id: number;
  error: string;
  detail?: {
    from?: string;
    to?: string;
    allowed?: string[];
    reason?: string;
  };
}

/** 逐项跳过（请求的目标状态本就成立，不算失败，也不写审计）。 */
export interface BulkSkip {
  id: number;
  reason: string;
}

/** 批量响应恒 200；成败逐项在三桶里，**顶层永不出现 allowed**（看板拖拽据此分流错误）。 */
export interface BulkResult {
  entity: "requirement" | "bug";
  action: BulkAction;
  requested: number;
  succeeded: number[];
  skipped: BulkSkip[];
  failed: BulkFailure[];
  counts: {
    requested: number;
    succeeded: number;
    skipped: number;
    failed: number;
  };
}

// PATCH /api/projects/:id（pm/admin）——改名 / 改 key / 改 owner / 归档；仅提供的键才更新。
export interface ProjectUpdate {
  name?: string;
  key?: string;
  description?: string;
  owner_id?: number | null;
  archived?: boolean;
}

// —— ticket-document-management：文档 ——
//
// 【评审 R12】uploader / created_by 一律用现网既有的 `AuthorSummary`（与「时间线作者」
// 同语义，已含区分 人/Agent/系统 的 `type` 字段）。**不要新造 `Principal`** —— 那个
// 标识符在本仓库里不存在，照抄会让 `npm run typecheck` 立即失败。

export type DocumentKind =
  | "requirement_spec"
  | "design"
  | "test_plan"
  | "test_report"
  | "bug_evidence"
  | "release_note"
  | "reference"
  | "other";

export interface DocumentVersion {
  id: number;
  document_id: number;
  version_no: number;
  original_filename: string;
  mime_type: string;
  size_bytes: number;
  sha256: string;
  note: string | null;
  uploader: AuthorSummary | null;
  created_at: string;
}

export interface DocumentSummary {
  id: number;
  title: string;
  kind: DocumentKind;
  description: string | null;
  project_id: number | null;
  uploader: AuthorSummary | null;
  current_version: DocumentVersion | null;
  link_count: number;
  /** 结构上可否在线编辑（文本扩展名 + 未超编辑阈值）。截断与非 UTF-8 两条判据
   *  需要读文件，由 `GET /documents/:id/content` 的 `editable` 给出最终答案。 */
  editable: boolean;
  /** 仅上传响应携带：后端命中了去重，本次没有真的写盘。 */
  deduped?: boolean;
  created_at: string;
  updated_at: string;
}

export interface DocumentLink {
  id: number;
  document_id: number;
  entity_type: "requirement" | "bug";
  entity_id: number;
  label: string | null;
  /** 绑定当时的工单状态**快照**，工单后续流转不会回写它。 */
  stage: string | null;
  created_by: AuthorSummary | null;
  created_at: string;
}

export interface TicketDocument extends DocumentSummary {
  link: DocumentLink;
}

export interface DocumentDetail extends DocumentSummary {
  versions: DocumentVersion[];
  links: DocumentLink[];
}

export interface DocumentContent {
  content: string;
  document_id: number;
  version_id: number;
  version_no: number;
  mime_type: string;
  truncated: boolean;
  encoding_confident: boolean;
  /** 四条判据的**最终**答案：文本类型 + 未超阈值 + 未截断 + 严格 UTF-8。 */
  editable: boolean;
}

export interface StageChecklistItem {
  kind: DocumentKind;
  label: string;
  satisfied: boolean;
  document_ids: number[];
}

export interface StageChecklist {
  entity: "requirement" | "bug";
  entity_id: number;
  stage: string;
  stage_label: string;
  /** 后端 `DOC_STAGE_GATE` 的真实值。**前端绝不自己猜这个开关。** */
  enforced: boolean;
  satisfied: boolean;
  items: StageChecklistItem[];
}

export interface DocumentRevisionResult {
  document: DocumentSummary;
  version: DocumentVersion;
  deduped: boolean;
  fanout_written: number;
  /** 绑定单数超过后端扇出上限时为真——如实告知，不假装全发了。 */
  fanout_truncated: boolean;
  link_count: number;
}
