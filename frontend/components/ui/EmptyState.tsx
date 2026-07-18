import type { ReactNode } from "react";

interface Props {
  // 图标（可选，传 svg / emoji 节点）。
  icon?: ReactNode;
  title: string;
  hint?: string;
  action?: ReactNode; // 可选 CTA
  className?: string;
}

// 空状态原语（Phase-2 §2.7）——图标 + 标题 + 提示 + 可选 CTA。
// 用于空列表、空看板列、无活动等，避免「一片空白」的失落感。
export default function EmptyState({ icon, title, hint, action, className = "" }: Props) {
  return (
    <div
      className={[
        "flex flex-col items-center justify-center gap-2 px-6 py-12 text-center",
        className,
      ].join(" ")}
    >
      {icon && <div className="text-ink-muted/60">{icon}</div>}
      <div className="text-sm font-medium text-ink">{title}</div>
      {hint && <div className="max-w-xs text-xs text-ink-muted">{hint}</div>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}
