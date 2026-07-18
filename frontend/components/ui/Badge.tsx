import type { BadgeStyle } from "@/lib/constants";

interface Props {
  style: BadgeStyle;
  className?: string;
}

// 读 constants 配色的状态/优先级/严重度徽章。
export default function Badge({ style, className = "" }: Props) {
  return (
    <span
      className={[
        "inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium whitespace-nowrap",
        className,
      ].join(" ")}
      style={{ backgroundColor: style.bg, color: style.fg }}
    >
      {style.label}
    </span>
  );
}
