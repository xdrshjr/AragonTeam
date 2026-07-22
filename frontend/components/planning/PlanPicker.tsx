"use client";

// **赋值**用的计划选择器（version-plan-console §3.6 / §6.3）——输出 `plan_id: number | null`。
//
// 与 `HierarchySelects`（**筛选**用）刻意分成两个组件：筛选的取值域是
// `"" | "none" | "<id>"` 三态，赋值的取值域是 `number | null` 两态。用一个组件同时
// 表达这两件事，最后一定会在某个页面上把「不过滤」和「解除归属」搞混。

import { useId, useMemo } from "react";
import { useHierarchyOptions } from "@/hooks/useHierarchyOptions";
import type { PlanContext } from "@/lib/types";

interface Props {
  /** 当前归属的计划 id；null = 未归属。 */
  value: number | null;
  onChange: (planId: number | null) => void;
  /** 工单自带的只读概要：用于「当前值恒可见」（§3.6）。 */
  context?: PlanContext | null;
  /** 限定到某项目（建单表单已选项目时传入）；缺省用全局作用域。 */
  projectId?: number | null;
  disabled?: boolean;
  label?: string;
}

interface PlanOption {
  id: number;
  label: string;
}

export default function PlanPicker({
  value, onChange, context, projectId, disabled = false, label = "计划",
}: Props) {
  const { versions, plans, isLoading, plansTruncated } = useHierarchyOptions(projectId);
  // 同 ui/Select 的做法：写死一个 id 会在「抽屉 + 弹窗同时挂载」时造出重复 DOM id，
  // 点标签会聚焦到错误的控件。useId 是 React 18 内置且 SSR 安全的稳定兜底。
  const selectId = useId();

  const options = useMemo<PlanOption[]>(() => {
    const versionName = (versionId: number) =>
      versions.find((v) => v.id === versionId)?.name ?? "—";
    const list: PlanOption[] = plans.map((p) => ({
      id: p.id,
      label: `${versionName(p.version_id)} · ${p.name}`,
    }));
    // 【§3.6 当前值恒可见】工单归属的计划可能已被归档，而选项来自默认列表（不含归档）。
    // 此时 <select> 的 value 匹配不到任何 option，浏览器会**静默显示第一项**——用户
    // 看到「这张单归属计划 A」，它其实归属已归档的计划 B，一次误保存就把归属改错了。
    // 手法同 ProjectFormModal 的 ownerOptions：当前值不在列表里就并进去并标注。
    if (context && !list.some((o) => o.id === context.id)) {
      list.unshift({
        id: context.id,
        label: `${context.version_name ?? "—"} · ${context.name}（已归档或超出范围）`,
      });
    }
    return list;
  }, [plans, versions, context]);

  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-sm font-medium text-ink" htmlFor={selectId}>
        {label}
      </label>
      <select
        id={selectId}
        value={value == null ? "" : String(value)}
        disabled={disabled || isLoading}
        onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
        className="h-9 rounded-lg border border-border bg-surface px-2 text-sm text-ink disabled:opacity-60 focus:border-clay focus:outline-none focus:ring-2 focus:ring-clay/20"
      >
        <option value="">未归属</option>
        {options.map((o) => (
          <option key={o.id} value={String(o.id)}>{o.label}</option>
        ))}
      </select>
      {plansTruncated && (
        <span className="text-xs text-ink-muted">
          仅显示前 200 个计划，请先切换到具体项目以缩小范围
        </span>
      )}
      {!isLoading && options.length === 0 && (
        <span className="text-xs text-ink-muted">
          当前项目还没有计划——先去「版本」页建一个版本与计划。
        </span>
      )}
    </div>
  );
}
