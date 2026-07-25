import NextAuth from "next-auth";
import Google from "next-auth/providers/google";

const googleId = process.env.AUTH_GOOGLE_ID?.trim();
const googleSecret = process.env.AUTH_GOOGLE_SECRET?.trim();

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [
    // Auth.js also auto-reads AUTH_GOOGLE_ID / AUTH_GOOGLE_SECRET when present.
    ...(googleId && googleSecret
      ? [Google({ clientId: googleId, clientSecret: googleSecret })]
      : []),
  ],
  pages: {
    signIn: "/login",
  },
  session: {
    strategy: "jwt",
    maxAge: 30 * 24 * 60 * 60,
  },
  callbacks: {
    async jwt({ token, account, profile }) {
      if (account?.provider === "google" && profile) {
        const googleProfile = profile as { sub?: string; email?: string; name?: string };
        if (googleProfile.sub) token.sub = googleProfile.sub;
        if (googleProfile.email) token.email = googleProfile.email;
        if (googleProfile.name) token.name = googleProfile.name;
      }
      return token;
    },
    async session({ session, token }) {
      if (session.user && token.sub) {
        session.user.id = token.sub;
      }
      return session;
    },
  },
  trustHost: true,
});
