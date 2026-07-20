// 确定进度条（ticket-document-management §3.4）。经核实现网 components/ui/ 无此原语，确需新建。
//
// a11y：`role="progressbar"` + `aria-valuenow/min/max`。`value` 为 null 时进入
// **不确定**模式（后端未回 Content-Length 等场景）——此时不给 aria-valuenow，
// 也不画一个假的百分比，屏幕阅读器与视觉用户看到的是同一件事：还在传，但不知道还剩多少。

interface Props {
  /** 0~100；null 表示进度未知。 */
  value: number | null;
  label?: string;
  className?: string;
}

export default function ProgressBar({ value, label, className = "" }: Props) {
  const determinate = value != null && Number.isFinite(value);
  const percent = determinate ? Math.max(0, Math.min(100, value as number)) : null;

  return (
    <div
      role="progressbar"
      aria-label={label || "上传进度"}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={percent ?? undefined}
      aria-valuetext={percent == null ? "进度未知" : `${percent}%`}
      className={["h-1.5 w-full overflow-hidden rounded-full bg-black/[0.06]", className].join(" ")}
    >
      <div
        className={[
          "h-full rounded-full bg-clay transition-[width] duration-200 ease-out",
          percent == null ? "animate-pulse" : "",
        ].join(" ")}
        style={{ width: percent == null ? "40%" : `${percent}%` }}
      />
    </div>
  );
}
