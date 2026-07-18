import { TextareaHTMLAttributes, forwardRef } from "react";

interface Props extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
}

const Textarea = forwardRef<HTMLTextAreaElement, Props>(function Textarea(
  { label, className = "", id, rows = 4, ...rest },
  ref
) {
  const areaId = id || rest.name;
  return (
    <div className="flex flex-col gap-1.5">
      {label && (
        <label htmlFor={areaId} className="text-sm font-medium text-ink">
          {label}
        </label>
      )}
      <textarea
        ref={ref}
        id={areaId}
        rows={rows}
        className={[
          "rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink resize-y",
          "placeholder:text-ink-muted/70",
          "focus:outline-none focus:border-clay focus:ring-2 focus:ring-clay/20",
          className,
        ].join(" ")}
        {...rest}
      />
    </div>
  );
});

export default Textarea;
