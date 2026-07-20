"use client";

import Button from "@/components/ui/Button";

/** `K` 由调用方的动作枚举收窄，`onAction` 因此不必在回调里 as 回去。 */
export interface BulkAction<K extends string = string> {
  key: K;
  label: string;
  /** 危险动作（删除）用红色描边按钮，并排在最右、与其它动作留出间距。 */
  danger?: boolean;
}

interface Props<K extends string> {
  count: number;
  /** 当前页可选总数，用于「已选 3 / 本页 50」这句诚实的话。 */
  pageTotal: number;
  actions: BulkAction<K>[];
  pending: boolean;
  onAction: (key: K) => void;
  onClear: () => void;
}

/**
 * 选中态浮动动作栏（bulk-operations §3.4）。
 *
 * 交互取舍：
 * - **浮在底部中央而非顶部**：列表最后一行与页脚分页之间是拇指与视线的落点，动作栏
 *   出现在那里，用户不必把视线拉回页首；同时它不占据文档流，出现/消失不会让表格跳动。
 * - **恒显示计数与范围**（「已选 3 · 本页 50」）：批量操作最怕的是「我以为选了 50 张」，
 *   把范围写在按钮旁边，比任何提示语都有效。
 * - **pending 期间全体禁用**：批量请求可能写几十行，慢网下双击就是两次全量写入。
 * - 选中为 0 时整条不渲染——空动作栏是纯粹的视觉噪音。
 */
export default function BulkActionBar<K extends string>({
  count,
  pageTotal,
  actions,
  pending,
  onAction,
  onClear,
}: Props<K>) {
  if (count === 0) return null;

  return (
    <div
      role="region"
      aria-label="批量操作"
      className="pointer-events-none fixed inset-x-0 bottom-6 z-40 flex justify-center px-4"
    >
      <div className="animate-bulk-bar-in pointer-events-auto flex max-w-full flex-wrap items-center gap-2 rounded-xl border border-border bg-surface px-3 py-2 shadow-lift">
        <span className="px-1 text-sm text-ink">
          已选 <strong className="font-semibold">{count}</strong>
          <span className="text-ink-muted"> · 本页 {pageTotal}</span>
        </span>
        <span aria-hidden className="mx-1 h-5 w-px bg-border" />
        {actions.map((action) => (
          <Button
            key={action.key}
            size="sm"
            variant={action.danger ? "danger" : "ghost"}
            disabled={pending}
            onClick={() => onAction(action.key)}
            className={action.danger ? "ml-1" : ""}
          >
            {action.label}
          </Button>
        ))}
        <span aria-hidden className="mx-1 h-5 w-px bg-border" />
        <Button size="sm" variant="subtle" disabled={pending} onClick={onClear}>
          清除选择
        </Button>
      </div>
    </div>
  );
}
