"use client";

import { ReactNode, useEffect, useRef } from "react";
import { useOverlayLayer } from "@/lib/overlay-stack";

interface Props {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: ReactNode;
  footer?: ReactNode;
  width?: number;
  /** 点遮罩是否关闭。默认 true（既有全部调用点行为逐字不变）。
   *
   *  置 false 只关掉**遮罩**这一条路径，Esc 与标题栏的 ✕ 照常可用——那两个是用户的
   *  明确动作，而遮罩误点不是。给「关掉就丢数据」的对话框（如一次性口令）用。
   *  **不要**用「把 onClose 传成空函数」来代替它：那会让标题栏那个 aria-label="关闭"
   *  的按钮变成一个点了没反应的死控件，键盘与读屏用户尤其受伤。 */
  dismissOnBackdrop?: boolean;
}

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])';

// 通用弹窗：遮罩 + 居中面板 + Esc 关闭。
// Phase-2 §2.7 a11y：role=dialog / aria-modal、打开时移入焦点、Tab 焦点陷阱。
export default function Modal({
  open,
  onClose,
  title,
  children,
  footer,
  width = 520,
  dismissOnBackdrop = true,
}: Props) {
  const panelRef = useRef<HTMLDivElement>(null);
  const restoreRef = useRef<HTMLElement | null>(null);
  // 【ticket-document-management §6.4 / 评审 R9】接入全局层栈。本轮的文档模态都开在
  // 工单抽屉**之内**：Esc 必须只由栈顶层消费，否则一按就会把模态与抽屉一起关掉，
  // 用户丢失整个工单上下文（编辑器的未保存二次确认也被绕过）。
  const layer = useOverlayLayer(open);

  useEffect(() => {
    if (!open) return;
    restoreRef.current = document.activeElement as HTMLElement;

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (!layer.isTop()) return;         // 不是栈顶 → 这一下不是给我的
        onClose();
        return;
      }
      if (e.key === "Tab" && panelRef.current) {
        // 焦点陷阱：Tab / Shift+Tab 在面板内循环。
        const nodes = panelRef.current.querySelectorAll<HTMLElement>(FOCUSABLE);
        if (nodes.length === 0) return;
        const first = nodes[0];
        const last = nodes[nodes.length - 1];
        const active = document.activeElement;
        if (e.shiftKey && active === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && active === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    window.addEventListener("keydown", onKey);
    // 滚动锁不再由本组件直接操作 `body.style`——它按引用计数收敛在 overlay-stack 里。
    // 此前每层各自 set/restore，模态卸载时会把 overflow 恢复成 ""，于是抽屉还开着、
    // 背景却已经能滚动。
    const t = setTimeout(() => {
      const nodes = panelRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE);
      (nodes && nodes.length ? nodes[0] : panelRef.current)?.focus();
    }, 40);

    return () => {
      window.removeEventListener("keydown", onKey);
      clearTimeout(t);
      restoreRef.current?.focus?.();
    };
  }, [open, onClose, layer]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink/30 p-4 pt-[8vh]"
      onMouseDown={dismissOnBackdrop ? onClose : undefined}
    >
      <div
        ref={panelRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="w-full rounded-xl border border-border bg-surface shadow-lift outline-none"
        style={{ maxWidth: width }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        {title && (
          <div className="flex items-center justify-between border-b border-border px-5 py-4">
            <h2 className="font-serif text-lg text-ink">{title}</h2>
            <button
              onClick={onClose}
              aria-label="关闭"
              className="rounded-md p-1 text-ink-muted hover:bg-black/[0.04] hover:text-ink"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
                   stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <path d="M18 6 6 18M6 6l12 12" />
              </svg>
            </button>
          </div>
        )}
        <div className="px-5 py-4">{children}</div>
        {footer && (
          <div className="flex justify-end gap-2 border-t border-border px-5 py-4">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}
