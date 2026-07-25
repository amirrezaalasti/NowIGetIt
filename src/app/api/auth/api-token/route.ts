import { SignJWT } from "jose";
import { auth } from "@/auth";
import { NextResponse } from "next/server";

const TOKEN_TTL_SECONDS = 60 * 60; // 1 hour

export async function GET() {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const secret = process.env.AUTH_SECRET;
  if (!secret) {
    return NextResponse.json(
      { error: "AUTH_SECRET is not configured" },
      { status: 500 },
    );
  }

  const expiresAt = Date.now() + TOKEN_TTL_SECONDS * 1000;
  const accessToken = await new SignJWT({
    email: session.user.email ?? null,
    name: session.user.name ?? null,
    image: session.user.image ?? null,
  })
    .setProtectedHeader({ alg: "HS256" })
    .setSubject(session.user.id)
    .setIssuedAt()
    .setExpirationTime(`${TOKEN_TTL_SECONDS}s`)
    .setAudience("nowigetit-api")
    .setIssuer("nowigetit")
    .sign(new TextEncoder().encode(secret));

  return NextResponse.json({ accessToken, expiresAt });
}
