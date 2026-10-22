// The only place the frontend talks to the server. The session lives in an HttpOnly cookie the browser sends
// by itself, so nothing here stores or reads a token.
import type {
  Action,
  BestFareRequest,
  BestFareResponse,
  Needs,
  QuotesResponse,
  ServerState,
} from "../rules/types.ts";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(
  method: "GET" | "POST",
  path: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      method,
      headers:
        body === undefined ? undefined : { "content-type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (error) {
    if ((error as Error).name === "AbortError") throw error;
    throw new ApiError(
      0,
      "We couldn’t reach PerkFlex. Please check your connection and try again.",
    );
  }
  const json = (await res.json().catch(() => ({}))) as { error?: string };
  if (!res.ok)
    throw new ApiError(
      res.status,
      json.error ?? `Request failed (${res.status})`,
    );
  return json as T;
}

export const api = {
  login: (loginId: string, password: string) =>
    request<{ user: { profileId: string | null; name: string } }>(
      "POST",
      "/auth/login",
      { loginId, password },
    ),
  logout: () => request<{ ok: true }>("POST", "/auth/logout", {}),
  state: () => request<ServerState>("GET", "/state"),
  switchTraveller: (profileId: string) =>
    request<{ user: { profileId: string | null } }>("POST", "/demo/switch", {
      profileId,
    }),
  quotes: (
    route: { flightId: string; from: string; to: string; date?: string },
    needs: Needs,
    signal?: AbortSignal,
  ) => request<QuotesResponse>("POST", "/quotes", { ...route, needs }, signal),
  bestFare: (req: BestFareRequest, signal?: AbortSignal) =>
    request<BestFareResponse>("POST", "/assistant/best-fare", req, signal),
  /** `profileId` is dropped: the server acts for the signed-in traveller only. */
  act: (
    action: Exclude<Action, { type: "profile" } | { type: "clear-notice" }>,
    idempotencyKey?: string,
  ) => {
    const { profileId: _ignored, ...rest } = action as typeof action & {
      profileId?: string;
    };
    return request<ServerState>("POST", "/actions", {
      ...rest,
      ...(idempotencyKey ? { idempotencyKey } : {}),
    });
  },
};
