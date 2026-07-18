"use client";

import { useState } from "react";
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  useSensor,
  useSensors,
  closestCorners,
  DragStartEvent,
  DragEndEvent,
} from "@dnd-kit/core";
import type { Board, Card, Requirement } from "@/lib/types";
import KanbanColumn from "@/components/kanban/KanbanColumn";
import KanbanCard from "@/components/kanban/KanbanCard";

interface Props {
  board: Board<Card>;
  entity: "requirements" | "bugs";
  onMove: (cardId: number, toStatus: string) => void;
  onConvert?: (req: Requirement) => void;
}

// @dnd-kit 容器：列布局，拖拽落列回调。
// 拖拽合法性交后端裁决（onMove → PATCH /move），前端只负责乐观 UI（§2.3 R-02）。
export default function KanbanBoard({ board, entity, onMove, onConvert }: Props) {
  const [activeCard, setActiveCard] = useState<Card | null>(null);

  // 需要移动阈值，避免点击（如「转 BUG」按钮）被误判为拖拽。
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } })
  );

  function findCard(id: number): Card | null {
    for (const col of board.columns) {
      const c = col.items.find((x) => x.id === id);
      if (c) return c;
    }
    return null;
  }

  function onDragStart(e: DragStartEvent) {
    setActiveCard(findCard(Number(e.active.id)));
  }

  function onDragEnd(e: DragEndEvent) {
    setActiveCard(null);
    const { active, over } = e;
    if (!over) return;
    const cardId = Number(active.id);
    const toStatus = String(over.id); // droppable id = 列 key
    const fromStatus = (active.data.current as { fromStatus?: string } | undefined)
      ?.fromStatus;
    if (fromStatus === toStatus) return;
    onMove(cardId, toStatus);
  }

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCorners}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onDragCancel={() => setActiveCard(null)}
    >
      <div className="no-scrollbar flex h-full gap-4 overflow-x-auto pb-4">
        {board.columns.map((col) => (
          <KanbanColumn
            key={col.key}
            columnKey={col.key}
            title={col.title}
            items={col.items}
            entity={entity}
            onConvert={onConvert}
          />
        ))}
      </div>

      <DragOverlay dropAnimation={null}>
        {activeCard ? (
          <KanbanCard card={activeCard} entity={entity} overlay />
        ) : null}
      </DragOverlay>
    </DndContext>
  );
}
