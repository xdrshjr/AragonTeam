"use client";

import Modal from "@/components/ui/Modal";
import Button from "@/components/ui/Button";
import {
  BULK_ACTION_LABELS,
  BulkEntity,
  ENTITY_LABELS,
  failureText,
  skipText,
} from "@/lib/bulk";
import type { BulkResult } from "@/lib/types";

interface Props {
  result: BulkResult | null;
  entity: BulkEntity;
  onClose: () => void;
}

/** 单号前缀：需求 REQ-12 / BUG-12，与两个列表页的编号列一致。 */
function ticketCode(entity: BulkEntity, id: number): string {
  return entity === "requirements" ? `REQ-${id}` : `BUG-${id}`;
}

/**
 * 批量结果详单（bulk-operations §3.5）。
 *
 * 【为什么不能只弹 toast】批量的失败是**逐项**的：50 张里 3 张因状态机不允许而没动，
 * 用户必须知道是哪 3 张、为什么、下一步能去哪。toast 一闪而过，正好把唯一一次能讲
 * 清楚的机会浪费掉。故：全成功 → 只 toast；有失败或跳过 → 弹本对话框（调用方据
 * `needsReview` 判断）。
 *
 * 失败在上、跳过在下：跳过是「本就如此」，不需要用户行动；失败才需要。
 */
export default function BulkResultDialog({ result, entity, onClose }: Props) {
  if (!result) return null;
  const { counts, failed, skipped } = result;

  return (
    <Modal
      open
      onClose={onClose}
      title={`${BULK_ACTION_LABELS[result.action]}结果`}
      width={560}
      footer={<Button onClick={onClose}>知道了</Button>}
    >
      <div className="space-y-4 text-sm">
        <p className="text-ink-muted">
          共 {counts.requested} 张{ENTITY_LABELS[entity]}：
          <strong className="text-ink"> 成功 {counts.succeeded}</strong>
          {counts.skipped > 0 && <> · 跳过 {counts.skipped}</>}
          {counts.failed > 0 && <> · 失败 {counts.failed}</>}
        </p>

        {failed.length > 0 && (
          <section className="space-y-1.5">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
              未能完成（{failed.length}）
            </h3>
            <ul className="max-h-56 space-y-1 overflow-y-auto rounded-lg border border-[#E8C9BC] bg-[#F3D2C7]/20 p-2">
              {failed.map((item) => (
                <li key={item.id} className="flex gap-2 px-1 py-0.5">
                  <span className="shrink-0 font-mono text-xs text-[#B23B1E]">
                    {ticketCode(entity, item.id)}
                  </span>
                  <span className="text-ink">{failureText(item, entity)}</span>
                </li>
              ))}
            </ul>
            <p className="text-xs text-ink-muted">
              失败的单已为你保留勾选，修正后可直接重试。
            </p>
          </section>
        )}

        {skipped.length > 0 && (
          <section className="space-y-1.5">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
              无需改动（{skipped.length}）
            </h3>
            <ul className="max-h-40 space-y-1 overflow-y-auto rounded-lg border border-border bg-bg p-2">
              {skipped.map((item) => (
                <li key={item.id} className="flex gap-2 px-1 py-0.5">
                  <span className="shrink-0 font-mono text-xs text-ink-muted">
                    {ticketCode(entity, item.id)}
                  </span>
                  <span className="text-ink-muted">{skipText(item)}</span>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </Modal>
  );
}
