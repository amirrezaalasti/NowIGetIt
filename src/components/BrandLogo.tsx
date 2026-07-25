import Image from "next/image";

type BrandLogoProps = {
  /** Compact mark for headers; larger for login. */
  size?: "sm" | "md" | "lg";
  className?: string;
  priority?: boolean;
  /** Show wordmark text beside the mark (site type, not baked into the image). */
  withWordmark?: boolean;
};

const SIZES = {
  sm: 44,
  md: 72,
  lg: 112,
} as const;

function ThemeMark({
  size,
  priority,
  decorative,
}: {
  size: number;
  priority?: boolean;
  decorative?: boolean;
}) {
  const alt = decorative ? "" : "NowIGetIt — turn ideas into understanding";
  return (
    <span className="brand-logo relative inline-block" style={{ width: size, height: size }}>
      <Image
        src="/logo-mark.png"
        alt={alt}
        width={size}
        height={size}
        priority={priority}
        className="brand-logo-dark rounded-xl"
      />
      <Image
        src="/logo-mark-light.png"
        alt={alt}
        width={size}
        height={size}
        priority={priority}
        className="brand-logo-light absolute inset-0 rounded-xl"
      />
    </span>
  );
}

export function BrandLogo({
  size = "md",
  className = "",
  priority = false,
  withWordmark = false,
}: BrandLogoProps) {
  const px = SIZES[size];
  const mark = (
    <ThemeMark size={px} priority={priority} decorative={withWordmark} />
  );

  if (!withWordmark) {
    return <div className={className}>{mark}</div>;
  }

  return (
    <div className={`flex items-center gap-3 sm:gap-4 ${className}`}>
      {mark}
      <div className="min-w-0 text-left">
        <p className="font-[family-name:var(--font-display)] text-3xl tracking-tight text-[var(--ink)] sm:text-4xl">
          NowIGetIt
        </p>
        <p className="mt-1 text-[11px] uppercase tracking-[0.18em] text-[var(--ink-muted)] sm:text-xs">
          Turn ideas into understanding
        </p>
      </div>
    </div>
  );
}
