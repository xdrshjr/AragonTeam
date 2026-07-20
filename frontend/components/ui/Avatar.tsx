import type { AssigneeSummary, AuthorSummary } from "@/lib/types";

interface Props {
  // 人：传 name + color；Agent：传 name + isAgent。
  name: string;
  color?: string | null;
  isAgent?: boolean;
  size?: number;
  title?: string;
}

// 人=首字母彩底圆形头像；Agent=机器人图标。
export default function Avatar({ name, color, isAgent, size = 28, title }: Props) {
  const initial = (name || "?").trim().charAt(0).toUpperCase();
  const dim = { width: size, height: size, fontSize: Math.round(size * 0.42) };

  if (isAgent) {
    return (
      <span
        title={title || name}
        className="inline-flex items-center justify-center rounded-lg bg-ink text-white"
        style={dim}
        aria-label={`Agent ${name}`}
      >
        {/* 简约机器人图标 */}
        <svg width={size * 0.6} height={size * 0.6} viewBox="0 0 24 24" fill="none"
             stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"
             strokeLinejoin="round">
          <rect x="4" y="7" width="16" height="12" rx="2" />
          <path d="M12 7V4M8 12h.01M16 12h.01M9 16h6" />
        </svg>
      </span>
    );
  }

  return (
    <span
      title={title || name}
      className="inline-flex items-center justify-center rounded-full font-semibold text-white select-none"
      style={{ ...dim, backgroundColor: color || "#C15F3C" }}
      aria-label={name}
    >
      {initial}
    </span>
  );
}

// 便捷：由 assignee 概要渲染头像；未指派返回占位。
export function AssigneeAvatar({
  assignee,
  size = 28,
}: {
  assignee: AssigneeSummary | null;
  size?: number;
}) {
  if (!assignee) {
    return (
      <span
        className="inline-flex items-center justify-center rounded-full border border-dashed border-border text-ink-muted"
        style={{ width: size, height: size, fontSize: size * 0.5 }}
        title="未指派"
      >
        ·
      </span>
    );
  }
  // 【lifecycle-and-governance §2.5/2.7】指向已删除目标 / 已停用成员时灰显 + 说明，
  // 让「这张单其实已经没人管了」看得见——而不是若无其事地画一个正常头像。
  const inactive = assignee.deleted === true || assignee.is_active === false;
  const suffix = assignee.deleted
    ? "（已删除）"
    : assignee.is_active === false
      ? "（已停用）"
      : assignee.type === "agent"
        ? "（Agent）"
        : "";
  return (
    <span className={inactive ? "inline-flex opacity-50 grayscale" : "inline-flex"}>
      <Avatar
        name={assignee.name}
        color={assignee.avatar_color}
        isAgent={assignee.type === "agent"}
        size={size}
        title={`${assignee.name}${suffix}`}
      />
    </span>
  );
}

// 由施动者概要渲染头像（Phase-3 通知铃铛）：user/agent 用常规头像；
// system / 空施动者用中性圆底 + fallback（如通知类型 emoji）。
export function AuthorAvatar({
  author,
  size = 26,
  fallback = "🔔",
}: {
  author: AuthorSummary | null;
  size?: number;
  fallback?: string;
}) {
  if (author && (author.type === "user" || author.type === "agent")) {
    return (
      <Avatar
        name={author.name}
        color={author.avatar_color}
        isAgent={author.type === "agent"}
        size={size}
        title={author.name}
      />
    );
  }
  return (
    <span
      className="inline-flex items-center justify-center rounded-full border border-border bg-black/[0.03] text-ink-muted"
      style={{ width: size, height: size, fontSize: Math.round(size * 0.5) }}
      title={author?.name || "系统"}
      aria-hidden="true"
    >
      {fallback}
    </span>
  );
}
