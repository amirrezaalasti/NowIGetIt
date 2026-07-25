"use client";

import { useEffect } from "react";
import { useSession } from "next-auth/react";
import { clearApiToken, ensureApiToken } from "@/lib/api";

/** Keeps a short-lived API JWT warm for media URLs and FastAPI calls. */
export function AuthTokenBridge() {
  const { status } = useSession();

  useEffect(() => {
    if (status === "authenticated") {
      void ensureApiToken();
    } else if (status === "unauthenticated") {
      clearApiToken();
    }
  }, [status]);

  return null;
}
