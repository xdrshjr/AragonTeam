"use client";

// SWR 前缀失效工具（lifecycle-and-governance §2.4）。
//
// 【为什么不各页手抄】删除一张工单会同时影响列表、看板、仪表盘统计、「我的工作」与通知，
// 而这些 key 现在都可能带 ?project_id= / ?limit= / ?status= 等后缀（scale-and-project-scope
// §2.4）——逐条写死字面量 key 会在切换项目后静默漏刷，页面「删了还在」。
// 本模块把 agents 页已验证的「前缀函数式 key」写法提取为两个共用函数。

import type { ScopedMutator } from "swr";

/** 受工单增删改影响的所有视图前缀。 */
const TICKET_VIEW_PREFIXES = [
  "/requirements",
  "/bugs",
  "/board/",
  "/stats",
  "/me/work",
  "/notifications",
  "/search",
];

/** 受成员 / 项目 / Agent 等管理动作影响的所有视图前缀。
 *  【login-hardening-and-audit-console §3.4】追加 `/settings/audit`：解锁账号 / 改注册配置
 *  后审计页要跟着刷。就地扩这个数组字面量（本常量模块私有，对外只暴露
 *  `invalidateAdminViews`）。 */
const ADMIN_VIEW_PREFIXES = ["/users", "/projects", "/agents", "/stats", "/settings/audit"];

function invalidateByPrefix(mutate: ScopedMutator, prefixes: string[]) {
  return mutate(
    (key) => typeof key === "string" && prefixes.some((p) => key.startsWith(p))
  );
}

/** 工单被创建 / 删除 / 改派后，失效所有会展示它的视图。 */
export function invalidateTicketViews(mutate: ScopedMutator) {
  return invalidateByPrefix(mutate, TICKET_VIEW_PREFIXES);
}

/** 成员 / 项目 / Agent 被增删改后，失效所有会展示它的管理视图。 */
export function invalidateAdminViews(mutate: ScopedMutator) {
  return invalidateByPrefix(mutate, ADMIN_VIEW_PREFIXES);
}

/** 文档被上传 / 改版 / 删除后，失效文档库自身的视图。
 *
 * **只负责 `/documents` 一个前缀**（ticket-document-management §3.5 / 评审 R7）。
 * 工单维度的键（`/requirements`、`/bugs`、`/board/`）已被上面的 `TICKET_VIEW_PREFIXES`
 * 覆盖——文档动作后应当**同时**调 `invalidateTicketViews`，而不是在这里再写一份
 * 重叠的前缀表：那就是第二个真相源，正是本文件开头警告的事。
 */
export function invalidateDocumentViews(mutate: ScopedMutator) {
  return invalidateByPrefix(mutate, ["/documents"]);
}
