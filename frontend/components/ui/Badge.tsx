import type { BadgeStyle } from "@/lib/constants";

interface Props {
  // 允许缺省：枚举越界时 PRIORITY_STYLES[p] / SEVERITY_STYLES[s] 运行期为 undefined。
  style?: BadgeStyle;
  className?: string;
}

// 中性兜底：枚举越界（脏数据 / 后端新增枚举未同步）时不再取 undefined.bg 崩溃（§2.7-C4）。
const FALLBACK_STYLE: BadgeStyle = { bg: "#EFEAE0", fg: "#6E6A62", label: "—" };

// 读 constants 配色的状态/优先级/严重度徽章。
export default function Badge({ style, className = "" }: Props) {
  const s = style ?? FALLBACK_STYLE;
  return (
    <span
      className={[
        "inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium whitespace-nowrap",
        className,
      ].join(" ")}
      style={{ backgroundColor: s.bg, color: s.fg }}
    >
      {s.label}
    </span>
  );
}
