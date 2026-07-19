interface Props {
  // 错误文案（可选，缺省给克制的兜底）。
  message?: string;
  // 重试回调（通常传 SWR 的 mutate），无则不渲染按钮。
  onRetry?: () => void;
  className?: string;
}

// 内联错误态原语（reliability-hardening §2.6）——消灭「后端抖动就永久卡骨架」：
// SWR 出错时页面读 error 渲染本组件（错误文案 + 「重试」），风格与 EmptyState 一致。
export default function ErrorState({ message, onRetry, className = "" }: Props) {
  return (
    <div
      className={[
        "flex flex-col items-center justify-center gap-2 px-6 py-12 text-center",
        className,
      ].join(" ")}
    >
      <div className="text-ink-muted/60">
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="9" />
          <path d="M12 8v4" />
          <path d="M12 16h.01" />
        </svg>
      </div>
      <div className="text-sm font-medium text-ink">{message || "加载失败"}</div>
      <div className="max-w-xs text-xs text-ink-muted">
        请检查网络或稍后重试；若持续失败，请确认后端服务已启动。
      </div>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-2 rounded-lg border border-border bg-surface px-3 py-1.5 text-sm text-ink hover:bg-black/[0.03]"
        >
          重试
        </button>
      )}
    </div>
  );
}
