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
  agents: { total: number; idle: number; busy: number; offline: number };
  members: number;
  recent_activities: Activity[];
}

// 任何卡片实体（需求 | BUG）的公共形状，看板通用组件用。
export type Card = Requirement | Bug;
