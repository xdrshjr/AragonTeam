"use client";

import { useState } from "react";
import DocumentTemplateMenu from "@/components/documents/DocumentTemplateMenu";
import type { DocumentTemplate, StageChecklist as Checklist } from "@/lib/types";

interface Props {
  checklist?: Checklist;
  /** 点击一个缺失项 → 打开上传对话框并**预选好该 kind**。 */
  onFill?: (kind: string) => void;
  /** 「用模板新建」——即时生成一份骨架并绑定（document-lifecycle-depth §2.3 C-1）。 */
  onCreateFromTemplate?: (kind: string) => void;
  /** `GET /api/documents/meta` 下发的模板清单；三个无模板的 kind 保持原行为。 */
  templates?: DocumentTemplate[];
  canUpload?: boolean;
}

// 当前阶段的文档清单（ticket-document-management §6.2）。
//
// 两处刻意的设计：
//   1. **缺失项本身就是上传按钮**——把「知道缺什么」与「补上它」压缩成一次点击，
//      这是本设计里交互密度最高、也最值得的一处。
//   2. **同一套组件，两种文案，由后端 `enforced` 字段驱动**。前端绝不自己猜那个开关：
//      门禁默认关闭，此时清单是纯建议性的，写成「必须补充」就是在吓唬用户。
export default function StageChecklist({
  checklist,
  onFill,
  onCreateFromTemplate,
  templates = [],
  canUpload = true,
}: Props) {
  // 【document-lifecycle-depth §6.1】缺失 chip 的一次点击由「直接开上传」升级为
  // 「二选一菜单」。多出来的这一次点击是**值得**的：它把「我没有现成文件」这个最常见
  // 的死路变成了出路。没有模板的三个 kind（复现材料 / 参考资料 / 其他）保持原行为——
  // 给它们配模板是硬套，一份自称完整的空「复现材料」比没有更糟。
  const [openKind, setOpenKind] = useState<string | null>(null);

  if (!checklist || checklist.items.length === 0) return null;

  const { enforced, stage_label, items, satisfied } = checklist;
  const missing = items.filter((i) => !i.satisfied);
  const hasTemplate = (kind: string) =>
    Boolean(onCreateFromTemplate) && templates.some((tpl) => tpl.kind === kind);

  return (
    <div className="rounded-lg border border-border bg-black/[0.015] px-3 py-2.5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-2 gap-y-1">
        <h4 className="text-xs font-semibold text-ink">
          {enforced ? "本阶段必需材料" : "本阶段建议材料"}
          <span className="ml-1.5 font-normal text-ink-muted">· {stage_label}</span>
        </h4>
        {satisfied ? (
          <span className="text-xs text-[#3E7A4F]">已齐备</span>
        ) : enforced ? (
          <span className="text-xs text-[#A44E30]">未补齐将无法推进到下一步</span>
        ) : (
          <span className="text-xs text-ink-muted">缺 {missing.length} 项（不影响流转）</span>
        )}
      </div>

      <ul className="mt-2 flex flex-wrap gap-1.5">
        {items.map((item) => (
          <li key={item.kind}>
            {item.satisfied ? (
              <span className="inline-flex items-center gap-1 rounded-md bg-[#D9EBDD] px-2 py-0.5 text-xs text-[#3E7A4F]">
                <span aria-hidden="true">✓</span>
                {item.label}
              </span>
            ) : canUpload && onFill ? (
              <span className="relative inline-block">
                <button
                  type="button"
                  aria-haspopup={hasTemplate(item.kind) ? "menu" : undefined}
                  aria-expanded={hasTemplate(item.kind) ? openKind === item.kind : undefined}
                  onClick={() => {
                    // 没有模板的 kind 直接开上传框——不为一项菜单多点一次。
                    if (!hasTemplate(item.kind)) {
                      onFill(item.kind);
                      return;
                    }
                    setOpenKind((k) => (k === item.kind ? null : item.kind));
                  }}
                  title={`补充${item.label}`}
                  className="inline-flex items-center gap-1 rounded-md border border-dashed border-border px-2 py-0.5 text-xs text-ink-muted transition-colors hover:border-clay hover:text-clay focus:outline-none focus:ring-2 focus:ring-clay/20"
                >
                  <span aria-hidden="true">＋</span>
                  {item.label}
                </button>
                <DocumentTemplateMenu
                  open={openKind === item.kind}
                  kind={item.kind}
                  label={item.label}
                  templates={templates}
                  onUpload={() => {
                    setOpenKind(null);
                    onFill(item.kind);
                  }}
                  onCreateFromTemplate={() => {
                    setOpenKind(null);
                    onCreateFromTemplate?.(item.kind);
                  }}
                  onClose={() => setOpenKind(null)}
                />
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 rounded-md border border-dashed border-border px-2 py-0.5 text-xs text-ink-muted">
                <span aria-hidden="true">○</span>
                {item.label}
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
