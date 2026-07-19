"use client";

import { useRef, useState } from "react";
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  KeyboardSensor,
  useSensor,
  useSensors,
  closestCorners,
  DragStartEvent,
  DragEndEvent,
} from "@dnd-kit/core";
import { sortableKeyboardCoordinates } from "@dnd-kit/sortable";
import { useAuth } from "@/lib/auth";
import { canManageTicket } from "@/lib/permissions";
import type { Board, Card, Requirement } from "@/lib/types";
import KanbanColumn from "@/components/kanban/KanbanColumn";
import KanbanCard from "@/components/kanban/KanbanCard";

interface Props {
  board: Board<Card>;
  entity: "requirements" | "bugs";
  // toIndex：目标列内 0-based 插入索引（Phase-2 §2.6）；缺省 = 追加列尾。
  onMove: (cardId: number, toStatus: string, toIndex?: number) => void;
  onConvert?: (req: Requirement) => void;
  onOpen?: (card: Card) => void; // 点击卡片打开详情抽屉
}

// @dnd-kit 容器：列布局 + 列内可排序，拖拽落点回调。
// 拖拽合法性交后端裁决（onMove → PATCH /move），前端只负责乐观 UI（§2.3 R-02）。
export default function KanbanBoard({ board, entity, onMove, onConvert, onOpen }: Props) {
  const { user } = useAuth();
  const [activeCard, setActiveCard] = useState<Card | null>(null);
  // 拖拽守卫：区分「点击打开抽屉」与「拖拽」，避免拖拽结束误触发 onClick。
  const draggingRef = useRef(false);

  const sensors = useSensors(
    // 需要移动阈值，避免点击（打开抽屉 / 转 BUG）被误判为拖拽。
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    // P2 无障碍：键盘可达拖拽。
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );

  function findCard(id: number): Card | null {
    for (const col of board.columns) {
      const c = col.items.find((x) => x.id === id);
      if (c) return c;
    }
    return null;
  }

  // 定位某卡所在列 key 与列内索引。
  function locate(id: number): { status: string; index: number } | null {
    for (const col of board.columns) {
      const index = col.items.findIndex((c) => c.id === id);
      if (index >= 0) return { status: col.key, index };
    }
    return null;
  }

  function onDragStart(e: DragStartEvent) {
    draggingRef.current = true;
    setActiveCard(findCard(Number(e.active.id)));
  }

  function endDrag() {
    setActiveCard(null);
    // 延后复位，让紧随 pointerup 的 click 事件仍看到 dragging=true 而被抑制。
    setTimeout(() => {
      draggingRef.current = false;
    }, 0);
  }

  function onDragEnd(e: DragEndEvent) {
    const { active, over } = e;
    endDrag();
    if (!over) return;

    const cardId = Number(active.id);
    const overId = over.id;

    let toStatus: string;
    let toIndex: number | undefined;

    if (typeof overId === "string") {
      // 落在列的空白 / droppable 上 → 追加到该列尾。
      toStatus = overId;
      toIndex = undefined;
    } else {
      // 落在某张卡上 → 目标列 = 该卡所在列，插入索引 = 该卡当前索引。
      const loc = locate(Number(overId));
      if (!loc) return;
      toStatus = loc.status;
      toIndex = loc.index;
    }

    const from = locate(cardId);
    if (!from) return;
    // 同列且落回自身位置 → 无变化。
    if (from.status === toStatus && toIndex === from.index) return;

    onMove(cardId, toStatus, toIndex);
  }

  // 打开抽屉：仅在非拖拽结束时触发（§2.4 点击/拖拽互斥）。
  function handleOpen(card: Card) {
    if (draggingRef.current) return;
    onOpen?.(card);
  }

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCorners}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onDragCancel={endDrag}
    >
      <div className="no-scrollbar flex h-full gap-4 overflow-x-auto pb-4">
        {board.columns.map((col) => (
          <KanbanColumn
            key={col.key}
            columnKey={col.key}
            title={col.title}
            items={col.items}
            entity={entity}
            // 【§2.8①】与后端 /move 的 can_manage_ticket 同判据：无权的卡不给抓手、不可拖。
            canDragCard={(card) => canManageTicket(user, card)}
            onConvert={onConvert}
            onOpen={handleOpen}
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
