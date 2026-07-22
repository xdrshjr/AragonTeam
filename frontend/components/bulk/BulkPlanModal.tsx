"use client";

// 批量「归属计划」弹窗（version-plan-console §5.4）。
//
// 形状照抄 bulk/BulkLevelModal：**只通过 `onConfirm(planId)` 把值交出去，自己不发请求、
// 不 catch**。既有三个批量弹窗都是这个形状——发请求、catch、toast 全在
// `BulkToolbar.applyFromModal` 里，弹窗在调用栈上根本看不到那个 ApiError，
// 让它「就地翻译请求级 400」是一句实现不了的话（翻译住在 lib/bulk.requestErrorText）。

import { useEffect, useState } from "react";
import Modal from "@/components/ui/Modal";
import Button from "@/components/ui/Button";
import PlanPicker from "@/components/planning/PlanPicker";
import { BulkEntity, ENTITY_LABELS } from "@/lib/bulk";

interface Props {
  open: boolean;
  entity: BulkEntity;
  count: number;
  pending: boolean;
  /** `number` = 归属到该计划；`null` = 解除归属。两者都是用户明确表达过的意图。 */
  onConfirm: (planId: number | null) => void;
  onClose: () => void;
}

/** 「归属到某计划」与「解除归属」是两种意图，用一个单选把它们分开——
 *  否则「未归属」这个 option 会同时承担「我还没选」和「我要清空」两种含义。 */
type Intent = "assign" | "detach";

export default function BulkPlanModal({
  open, entity, count, pending, onConfirm, onClose,
}: Props) {
  const [intent, setIntent] = useState<Intent>("assign");
  const [planId, setPlanId] = useState<number | null>(null);

  useEffect(() => {
    if (open) {
      setIntent("assign");
      setPlanId(null);
    }
  }, [open]);

  const canSubmit = intent === "detach" || planId != null;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`批量归属计划 · ${count} 张${ENTITY_LABELS[entity]}`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={pending}>取消</Button>
          <Button
            onClick={() => onConfirm(intent === "detach" ? null : planId)}
            disabled={pending || !canSubmit}
          >
            {pending ? "提交中…" : intent === "detach" ? "确认解除归属" : "确认归属"}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <fieldset className="space-y-2">
          <legend className="text-xs font-medium text-ink-muted">操作</legend>
          <label className="flex items-center gap-2 text-sm text-ink">
            <input
              type="radio"
              name="bulk-plan-intent"
              className="accent-clay"
              checked={intent === "assign"}
              onChange={() => setIntent("assign")}
            />
            归属到某个计划
          </label>
          <label className="flex items-center gap-2 text-sm text-ink">
            <input
              type="radio"
              name="bulk-plan-intent"
              className="accent-clay"
              checked={intent === "detach"}
              onChange={() => setIntent("detach")}
            />
            解除归属（把这些单变成「未归属」）
          </label>
        </fieldset>

        {intent === "assign" && (
          <PlanPicker label="目标计划" value={planId} onChange={setPlanId} />
        )}

        <p className="text-xs leading-relaxed text-ink-muted">
          本就归属该计划的单会被跳过；与目标计划
          <strong className="text-ink">不在同一个项目</strong>的单会被逐项列出，不影响其余单。
          没有项目的单会顺带落进该计划所属的项目。
        </p>
      </div>
    </Modal>
  );
}
