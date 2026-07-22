"use client";

// 受控级联双下拉「版本 → 计划」（version-plan-console §3.3 / §6.3）。
//
// 本组件**不自带数据**：调用方（列表页 / 看板页）已经在用 `useHierarchyOptions()`，
// 让组件再取一次会造出第二份缓存与第二种加载态。全部级联判据都在 lib/hierarchy.ts，
// 这里只负责把它们渲染出来。

import {
  isPlanSelectDisabled,
  allowsUnassignedPlan,
  nextValueOnVersionChange,
  plansOfVersion,
  UNASSIGNED,
  type HierarchyFilterValue,
} from "@/lib/hierarchy";
import type { Plan, Version } from "@/lib/types";

interface Props {
  value: HierarchyFilterValue;
  onChange: (next: HierarchyFilterValue) => void;
  versions: Version[];
  plans: Plan[];
  /** 数据未就绪时把两个 select 置灰（仿 ProjectSwitcher，不用骨架）。 */
  loading?: boolean;
  /** `limit=200` 截断时给一行灰字提示——绝不静默少几个选项。 */
  versionsTruncated?: boolean;
  plansTruncated?: boolean;
  className?: string;
}

/** 与 FilterBar 内既有 `<select>` 逐字一致的样式串（两处筛选条必须长得一样）。 */
const selectCls =
  "h-9 rounded-lg border border-border bg-surface px-2.5 text-sm text-ink " +
  "disabled:cursor-not-allowed disabled:opacity-60 " +
  "focus:border-clay focus:outline-none focus:ring-2 focus:ring-clay/20";

export default function HierarchySelects({
  value, onChange, versions, plans, loading = false,
  versionsTruncated = false, plansTruncated = false, className = "",
}: Props) {
  const planOptions = plansOfVersion(plans, value.version);
  const planDisabled = loading || isPlanSelectDisabled(value);
  const truncated = versionsTruncated || plansTruncated;

  return (
    <div className={`flex flex-wrap items-center gap-3 ${className}`.trim()}>
      <select
        value={value.version}
        onChange={(e) => onChange(nextValueOnVersionChange(value, e.target.value, plans))}
        disabled={loading}
        aria-label="按版本过滤"
        className={selectCls}
      >
        <option value="">全部版本</option>
        <option value={UNASSIGNED}>未归属版本</option>
        {versions.map((v) => (
          <option key={v.id} value={String(v.id)}>{v.name}</option>
        ))}
      </select>

      <select
        value={value.plan}
        onChange={(e) => onChange({ ...value, plan: e.target.value })}
        disabled={planDisabled}
        aria-label="按计划过滤"
        // 选了「未归属版本」时计划下拉恒为空集组合，禁用并说明原因——
        // 一个点了没反应的控件就是在对用户说谎。
        title={
          isPlanSelectDisabled(value)
            ? "已选「未归属版本」，这些工单本就没有计划"
            : undefined
        }
        className={selectCls}
      >
        <option value="">全部计划</option>
        {/* 具体版本被选中时**不提供**「未归属」项：`plan_id=none` 与 `version_id=<id>`
            同传必然空集，不给用户挖这个坑。 */}
        {allowsUnassignedPlan(value) && <option value={UNASSIGNED}>未归属计划</option>}
        {planOptions.map((p) => (
          <option key={p.id} value={String(p.id)}>{p.name}</option>
        ))}
      </select>

      {truncated && (
        <span className="text-xs text-ink-muted">
          仅显示前 200 个，请先在顶部切换到具体项目以缩小范围
        </span>
      )}
    </div>
  );
}
