"use client";

import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import type { Card, Requirement, Bug } from "@/lib/types";
import { AssigneeAvatar } from "@/components/ui/Avatar";
import Badge from "@/components/ui/Badge";
import { PRIORITY_STYLES, SEVERITY_STYLES } from "@/lib/constants";

interface Props {
  card: Card;
  entity: "requirements" | "bugs";
  overlay?: boolean; // DragOverlay 里渲染时禁用 dnd 绑定
  /** 当前用户是否可移动这张卡（后端 can_manage_ticket 同判据）。false 时禁用拖拽。 */
  canDrag?: boolean;
  onConvert?: (req: Requirement) => void; // 需求转 BUG
  onOpen?: (card: Card) => void; // 点击卡片打开工单详情抽屉（§2.4，与拖拽互斥）
}

function isBug(card: Card): card is Bug {
  return (card as Bug).severity !== undefined;
}

export default function KanbanCard({
  card, entity, overlay, canDrag = true, onConvert, onOpen,
}: Props) {
  // Phase-2 §2.6：改用 useSortable 支持同列精确重排（SortableContext 内生效）。
  // 【§2.8①】无管理权的卡**不可拖**：此前对每张卡无条件启用，member 拖别人的卡会飞过去又弹回，
  // 并弹出后端原样的英文 toast `forbidden` —— 与抽屉早已按 canManage 门禁的做法不一致。
  const {
    attributes, listeners, setNodeRef, transform, transition, isDragging,
  } = useSortable({
    id: card.id,
    data: { fromStatus: card.status },
    disabled: overlay || !canDrag,
  });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };

  const badge = isBug(card)
    ? SEVERITY_STYLES[card.severity]
    : PRIORITY_STYLES[(card as Requirement).priority];

  // 需求在 testing / reviewing 列可「转 BUG」（后端校验当前态 ∈ {testing,reviewing}）。
  const canConvert =
    entity === "requirements" &&
    !overlay &&
    ((card as Requirement).status === "testing" ||
      (card as Requirement).status === "reviewing");

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={[
        "group rounded-xl border border-border bg-surface p-3 shadow-card",
        overlay
          ? "shadow-lift rotate-[1.5deg]"
          : canDrag
            ? "cursor-grab active:cursor-grabbing"
            : "cursor-pointer",
        isDragging ? "opacity-40" : "",
      ].join(" ")}
      // 点击打开详情抽屉；拖拽与点击互斥由 KanbanBoard 的 dragging 守卫兜底（§2.4）。
      onClick={overlay ? undefined : () => onOpen?.(card)}
      {...(overlay ? {} : listeners)}
      {...(overlay ? {} : attributes)}
    >
      <div className="mb-2 flex items-start justify-between gap-2">
        <span className="text-xs font-medium text-ink-muted">
          {entity === "bugs" ? "BUG" : "REQ"}-{card.id}
        </span>
        <Badge style={badge} />
      </div>

      <div className="mb-3 text-sm font-medium leading-snug text-ink">
        {card.title}
      </div>

      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <AssigneeAvatar assignee={card.assignee} size={24} />
          {/* 【ticket-document-management §6.1】回形针 + 数字，**只读**：点击不做任何事
              （打开工单才是唯一入口），避免在卡片上堆第二种点击语义。 */}
          {(card.document_count ?? 0) > 0 && (
            <span
              title={`${card.document_count} 份文档`}
              aria-label={`${card.document_count} 份文档`}
              className="inline-flex items-center gap-0.5 rounded-md bg-black/[0.045] px-1.5 py-0.5 text-xs text-ink-muted"
            >
              <span aria-hidden="true">📎</span>
              {card.document_count}
            </span>
          )}
        </div>
        {isBug(card) && card.related_requirement_id && (
          <span className="text-xs text-ink-muted">
            源需求 #{card.related_requirement_id}
          </span>
        )}
        {canConvert && onConvert && (
          <button
            // 阻止拖拽监听吞掉点击，并避免冒泡到卡片 onClick（打开抽屉）。
            onPointerDown={(e) => e.stopPropagation()}
            onClick={(e) => {
              e.stopPropagation();
              onConvert(card as Requirement);
            }}
            aria-label={`把需求 #${card.id} 转为 BUG`}
            // 【H6】opacity:0 **不移除命中区**：触屏点卡片右下角会误触发这个**不可逆**的转 BUG。
            // 用 pointer-events 真正屏蔽命中，并给键盘用户留 focus-visible 通路。
            className="rounded-md border border-[#E8C9BC] px-2 py-0.5 text-xs text-clay-dark pointer-events-none opacity-0 transition-opacity hover:bg-clay-soft/40 group-hover:pointer-events-auto group-hover:opacity-100 focus-visible:pointer-events-auto focus-visible:opacity-100"
          >
            转 BUG
          </button>
        )}
      </div>
    </div>
  );
}
