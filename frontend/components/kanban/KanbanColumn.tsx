"use client";

import Link from "next/link";
import { useDroppable } from "@dnd-kit/core";
import { SortableContext, verticalListSortingStrategy } from "@dnd-kit/sortable";
import type { Card, Requirement } from "@/lib/types";
import KanbanCard from "@/components/kanban/KanbanCard";

interface Props {
  columnKey: string;
  title: string;
  items: Card[];
  /** 该列的真实总数（可能大于 items.length；§2.8）。 */
  total?: number;
  /** items 是否被每列上限截断——为真时列头必须诚实写出「显示 x / 共 y」。 */
  truncated?: boolean;
  entity: "requirements" | "bugs";
  /** 逐卡计算「当前用户可否移动它」（§2.8①），由 KanbanBoard 传入。 */
  canDragCard?: (card: Card) => boolean;
  onConvert?: (req: Requirement) => void;
  onOpen?: (card: Card) => void;
}

// 单列（droppable）+ 列头计数。
export default function KanbanColumn({
  columnKey,
  title,
  items,
  total,
  truncated,
  entity,
  canDragCard,
  onConvert,
  onOpen,
}: Props) {
  const { setNodeRef, isOver } = useDroppable({ id: columnKey });
  // 【lifecycle-and-governance §2.8】被截断时列头必须说实话，并给出「查看全部」的出口；
  // **未截断时不渲染任何额外元素**——小库的观感与本轮之前完全一致。
  const shownTotal = total ?? items.length;

  return (
    <div className="flex w-72 shrink-0 flex-col">
      <div className="mb-2 flex items-center justify-between px-1">
        <h3 className="text-sm font-semibold text-ink">{title}</h3>
        <span className="rounded-full bg-black/[0.05] px-2 py-0.5 text-xs text-ink-muted">
          {shownTotal}
        </span>
      </div>
      {truncated && (
        <div className="mb-2 flex items-center justify-between gap-2 px-1 text-xs text-ink-muted">
          <span title="排序以完整列为准，此处仅显示前若干张">
            显示 {items.length} / 共 {shownTotal}
          </span>
          <Link
            href={`/${entity}?status=${columnKey}`}
            className="shrink-0 text-clay-dark hover:underline"
          >
            查看全部
          </Link>
        </div>
      )}

      <div
        ref={setNodeRef}
        className={[
          "flex min-h-[120px] flex-1 flex-col gap-2 rounded-xl border p-2 transition-colors",
          isOver
            ? "border-clay bg-clay-soft/25"
            : "border-transparent bg-black/[0.02]",
        ].join(" ")}
      >
        {/* Phase-2 §2.6：列内可排序上下文，支撑同列精确重排。 */}
        <SortableContext
          items={items.map((c) => c.id)}
          strategy={verticalListSortingStrategy}
        >
          {items.map((card) => (
            <KanbanCard
              key={card.id}
              card={card}
              entity={entity}
              canDrag={canDragCard ? canDragCard(card) : true}
              onConvert={onConvert}
              onOpen={onOpen}
            />
          ))}
        </SortableContext>
        {items.length === 0 && (
          <div className="flex flex-1 items-center justify-center py-6 text-xs text-ink-muted/70">
            拖拽卡片到此
          </div>
        )}
      </div>
    </div>
  );
}
