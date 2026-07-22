// status/priority/severity 的 key→中文名→配色映射（§2.5 / §3.3 lib/constants.ts）。
// 契约铁律：status key 集合必须与后端 workflow.py 逐字一致。

import type {
  RequirementStatus,
  BugStatus,
  DocumentKind,
  GovernanceAction,
  NotificationType,
  PlanStatus,
  Priority,
  Severity,
  SettingsActivityAction,
  UserActivityAction,
  UserSource,
  VersionStatus,
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

// —— version-plan-console：版本 / 计划状态徽章 ——
// 色值全部取自既有明度基线（中性 / 蓝 / 绿），对比度 ≥ 4.5:1。
// `archived` 与 `planning` 同为中性，靠**更冷更深一档的底色 + 不同文案**区分——
// 归档是「收起来了」，不是「还没开始」，二者不可长得一样。
// 必须是穷尽的 Record<Union, BadgeStyle>（同 NOTIFICATION_LABELS 的理由）：
// 漏一个键就是编译错误，而不是界面上冒出一串英文原文。

export const VERSION_STATUS_STYLES: Record<VersionStatus, BadgeStyle> = {
  planning: { label: "规划中", bg: "#EDEAE3", fg: "#6E6A62" },
  active: { label: "进行中", bg: "#DCE7F2", fg: "#3B6EA5" },
  released: { label: "已发布", bg: "#D9EBDD", fg: "#3E7A4F" },
  archived: { label: "已归档", bg: "#E4E1DA", fg: "#5F5B54" },
};

export const PLAN_STATUS_STYLES: Record<PlanStatus, BadgeStyle> = {
  planning: { label: "规划中", bg: "#EDEAE3", fg: "#6E6A62" },
  active: { label: "进行中", bg: "#DCE7F2", fg: "#3B6EA5" },
  completed: { label: "已完成", bg: "#D9EBDD", fg: "#3E7A4F" },
  archived: { label: "已归档", bg: "#E4E1DA", fg: "#5F5B54" },
};

/** 下拉选项从配色表派生（同 DOCUMENT_KIND_OPTIONS），确保文案永不分叉。 */
export const VERSION_STATUS_OPTIONS = (Object.keys(VERSION_STATUS_STYLES) as VersionStatus[])
  .map((k) => ({ value: k, label: VERSION_STATUS_STYLES[k].label }));

export const PLAN_STATUS_OPTIONS = (Object.keys(PLAN_STATUS_STYLES) as PlanStatus[])
  .map((k) => ({ value: k, label: PLAN_STATUS_STYLES[k].label }));

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
  // 【lifecycle-and-governance §2.4-B2】新 action，无映射时间线会直接显示英文原文。
  unassigned: "取消指派",
  moved: "流转",
  converted: "转 BUG",
  agent_advanced: "Agent 推进",
  updated: "更新",
  deleted: "删除",
  commented: "评论",
  // 【ticket-document-management §2.5 / 评审 R10】漏登记这四项**不会报错**——
  // actionLabel() 会静默回退到兜底文案——于是「文档动作进时间线」这个本轮的核心
  // 卖点，会以一串裸英文 action 名呈现给用户。
  doc_attached: "上传文档",
  doc_detached: "解除文档",
  doc_revised: "文档改版",
  doc_missing_hint: "材料提示",
  // 【document-lifecycle-depth §3.4 / R-10】上一轮 R10 的原样重演：漏登记这三项
  // 同样不报错，只会让时间线出现裸英文。
  doc_rolled_back: "文档回滚",
  doc_trashed: "移入回收站",
  doc_restored: "恢复文档",
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
//
// 【self-service-registration §2.3 C-1 / R-17】两个 map 的类型由 `Record<string, string>`
// 收紧为 `Record<NotificationType, string>`。这是**纯类型收紧，运行时零变化**，但它把
// 「后端加了一个通知类型、前端忘了加标签」从「铃铛里显示英文原文 user_registered + 🔔，
// 而 typecheck 一路绿灯」变成了一个编译错误。收紧**有意不外扩**到 STATUS_STYLES /
// ROLE_LABELS / ACTION_LABELS（它们同样是 Record<string, …>）——那是另一轮的清理。
export const NOTIFICATION_LABELS: Record<NotificationType, string> = {
  assigned: "指派",
  commented: "评论",
  mentioned: "提及",
  status_changed: "状态流转",
  agent_advanced: "Agent 推进",
  converted: "转 BUG",
  document_added: "文档",
  user_registered: "新成员注册",
  account_locked: "账号被锁定",
};

export const NOTIFICATION_ICONS: Record<NotificationType, string> = {
  assigned: "📌",
  commented: "💬",
  mentioned: "@",
  status_changed: "↔",
  agent_advanced: "🤖",
  converted: "🐞",
  document_added: "📎",
  user_registered: "🎉",
  account_locked: "🔒",
};

// 形参收紧为 NotificationType（不再是 string）：两个 map 现在对该联合是**全覆盖**的，
// 编译期不可能取不到值。运行时兜底只为一种情形保留——后端比这份 bundle 新，
// 推来了一个前端还不认识的类型。
export function notificationLabel(type: NotificationType): string {
  return NOTIFICATION_LABELS[type] || type;
}

export function notificationIcon(type: NotificationType): string {
  return NOTIFICATION_ICONS[type] || "🔔";
}

// —— self-service-registration §2.3 C-3：账号来源的中文名（团队页徽章）——
// `admin` / `seed` 有意**不渲染徽章**（那是绝大多数行，标了等于没标），
// 但标签仍然给全，好让筛选器的下拉与徽章共用同一份文案。
export const USER_SOURCE_LABELS: Record<UserSource, string> = {
  seed: "示例数据",
  admin: "管理员创建",
  signup: "自助注册",
  root: "根管理员",
};

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

// —— ticket-document-management：文档类型徽章 / 图标 / 体积格式化 ——
//
// 沿用现网 `BadgeStyle {label,bg,fg}` 的内联十六进制色写法（**不引入 Tailwind class
// 体系**，那会在同一个仓库里造出第二套配色语言）。八个 kind 各一组低饱和底色 + 深色字，
// 对比度 ≥ 4.5:1。

export const DOCUMENT_KIND_STYLES: Record<DocumentKind, BadgeStyle> = {
  requirement_spec: { label: "需求说明", bg: "#DCE7F2", fg: "#2F5A87" },
  design: { label: "技术方案", bg: "#E7DCF0", fg: "#6B458A" },
  test_plan: { label: "测试计划", bg: "#F6E7C8", fg: "#8A6716" },
  test_report: { label: "测试报告", bg: "#D9EBDD", fg: "#356B45" },
  bug_evidence: { label: "复现材料", bg: "#F3D2C7", fg: "#A03518" },
  release_note: { label: "发布说明", bg: "#D6E9E6", fg: "#2F6B63" },
  reference: { label: "参考资料", bg: "#E4E7D6", fg: "#5C6B33" },
  other: { label: "其他", bg: "#EDEAE3", fg: "#6E6A62" },
};

export function documentKindStyle(kind: string): BadgeStyle {
  return DOCUMENT_KIND_STYLES[kind as DocumentKind] || DOCUMENT_KIND_STYLES.other;
}

/** 全部 kind 的有序选项（上传 / 筛选下拉共用，顺序与后端 DOCUMENT_KINDS 一致）。 */
export const DOCUMENT_KIND_OPTIONS: { value: DocumentKind; label: string }[] =
  (Object.keys(DOCUMENT_KIND_STYLES) as DocumentKind[]).map((k) => ({
    value: k,
    label: DOCUMENT_KIND_STYLES[k].label,
  }));

/** 文件名 → 一个 emoji 图标（零依赖，与通知图标同策略）。 */
export function documentIcon(filename?: string | null): string {
  const ext = (filename || "").toLowerCase().split(".").pop() || "";
  if (["png", "jpg", "jpeg", "gif", "webp"].includes(ext)) return "🖼";
  if (ext === "pdf") return "📕";
  if (["md", "txt", "log"].includes(ext)) return "📝";
  if (["csv", "xls", "xlsx"].includes(ext)) return "📊";
  if (["doc", "docx"].includes(ext)) return "📄";
  if (["ppt", "pptx"].includes(ext)) return "📽";
  if (["json", "yaml", "yml"].includes(ext)) return "🧾";
  if (ext === "zip") return "🗜";
  return "📎";
}

/** 字节数 → 人类可读体积。用 1024 进制（与操作系统的文件属性对得上）。 */
export function formatBytes(bytes?: number | null): string {
  if (bytes == null || Number.isNaN(bytes)) return "—";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value >= 10 ? Math.round(value) : value.toFixed(1)} ${units[unit]}`;
}

/** 可以安全地 inline 预览的 MIME 白名单——**必须**与后端 INLINE_SAFE_MIMES 逐字一致。
 *
 * 【评审 R6】`blob:` URL 的 MIME 完全取自前端 `new Blob(..., {type})` 的入参、与任何
 * 响应头无关，且 `blob:` 文档运行在**本源**（JWT 就在这个源的 localStorage 里）。
 * 也就是说 §8 R-2 的三道防线里，`Content-Disposition` 与 `nosniff` 在预览路径上
 * 完全失效——这张白名单与扩展名白名单才是真正在起作用的两道。
 */
export const INLINE_SAFE_MIMES = [
  "image/png",
  "image/jpeg",
  "image/gif",
  "image/webp",
  "application/pdf",
  "text/plain",
  "text/markdown",
] as const;

export function isInlineSafeMime(mime?: string | null): boolean {
  return (INLINE_SAFE_MIMES as readonly string[]).includes(mime || "");
}

/**
 * 可当作**纯文本正文**读取的扩展名全集，与后端 `services/documents/mime.py:12` 的
 * `TEXT_EXTENSIONS` **逐字一致**（document-lifecycle-depth §3.4）。
 *
 * 【它与上面的 INLINE_SAFE_MIMES 职责完全不同，不可互换】
 *   - TEXT_EXTENSIONS  = 「这份东西的正文能不能当纯文本读」。正文经 `/content` 这个
 *     JSON 端点取回，最终落进 `<pre>` 的**文本节点**，全程不产生 `blob:` URL、
 *     不产生任何由浏览器自主解析的文档，故它**没有任何安全职责**。
 *   - INLINE_SAFE_MIMES = 「哪些 MIME 允许被浏览器当作文档直接渲染」。它是 `blob:`
 *     预览与 `Content-Disposition: inline` 的判据，`text/html` 与 `image/svg+xml`
 *     被刻意排除在外，因为它们能在本站源上执行脚本。
 *
 * 把 csv / json / yaml 加进 `INLINE_SAFE_MIMES` 是一个看起来更短、实则把上一轮唯一
 * 还生效的防线撬松的改法（`text/html` 与它们只隔一行）。**不要那样做**（R-13）。
 */
export const TEXT_EXTENSIONS = [
  "md",
  "txt",
  "log",
  "csv",
  "json",
  "yaml",
  "yml",
] as const;

/** 取文件名的小写扩展名；无扩展名 / 形状异常返回空串（与后端 `extension_of` 同判据）。 */
export function extensionOf(filename?: string | null): string {
  const name = filename || "";
  if (!name.includes(".")) return "";
  const ext = name.split(".").pop()!.toLowerCase();
  return /^[a-z0-9]{1,16}$/.test(ext) ? ext : "";
}

export function isTextExtension(extension: string): boolean {
  return (TEXT_EXTENSIONS as readonly string[]).includes(extension);
}

/** 该扩展名是否走 Markdown 渲染视图（其余文本类型行为逐字节不变，仍是 `<pre>`）。 */
export function isMarkdownExtension(extension: string): boolean {
  return extension === "md" || extension === "markdown";
}


// —— account-security-and-governance §3.5：账号治理动作的中文名 + 图标 ——
//
// 类型是 `Record<UserActivityAction, string>` 而不是 `Record<string, string>`：
// 与上面两个通知 map 同款手法——后端新增一个治理动作而前端忘了加标签时，
// 这里会**编译失败**，而不是在团队页的时间线里显示一串英文原文。
export const USER_ACTIVITY_LABELS: Record<UserActivityAction, string> = {
  user_created: "创建账号",
  user_registered: "自助注册",
  role_changed: "角色变更",
  activated: "启用账号",
  deactivated: "停用账号",
  password_reset: "重置密码",
  password_changed: "修改密码",
  account_locked: "账号被锁定",
  account_unlocked: "解除锁定",
};

export const USER_ACTIVITY_ICONS: Record<UserActivityAction, string> = {
  user_created: "✚",
  user_registered: "🎉",
  role_changed: "⇄",
  activated: "✓",
  deactivated: "⊘",
  password_reset: "🔑",
  password_changed: "🔒",
  account_locked: "🔒",
  account_unlocked: "🔓",
};

// —— login-hardening-and-audit-console §3.4：审计页实体维度的中文名 ——
export const AUDIT_ENTITY_LABELS: Record<"user" | "app_setting", string> = {
  user: "账号",
  app_setting: "站点设置",
};

/** 运行时兜底只为一种情形保留：后端比这份 bundle 新，推来了前端还不认识的动作。 */
export function userActivityLabel(action: UserActivityAction): string {
  return USER_ACTIVITY_LABELS[action] || action;
}

export function userActivityIcon(action: UserActivityAction): string {
  return USER_ACTIVITY_ICONS[action] || "•";
}

// —— login-hardening-and-audit-console §5.3：站点治理审计的动作文案 ——
// 站点设置动作（app_setting）的两个标签；账号动作复用上面的 USER_ACTIVITY_*。
const SETTINGS_ACTIVITY_LABELS: Record<SettingsActivityAction, string> = {
  registration_updated: "更新注册配置",
  invite_code_rotated: "重新生成邀请码",
};

const SETTINGS_ACTIVITY_ICONS: Record<SettingsActivityAction, string> = {
  registration_updated: "⚙",
  invite_code_rotated: "🔑",
};

export function governanceActionLabel(action: GovernanceAction): string {
  if (action in SETTINGS_ACTIVITY_LABELS) {
    return SETTINGS_ACTIVITY_LABELS[action as SettingsActivityAction];
  }
  return USER_ACTIVITY_LABELS[action as UserActivityAction] || action;
}

export function governanceActionIcon(action: GovernanceAction): string {
  if (action in SETTINGS_ACTIVITY_ICONS) {
    return SETTINGS_ACTIVITY_ICONS[action as SettingsActivityAction];
  }
  return USER_ACTIVITY_ICONS[action as UserActivityAction] || "•";
}
