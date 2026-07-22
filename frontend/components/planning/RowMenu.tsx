"use client";

// 版本卡 / 计划行共用的「⋯」菜单（version-plan-console §7.1）。
//
// 【为什么单独成文件（对 §5.4 清单的一处偏差，已登记进 spec「实施过程发现的方案缺陷」）】
// spec 说「⋯ 菜单（版本 / 计划共用形状）」，但没有给它一个落点。两级各写一份就是两套
// Esc / 失焦 / a11y 属性，改一处忘一处是必然。本仓库没有 Dropdown 原语，写法照抄
// `layout/Header.tsx` 的头像菜单（mousedown 关闭 + 绝对定位面板），另补 Esc 关闭。

import { useEffect, useRef, useState } from "react";

export interface RowMenuItem {
  label: string;
  onSelect: () => void;
  danger?: boolean;
}

interface Props {
  items: RowMenuItem[];
  /** 读屏用：「版本 v1.0 的更多操作」比一个裸「更多操作」有用得多。 */
  ariaLabel: string;
}

export default function RowMenu({ items, ariaLabel }: Props) {
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onMouseDown(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onMouseDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onMouseDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="relative" ref={boxRef}>
      <button
        type="button"
        aria-label={ariaLabel}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={(e) => {
          // 卡头本身是折叠按钮 / 行本身可点，菜单必须掐断冒泡。
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        className="rounded-md px-2 py-1 text-ink-muted hover:bg-black/[0.06] hover:text-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-clay/40"
      >
        <span aria-hidden="true">⋯</span>
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 z-20 mt-1 w-36 rounded-xl border border-border bg-surface p-1.5 shadow-lift"
          onClick={(e) => e.stopPropagation()}
        >
          {items.map((item) => (
            <button
              key={item.label}
              type="button"
              role="menuitem"
              onClick={() => {
                setOpen(false);
                item.onSelect();
              }}
              className={[
                "w-full rounded-lg px-3 py-2 text-left text-sm",
                item.danger
                  ? "text-[#B23B1E] hover:bg-[#F3D2C7]/40"
                  : "text-ink hover:bg-black/[0.04]",
              ].join(" ")}
            >
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
