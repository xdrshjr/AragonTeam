// 级联筛选（版本 → 计划）的纯逻辑层（version-plan-console §3.3）。
//
// 【为什么单独成文件】需求列表、BUG 列表、需求看板、BUG 看板四处都要同一套判据，
// 各抄一份的下场必然是「有的页面选了『未归属版本』还能再选计划」这种只在一个页面
// 成立的边界语义。本模块是这些判据的**唯一真相**，也是 `HierarchyFilterValue`
// 的**唯一声明处**。
//
// 依赖方向恒为：lib/hierarchy.ts（纯函数，无 React）← hooks/* ← components/* ← app/*。
// 绝不把这个类型挪进某个 "use client" 组件里——`hooks/useBoard.ts` 要用它，
// 那会造成层级倒置。

import type { Plan, Version } from "@/lib/types";

/** 单个层级筛选值的取值域：`""`=不过滤 · `"none"`=未归属 · `"<正整数>"`=具体 id。
 *  与后端 services/scope.py 的 UNASSIGNED 哨兵（`"none"`）逐字对齐。 */
export interface HierarchyFilterValue {
  version: string;
  plan: string;
}

/** 空筛选（两个维度都不过滤）。各页 `useState` 的初值都取它，免得各写一份字面量。 */
export const EMPTY_HIERARCHY: HierarchyFilterValue = { version: "", plan: "" };

/** 「未归属」哨兵。后端 `?version_id=none` ⇒ `plan_id IS NULL`。 */
export const UNASSIGNED = "none";

/** URL 深链参数的白名单：只接受正整数或 `"none"`。
 *
 *  把任意串灌进筛选条会显示一个**假筛选**——后端也会 400，但 UI 已经先说了谎。
 *  形状照抄 `requirements/page.tsx` 对 `?status=` 的既有守卫。 */
export function isHierarchyParam(raw: string): boolean {
  return raw === UNASSIGNED || /^[1-9]\d*$/.test(raw);
}

/** 筛选值 → 查询串片段（`""` 的维度整个省略，不发空参数）。 */
export function toHierarchyQuery(value: HierarchyFilterValue): string {
  const parts: string[] = [];
  if (value.version) parts.push(`version_id=${encodeURIComponent(value.version)}`);
  if (value.plan) parts.push(`plan_id=${encodeURIComponent(value.plan)}`);
  return parts.join("&");
}

/** 是否有任何一个维度在过滤（供 `hasFilter` / `filterSignature` 使用）。 */
export function hasHierarchyFilter(value: HierarchyFilterValue): boolean {
  return Boolean(value.version || value.plan);
}

/** 计划下拉在当前版本选择下应当列出的选项（§3.3 级联语义表第二列）。
 *
 *  - 版本 `""`（全部版本）→ 作用域内**所有**计划，计划可跨版本任选。
 *  - 版本 `"none"`（未归属版本）→ **空**：后端 `version_id=none` ⇒ `plan_id IS NULL`，
 *    再叠任何 `plan_id=<id>` 必然空集，给用户挖这个坑毫无意义（调用方据此禁用下拉）。
 *  - 版本 `"<id>"` → 只列该版本下的计划。
 */
export function plansOfVersion(plans: Plan[], version: string): Plan[] {
  if (version === UNASSIGNED) return [];
  if (!version) return plans;
  const versionId = Number(version);
  return plans.filter((p) => p.version_id === versionId);
}

/** 版本选择变化时的下一个筛选值（§3.3 最后一段）。
 *
 *  切换版本时若当前所选计划不属于新版本，**把计划复位为 `""`**——否则筛选条会
 *  静默变成一个恒为空集的组合，用户会以为数据丢了。
 */
export function nextValueOnVersionChange(
  current: HierarchyFilterValue,
  nextVersion: string,
  plans: Plan[],
): HierarchyFilterValue {
  if (!current.plan) return { version: nextVersion, plan: "" };
  const stillValid = plansOfVersion(plans, nextVersion)
    .some((p) => String(p.id) === current.plan);
  return { version: nextVersion, plan: stillValid ? current.plan : "" };
}

/** 「未归属版本」下计划下拉必须禁用（同 `plansOfVersion` 的第二条语义）。 */
export function isPlanSelectDisabled(value: HierarchyFilterValue): boolean {
  return value.version === UNASSIGNED;
}

/** 具体版本被选中时**不提供**「未归属」计划项：`plan_id=none` 与 `version_id=<id>`
 *  同传必然空集。 */
export function allowsUnassignedPlan(value: HierarchyFilterValue): boolean {
  return !value.version;
}

/** 版本 id → 版本名（取不到时回落到 `—`，绝不渲染一个裸数字给用户看）。 */
export function versionNameOf(versions: Version[], versionId: number | null): string {
  if (versionId === null) return "—";
  return versions.find((v) => v.id === versionId)?.name ?? "—";
}
