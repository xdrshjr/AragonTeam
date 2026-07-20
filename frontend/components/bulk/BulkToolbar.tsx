"use client";

import { useState } from "react";
import { ApiError } from "@/lib/api";
import { useToast } from "@/lib/toast";
import {
  BulkEntity,
  ENTITY_LABELS,
  bulkSummary,
  needsReview,
  runBulk,
} from "@/lib/bulk";
import type { BulkRequest, BulkResult, Card } from "@/lib/types";
import type { BulkSelection } from "@/hooks/useBulkSelection";
import type { AssigneeValue } from "@/components/AssigneePicker";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import BulkActionBar, { BulkAction } from "@/components/bulk/BulkActionBar";
import BulkAssignModal from "@/components/bulk/BulkAssignModal";
import BulkLevelModal from "@/components/bulk/BulkLevelModal";
import BulkStatusModal from "@/components/bulk/BulkStatusModal";
import BulkResultDialog from "@/components/bulk/BulkResultDialog";

interface Props {
  entity: BulkEntity;
  selection: BulkSelection<Card>;
  /** 当前页可选行数，动作栏用它说清「已选 3 · 本页 50」。 */
  pageTotal: number;
  /** pm/admin：与单条端点一致，只有他们能批量指派与删除。 */
  canManage: boolean;
  /** 写成功后刷新列表（SWR mutate）。 */
  onDone: () => void;
}

/** 动作栏按钮 key = 弹窗模式，两者共用一个枚举，省掉一次 as 转换。 */
type BulkMode = "assign" | "move" | "level" | "delete";
type Mode = BulkMode | null;

/**
 * 列表页批量操作的编排器（bulk-operations §3.4）。
 *
 * 需求页与 BUG 页的批量部分除了「级别叫优先级还是严重度」以外完全同构，故整块收敛
 * 在这里：两个页面各自只需要「渲染复选框列 + 挂上本组件」。
 *
 * 三条贯穿始终的交互约定：
 * - **动作后不清空全部选择，只保留失败项**：批量失败几乎总是要重试的，把成功的清掉、
 *   失败的留着，用户下一步就能直接再点一次，不必重新勾。
 * - **失败/跳过必须被读到**：全成功只弹 toast，有失败或跳过则打开结果详单。
 * - **删除要求键入数量**：这是全站唯一一个一次删掉几十行的入口，键入数字迫使用户
 *   与「到底删几张」这个事实对上一次眼（复用 ConfirmDialog 的既有机制）。
 */
export default function BulkToolbar({
  entity, selection, pageTotal, canManage, onDone,
}: Props) {
  const toast = useToast();
  const [mode, setMode] = useState<Mode>(null);
  const [pending, setPending] = useState(false);
  const [result, setResult] = useState<BulkResult | null>(null);

  const levelLabel = entity === "requirements" ? "优先级" : "严重度";
  // 一处声明顺序与门禁：指派 · 流转 · 改级别 · 删除（破坏性动作恒在最右）。
  const actions: (BulkAction<BulkMode> & { requiresManage?: boolean })[] = [
    { key: "assign", label: "指派", requiresManage: true },
    { key: "move", label: "流转状态" },
    { key: "level", label: `改${levelLabel}` },
    { key: "delete", label: "删除", danger: true, requiresManage: true },
  ];
  const visibleActions = actions.filter((a) => canManage || !a.requiresManage);

  /** 发一次批量请求并落地结果；抛出的 ApiError 交由调用方决定就地显示还是 toast。 */
  async function apply(body: Omit<BulkRequest, "ids">) {
    setPending(true);
    try {
      const res = await runBulk(entity, { ...body, ids: selection.selectedIds });
      // 只保留失败项的勾选：成功的已经变了样，留着只会碍事。
      selection.replace(res.failed.map((f) => f.id));
      onDone();
      setMode(null);
      toast[res.counts.failed > 0 ? "error" : "success"](bulkSummary(res));
      if (needsReview(res)) setResult(res);
      return res;
    } finally {
      setPending(false);
    }
  }

  /** 弹窗内的动作：失败时就地 toast 并保持弹窗打开，让用户能改了再试。 */
  async function applyFromModal(body: Omit<BulkRequest, "ids">) {
    try {
      await apply(body);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "批量操作失败");
    }
  }

  function handleAssign(value: AssigneeValue) {
    if (value.assignee_type && value.assignee_id != null) {
      void applyFromModal({
        action: "assign",
        assignee_type: value.assignee_type,
        assignee_id: value.assignee_id,
      });
      return;
    }
    void applyFromModal({ action: "unassign" });
  }

  return (
    <>
      <BulkActionBar
        count={selection.count}
        pageTotal={pageTotal}
        actions={visibleActions}
        pending={pending}
        onAction={setMode}
        onClear={selection.clear}
      />

      <BulkAssignModal
        open={mode === "assign"}
        entity={entity}
        count={selection.count}
        pending={pending}
        onConfirm={handleAssign}
        onClose={() => setMode(null)}
      />

      <BulkStatusModal
        open={mode === "move"}
        entity={entity}
        rows={selection.selectedRows}
        pending={pending}
        onConfirm={(status) => void applyFromModal({ action: "move", status })}
        onClose={() => setMode(null)}
      />

      <BulkLevelModal
        open={mode === "level"}
        entity={entity}
        rows={selection.selectedRows}
        pending={pending}
        onConfirm={(value) =>
          void applyFromModal({
            action: entity === "requirements" ? "priority" : "severity",
            value,
          })
        }
        onClose={() => setMode(null)}
      />

      <ConfirmDialog
        open={mode === "delete"}
        title={`删除 ${selection.count} 张${ENTITY_LABELS[entity]}`}
        description={
          <>
            将永久删除选中的 <strong className="text-ink">{selection.count}</strong> 张
            {ENTITY_LABELS[entity]}，其评论、协作时间线与相关通知会
            <strong className="text-ink">一并清除</strong>且无法恢复。
            由需求转出的 BUG 不会被删除，只会解除与该需求的关联。
          </>
        }
        confirmLabel={`确认删除 ${selection.count} 张`}
        requireTypedConfirmation={String(selection.count)}
        onConfirm={async () => {
          await apply({ action: "delete" });
        }}
        onClose={() => setMode(null)}
      />

      <BulkResultDialog result={result} entity={entity} onClose={() => setResult(null)} />
    </>
  );
}
