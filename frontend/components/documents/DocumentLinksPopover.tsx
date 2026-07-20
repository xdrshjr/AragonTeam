"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Badge from "@/components/ui/Badge";
import { statusStyle } from "@/lib/constants";
import { useDocumentDetail } from "@/hooks/useDocumentLibrary";

interface Props {
  documentId: number;
  linkCount: number;
}

const ENTITY_LABELS: Record<string, string> = { requirement: "需求", bug: "BUG" };

/**
 * 「被引用 N」点开后的工单清单（document-lifecycle-depth §2.1 A-4①）。
 *
 * 补的是复用能力的最后一公里：用户在决定「能不能改这份 PRD」时，第一个问题就是
 * 「谁在用它」。此前 `link_count` 只是一个数字，`links[]` 里也只有 id、没有标题——
 * 本轮详情端点富化了 `entity_title`，这里把数字变成可点开、可跳转的清单。
 *
 * 它是**轻量下拉、不是模态**：点外即关、不锁滚动、不进 `overlay-stack`——把一个下拉
 * 推进层栈会让它抢走抽屉的 Esc（§6.5）。
 */
export default function DocumentLinksPopover({ documentId, linkCount }: Props) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);
  const { document: detail, isLoading } = useDocumentDetail(open ? documentId : null);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (!boxRef.current?.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", onDocClick);
    return () => window.removeEventListener("mousedown", onDocClick);
  }, [open]);

  if (linkCount <= 0) {
    return <span className="text-xs text-ink-muted">未被引用</span>;
  }

  function goto(entityType: string, entityId: number) {
    setOpen(false);
    const segment = entityType === "bug" ? "bugs" : "requirements";
    router.push(`/${segment}/board?ticket=${entityId}`);
  }

  return (
    <div ref={boxRef} className="relative inline-block">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(e) => {
          if (e.key === "Escape" && open) {
            e.stopPropagation();          // 开着时 Esc 只关本浮层，不冒泡去关抽屉
            setOpen(false);
          }
        }}
        className="rounded text-xs text-clay hover:underline focus:outline-none focus:ring-2 focus:ring-clay/20"
      >
        被引用 {linkCount}
      </button>
      {open && (
        <div
          role="menu"
          aria-label="引用这份文档的工单"
          className="absolute right-0 top-full z-20 mt-1 w-64 overflow-hidden rounded-lg border border-border bg-surface py-1 shadow-lift"
        >
          {isLoading && !detail && (
            <p className="px-3 py-2 text-xs text-ink-muted">加载中…</p>
          )}
          {detail?.links.map((link) => (
            <button
              key={link.id}
              role="menuitem"
              onClick={() => goto(link.entity_type, link.entity_id)}
              className="flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-black/[0.04]"
            >
              <span className="shrink-0 text-xs text-ink-muted">
                {ENTITY_LABELS[link.entity_type] ?? link.entity_type}
              </span>
              <span className="min-w-0 flex-1 truncate text-sm text-ink">
                {link.entity_title ?? `#${link.entity_id}（已删除）`}
              </span>
              {link.stage && <Badge style={statusStyle(link.stage)} />}
            </button>
          ))}
          {detail && detail.links.length === 0 && (
            <p className="px-3 py-2 text-xs text-ink-muted">没有任何工单引用它。</p>
          )}
        </div>
      )}
    </div>
  );
}
