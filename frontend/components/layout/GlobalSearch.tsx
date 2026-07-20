"use client";

import {
  useState,
  useRef,
  useEffect,
  useMemo,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { swrFetcher } from "@/lib/api";
import { useProjectScope } from "@/lib/project-scope";
import { documentKindStyle, statusStyle } from "@/lib/constants";
import type { DocumentSummary, SearchResults, Requirement, Bug } from "@/lib/types";
import Badge from "@/components/ui/Badge";

// 命中项的 kind 恒为**复数路由段**（'requirements'/'bugs'）——须与路由段、
// aragon:open-ticket 的 detail.entity、board 页比较值四处逐字一致（spec §2.2 命名不变量）。
// document-lifecycle-depth §2.1 A-3 新增第三个桶 'documents'：它的**落点完全不同**
// （不是看板抽屉，而是 /documents 的深链预览），故 onSelect 必须分流。
type Kind = "requirements" | "bugs" | "documents";
type TicketKind = "requirements" | "bugs";

interface Hit {
  kind: Kind;
  id: number;
  title: string;
  status: string;
}

const DEBOUNCE_MS = 300;
const PREVIEW_LIMIT = 5;

// 视觉顺序 = 键盘顺序 = Enter 兜底的优先顺序。三处必须一致，故只写这一份。
const KIND_ORDER: readonly Kind[] = ["requirements", "bugs", "documents"];

function hitOf(kind: Kind, t: Requirement | Bug): Hit {
  return { kind, id: t.id, title: t.title, status: t.status };
}

function documentHit(doc: DocumentSummary): Hit {
  // 文档没有工单状态，这里放**类型**——徽章位置上有一个恒定的语义标记比空着好。
  return { kind: "documents", id: doc.id, title: doc.title, status: doc.kind };
}

// 命中扁平化：需求 → BUG → 文档（与 ↑/↓ 键盘顺序及分组渲染的 base 偏移一致）。
// 漏掉任何一组，方向键都会在那一组上失灵。
function flatten(data?: SearchResults): Hit[] {
  if (!data) return [];
  return [
    ...data.requirements.map((r) => hitOf("requirements", r)),
    ...data.bugs.map((b) => hitOf("bugs", b)),
    ...data.documents.map(documentHit),
  ];
}

/**
 * 「有结果但没有任何高亮项时按 Enter」的落点（评审 V-08）。
 *
 * 它此前是一个 requirements / bugs **二选一**表达式，加了文档桶之后，一次**只命中
 * 文档**的搜索按 Enter 会落进 else 分支 → 跳 `/requirements/board` → 用户看到一个与
 * 关键词无关的空看板。
 *
 * 三态规则，且**宁可不跳也不乱跳**：
 *   - 恰有一个桶非零 → 跳该桶；
 *   - 多个桶非零     → 跳第一个非零桶（顺序固定为 requirements → bugs → documents，
 *                      与视觉顺序一致——用户按 Enter 时看到的第一组就是它）；
 *   - 全为零         → **什么都不做**（原二选一表达式恰好总能给出一个答案，那是巧合，
 *                      不是设计）。
 *
 * 抽成纯函数是为了让第四个桶出现时不会再漏这一处。
 */
export function pickFallbackTarget(counts?: SearchResults["counts"]): Kind | null {
  if (!counts) return null;
  return KIND_ORDER.find((kind) => (counts[kind] ?? 0) > 0) ?? null;
}

export default function GlobalSearch() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const wrapRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // 防抖：输入停 300ms 后进入 SWR key；每次输入即重置高亮并展开下拉。
  // 【H2】`setOpen(true)` 必须**有守卫**：onSelect 会同时置 open=false 与 query=""，
  // 而 query 变化又会触发本 effect —— 无守卫时下拉会在选中后立刻「闪回」再等 300ms 才消失。
  useEffect(() => {
    setActive(-1);
    if (query.trim()) setOpen(true);
    const t = setTimeout(() => setDebounced(query.trim()), DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [query]);

  const key = debounced
    ? `/search?q=${encodeURIComponent(debounced)}&limit=${PREVIEW_LIMIT}`
    : null;
  const { data, error } = useSWR<SearchResults>(key, swrFetcher);
  const flat = useMemo(() => flatten(data), [data]);

  // `/` 全局聚焦（非输入态时，从 Header 迁入）。
  useEffect(() => {
    function onKey(e: globalThis.KeyboardEvent) {
      const tag = (e.target as HTMLElement)?.tagName;
      const typing = tag === "INPUT" || tag === "TEXTAREA";
      if (e.key === "/" && !typing) {
        e.preventDefault();
        inputRef.current?.focus();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  // 点击外部关闭下拉（a11y；Esc 由输入框 onKeyDown 处理）。
  useEffect(() => {
    if (!open) return;
    function onClick(e: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  function dismiss() {
    setOpen(false);
    setQuery("");
    setDebounced("");   // 【H2】同步清空，否则下拉的 `open && debounced` 条件仍成立 300ms。
  }

  function onSelect(hit: Hit) {
    // 【§2.1 A-3】文档的落点与工单**完全不同**：它没有看板、没有抽屉，
    // 走 /documents 的 `?doc=` 深链自动开预览。分流必须在这里，不能靠拼字符串蒙混。
    if (hit.kind === "documents") {
      onSelectDocument(hit.id);
      return;
    }
    router.push(`/${hit.kind}/board?ticket=${hit.id}`);
    // 已在目标看板时同路由 push 不重挂载，派发事件即时打开抽屉（与 NotificationBell 同策略）。
    window.dispatchEvent(
      new CustomEvent("aragon:open-ticket", { detail: { entity: hit.kind, id: hit.id } })
    );
    dismiss();
  }

  function onSelectDocument(documentId: number) {
    router.push(`/documents?doc=${documentId}`);
    dismiss();
  }

  function onSeeAll(kind: Kind) {
    if (kind === "documents") {
      router.push(`/documents?q=${encodeURIComponent(debounced)}`);
      setOpen(false);
      return;
    }
    router.push(`/${kind}?q=${encodeURIComponent(debounced)}`);
    window.dispatchEvent(new CustomEvent<string>("aragon:search", { detail: debounced }));
    setOpen(false);
  }

  function handleInputKey(e: ReactKeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((i) => Math.min(i + 1, flat.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, -1));
    } else if (e.key === "Enter") {
      if (active >= 0 && active < flat.length) onSelect(flat[active]);
      else if (debounced) {
        // 【§2.7-C3 / 评审 V-08】无高亮行时跳到「真有命中」的第一个分组。
        // 全为零时 `pickFallbackTarget` 返回 null → **什么都不做**，不乱跳。
        const target = pickFallbackTarget(data?.counts);
        if (target) onSeeAll(target);
      }
    } else if (e.key === "Escape") {
      if (open) setOpen(false);
      else {
        setQuery("");
        inputRef.current?.blur();
      }
    }
  }

  return (
    <div ref={wrapRef} className="relative hidden md:block">
      <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted/70">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="11" cy="11" r="8" />
          <path d="m21 21-4.3-4.3" />
        </svg>
      </span>
      <input
        ref={inputRef}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onFocus={() => setOpen(true)}
        onKeyDown={handleInputKey}
        placeholder="搜索需求 / BUG / 文档…（/）"
        aria-label="全局搜索"
        className="h-9 w-56 rounded-lg border border-border bg-bg pl-9 pr-3 text-sm text-ink placeholder:text-ink-muted/60 focus:border-clay focus:outline-none focus:ring-2 focus:ring-clay/20"
      />

      {open && debounced && (
        <div className="absolute right-0 z-50 mt-2 w-96 overflow-hidden rounded-xl border border-border bg-surface shadow-lift">
          <SearchDropdown
            data={data}
            error={error}
            active={active}
            onSelect={onSelect}
            onSeeAll={onSeeAll}
          />
        </div>
      )}
    </div>
  );
}

// —— 下拉内容：加载 / 降级 / 无命中 / 分组命中四态 ——

interface DropdownProps {
  data?: SearchResults;
  error: unknown;
  active: number;
  onSelect: (hit: Hit) => void;
  onSeeAll: (kind: Kind) => void;
}

function DropdownMessage({ text }: { text: string }) {
  return <div className="px-4 py-6 text-center text-sm text-ink-muted">{text}</div>;
}

function SearchDropdown({ data, error, active, onSelect, onSeeAll }: DropdownProps) {
  // 必须在任何早返回**之前**调用（React hooks 规则）。
  const { scopeLabel } = useProjectScope();
  if (error) return <DropdownMessage text="搜索服务暂不可用" />; // P2-2：后端不可用降级
  if (!data) return <DropdownMessage text="搜索中…" />;
  if (
    data.counts.requirements === 0 &&
    data.counts.bugs === 0 &&
    data.counts.documents === 0
  ) {
    return <DropdownMessage text="未找到匹配的需求、BUG 或文档" />;
  }
  return (
    <div className="max-h-[24rem] overflow-y-auto py-1">
      <HitGroup
        label="需求" prefix="REQ" kind="requirements"
        items={data.requirements} total={data.counts.requirements}
        base={0} active={active} onSelect={onSelect} onSeeAll={onSeeAll}
      />
      <HitGroup
        label="BUG" prefix="BUG" kind="bugs"
        items={data.bugs} total={data.counts.bugs}
        base={data.requirements.length} active={active} onSelect={onSelect} onSeeAll={onSeeAll}
      />
      {/* 第三组：图标用回形针以与前两组的状态色区分（§6.1 触点 3）。
          base 偏移必须累加**前两组的实际条数**，否则方向键会在文档组上错位。 */}
      <DocumentGroup
        items={data.documents} total={data.counts.documents}
        base={data.requirements.length + data.bugs.length}
        active={active} onSelect={onSelect} onSeeAll={onSeeAll}
      />
      {/* 【§2.4⑦'】搜索的语义就是「全局」，**有意不受 Header 项目切换器约束** —— 显式标注，
          否则用户看到 Header 写着某个项目，却在同一屏读到跨项目的搜索结果。
          只在选了具体项目时标注（验收 C8：切回「全部项目」时消失）。 */}
      {scopeLabel && (
        <div className="px-4 py-2 text-[11px] text-ink-muted/70">搜索范围：全部项目</div>
      )}
    </div>
  );
}

interface GroupProps {
  label: string;
  prefix: string;
  kind: TicketKind;
  items: (Requirement | Bug)[];
  total: number;
  base: number; // 该组首行在扁平命中列表中的起始下标
  active: number;
  onSelect: (hit: Hit) => void;
  onSeeAll: (kind: Kind) => void;
}

function HitGroup(props: GroupProps) {
  const { label, prefix, kind, items, total, base, active, onSelect, onSeeAll } = props;
  if (items.length === 0) return null;
  return (
    <div className="border-b border-border py-1 last:border-0">
      <div className="px-4 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-muted/70">
        {label}
      </div>
      <ul>
        {items.map((t, i) => (
          <li key={t.id}>
            <button
              type="button"
              onClick={() => onSelect(hitOf(kind, t))}
              className={[
                "flex w-full items-center gap-2 px-4 py-2 text-left hover:bg-black/[0.03]",
                base + i === active ? "bg-clay-soft/20" : "",
              ].join(" ")}
            >
              <span className="shrink-0 text-xs text-ink-muted">{prefix}-{t.id}</span>
              <span className="min-w-0 flex-1 truncate text-sm text-ink">{t.title}</span>
              <Badge style={statusStyle(t.status)} />
            </button>
          </li>
        ))}
      </ul>
      {total > items.length && (
        <button
          type="button"
          onClick={() => onSeeAll(kind)}
          className="w-full px-4 py-2 text-left text-xs text-clay-dark hover:underline"
        >
          查看全部 {total} 条{label} →
        </button>
      )}
    </div>
  );
}

interface DocumentGroupProps {
  items: DocumentSummary[];
  total: number;
  base: number;
  active: number;
  onSelect: (hit: Hit) => void;
  onSeeAll: (kind: Kind) => void;
}

function DocumentGroup({ items, total, base, active, onSelect, onSeeAll }: DocumentGroupProps) {
  if (items.length === 0) return null;
  return (
    <div className="border-b border-border py-1 last:border-0">
      <div className="px-4 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-muted/70">
        文档
      </div>
      <ul>
        {items.map((doc, i) => (
          <li key={doc.id}>
            <button
              type="button"
              onClick={() => onSelect(documentHit(doc))}
              className={[
                "flex w-full items-center gap-2 px-4 py-2 text-left hover:bg-black/[0.03]",
                base + i === active ? "bg-clay-soft/20" : "",
              ].join(" ")}
            >
              <span aria-hidden="true" className="shrink-0 text-xs text-ink-muted">📎</span>
              <span className="min-w-0 flex-1 truncate text-sm text-ink">{doc.title}</span>
              <Badge style={documentKindStyle(doc.kind)} />
            </button>
          </li>
        ))}
      </ul>
      {total > items.length && (
        <button
          type="button"
          onClick={() => onSeeAll("documents")}
          className="w-full px-4 py-2 text-left text-xs text-clay-dark hover:underline"
        >
          查看全部 {total} 份文档 →
        </button>
      )}
    </div>
  );
}
