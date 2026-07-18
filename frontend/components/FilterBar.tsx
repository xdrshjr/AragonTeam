"use client";

import AssigneePicker, { AssigneeValue } from "@/components/AssigneePicker";

interface Option {
  value: string;
  label: string;
}

interface Props {
  keyword: string;
  onKeyword: (v: string) => void;
  status: string;
  onStatus: (v: string) => void;
  statusOptions: Option[];
  level: string;
  onLevel: (v: string) => void;
  levelLabel: string;
  levelOptions: Option[];
  assignee: AssigneeValue;
  onAssignee: (v: AssigneeValue) => void;
}

// 列表页过滤条（Phase-3 §2.6）：关键字 + 状态 + 优先级/严重度 + 指派人。
// 全部走后端 query 参数；清空即回到无过滤（AND 组合、向后兼容）。
export default function FilterBar({
  keyword,
  onKeyword,
  status,
  onStatus,
  statusOptions,
  level,
  onLevel,
  levelLabel,
  levelOptions,
  assignee,
  onAssignee,
}: Props) {
  const hasFilter =
    keyword || status || level || (assignee.assignee_type && assignee.assignee_id != null);

  const selectCls =
    "h-9 rounded-lg border border-border bg-surface px-2.5 text-sm text-ink focus:border-clay focus:outline-none focus:ring-2 focus:ring-clay/20";

  return (
    <div className="mb-4 flex flex-wrap items-end gap-3">
      <div className="relative">
        <span className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-muted/70">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="8" />
            <path d="m21 21-4.3-4.3" />
          </svg>
        </span>
        <input
          value={keyword}
          onChange={(e) => onKeyword(e.target.value)}
          placeholder="关键字（标题 / 描述）"
          aria-label="关键字搜索"
          className="h-9 w-56 rounded-lg border border-border bg-surface pl-8 pr-3 text-sm text-ink placeholder:text-ink-muted/60 focus:border-clay focus:outline-none focus:ring-2 focus:ring-clay/20"
        />
      </div>

      <select
        value={status}
        onChange={(e) => onStatus(e.target.value)}
        aria-label="按状态过滤"
        className={selectCls}
      >
        <option value="">全部状态</option>
        {statusOptions.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>

      <select
        value={level}
        onChange={(e) => onLevel(e.target.value)}
        aria-label={`按${levelLabel}过滤`}
        className={selectCls}
      >
        <option value="">全部{levelLabel}</option>
        {levelOptions.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>

      <div className="w-48">
        <AssigneePicker label="" value={assignee} onChange={onAssignee} />
      </div>

      {hasFilter && (
        <button
          onClick={() => {
            onKeyword("");
            onStatus("");
            onLevel("");
            onAssignee({ assignee_type: null, assignee_id: null });
          }}
          className="h-9 rounded-lg px-3 text-sm text-ink-muted hover:bg-black/[0.04] hover:text-ink"
        >
          清空
        </button>
      )}
    </div>
  );
}
