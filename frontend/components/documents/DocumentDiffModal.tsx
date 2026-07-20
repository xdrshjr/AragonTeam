"use client";

import { useEffect, useMemo, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { diffLines, type DiffResult, type DiffRow } from "@/lib/diff";
import Button from "@/components/ui/Button";
import Modal from "@/components/ui/Modal";
import ErrorState from "@/components/ui/ErrorState";
import type { DocumentContent, DocumentSummary, DocumentVersion } from "@/lib/types";

interface Props {
  open: boolean;
  document: DocumentSummary | null;
  /** 恰好两个版本，调用方保证按 version_no 升序（左旧右新）。 */
  versions: [DocumentVersion, DocumentVersion] | null;
  onClose: () => void;
}

type View = "unified" | "split";

/**
 * 双版本对比（document-lifecycle-depth §6.3）。
 *
 * 交互取向：
 * - 默认**统一视图**（移动端唯一可行的视图），宽屏提供并排切换；
 * - 增删行用左侧 4px 色条 + 极浅底色标注，**不靠纯色块**（色觉障碍友好），
 *   并在行首标注 `+` / `-` 字符——**颜色永远只是冗余通道**；
 * - `degraded` 为真时顶部横幅如实说明「已降级为整块对比」。
 *
 * 复用 `components/ui/Modal`，自动继承 `lib/overlay-stack` 的层叠语义：抽屉内按 Esc
 * 只关本模态、抽屉仍开、背景仍锁滚。**不要**自己挂 window 级 Esc 监听。
 */
export default function DocumentDiffModal({ open, document: doc, versions, onClose }: Props) {
  const [left, setLeft] = useState<string | null>(null);
  const [right, setRight] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [view, setView] = useState<View>("unified");

  useEffect(() => {
    if (!open || !doc || !versions) return;
    let cancelled = false;
    setError(null);
    setLeft(null);
    setRight(null);
    setLoading(true);

    (async () => {
      try {
        const [a, b] = await Promise.all(
          versions.map((v) =>
            api.get<DocumentContent>(`/documents/${doc.id}/content?version_id=${v.id}`)
          )
        );
        if (cancelled) return;
        setLeft(a.content);
        setRight(b.content);
      } catch (err) {
        if (cancelled) return;
        // 415 = 该版本不是文本。按钮本该已置灰，这里是后端权威的兜底。
        setError(err instanceof ApiError ? err.message : "无法加载版本正文");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [open, doc, versions]);

  const result: DiffResult | null = useMemo(
    () => (left === null || right === null ? null : diffLines(left, right)),
    [left, right]
  );

  if (!doc || !versions) return null;
  const [older, newer] = versions;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`对比 v${older.version_no} → v${newer.version_no}`}
      width={900}
      footer={<Button size="sm" variant="ghost" onClick={onClose}>关闭</Button>}
    >
      <div className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs text-ink-muted">
            {doc.title}
            {result && !result.degraded && (
              <>
                {" · "}
                <span className="text-[#3E7A4F]">+{result.added}</span>{" "}
                <span className="text-[#B23B1E]">−{result.removed}</span>
              </>
            )}
          </p>
          <div
            role="group"
            aria-label="对比视图"
            className="hidden overflow-hidden rounded-md border border-border text-xs md:inline-flex"
          >
            {VIEWS.map(([label, value]) => (
              <button
                key={value}
                type="button"
                aria-pressed={view === value}
                onClick={() => setView(value)}
                className={
                  view === value
                    ? "bg-clay px-2.5 py-1 text-white"
                    : "px-2.5 py-1 text-ink-muted hover:bg-black/[0.04]"
                }
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {loading && <div className="py-10 text-center text-sm text-ink-muted">加载正文…</div>}
        {!loading && error && <ErrorState message={error} />}

        {!loading && !error && result && (
          <>
            {result.degraded && (
              <p
                role="status"
                className="rounded-md border border-[#E4C9A8] bg-[#FBF3E7] px-3 py-2 text-xs text-[#8A5A16]"
              >
                ⚠ 文件过大（两侧共 {result.totalLines} 行），已降级为整块对比：
                左侧整段视为删除、右侧整段视为新增。逐行比较会让页面长时间无响应，
                <strong className="font-medium">如实降级好过假装计算</strong>。
              </p>
            )}
            <div className="max-h-[60vh] overflow-auto rounded-lg border border-border">
              {view === "split" ? (
                <SplitView rows={result.rows} />
              ) : (
                <UnifiedView rows={result.rows} />
              )}
            </div>
          </>
        )}
      </div>
    </Modal>
  );
}

const VIEWS: ReadonlyArray<readonly [string, View]> = [
  ["统一", "unified"],
  ["并排", "split"],
];

/** 行样式：4px 左色条 + 极浅底色；`+` / `-` 字符是给色觉障碍用户的冗余通道。 */
function rowClass(op: DiffRow["op"]): string {
  if (op === "insert") return "border-l-4 border-l-[#3E7A4F] bg-[#3E7A4F]/[0.06]";
  if (op === "delete") return "border-l-4 border-l-[#B23B1E] bg-[#B23B1E]/[0.06]";
  return "border-l-4 border-l-transparent";
}

function sign(op: DiffRow["op"]): string {
  return op === "insert" ? "+" : op === "delete" ? "−" : " ";
}

function ariaLabel(op: DiffRow["op"]): string | undefined {
  return op === "insert" ? "新增行" : op === "delete" ? "删除行" : undefined;
}

function UnifiedView({ rows }: { rows: DiffRow[] }) {
  return (
    <div role="table" aria-label="版本差异（统一视图）" className="font-mono text-xs">
      {rows.map((row, index) => (
        <div
          key={index}
          role="row"
          aria-label={ariaLabel(row.op)}
          className={`flex items-start gap-2 px-2 py-0.5 ${rowClass(row.op)}`}
        >
          <span role="cell" className="w-8 shrink-0 select-none text-right text-ink-muted">
            {row.leftNo ?? ""}
          </span>
          <span role="cell" className="w-8 shrink-0 select-none text-right text-ink-muted">
            {row.rightNo ?? ""}
          </span>
          <span role="cell" aria-hidden="true" className="w-3 shrink-0 select-none text-ink-muted">
            {sign(row.op)}
          </span>
          <span role="cell" className="min-w-0 flex-1 whitespace-pre-wrap break-words text-ink">
            {row.text || " "}
          </span>
        </div>
      ))}
    </div>
  );
}

function SplitView({ rows }: { rows: DiffRow[] }) {
  return (
    <div role="table" aria-label="版本差异（并排视图）" className="font-mono text-xs">
      {rows.map((row, index) => (
        <div key={index} role="row" aria-label={ariaLabel(row.op)} className="flex">
          <div
            className={`flex w-1/2 items-start gap-2 border-r border-border px-2 py-0.5 ${
              row.op === "insert" ? "bg-black/[0.02]" : rowClass(row.op)
            }`}
          >
            <span role="cell" className="w-8 shrink-0 select-none text-right text-ink-muted">
              {row.leftNo ?? ""}
            </span>
            <span role="cell" className="min-w-0 flex-1 whitespace-pre-wrap break-words text-ink">
              {row.op === "insert" ? "" : row.text || " "}
            </span>
          </div>
          <div
            className={`flex w-1/2 items-start gap-2 px-2 py-0.5 ${
              row.op === "delete" ? "bg-black/[0.02]" : rowClass(row.op)
            }`}
          >
            <span role="cell" className="w-8 shrink-0 select-none text-right text-ink-muted">
              {row.rightNo ?? ""}
            </span>
            <span role="cell" className="min-w-0 flex-1 whitespace-pre-wrap break-words text-ink">
              {row.op === "delete" ? "" : row.text || " "}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}
