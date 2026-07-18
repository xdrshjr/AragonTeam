"use client";

import { useDroppable } from "@dnd-kit/core";
import { SortableContext, verticalListSortingStrategy } from "@dnd-kit/sortable";
import type { Card, Requirement } from "@/lib/types";
import KanbanCard from "@/components/kanban/KanbanCard";

interface Props {
  columnKey: string;
  title: string;
  items: Card[];
  entity: "requirements" | "bugs";
  onConvert?: (req: Requirement) => void;
  onOpen?: (card: Card) => void;
}

// 单列（droppable）+ 列头计数。
export default function KanbanColumn({
  columnKey,
  title,
  items,
  entity,
  onConvert,
  onOpen,
}: Props) {
  const { setNodeRef, isOver } = useDroppable({ id: columnKey });

  return (
    <div className="flex w-72 shrink-0 flex-col">
      <div className="mb-2 flex items-center justify-between px-1">
        <h3 className="text-sm font-semibold text-ink">{title}</h3>
        <span className="rounded-full bg-black/[0.05] px-2 py-0.5 text-xs text-ink-muted">
          {items.length}
        </span>
      </div>

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
