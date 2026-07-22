// 批量操作的前端契约层（bulk-operations §3.2）：请求封装 + 结果文案。
//
// 为什么单独成文件：批量的「三桶结果」需要被翻成人话，而这套翻译在需求页、BUG 页、
// 结果弹窗、toast 四处都要用。散落四份的下场必然是「同一个 error 串在两个地方说了
// 两种话」——用户会以为是两回事。

import { ApiError, api } from "@/lib/api";
import { statusStyle } from "@/lib/constants";
import type { BulkAction, BulkFailure, BulkRequest, BulkResult, BulkSkip } from "@/lib/types";

/** 列表页的两种实体；同时就是 REST 路径前缀。 */
export type BulkEntity = "requirements" | "bugs";

export const ENTITY_LABELS: Record<BulkEntity, string> = {
  requirements: "需求",
  bugs: "BUG",
};

/** 动作 → 按钮 / 标题文案。与后端 bulk_ops.ACTIONS 一一对应。 */
export const BULK_ACTION_LABELS: Record<BulkAction, string> = {
  move: "流转状态",
  assign: "指派",
  unassign: "取消指派",
  priority: "改优先级",
  severity: "改严重度",
  plan: "归属计划",
  delete: "删除",
};

/** 发起一次批量请求。非 2xx 仍按既有 ApiError 抛出（请求本身不合法才会发生）。
 *
 *  后端另有 200 条的批量上限（bulk_ops.MAX_BULK_IDS），这里**不重复一份常量**：
 *  选择是页内作用域、每页最多 PAGE_SIZE(50) 条，永远撞不到那个上限，写一个够不着的
 *  阈值只会变成日后漂移的第二真相。 */
export function runBulk(entity: BulkEntity, body: BulkRequest): Promise<BulkResult> {
  return api.post<BulkResult>(`/${entity}/bulk`, body);
}

/** toast 用的一句话概要：只说数字，细节留给结果弹窗。 */
export function bulkSummary(result: BulkResult): string {
  const { succeeded, skipped, failed } = result.counts;
  const parts = [`成功 ${succeeded}`];
  if (skipped) parts.push(`跳过 ${skipped}`);
  if (failed) parts.push(`失败 ${failed}`);
  return `${BULK_ACTION_LABELS[result.action]}：${parts.join(" · ")}`;
}

/** 逐项失败 → 人话。未知 error 原样透出，绝不吞掉后端说了什么。 */
export function failureText(failure: BulkFailure, entity: BulkEntity): string {
  const detail = failure.detail ?? {};
  switch (failure.error) {
    case "requirement not found":
    case "bug not found":
      return `这张${ENTITY_LABELS[entity]}已不存在（可能刚被他人删除）`;
    case "forbidden":
      return "你没有权限操作这张单（仅负责人、报告人或 PM/管理员可操作）";
    case "illegal transition": {
      const from = statusStyle(detail.from ?? "").label;
      const to = statusStyle(detail.to ?? "").label;
      const allowed = (detail.allowed ?? []).map((k) => statusStyle(k).label);
      const tail = allowed.length ? `，当前只能流转到：${allowed.join("、")}` : "";
      return `「${from}」不能直接流转到「${to}」${tail}`;
    }
    case "plan and ticket must be in the same project":
      return "该工单与目标计划不在同一个项目";
    default:
      return failure.error;
  }
}

/** **请求级**错误（整批 400/403/404）→ 人话。与逐项三桶是两条不同的路径：
 *  三桶走 `BulkResultDialog`，本函数走 `BulkToolbar.applyFromModal` 的 toast。
 *  弹窗组件在调用栈上根本看不到这个 `ApiError`（它们只 `onConfirm` 交值），
 *  所以翻译只能落在这里。
 *
 *  **default 分支原样返回 `err.message`**，故对既有四个动作（assign/move/level/delete）
 *  **零行为变化**；这与 `failureText`「未知 error 原样透出，绝不吞掉后端说了什么」同款。 */
export function requestErrorText(err: unknown): string {
  if (!(err instanceof ApiError)) return "批量操作失败";
  switch (err.message) {
    case "plan_id is required":
      return "请先选择目标计划，或选择「解除归属」";
    case "plan_id is invalid":
      return "所选计划已不存在（可能刚被他人删除），请重新选择";
    default:
      return err.message;
  }
}

/** 逐项跳过 → 人话。跳过不是错误，文案要中性，不能让用户以为出了问题。 */
export function skipText(skip: BulkSkip): string {
  switch (skip.reason) {
    case "already in target status":
      return "已经处于目标状态";
    case "already assigned to this target":
      return "已经指派给该对象";
    case "already unassigned":
      return "本就未指派";
    case "already at this priority":
      return "优先级本就是该取值";
    case "already at this severity":
      return "严重度本就是该取值";
    case "already in target plan":
      return "本就归属该计划";
    default:
      return skip.reason;
  }
}

/** 结果里需要用户过目的部分（失败 + 跳过）是否非空——为空时只弹 toast，不打断操作流。 */
export function needsReview(result: BulkResult): boolean {
  return result.counts.failed > 0 || result.counts.skipped > 0;
}
