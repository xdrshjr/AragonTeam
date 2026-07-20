"use client";

import { useEffect, useMemo, useState } from "react";
import Modal from "@/components/ui/Modal";
import Button from "@/components/ui/Button";
import Select from "@/components/ui/Select";
import Badge from "@/components/ui/Badge";
import { statusStyle, REQUIREMENT_COLUMNS, BUG_COLUMNS } from "@/lib/constants";
import { BulkEntity, ENTITY_LABELS } from "@/lib/bulk";
import type { Card } from "@/lib/types";

interface Props {
  open: boolean;
  entity: BulkEntity;
  rows: Card[];
  pending: boolean;
  onConfirm: (status: string) => void;
  onClose: () => void;
}

/**
 * 批量流转目标状态选择（bulk-operations §3.4）。
 *
 * 【为什么不在前端预判哪些单能流转】状态机的唯一真相在后端 `services/workflow.py`
 * 的邻接表（CLAUDE.md：state machine is sacred）。在这里放一份「合法迁移表」用来把
 * 不可流转的选项置灰，短期好看，长期必然与后端漂移，且漂移的方向恰好是「前端说不
 * 行、后端其实行」这种最难排查的假象。
 *
 * 因此这里只展示**不需要状态机知识**就能给出的信息——选中项当前的状态分布——并
 * 明说不合法的单会被逐项跳过、原因在结果里列出。判决权始终在后端。
 */
export default function BulkStatusModal({
  open, entity, rows, pending, onConfirm, onClose,
}: Props) {
  const columns = entity === "requirements" ? REQUIREMENT_COLUMNS : BUG_COLUMNS;
  const [status, setStatus] = useState("");

  useEffect(() => {
    if (open) setStatus("");
  }, [open]);

  // 当前状态分布：按列顺序统计，读起来与看板从左到右一致。
  const distribution = useMemo(() => {
    const tally = new Map<string, number>();
    for (const row of rows) tally.set(row.status, (tally.get(row.status) ?? 0) + 1);
    return columns
      .filter((c) => tally.has(c.key))
      .map((c) => ({ key: c.key as string, count: tally.get(c.key) as number }));
  }, [rows, columns]);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`批量流转 · ${rows.length} 张${ENTITY_LABELS[entity]}`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={pending}>
            取消
          </Button>
          <Button onClick={() => onConfirm(status)} disabled={pending || !status}>
            {pending ? "流转中…" : "确认流转"}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="space-y-1.5">
          <p className="text-xs font-medium text-ink-muted">选中项当前状态</p>
          <div className="flex flex-wrap items-center gap-1.5">
            {distribution.map((item) => (
              <span key={item.key} className="inline-flex items-center gap-1">
                <Badge style={statusStyle(item.key)} />
                <span className="text-xs text-ink-muted">×{item.count}</span>
              </span>
            ))}
          </div>
        </div>

        <Select
          label="流转到"
          value={status}
          placeholder="请选择目标状态"
          onChange={(e) => setStatus(e.target.value)}
          options={columns.map((c) => ({ value: c.key, label: c.title }))}
        />

        <p className="text-xs leading-relaxed text-ink-muted">
          状态流转规则由服务端状态机裁决：已在目标状态的单会被跳过，当前状态不允许直达
          目标状态的单会被逐项列出原因，其余单照常流转——不会因为个别单不合法而整批失败。
        </p>
      </div>
    </Modal>
  );
}
