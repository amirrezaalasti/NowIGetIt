import { auth, signIn } from "@/auth";
import { BrandLogo } from "@/components/BrandLogo";
import { redirect } from "next/navigation";

function googleConfigured(): boolean {
  return Boolean(
    process.env.AUTH_GOOGLE_ID?.trim() && process.env.AUTH_GOOGLE_SECRET?.trim(),
  );
}

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ callbackUrl?: string }>;
}) {
  const session = await auth();
  const params = await searchParams;
  const raw = params.callbackUrl || "/";
  const callbackUrl =
    raw.startsWith("/") && !raw.startsWith("//") ? raw : "/";

  if (session?.user) {
    redirect(callbackUrl);
  }

  const ready = googleConfigured();

  return (
    <main className="relative flex min-h-full flex-1 flex-col items-center justify-center overflow-hidden bg-atmosphere px-6">
      <div className="pointer-events-none absolute inset-0 grid-haze" aria-hidden />

      <div className="relative z-10 flex w-full max-w-md flex-col items-center text-center">
        <BrandLogo size="lg" priority />
        <p className="mt-4 font-[family-name:var(--font-display)] text-3xl tracking-tight text-[var(--ink)]">
          NowIGetIt
        </p>
        <h1 className="mt-3 text-lg text-[var(--ink-muted)]">
          Sign in to save and revisit your explanations.
        </h1>

        {ready ? (
          <form
            className="mt-10 w-full"
            action={async () => {
              "use server";
              await signIn("google", { redirectTo: callbackUrl });
            }}
          >
            <button
              type="submit"
              className="inline-flex w-full items-center justify-center gap-3 rounded-full bg-[var(--accent)] px-8 py-3.5 text-base font-semibold text-[var(--on-accent,#062016)] transition hover:brightness-110"
            >
              <GoogleIcon />
              Continue with Google
            </button>
          </form>
        ) : (
          <div className="mt-10 rounded-2xl border border-[var(--accent-hot)]/40 bg-[rgba(240,199,94,0.08)] px-5 py-5 text-left text-sm text-[var(--ink)]">
            <p className="font-semibold text-[var(--accent-hot)]">
              Google OAuth is not configured
            </p>
            <p className="mt-2 text-[var(--ink-muted)]">
              Set <code className="text-[var(--ink)]">AUTH_GOOGLE_ID</code> and{" "}
              <code className="text-[var(--ink)]">AUTH_GOOGLE_SECRET</code> in{" "}
              <code className="text-[var(--ink)]">.env.local</code>, then restart{" "}
              <code className="text-[var(--ink)]">npm run dev</code>.
            </p>
            <ol className="mt-3 list-decimal space-y-1 pl-5 text-[var(--ink-muted)]">
              <li>
                Create an OAuth client in{" "}
                <a
                  className="text-[var(--accent)] underline-offset-2 hover:underline"
                  href="https://console.cloud.google.com/apis/credentials"
                  target="_blank"
                  rel="noreferrer"
                >
                  Google Cloud Console
                </a>{" "}
                (type: Web application).
              </li>
              <li>
                Add redirect URI:{" "}
                <code className="text-[var(--ink)]">
                  http://localhost:3000/api/auth/callback/google
                </code>
              </li>
              <li>Paste Client ID / Client secret into your env files.</li>
            </ol>
          </div>
        )}

        <p className="mt-6 text-sm text-[var(--ink-muted)]">
          Your jobs and videos stay private to your account.
        </p>
      </div>
    </main>
  );
}

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden>
      <path
        fill="currentColor"
        d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.3 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34.2 6.1 29.4 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.2-.4-3.5z"
      />
    </svg>
  );
}
