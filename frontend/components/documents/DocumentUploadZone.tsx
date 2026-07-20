"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api";
import { DOCUMENT_KIND_OPTIONS, formatBytes } from "@/lib/constants";
import { useToast } from "@/lib/toast";
import ProgressBar from "@/components/ui/ProgressBar";
import type { UploadFields } from "@/hooks/useTicketDocuments";

/** 并发上限：其余排队。用户的带宽是共享资源，一次发十个只会让每个都变慢。 */
const MAX_CONCURRENT = 3;

type ItemState = "queued" | "uploading" | "done" | "failed" | "cancelled";

interface QueueItem {
  id: number;
  file: File;
  state: ItemState;
  percent: number | null;
  error?: string;
  xhr?: XMLHttpRequest;
}

interface Props {
  /** 由外层 hook 提供，返回一个 Promise；`deduped` 由调用方在 toast 里如实告知。 */
  onUpload: (
    file: File,
    fields: UploadFields,
    options: { onProgress: (p: { percent: number | null }) => void;
               onStart: (xhr: XMLHttpRequest) => void }
  ) => Promise<unknown>;
  /** 由 StageChecklist 的缺失项点击预选。 */
  presetKind?: string;
  disabled?: boolean;
  /** 面板级拖放：外层把整块面板的 drop 事件转进来（§6.3）。 */
  externalFiles?: File[] | null;
  onExternalConsumed?: () => void;
}

let nextItemId = 1;

// 拖放 / 点击上传 + 进度条 + 多文件队列（ticket-document-management §6.3）。
//
// a11y：区域 `tabIndex=0` + `role="button"`，Enter/Space 触发文件选择；
// `<input type="file">` 视觉隐藏但**保持可聚焦**（不用 `display:none`，那会让它
// 从 tab 序列里消失，键盘用户再也够不到上传）。
export default function DocumentUploadZone({
  onUpload,
  presetKind,
  disabled = false,
  externalFiles,
  onExternalConsumed,
}: Props) {
  const toast = useToast();
  const inputRef = useRef<HTMLInputElement>(null);
  const [items, setItems] = useState<QueueItem[]>([]);
  const [kind, setKind] = useState(presetKind || "other");
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    if (presetKind) setKind(presetKind);
  }, [presetKind]);

  const patchItem = useCallback((id: number, patch: Partial<QueueItem>) => {
    setItems((prev) => prev.map((i) => (i.id === id ? { ...i, ...patch } : i)));
  }, []);

  const run = useCallback(
    async (item: QueueItem, selectedKind: string) => {
      patchItem(item.id, { state: "uploading", percent: 0 });
      try {
        const result: any = await onUpload(
          item.file,
          { kind: selectedKind },
          {
            onProgress: (p) => patchItem(item.id, { percent: p.percent }),
            onStart: (xhr) => patchItem(item.id, { xhr }),
          }
        );
        patchItem(item.id, { state: "done", percent: 100 });
        // 【§6.3】去重命中时如实告知，而不是假装上传了一份。
        const deduped = result?.document?.deduped ?? result?.deduped;
        toast.success(deduped ? "该文件已在库中，已直接绑定" : `已上传「${item.file.name}」`);
      } catch (err) {
        if (err instanceof ApiError && err.message === "已取消上传") {
          patchItem(item.id, { state: "cancelled" });
          return;
        }
        const message = err instanceof ApiError ? err.message : "上传失败";
        patchItem(item.id, { state: "failed", error: message, percent: null });
      }
    },
    [onUpload, patchItem, toast]
  );

  const enqueue = useCallback(
    (files: File[]) => {
      if (disabled || files.length === 0) return;
      const queued: QueueItem[] = files.map((file) => ({
        id: nextItemId++, file, state: "queued", percent: null,
      }));
      setItems((prev) => [...prev, ...queued]);
      // 简单的并发闸：分批 await，超出 MAX_CONCURRENT 的自然排队。
      (async () => {
        for (let i = 0; i < queued.length; i += MAX_CONCURRENT) {
          await Promise.all(
            queued.slice(i, i + MAX_CONCURRENT).map((item) => run(item, kind))
          );
        }
      })();
    },
    [disabled, kind, run]
  );

  // 外层面板整块拖放进来的文件。
  useEffect(() => {
    if (externalFiles && externalFiles.length) {
      enqueue(externalFiles);
      onExternalConsumed?.();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [externalFiles]);

  function retry(item: QueueItem) {
    run({ ...item, state: "queued" }, kind);
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <label className="text-xs text-ink-muted" htmlFor="doc-upload-kind">
          文档类型
        </label>
        <select
          id="doc-upload-kind"
          value={kind}
          onChange={(e) => setKind(e.target.value)}
          disabled={disabled}
          className="h-8 rounded-lg border border-border bg-surface px-2 text-xs text-ink disabled:opacity-60 focus:border-clay focus:outline-none focus:ring-2 focus:ring-clay/20"
        >
          {DOCUMENT_KIND_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </div>

      <div
        role="button"
        tabIndex={disabled ? -1 : 0}
        aria-label="拖放文件到此处上传，或按 Enter 选择文件"
        aria-disabled={disabled}
        onClick={() => !disabled && inputRef.current?.click()}
        onKeyDown={(e) => {
          if (disabled) return;
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          enqueue(Array.from(e.dataTransfer.files || []));
        }}
        className={[
          "flex min-h-[52px] cursor-pointer items-center justify-center rounded-lg border border-dashed px-3 py-3 text-center text-xs transition-colors",
          disabled
            ? "cursor-not-allowed border-border text-ink-muted opacity-60"
            : dragging
              ? "border-clay bg-clay/[0.08] text-clay"
              : "border-border text-ink-muted hover:border-clay hover:text-clay",
          "focus:outline-none focus:ring-2 focus:ring-clay/20",
        ].join(" ")}
      >
        {dragging ? "松手即可上传" : "拖放文件到此处上传，或点击选择"}
      </div>

      {/* 视觉隐藏但保持可聚焦：display:none 会把它从 tab 序列里删掉。 */}
      <input
        ref={inputRef}
        type="file"
        multiple
        className="absolute h-px w-px overflow-hidden opacity-0"
        onChange={(e) => {
          enqueue(Array.from(e.target.files || []));
          e.target.value = "";
        }}
      />

      {items.length > 0 && (
        <ul className="space-y-1.5">
          {items.map((item) => (
            <li key={item.id} className="rounded-lg border border-border px-2.5 py-1.5">
              <div className="flex items-center justify-between gap-2 text-xs">
                <span className="min-w-0 flex-1 truncate text-ink" title={item.file.name}>
                  {item.file.name}
                </span>
                <span className="shrink-0 text-ink-muted">{formatBytes(item.file.size)}</span>
                {item.state === "uploading" && (
                  <button
                    type="button"
                    onClick={() => item.xhr?.abort()}
                    className="shrink-0 text-ink-muted hover:text-[#B23B1E]"
                  >
                    取消
                  </button>
                )}
                {/* 失败**不自动重试**：用户的文件、用户的带宽，由用户决定。 */}
                {item.state === "failed" && (
                  <button
                    type="button"
                    onClick={() => retry(item)}
                    className="shrink-0 text-clay hover:underline"
                  >
                    重试
                  </button>
                )}
              </div>
              {item.state === "uploading" && (
                <ProgressBar
                  value={item.percent}
                  label={`上传「${item.file.name}」`}
                  className="mt-1.5"
                />
              )}
              {item.state === "failed" && (
                <p className="mt-1 text-xs text-[#B23B1E]">{item.error}</p>
              )}
              {item.state === "cancelled" && (
                <p className="mt-1 text-xs text-ink-muted">已取消</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
