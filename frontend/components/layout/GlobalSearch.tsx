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
import { statusStyle } from "@/lib/constants";
import type { SearchResults, Requirement, Bug } from "@/lib/types";
import Badge from "@/components/ui/Badge";

// 命中项的 kind 恒为**复数路由段**（'requirements'/'bugs'）——须与路由段、
// aragon:open-ticket 的 detail.entity、board 页比较值四处逐字一致（spec §2.2 命名不变量）。
type Kind = "requirements" | "bugs";

interface Hit {
  kind: Kind;
  id: number;
  title: string;
  status: string;
}

const DEBOUNCE_MS = 300;
const PREVIEW_LIMIT = 5;

function hitOf(kind: Kind, t: Requirement | Bug): Hit {
  return { kind, id: t.id, title: t.title, status: t.status };
}

// 命中扁平化：需求在前、BUG 在后（与 ↑/↓ 键盘顺序及分组渲染的 base 偏移一致）。
function flatten(data?: SearchResults): Hit[] {
  if (!data) return [];
  return [
    ...data.requirements.map((r) => hitOf("requirements", r)),
    ...data.bugs.map((b) => hitOf("bugs", b)),
  ];
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
  useEffect(() => {
    setActive(-1);
    setOpen(true);
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

  function onSelect(hit: Hit) {
    router.push(`/${hit.kind}/board?ticket=${hit.id}`);
    // 已在目标看板时同路由 push 不重挂载，派发事件即时打开抽屉（与 NotificationBell 同策略）。
    window.dispatchEvent(
      new CustomEvent("aragon:open-ticket", { detail: { entity: hit.kind, id: hit.id } })
    );
    setOpen(false);
    setQuery("");
  }

  function onSeeAll(kind: Kind) {
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
        // 【§2.7-C3】无高亮行时跳到「真有命中」的分组：仅 BUG 有命中则去 bugs，
        // 否则默认 requirements（避免命中 BUG 却跳到空的需求列表）。
        const counts = data?.counts;
        const target: Kind =
          counts && counts.bugs > 0 && counts.requirements === 0 ? "bugs" : "requirements";
        onSeeAll(target);
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
        placeholder="搜索需求 / BUG…（/）"
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
  if (error) return <DropdownMessage text="搜索服务暂不可用" />; // P2-2：后端不可用降级
  if (!data) return <DropdownMessage text="搜索中…" />;
  if (data.counts.requirements === 0 && data.counts.bugs === 0) {
    return <DropdownMessage text="未找到匹配的需求或 BUG" />;
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
    </div>
  );
}

interface GroupProps {
  label: string;
  prefix: string;
  kind: Kind;
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
