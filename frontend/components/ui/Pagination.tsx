"use client";

import Button from "@/components/ui/Button";

interface Props {
  /** 当前页首条下标（0 基）。 */
  offset: number;
  /** 每页条数。 */
  limit: number;
  /** 后端 X-Total-Count（未分页前总数）。 */
  total: number;
  onOffset: (next: number) => void;
  /** 取数中禁用，防连点越界。 */
  disabled?: boolean;
}

/**
 * 受控分页条（scale-and-project-scope §2.3①）——无 state、无副作用。
 *
 * `total <= limit` 时**不渲染**：保证小数据量下页面观感与接入分页前完全一致（零视觉回归）。
 */
export default function Pagination({ offset, limit, total, onOffset, disabled }: Props) {
  if (total <= limit) return null;

  const from = offset + 1;
  const to = Math.min(offset + limit, total);
  const isFirst = offset <= 0;
  const isLast = offset + limit >= total;

  return (
    <div className="flex items-center justify-between border-t border-border px-4 py-3 text-sm text-ink-muted">
      <span>
        第 {from}–{to} 条 / 共 {total} 条
      </span>
      <div className="flex items-center gap-2">
        <Button
          variant="ghost"
          size="sm"
          disabled={disabled || isFirst}
          onClick={() => onOffset(Math.max(0, offset - limit))}
        >
          上一页
        </Button>
        <Button
          variant="ghost"
          size="sm"
          disabled={disabled || isLast}
          onClick={() => onOffset(offset + limit)}
        >
          下一页
        </Button>
      </div>
    </div>
  );
}
