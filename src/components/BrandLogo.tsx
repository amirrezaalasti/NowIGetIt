import { useId } from "react";

type BrandLogoProps = {
  /** Compact lockup for headers; larger for login and the home hero. */
  size?: "sm" | "md" | "lg" | "xl";
  className?: string;
  /** Show the wordmark next to (sm) or under (md+) the mascot. */
  withWordmark?: boolean;
  align?: "start" | "center";
  /** Idle animation: blink, twinkle, float. Off in headers by default. */
  animated?: boolean;
};

const SIZES = {
  sm: 34,
  md: 88,
  lg: 128,
  xl: 220,
} as const;

const WORDMARK = {
  sm: "text-[1.2rem] tracking-[-0.03em]",
  md: "text-[1.65rem] tracking-[-0.04em] sm:text-[1.85rem]",
  lg: "text-[2.1rem] tracking-[-0.045em] sm:text-[2.6rem]",
  xl: "text-[2.6rem] tracking-[-0.045em] sm:text-[3.4rem]",
} as const;

export function Sparkle({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden fill="currentColor">
      <path d="M12 0c.35 5.1 2.2 8.9 7.4 10.6C14.2 12.3 12.35 16.1 12 21.2 11.65 16.1 9.8 12.3 4.6 10.6 9.8 8.9 11.65 5.1 12 0z" />
    </svg>
  );
}

/**
 * The "aha" mascot, drawn inline so it follows the site palette and theme.
 * Colors come from the --mascot-* tokens in globals.css.
 */
export function BrandMark({
  size = 128,
  animated = false,
  className = "",
  title,
}: {
  size?: number;
  animated?: boolean;
  className?: string;
  title?: string;
}) {
  const gradientId = `nig-mascot-${useId().replace(/:/g, "")}`;

  return (
    <svg
      viewBox="0 0 120 120"
      width={size}
      height={size}
      className={`brand-mark ${animated ? "brand-mark--animated" : ""} ${className}`}
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
    >
      <defs>
        <linearGradient id={gradientId} x1=".75" y1="0" x2=".2" y2="1">
          <stop offset="0" style={{ stopColor: "var(--mascot-body-hi)" }} />
          <stop offset=".55" style={{ stopColor: "var(--mascot-body)" }} />
          <stop offset="1" style={{ stopColor: "var(--mascot-body-lo)" }} />
        </linearGradient>
      </defs>
      <ellipse className="brand-mark-shadow" cx="60" cy="111" rx="24" ry="3" />
      <g className="brand-mark-burst">
        <path d="M17 44l6 5" />
        <path d="M12 61l8 1" />
        <path d="M101 38l5-5" />
        <path d="M103 55l8-1" />
      </g>
      <path
        className="brand-mark-spark"
        d="M95 7c.5 7.2 3.1 10.9 10 12.6-6.9 1.7-9.5 5.4-10 12.6-.5-7.2-3.1-10.9-10-12.6 6.9-1.7 9.5-5.4 10-12.6z"
      />
      <g className="brand-mark-body">
        <path
          className="brand-mark-shade"
          d="M36 101C24 93 21 74 26 57 31 39 46 29 63 30c18 1 31 13 30 31-1 19-11 37-30 41-10 2-20 4-27-1z"
        />
        <path
          d="M42 99c-9-9-10-25-6-40 5-17 18-26 32-25 15 1 26 12 25 28-1 19-11 34-29 39-8 2-16 3-22-2z"
          fill={`url(#${gradientId})`}
        />
        <g className="brand-mark-brows">
          <path d="M42 33c3-4 8-5 12-3" />
          <path d="M68 22c4-3 9-3 12 0" />
        </g>
        <g className="brand-mark-eye">
          <circle className="brand-mark-sclera" cx="55" cy="56" r="11" />
          <circle className="brand-mark-pupil" cx="58" cy="53" r="6" />
          <circle className="brand-mark-glint" cx="60" cy="50.8" r="1.8" />
        </g>
        <g className="brand-mark-eye">
          <circle className="brand-mark-sclera" cx="78" cy="47" r="10" />
          <circle className="brand-mark-pupil" cx="81" cy="44.5" r="5.5" />
          <circle className="brand-mark-glint" cx="82.8" cy="42.5" r="1.6" />
        </g>
        <path
          className="brand-mark-pupil"
          d="M71 66c4-3 9-2 10 3 1 6-2 12-7 12-5 0-6-5-6-8 0-3 1-5 3-7z"
        />
        <path
          className="brand-mark-tongue"
          d="M70.5 76.5c2-2.2 6-2.2 8 0-1 2.6-2.6 3.8-4.4 3.8-2 0-3.4-1.6-3.6-3.8z"
        />
      </g>
    </svg>
  );
}

export function BrandWordmark({
  size = "md",
  className = "",
}: {
  size?: keyof typeof WORDMARK;
  className?: string;
}) {
  return (
    <span className={`brand-wordmark ${WORDMARK[size]} ${className}`}>
      <span className="brand-wordmark-now">Now I</span>
      <span className="brand-wordmark-get">Get It</span>
      <Sparkle className="brand-wordmark-sparkle" />
    </span>
  );
}

export function BrandLogo({
  size = "md",
  className = "",
  withWordmark = true,
  align = "center",
  animated,
}: BrandLogoProps) {
  const px = SIZES[size];
  const mark = (
    <BrandMark
      size={px}
      animated={animated ?? size !== "sm"}
      title={withWordmark ? undefined : "Now I Get It"}
      className="shrink-0"
    />
  );

  if (!withWordmark) {
    return <div className={className}>{mark}</div>;
  }

  // Headers read left to right; heroes stack the wordmark under the mascot.
  if (size === "sm") {
    return (
      <div className={`brand-lockup flex items-center gap-2 ${className}`}>
        {mark}
        <BrandWordmark size="sm" />
      </div>
    );
  }

  const alignment = align === "start" ? "items-start text-left" : "items-center text-center";

  return (
    <div className={`brand-lockup flex flex-col ${alignment} gap-1.5 sm:gap-2 ${className}`}>
      {mark}
      <BrandWordmark size={size} />
    </div>
  );
}
