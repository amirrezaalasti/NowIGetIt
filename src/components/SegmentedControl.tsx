"use client";

type Option<T extends string> = {
  id: T;
  label: string;
  hint?: string;
};

type Props<T extends string> = {
  value: T;
  options: Option<T>[];
  onChange: (value: T) => void;
  disabled?: boolean;
  label?: string;
};

export function SegmentedControl<T extends string>({
  value,
  options,
  onChange,
  disabled,
  label,
}: Props<T>) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      {label ? (
        <span className="text-[11px] uppercase tracking-[0.14em] text-[var(--ink-muted)]">
          {label}
        </span>
      ) : null}
      <div
        role="radiogroup"
        aria-label={label}
        className="inline-flex max-w-full flex-wrap rounded-lg border border-[var(--line)] bg-[var(--surface-inset)] p-0.5"
      >
        {options.map((opt) => {
          const selected = value === opt.id;
          return (
            <button
              key={opt.id}
              type="button"
              role="radio"
              aria-checked={selected}
              title={opt.hint}
              disabled={disabled}
              onClick={() => onChange(opt.id)}
              className={`rounded-md px-3 py-1.5 text-sm transition disabled:cursor-not-allowed disabled:opacity-40 ${
                selected
                  ? "bg-[var(--bg-lift)] text-[var(--ink)] shadow-sm"
                  : "text-[var(--ink-muted)] hover:text-[var(--ink)]"
              }`}
            >
              {opt.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
