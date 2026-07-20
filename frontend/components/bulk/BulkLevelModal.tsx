"use client";

import { useEffect, useMemo, useState } from "react";
import Modal from "@/components/ui/Modal";
import Button from "@/components/ui/Button";
import Select from "@/components/ui/Select";
import Badge from "@/components/ui/Badge";
import { PRIORITY_STYLES, SEVERITY_STYLES } from "@/lib/constants";
import type { BadgeStyle } from "@/lib/constants";
import { BulkEntity, ENTITY_LABELS } from "@/lib/bulk";
import type { Card } from "@/lib/types";

interface Props {
  open: boolean;
  entity: BulkEntity;
  rows: Card[];
  pending: boolean;
  onConfirm: (value: string) => void;
  onClose: () => void;
}

/** 需求看优先级、BUG 看严重度——两者在批量语义上同构，仅字段与文案不同。 */
function levelOf(entity: BulkEntity, row: Card): string {
  return entity === "requirements"
    ? (row as { priority: string }).priority
    : (row as { severity: string }).severity;
}

/**
 * 批量改优先级 / 严重度（bulk-operations §3.4）。
 *
 * 与批量流转同构地先摆出「选中项当前分布」：调级别是个覆盖性动作，用户在按下确认前
 * 有权知道自己正在覆盖掉什么。
 */
export default function BulkLevelModal({
  open, entity, rows, pending, onConfirm, onClose,
}: Props) {
  // 两张表的键集合不同，但值形状相同；以 BadgeStyle 索引签名统一读取，省掉逐处断言。
  const styles: Record<string, BadgeStyle> =
    entity === "requirements" ? PRIORITY_STYLES : SEVERITY_STYLES;
  const fieldLabel = entity === "requirements" ? "优先级" : "严重度";
  const [value, setValue] = useState("");

  useEffect(() => {
    if (open) setValue("");
  }, [open]);

  const distribution = useMemo(() => {
    const tally = new Map<string, number>();
    for (const row of rows) {
      const key = levelOf(entity, row);
      tally.set(key, (tally.get(key) ?? 0) + 1);
    }
    return Object.keys(styles)
      .filter((key) => tally.has(key))
      .map((key) => ({ key, count: tally.get(key) as number }));
  }, [rows, entity, styles]);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`批量改${fieldLabel} · ${rows.length} 张${ENTITY_LABELS[entity]}`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={pending}>
            取消
          </Button>
          <Button onClick={() => onConfirm(value)} disabled={pending || !value}>
            {pending ? "提交中…" : "确认修改"}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="space-y-1.5">
          <p className="text-xs font-medium text-ink-muted">选中项当前{fieldLabel}</p>
          <div className="flex flex-wrap items-center gap-1.5">
            {distribution.map((item) => (
              <span key={item.key} className="inline-flex items-center gap-1">
                <Badge style={styles[item.key]} />
                <span className="text-xs text-ink-muted">×{item.count}</span>
              </span>
            ))}
          </div>
        </div>

        <Select
          label="统一设为"
          value={value}
          placeholder={`请选择${fieldLabel}`}
          onChange={(e) => setValue(e.target.value)}
          options={Object.entries(styles).map(([key, style]) => ({
            value: key,
            label: style.label,
          }))}
        />

        <p className="text-xs leading-relaxed text-ink-muted">
          {fieldLabel}本就是该取值的单会被跳过；你无权编辑的单会被逐项列出，不影响其余单。
        </p>
      </div>
    </Modal>
  );
}
