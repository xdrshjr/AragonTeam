"use client";

import { ReactNode, useEffect, useState } from "react";
import Modal from "@/components/ui/Modal";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import { ApiError } from "@/lib/api";

interface Props {
  open: boolean;
  title: string;
  /** 必须说清后果与范围，例如「将同时删除 12 条评论与全部协作时间线」。 */
  description: ReactNode;
  confirmLabel?: string;
  /** 默认 true → 红色确认按钮。 */
  danger?: boolean;
  /** 高危动作要求用户键入该文本才解锁确认按钮（删项目用项目 key）。 */
  requireTypedConfirmation?: string;
  onConfirm: () => Promise<void>;
  onClose: () => void;
}

/**
 * 全站统一的破坏性二次确认（lifecycle-and-governance §2.9）。
 *
 * 本轮一次性引入 4 个破坏性动作（删工单 / 删项目 / 删 Agent / 停用成员）。四处各写一遍
 * 必然出现文案风格、按钮顺序、加载态、错误处理各不相同的四份实现，故收敛到本组件：
 *
 * - 确认按钮在**右**、取消在左；pending 期间禁用并显示「处理中…」，杜绝双击造成的
 *   重复 DELETE（第二次必然 404，用户会看到一个莫名其妙的错误）。
 * - `onConfirm` 抛错时**不关闭对话框**，就地显示错误文案——这正是 409（「还有 12 张单」）
 *   需要被读到的地方，弹一个转瞬即逝的 toast 然后关窗是最差解。
 * - Esc / 遮罩点击在 pending 期间不生效。
 */
export default function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = "确认删除",
  danger = true,
  requireTypedConfirmation,
  onConfirm,
  onClose,
}: Props) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [typed, setTyped] = useState("");

  // 每次打开都从干净状态开始，避免上一次的错误文案 / 已键入的确认串残留。
  useEffect(() => {
    if (open) {
      setError(null);
      setTyped("");
      setPending(false);
    }
  }, [open]);

  const typedOk =
    !requireTypedConfirmation ||
    typed.trim().toUpperCase() === requireTypedConfirmation.trim().toUpperCase();

  function handleClose() {
    if (pending) return; // pending 期间 Esc / 遮罩点击不生效
    onClose();
  }

  async function handleConfirm() {
    if (pending || !typedOk) return;
    setPending(true);
    setError(null);
    try {
      await onConfirm();
      onClose();
    } catch (err) {
      // 就地显示：409 的可操作信息（「还有 12 个需求、3 个 BUG」）必须能被读到。
      setError(err instanceof ApiError ? err.message : "操作失败，请重试");
    } finally {
      setPending(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title={title}
      width={480}
      footer={
        <>
          <Button variant="ghost" onClick={handleClose} disabled={pending}>
            取消
          </Button>
          <Button
            variant={danger ? "danger" : "primary"}
            onClick={handleConfirm}
            disabled={pending || !typedOk}
          >
            {pending ? "处理中…" : confirmLabel}
          </Button>
        </>
      }
    >
      <div className="space-y-3 text-sm text-ink">
        <div className="leading-relaxed text-ink-muted">{description}</div>
        {requireTypedConfirmation && (
          <div className="space-y-1.5">
            <label className="block text-xs text-ink-muted">
              请键入 <span className="font-mono font-semibold text-ink">
                {requireTypedConfirmation}
              </span> 以确认
            </label>
            <Input
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              placeholder={requireTypedConfirmation}
              disabled={pending}
            />
          </div>
        )}
        {error && (
          <div className="rounded-lg border border-[#E8C9BC] bg-[#F3D2C7]/30 px-3 py-2 text-[#B23B1E]">
            {error}
          </div>
        )}
      </div>
    </Modal>
  );
}
