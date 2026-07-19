"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { ChangeEvent, KeyboardEvent } from "react";
import useSWR from "swr";
import { USERS_KEY, swrFetcher } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { User } from "@/lib/types";
import { activeMention, applyMention } from "@/lib/mentions";
import Avatar from "@/components/ui/Avatar";

interface MentionTextareaProps {
  value: string;
  onChange: (v: string) => void;
  // 下拉未消费按键时透传（父级据此实现 Cmd/Ctrl+Enter 发送）。
  onKeyDown?: (e: KeyboardEvent<HTMLTextAreaElement>) => void;
  placeholder?: string;
  rows?: number;
  disabled?: boolean;
  id?: string;
  "aria-label"?: string;
}

// 只保留 username 匹配 ^[A-Za-z0-9_]+$ 的成员——绝不建议一个「补出来也解析不了」的提及（R3）。
const RESOLVABLE = /^[A-Za-z0-9_]+$/;
const MAX_CANDIDATES = 6;

// 提及感知 textarea（mention-autocomplete spec §2.2/§2.3）：
// 键入 @ → 弹团队成员下拉，↑/↓ 选择、Enter/Tab 确认、Esc 关闭、鼠标点选；
// 选中精确插入 "@username "（含尾随空格），保证后端正则一定解析命中。
export default function MentionTextarea({
  value,
  onChange,
  onKeyDown,
  placeholder,
  rows = 2,
  disabled,
  id,
  "aria-label": ariaLabel,
}: MentionTextareaProps) {
  const { data: users } = useSWR<User[]>(USERS_KEY, swrFetcher); // 与 AssigneePicker 同 key，去重
  const { user: me } = useAuth();

  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [anchor, setAnchor] = useState(0);
  const [activeIndex, setActiveIndex] = useState(0);

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const pendingCaretRef = useRef<number | null>(null); // 受控插入后回填光标（R7）
  const listboxId = useId();

  // 候选：排除自己 + 硬过滤可解析 username；query 命中 username/display_name；「以 q 开头」者优先。
  const candidates = useMemo<User[]>(() => {
    if (!users) return [];
    const q = query.toLowerCase();
    const pool = users.filter((u) => u.id !== me?.id && RESOLVABLE.test(u.username));
    const matched = q
      ? pool.filter(
          (u) =>
            u.username.toLowerCase().includes(q) ||
            (u.display_name || "").toLowerCase().includes(q)
        )
      : pool;
    const starts = (u: User) =>
      u.username.toLowerCase().startsWith(q) || (u.display_name || "").toLowerCase().startsWith(q);
    return [...matched]
      .sort((a, b) => Number(starts(b)) - Number(starts(a)))
      .slice(0, MAX_CANDIDATES);
  }, [users, query, me?.id]);

  const showDropdown = open && candidates.length > 0;

  // value 受控，插入后需在渲染后回填光标一次。
  useEffect(() => {
    if (pendingCaretRef.current == null) return;
    const el = textareaRef.current;
    if (el) {
      const pos = pendingCaretRef.current;
      el.setSelectionRange(pos, pos);
    }
    pendingCaretRef.current = null;
  }, [value]);

  // 依当前光标位置重算 @token：命中则开、按 query 过滤并复位高亮；否则关。
  function syncMention(text: string, caret: number) {
    const m = activeMention(text, caret);
    if (!m) {
      setOpen(false);
      return;
    }
    setQuery(m.query);
    setAnchor(m.anchor);
    setActiveIndex(0);
    setOpen(true);
  }

  function handleChange(e: ChangeEvent<HTMLTextAreaElement>) {
    const v = e.target.value;
    onChange(v);
    syncMention(v, e.target.selectionStart ?? v.length);
  }

  // 光标移动（方向键 / Home/End / 点击 / 拖选 / 回填）统一从 onSelect 重算；
  // ↑/↓ 因 preventDefault 不移动光标，不触发 onSelect，故高亮不被复位。
  function handleSelect() {
    const el = textareaRef.current;
    if (!el) return;
    syncMention(el.value, el.selectionStart ?? el.value.length);
  }

  function selectAt(index: number) {
    const u = candidates[index];
    if (!u) return;
    const el = textareaRef.current;
    const caret = el?.selectionStart ?? value.length;
    const { next, nextCaret } = applyMention(value, anchor, caret, u.username);
    pendingCaretRef.current = nextCaret;
    onChange(next);
    setOpen(false);
    el?.focus();
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    // 【P2-2】IME 组字态：绝不拦截，交还默认行为（避免 ↑/↓/Enter 劫持中文候选确认）。
    if (e.nativeEvent.isComposing) return;

    if (showDropdown) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActiveIndex((i) => (i + 1) % candidates.length);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setActiveIndex((i) => (i - 1 + candidates.length) % candidates.length);
        return;
      }
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        e.stopPropagation();
        selectAt(activeIndex);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation(); // 阻断冒泡至 window，避免连带触发抽屉 Esc 关闭（R1）
        setOpen(false);
        return;
      }
    }
    // 其它键（含下拉关闭时的 Cmd/Ctrl+Enter 发送）透传给父级。
    onKeyDown?.(e);
  }

  return (
    <div className="relative">
      <textarea
        ref={textareaRef}
        id={id}
        value={value}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        onSelect={handleSelect}
        onBlur={() => setOpen(false)}
        rows={rows}
        disabled={disabled}
        placeholder={placeholder}
        aria-label={ariaLabel}
        role="textbox"
        aria-autocomplete="list"
        aria-expanded={showDropdown}
        aria-controls={showDropdown ? listboxId : undefined}
        aria-activedescendant={showDropdown ? `${listboxId}-opt-${activeIndex}` : undefined}
        className="w-full resize-y rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-muted/70 focus:border-clay focus:outline-none focus:ring-2 focus:ring-clay/20"
      />
      {showDropdown && (
        <ul
          id={listboxId}
          role="listbox"
          aria-label="团队成员"
          className="absolute bottom-full left-0 z-20 mb-1 max-h-56 w-64 max-w-full overflow-y-auto rounded-lg border border-border bg-surface py-1 shadow-lg"
        >
          {candidates.map((u, i) => (
            <li
              key={u.id}
              id={`${listboxId}-opt-${i}`}
              role="option"
              aria-selected={i === activeIndex}
              // onMouseDown + preventDefault：保住 textarea 焦点，避免 blur 抢先关下拉。
              onMouseDown={(e) => {
                e.preventDefault();
                selectAt(i);
              }}
              onMouseEnter={() => setActiveIndex(i)}
              className={[
                "flex cursor-pointer items-center gap-2 px-2.5 py-1.5 text-sm",
                i === activeIndex ? "bg-clay/10" : "hover:bg-black/[0.03]",
              ].join(" ")}
            >
              <Avatar name={u.display_name || u.username} color={u.avatar_color} size={22} />
              <span className="min-w-0 flex-1 truncate">
                <span className="text-ink">{u.display_name || u.username}</span>
                <span className="ml-1 text-ink-muted/70">@{u.username}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
