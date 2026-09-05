import { AsyncLocalStorage } from "node:async_hooks";
import { MCP_USER_ID } from "./config";

export type McpUser = {
  id: string;
  email?: string | null;
  name?: string | null;
};

const storage = new AsyncLocalStorage<McpUser>();

export function runWithMcpUser<T>(user: McpUser, fn: () => T): T {
  return storage.run(user, fn);
}

export function currentMcpUser(): McpUser {
  return (
    storage.getStore() || {
      id: MCP_USER_ID,
      name: "MCP connector",
      email: null,
    }
  );
}
