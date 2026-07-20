"use client";

import { useEffect, useRef, useState } from "react";
import Badge from "@/components/ui/Badge";
import {
  documentIcon,
  documentKindStyle,
  formatBytes,
  statusStyle,
} from "@/lib/constants";
import type { DocumentSummary, TicketDocument } from "@/lib/types";

export interface RowAction {
  key: string;
  label: string;
  onSelect: () => void;
  /** 破坏性动作：置于分隔线之下并用危险色（与既有 ConfirmDialog 的分区惯例一致）。 */
  danger?: boolean;
}

interface Props {
  document: DocumentSummary | TicketDocument;
  actions: RowAction[];
  /** 绑定阶段徽章（仅工单内的文档行有）。 */
  showStage?: boolean;
  onOpen?: () => void;
}

function shortDate(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? ""
    : d.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" });
}

// 文档单行（ticket-document-management §6.2）：类型徽章、名称、版本、大小、上传人、操作菜单。
export default function DocumentRow({ document: doc, actions, showStage, onOpen }: Props) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const version = doc.current_version;
  const link = (doc as TicketDocument).link;

  // 点击别处 / 按 Esc 关掉菜单。菜单不是覆盖层，不进 overlay-stack——它不锁滚动，
  // 也不该在抽屉之上抢 Esc；这里的 Esc 处理挂在菜单容器上而非 window，天然不越界。
  useEffect(() => {
    if (!menuOpen) return;
    const onDocClick = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) setMenuOpen(false);
    };
    window.addEventListener("mousedown", onDocClick);
    return () => window.removeEventListener("mousedown", onDocClick);
  }, [menuOpen]);

  const normal = actions.filter((a) => !a.danger);
  const dangerous = actions.filter((a) => a.danger);

  return (
    <div className="group flex items-center gap-2 rounded-lg border border-transparent px-2 py-1.5 transition-colors hover:border-border hover:bg-black/[0.015]">
      <span aria-hidden="true" className="shrink-0 text-base leading-none">
        {documentIcon(version?.original_filename)}
      </span>
      <Badge style={documentKindStyle(doc.kind)} className="shrink-0" />

      <button
        type="button"
        onClick={onOpen}
        title={doc.title}
        className="min-w-0 flex-1 truncate text-left text-sm text-ink hover:text-clay focus:outline-none focus:ring-2 focus:ring-clay/20 rounded"
      >
        {doc.title}
      </button>

      <div className="hidden shrink-0 items-center gap-2 text-xs text-ink-muted sm:flex">
        {version && <span>v{version.version_no}</span>}
        <span>{formatBytes(version?.size_bytes)}</span>
        {doc.uploader && <span className="max-w-[6rem] truncate">{doc.uploader.name}</span>}
        <span>{shortDate(version?.created_at ?? doc.created_at)}</span>
        {showStage && link?.stage && <Badge style={statusStyle(link.stage)} />}
      </div>

      <div ref={menuRef} className="relative shrink-0">
        <button
          type="button"
          aria-label={`「${doc.title}」的操作`}
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen((v) => !v)}
          onKeyDown={(e) => {
            if (e.key === "Escape" && menuOpen) {
              e.stopPropagation();          // 菜单开着时 Esc 只关菜单，不冒泡去关抽屉
              setMenuOpen(false);
            }
          }}
          className="rounded-md px-1.5 py-1 text-ink-muted hover:bg-black/[0.05] hover:text-ink focus:outline-none focus:ring-2 focus:ring-clay/20"
        >
          ⋯
        </button>
        {menuOpen && (
          <div
            role="menu"
            className="absolute right-0 top-full z-20 mt-1 w-40 overflow-hidden rounded-lg border border-border bg-surface py-1 shadow-lift"
          >
            {normal.map((action) => (
              <button
                key={action.key}
                role="menuitem"
                onClick={() => {
                  setMenuOpen(false);
                  action.onSelect();
                }}
                className="block w-full px-3 py-1.5 text-left text-sm text-ink hover:bg-black/[0.04]"
              >
                {action.label}
              </button>
            ))}
            {dangerous.length > 0 && (
              <div className="my-1 border-t border-border" role="separator" />
            )}
            {dangerous.map((action) => (
              <button
                key={action.key}
                role="menuitem"
                onClick={() => {
                  setMenuOpen(false);
                  action.onSelect();
                }}
                className="block w-full px-3 py-1.5 text-left text-sm text-[#B23B1E] hover:bg-[#F3D2C7]/40"
              >
                {action.label}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
