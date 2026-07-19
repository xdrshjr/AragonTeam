import { SelectHTMLAttributes, forwardRef, useId } from "react";

interface Option {
  value: string;
  label: string;
}

interface Props extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  options: Option[];
  placeholder?: string;
}

const Select = forwardRef<HTMLSelectElement, Props>(function Select(
  { label, options, placeholder, className = "", id, ...rest },
  ref
) {
  // 【H7】多数调用方既不传 id 也不传 name → <label> 与控件未关联：点标签不聚焦，
  // 读屏播报「未命名输入框」。useId() 是 React 18 内置且 SSR 安全的稳定兜底。
  const fallbackId = useId();
  const selectId = id || rest.name || fallbackId;
  return (
    <div className="flex flex-col gap-1.5">
      {label && (
        <label htmlFor={selectId} className="text-sm font-medium text-ink">
          {label}
        </label>
      )}
      <select
        ref={ref}
        id={selectId}
        className={[
          "h-10 rounded-lg border border-border bg-surface px-3 text-sm text-ink",
          "focus:outline-none focus:border-clay focus:ring-2 focus:ring-clay/20",
          className,
        ].join(" ")}
        {...rest}
      >
        {placeholder && <option value="">{placeholder}</option>}
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
});

export default Select;
