import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import * as oauth from "./oauth";

process.env.AUTH_SECRET ||= "test-oauth-secret-for-nowigetit-mcp";

afterEach(() => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  delete (globalThis as any).fetch;
});

test("authorization server metadata advertises CIMD for ChatGPT Apps", () => {
  const meta = oauth.authorizationServerMetadata("https://example.com");
  assert.equal(meta.client_id_metadata_document_supported, true);
  assert.ok(meta.token_endpoint_auth_methods_supported.includes("none"));
  assert.equal(meta.authorization_endpoint, "https://example.com/oauth/authorize");
});

test("ChatGPT App connector redirect URIs are allowed", () => {
  assert.equal(
    oauth.isAllowedRedirectUri("https://chatgpt.com/connector/oauth/callback-id"),
    true,
  );
  assert.equal(
    oauth.isAllowedRedirectUri("https://chatgpt.com/connector_platform_oauth_redirect"),
    true,
  );
  assert.equal(oauth.isAllowedRedirectUri("https://evil.example/callback"), false);
});

test("CIMD client_id is an https URL with a path", () => {
  assert.equal(oauth.isCimdClientId("https://chatgpt.com/oauth/abc/client.json"), true);
  assert.equal(oauth.isCimdClientId("https://chatgpt.com/"), false);
  assert.equal(oauth.isCimdClientId("not-a-url"), false);
});

test("loadClient fetches ChatGPT CIMD metadata", async () => {
  const clientId = "https://chatgpt.com/oauth/nowigetit/client.json";
  const redirect = "https://chatgpt.com/connector/oauth/abc";
  globalThis.fetch = (async () =>
    new Response(
      JSON.stringify({
        client_id: clientId,
        client_name: "ChatGPT",
        redirect_uris: [redirect],
        token_endpoint_auth_method: "none",
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    )) as typeof fetch;

  const client = await oauth.loadClient(clientId);
  assert.ok(client);
  assert.equal(client.client_name, "ChatGPT");
  assert.equal(client.token_endpoint_auth_method, "none");
  assert.equal(oauth.clientAllowsRedirect(client, redirect), true);
});

test("loadClient rejects CIMD documents hosted on private hosts", async () => {
  const clientId = "https://127.0.0.1/client.json";
  let fetched = false;
  globalThis.fetch = (async () => {
    fetched = true;
    return new Response("{}", { status: 200 });
  }) as typeof fetch;
  const client = await oauth.loadClient(clientId);
  assert.equal(client, null);
  assert.equal(fetched, false);
});

test("clientAuthFrom reads HTTP Basic client_id", () => {
  const id = "https://chatgpt.com/oauth/nowigetit/client.json";
  const req = new Request("https://example.com/oauth/token", {
    method: "POST",
    headers: {
      Authorization: `Basic ${Buffer.from(`${encodeURIComponent(id)}:`).toString("base64")}`,
    },
  });
  const auth = oauth.clientAuthFrom(req, new URLSearchParams());
  assert.equal(auth.clientId, id);
  assert.equal(auth.clientSecret, "");
});

test("resourcesMatch ignores trailing slashes", () => {
  assert.equal(
    oauth.resourcesMatch("https://example.com/api/mcp", "https://example.com/api/mcp/"),
    true,
  );
});
