"use client";

import type { StageChecklist as Checklist } from "@/lib/types";

interface Props {
  checklist?: Checklist;
  /** 点击一个缺失项 → 打开上传对话框并**预选好该 kind**。 */
  onFill?: (kind: string) => void;
  canUpload?: boolean;
}

// 当前阶段的文档清单（ticket-document-management §6.2）。
//
// 两处刻意的设计：
//   1. **缺失项本身就是上传按钮**——把「知道缺什么」与「补上它」压缩成一次点击，
//      这是本设计里交互密度最高、也最值得的一处。
//   2. **同一套组件，两种文案，由后端 `enforced` 字段驱动**。前端绝不自己猜那个开关：
//      门禁默认关闭，此时清单是纯建议性的，写成「必须补充」就是在吓唬用户。
export default function StageChecklist({ checklist, onFill, canUpload = true }: Props) {
  if (!checklist || checklist.items.length === 0) return null;

  const { enforced, stage_label, items, satisfied } = checklist;
  const missing = items.filter((i) => !i.satisfied);

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
              <button
                type="button"
                onClick={() => onFill(item.kind)}
                title={`上传${item.label}`}
                className="inline-flex items-center gap-1 rounded-md border border-dashed border-border px-2 py-0.5 text-xs text-ink-muted transition-colors hover:border-clay hover:text-clay focus:outline-none focus:ring-2 focus:ring-clay/20"
              >
                <span aria-hidden="true">＋</span>
                {item.label}
              </button>
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
