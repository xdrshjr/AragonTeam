// 前端行级权限判据（scale-and-project-scope §2.8①）。
// **单一真相**：本文件是全站唯一的工单管理权判据，任何页面都不得再内联一份（会漂移）。

import type { Card, User } from "@/lib/types";

/**
 * 与后端 `services/auth_helpers.py::can_manage_ticket` **同判据**：pm/admin ｜ reporter ｜ 人类 assignee。
 *
 * 任何一侧变更须同步另一侧——判据不一致会让 UI 放行一个后端必 403 的操作（或反之，藏掉合法操作）。
 */
export function canManageTicket(user: User | null, ticket: Card | null): boolean {
  if (!user) return false;
  if (user.role === "admin" || user.role === "pm") return true;
  if (!ticket) return false;
  return (
    ticket.reporter_id === user.id ||
    (ticket.assignee_type === "user" && ticket.assignee_id === user.id)
  );
}
