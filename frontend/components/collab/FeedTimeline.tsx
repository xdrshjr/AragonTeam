"use client";

import type { ReactNode } from "react";
import type { FeedItem, AuthorSummary } from "@/lib/types";
import { actionLabel, statusStyle, MENTION_RE } from "@/lib/constants";
import Avatar from "@/components/ui/Avatar";
import EmptyState from "@/components/ui/EmptyState";

interface Props {
  items: FeedItem[];
}

// 把评论正文里的 @username 渲染为 clay chip；非提及段原样输出（外层保留 whitespace-pre-wrap）。
// 用 String.prototype.matchAll（无状态消费全局 MENTION_RE，见 constants.ts·P2-1）切分。
function renderBody(body: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let last = 0;
  let key = 0;
  for (const m of body.matchAll(MENTION_RE)) {
    const start = m.index ?? 0;
    if (start > last) nodes.push(body.slice(last, start));
    nodes.push(
      <span key={`m-${key++}`} className="rounded bg-clay/10 px-1 font-medium text-clay-dark">
        {m[0]}
      </span>
    );
    last = start + m[0].length;
  }
  if (last < body.length) nodes.push(body.slice(last));
  return nodes;
}

// 短时间格式（created_at 为 UTC，带 Z；JS Date 正确解析为本地时间）。
function shortTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function authorName(a: AuthorSummary | null): string {
  return a?.name || "系统";
}

// 合并 feed 时间线（§2.4 协作区核心）：
// - activity → 细线时间轴上的小圆点 + 灰字（谁 + 动作 + 说明）；
// - comment  → 带作者头像的气泡，Agent 作者用机器人图标 + clay 描边区分于人类，
//   system 用中性描边。人 / Agent / 系统三类视觉可区分（P-U2）。
export default function FeedTimeline({ items }: Props) {
  if (!items.length) {
    return (
      <EmptyState
        title="还没有协作记录"
        hint="创建、指派、流转与评论都会出现在这里，形成人机混合协作时间线。"
      />
    );
  }

  return (
    <ol className="relative space-y-4 py-1">
      {items.map((item) => {
        if (item.kind === "activity") {
          const dotColor = statusStyle(item.to_status || "new").fg;
          return (
            <li key={`a-${item.id}`} className="flex items-start gap-3 pl-1">
              <span
                className="mt-1.5 inline-block h-2 w-2 shrink-0 rounded-full ring-4 ring-bg"
                style={{ backgroundColor: dotColor }}
              />
              <div className="min-w-0 flex-1 text-sm">
                <span className="text-ink">{authorName(item.actor)}</span>{" "}
                <span className="text-ink-muted">
                  {actionLabel(item.action)}
                  {item.message ? ` · ${item.message}` : ""}
                </span>
                <div className="mt-0.5 text-xs text-ink-muted/70">
                  {shortTime(item.created_at)}
                </div>
              </div>
            </li>
          );
        }

        // comment
        const isAgent = item.author_type === "agent";
        const isSystem = item.author_type === "system";
        return (
          <li key={`c-${item.id}`} className="flex items-start gap-3">
            {isSystem ? (
              <span
                className="mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-border bg-black/[0.03] text-ink-muted"
                title="系统"
                aria-label="系统"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
                     stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
                  <circle cx="12" cy="12" r="9" />
                  <path d="M12 8v4M12 16h.01" />
                </svg>
              </span>
            ) : (
              <Avatar
                name={item.author.name}
                color={item.author.avatar_color}
                isAgent={isAgent}
                size={28}
              />
            )}
            <div
              className={[
                "min-w-0 flex-1 rounded-xl border px-3 py-2",
                isAgent
                  ? "border-clay-soft bg-clay-soft/25"
                  : isSystem
                  ? "border-border bg-black/[0.02]"
                  : "border-border bg-surface",
              ].join(" ")}
            >
              <div className="mb-0.5 flex items-center gap-2">
                <span className="text-sm font-medium text-ink">
                  {item.author.name}
                </span>
                {isAgent && (
                  <span className="rounded bg-clay/10 px-1.5 py-0.5 text-[10px] font-medium text-clay-dark">
                    Agent
                  </span>
                )}
                <span className="text-xs text-ink-muted/70">
                  {shortTime(item.created_at)}
                </span>
              </div>
              <div className="whitespace-pre-wrap text-sm text-ink">{renderBody(item.body)}</div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
