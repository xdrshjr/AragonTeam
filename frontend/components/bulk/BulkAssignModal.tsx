"use client";

import { useEffect, useState } from "react";
import Modal from "@/components/ui/Modal";
import Button from "@/components/ui/Button";
import AssigneePicker, { AssigneeValue } from "@/components/AssigneePicker";
import { BulkEntity, ENTITY_LABELS } from "@/lib/bulk";

interface Props {
  open: boolean;
  entity: BulkEntity;
  count: number;
  pending: boolean;
  /** 选「未指派」即批量取消指派——后端是两个 action，界面上是同一件事的两个取值。 */
  onConfirm: (value: AssigneeValue) => void;
  onClose: () => void;
}

/**
 * 批量指派 / 取消指派（bulk-operations §3.4）。
 *
 * 复用与单条指派完全相同的 `AssigneePicker`：同一件事在两个入口长得不一样，是列表页
 * 最容易积累的那种不一致。选择器的「未指派」选项在这里承担「批量取消指派」——把它
 * 拆成两个按钮反而要求用户先想清楚自己要调用哪个动词。
 */
export default function BulkAssignModal({
  open, entity, count, pending, onConfirm, onClose,
}: Props) {
  const [value, setValue] = useState<AssigneeValue>({
    assignee_type: null,
    assignee_id: null,
  });

  // 每次打开都从「未指派」起步，避免上一次的选择残留成一次误操作。
  useEffect(() => {
    if (open) setValue({ assignee_type: null, assignee_id: null });
  }, [open]);

  const isUnassign = !value.assignee_type || value.assignee_id == null;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`批量指派 · ${count} 张${ENTITY_LABELS[entity]}`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={pending}>
            取消
          </Button>
          <Button onClick={() => onConfirm(value)} disabled={pending}>
            {pending ? "提交中…" : isUnassign ? "确认取消指派" : "确认指派"}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <AssigneePicker value={value} onChange={setValue} />
        <p className="text-xs leading-relaxed text-ink-muted">
          {isUnassign
            ? "将把选中的单全部置为「未指派」；本就未指派的单会被跳过，状态不受影响。"
            : "已经指派给该对象的单会被跳过；处于首列的单会自动流转为「已指派」，与单条指派的行为一致。"}
        </p>
      </div>
    </Modal>
  );
}
