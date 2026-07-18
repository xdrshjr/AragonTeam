// status/priority/severity 的 key→中文名→配色映射（§2.5 / §3.3 lib/constants.ts）。
// 契约铁律：status key 集合必须与后端 workflow.py 逐字一致。

import type {
  RequirementStatus,
  BugStatus,
  Priority,
  Severity,
} from "@/lib/types";

// 徽章配色（浅底 + 深字），符合 Anthropic 暖色浅色风。
export interface BadgeStyle {
  label: string;
  bg: string;
  fg: string;
}

// 需求列（从左到右）——与后端 REQUIREMENT_COLUMNS 逐字一致。
export const REQUIREMENT_COLUMNS: { key: RequirementStatus; title: string }[] = [
  { key: "new", title: "新建" },
  { key: "assigned", title: "已指派" },
  { key: "in_development", title: "开发中" },
  { key: "testing", title: "测试中" },
  { key: "reviewing", title: "审批中" },
  { key: "bug_fixing", title: "修复中" },
  { key: "done", title: "已完成" },
];

// BUG 列。
export const BUG_COLUMNS: { key: BugStatus; title: string }[] = [
  { key: "open", title: "新建" },
  { key: "assigned", title: "已指派" },
  { key: "fixing", title: "修复中" },
  { key: "verifying", title: "验证中" },
  { key: "closed", title: "已关闭" },
];

// 状态徽章配色（§2.5：new/open=灰、assigned=蓝、in_development/fixing=clay、
// testing/verifying=琥珀、reviewing=紫、done/closed=绿）。
export const STATUS_STYLES: Record<string, BadgeStyle> = {
  // requirement
  new: { label: "新建", bg: "#EDEAE3", fg: "#6E6A62" },
  assigned: { label: "已指派", bg: "#DCE7F2", fg: "#3B6EA5" },
  in_development: { label: "开发中", bg: "#F3DCD1", fg: "#A44E30" },
  testing: { label: "测试中", bg: "#F6E7C8", fg: "#9A7420" },
  reviewing: { label: "审批中", bg: "#E7DCF0", fg: "#7A5296" },
  bug_fixing: { label: "修复中", bg: "#F3DCD1", fg: "#A44E30" },
  done: { label: "已完成", bg: "#D9EBDD", fg: "#3E7A4F" },
  // bug
  open: { label: "新建", bg: "#EDEAE3", fg: "#6E6A62" },
  fixing: { label: "修复中", bg: "#F3DCD1", fg: "#A44E30" },
  verifying: { label: "验证中", bg: "#F6E7C8", fg: "#9A7420" },
  closed: { label: "已关闭", bg: "#D9EBDD", fg: "#3E7A4F" },
};

export const PRIORITY_STYLES: Record<Priority, BadgeStyle> = {
  low: { label: "低", bg: "#EDEAE3", fg: "#6E6A62" },
  medium: { label: "中", bg: "#DCE7F2", fg: "#3B6EA5" },
  high: { label: "高", bg: "#F6E7C8", fg: "#9A7420" },
  urgent: { label: "紧急", bg: "#F3D2C7", fg: "#B23B1E" },
};

export const SEVERITY_STYLES: Record<Severity, BadgeStyle> = {
  trivial: { label: "轻微", bg: "#EDEAE3", fg: "#6E6A62" },
  minor: { label: "次要", bg: "#DCE7F2", fg: "#3B6EA5" },
  major: { label: "主要", bg: "#F6E7C8", fg: "#9A7420" },
  critical: { label: "严重", bg: "#F3D2C7", fg: "#B23B1E" },
};

export const ROLE_LABELS: Record<string, string> = {
  admin: "管理员",
  pm: "项目经理",
  member: "成员",
};

export const AGENT_KIND_LABELS: Record<string, string> = {
  dev: "开发",
  qa: "测试",
  generic: "通用",
};

export const AGENT_STATUS_LABELS: Record<string, string> = {
  idle: "空闲",
  busy: "忙碌",
  offline: "离线",
};

export function statusStyle(key: string): BadgeStyle {
  return STATUS_STYLES[key] || { label: key, bg: "#EDEAE3", fg: "#6E6A62" };
}
