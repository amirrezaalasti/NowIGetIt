import Image from "next/image";

type BrandLogoProps = {
  /** Compact mark for headers; larger for login and the home hero. */
  size?: "sm" | "md" | "lg";
  className?: string;
  priority?: boolean;
  /** Stack the designed wordmark under the mark. */
  withWordmark?: boolean;
  align?: "start" | "center";
};

const SIZES = {
  sm: 40,
  md: 88,
  lg: 128,
} as const;

const WORDMARK = {
  sm: "text-[13px] tracking-[-0.03em]",
  md: "text-[1.65rem] tracking-[-0.04em] sm:text-[1.85rem]",
  lg: "text-[2rem] tracking-[-0.045em] sm:text-[2.55rem]",
} as const;

function Sparkle({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={className}
      aria-hidden
      fill="currentColor"
    >
      <path d="M12 0c.35 5.1 2.2 8.9 7.4 10.6C14.2 12.3 12.35 16.1 12 21.2 11.65 16.1 9.8 12.3 4.6 10.6 9.8 8.9 11.65 5.1 12 0z" />
    </svg>
  );
}

function BrandWordmark({ size }: { size: keyof typeof WORDMARK }) {
  return (
    <span className={`brand-wordmark ${WORDMARK[size]}`}>
      <span className="brand-wordmark-now">Now I</span>
      <span className="brand-wordmark-get">Get It</span>
      <Sparkle className="brand-wordmark-sparkle" />
    </span>
  );
}

export function BrandLogo({
  size = "md",
  className = "",
  priority = false,
  withWordmark = true,
  align = "center",
}: BrandLogoProps) {
  const px = SIZES[size];
  const alt = withWordmark ? "" : "Now I Get It";

  const mark = (
    <span
      className="brand-logo relative inline-block shrink-0"
      style={{ width: px, height: px }}
    >
      <Image
        src="/logo.png"
        alt={alt}
        width={px}
        height={px}
        priority={priority}
        sizes={`${px}px`}
        className="brand-logo-mark"
      />
    </span>
  );

  if (!withWordmark) {
    return <div className={className}>{mark}</div>;
  }

  const alignment = align === "start" ? "items-start text-left" : "items-center text-center";

  return (
    <div className={`flex flex-col ${alignment} gap-1.5 sm:gap-2 ${className}`}>
      {mark}
      <BrandWordmark size={size} />
    </div>
  );
}
