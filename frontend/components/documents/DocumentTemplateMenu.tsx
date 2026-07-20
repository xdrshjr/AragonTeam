"use client";

import { useEffect, useRef } from "react";
import type { DocumentTemplate } from "@/lib/types";

interface Props {
  open: boolean;
  /** 缺失项的 kind；决定「用模板新建」这一项是否可用。 */
  kind: string;
  label: string;
  templates: DocumentTemplate[];
  onUpload: () => void;
  onCreateFromTemplate: () => void;
  onClose: () => void;
}

/**
 * 阶段清单缺失项的「上传文件 / 用模板新建」二选一菜单（document-lifecycle-depth §6.1）。
 *
 * 这多出来的一次点击是**值得**的：它把「我没有现成文件」这个最常见的死路变成了出路。
 * 菜单只有两项、无子菜单、Esc 即关，不构成认知负担。
 *
 * **它不是模态，不进 overlay-stack**（§6.5）：与 `DocumentRow` 的 ⋯ 菜单同类——轻量、
 * 点外即关、不锁滚动。把一个下拉菜单推进层栈会让它抢走抽屉的 Esc，那正好是上一轮
 * R9 的镜像错误。方向键上下移动、Esc 关闭并把焦点还给触发它的 chip。
 */
export default function DocumentTemplateMenu({
  open,
  kind,
  label,
  templates,
  onUpload,
  onCreateFromTemplate,
  onClose,
}: Props) {
  const boxRef = useRef<HTMLDivElement>(null);
  /** 打开前持有焦点的元素（即触发它的 chip），关闭时焦点必须还给它。 */
  const triggerRef = useRef<HTMLElement | null>(null);
  const hasTemplate = templates.some((t) => t.kind === kind);
  const summary = templates.find((t) => t.kind === kind)?.summary;

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (!boxRef.current?.contains(e.target as Node)) onClose();
    };
    window.addEventListener("mousedown", onDocClick);
    return () => window.removeEventListener("mousedown", onDocClick);
  }, [open, onClose]);

  // 打开时记住 chip 并把焦点移进第一项；Esc 的回收在 `onKeyDown` 里做——**不能**写成
  // effect 的 cleanup：菜单关闭时组件先 `return null`，React 在 cleanup 之前就把
  // `boxRef` 置空、DOM 节点也已摘除，那时既判断不出焦点在哪、也无从收回。
  useEffect(() => {
    if (!open) return;
    triggerRef.current = document.activeElement as HTMLElement | null;
    boxRef.current?.querySelector<HTMLButtonElement>('[role="menuitem"]')?.focus();
  }, [open]);

  if (!open) return null;

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") {
      e.stopPropagation();               // 只关菜单，不冒泡去关抽屉
      // 先把焦点还给 chip 再卸载菜单：反过来的话焦点已经落到 body 上，收不回来了。
      triggerRef.current?.focus();
      onClose();
      return;
    }
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    const items = Array.from(
      boxRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]') ?? []
    );
    if (!items.length) return;
    const index = items.indexOf(document.activeElement as HTMLButtonElement);
    const next = e.key === "ArrowDown" ? index + 1 : index - 1;
    items[(next + items.length) % items.length].focus();
  }

  return (
    <div
      ref={boxRef}
      role="menu"
      aria-label={`补充${label}`}
      onKeyDown={onKeyDown}
      className="absolute left-0 top-full z-20 mt-1 w-56 overflow-hidden rounded-lg border border-border bg-surface py-1 text-left shadow-lift"
    >
      <button
        role="menuitem"
        type="button"
        onClick={onUpload}
        className="block w-full px-3 py-2 text-left text-sm text-ink hover:bg-black/[0.04] focus:bg-black/[0.04] focus:outline-none"
      >
        上传文件
        <span className="mt-0.5 block text-xs text-ink-muted">从本机选一份现成的</span>
      </button>
      {hasTemplate && (
        <button
          role="menuitem"
          type="button"
          onClick={onCreateFromTemplate}
          className="block w-full px-3 py-2 text-left text-sm text-ink hover:bg-black/[0.04] focus:bg-black/[0.04] focus:outline-none"
        >
          用模板新建
          <span className="mt-0.5 block text-xs text-ink-muted">
            {summary || `生成一份带工单信息的${label}骨架`}
          </span>
        </button>
      )}
    </div>
  );
}
