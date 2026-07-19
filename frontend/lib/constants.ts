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

// —— Phase-2：活动动作中文名（含 agent_advanced / updated / deleted）——
export const ACTION_LABELS: Record<string, string> = {
  created: "创建",
  assigned: "指派",
  moved: "流转",
  converted: "转 BUG",
  agent_advanced: "Agent 推进",
  updated: "更新",
  deleted: "删除",
  commented: "评论",
};

export function actionLabel(action: string): string {
  return ACTION_LABELS[action] || action;
}

// —— Phase-2：作者类型视觉映射（feed 区分 人 / Agent / 系统）——
export interface AuthorStyle {
  label: string;
  bg: string;
  fg: string;
}
export const AUTHOR_STYLES: Record<string, AuthorStyle> = {
  user: { label: "成员", bg: "#DCE7F2", fg: "#3B6EA5" },
  agent: { label: "Agent", bg: "#F3DCD1", fg: "#A44E30" },
  system: { label: "系统", bg: "#EDEAE3", fg: "#6E6A62" },
};

export function authorStyle(type: string): AuthorStyle {
  return AUTHOR_STYLES[type] || AUTHOR_STYLES.system;
}

// —— Phase-3：通知类型中文名 + 图标（emoji，零依赖）——
export const NOTIFICATION_LABELS: Record<string, string> = {
  assigned: "指派",
  commented: "评论",
  mentioned: "提及",
  status_changed: "状态流转",
  agent_advanced: "Agent 推进",
  converted: "转 BUG",
};

export const NOTIFICATION_ICONS: Record<string, string> = {
  assigned: "📌",
  commented: "💬",
  mentioned: "@",
  status_changed: "↔",
  agent_advanced: "🤖",
  converted: "🐞",
};

export function notificationLabel(type: string): string {
  return NOTIFICATION_LABELS[type] || type;
}

export function notificationIcon(type: string): string {
  return NOTIFICATION_ICONS[type] || "🔔";
}

// —— mention-autocomplete：评论正文 @提及渲染切分 ——
// 时间线渲染用：把评论正文里的 @token 标为 chip；字符集与后端解析口径一致。
// 【P2-1】带 /g，仅供 String.prototype.matchAll（无状态）使用；禁止对其调用
// .test()/.exec()——全局正则的 lastIndex 会跨调用残留、引发间歇性错配。
// 需要「单个 username 是否可解析」的判定请用新鲜字面量 /^[A-Za-z0-9_]+$/（见 MentionTextarea 候选硬过滤）。
export const MENTION_RE = /@([A-Za-z0-9_]+)/g;

// —— Phase-3：Agent 自主运行结果 → 一句话概要（toast 用）——
export function autopilotSummary(name: string, opts: {
  claimed?: number;
  advanced?: number;
  skipped?: number;
}): string {
  const parts: string[] = [];
  if (opts.claimed) parts.push(`认领 ${opts.claimed} 张`);
  if (opts.advanced) parts.push(`推进 ${opts.advanced} 步`);
  if (!parts.length) return `${name}：暂无可处理的工单`;
  return `${name}：${parts.join(" · ")}`;
}
