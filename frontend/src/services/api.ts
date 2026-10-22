// The only place the frontend talks to the server. The session lives in an HttpOnly cookie the browser sends
// by itself, so nothing here stores or reads a token.
import type {
  Action,
  AdminControls,
  AdminOverview,
  BestFareRequest,
  BestFareResponse,
  EmailPrefs,
  Needs,
  PerkAdviceResponse,
  UnderstandResponse,
  PerkNudge,
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
    request<{
      user: { profileId: string | null; name: string; role?: string };
    }>(
      "POST",
      "/auth/login",
      { loginId, password },
    ),
  me: () =>
    request<{ user: { role: "PASSENGER" | "AIRLINE_ADMIN" } }>("GET", "/auth/me"),
  adminOverview: (signal?: AbortSignal) =>
    request<AdminOverview>("GET", "/admin/overview", undefined, signal),
  logout: () => request<{ ok: true }>("POST", "/auth/logout", {}),
  state: () => request<ServerState>("GET", "/state"),
  switchTraveller: (profileId: string) =>
    request<{ user: { profileId: string | null } }>("POST", "/demo/switch", {
      profileId,
    }),
  /** Demo only: restores every demo traveller's trips and points to the saved starting point. */
  resetDemo: () => request<ServerState>("POST", "/demo/reset", {}),
  /** Demo only: one other traveller on the flight acts (takes a released seat or adds a bag). */
  simulateOthers: () => request<ServerState>("POST", "/demo/simulate", {}),
  /** Demo only: the airline puts one benefit on a 25% points sale on this traveller's flight. */
  demoSale: (benefit: string) => request<ServerState>("POST", "/demo/sale", { benefit }),
  emailPrefs: (signal?: AbortSignal) => request<EmailPrefs>("GET", "/me/email", undefined, signal),
  setEmailPrefs: (body: { email: string; enabled: boolean }) => request<EmailPrefs>("POST", "/me/email", body),
  adminControls: (signal?: AbortSignal) => request<AdminControls>("GET", "/admin/controls", undefined, signal),
  adminPolicy: (body: Partial<Pick<AdminControls["policy"], "mode" | "valuePercent" | "centsPerPoint" | "completionBonus">>) =>
    request<AdminControls>("POST", "/admin/policy", body),
  adminSale: (body: { flightId: string; benefit: string; discountPct: number }) =>
    request<AdminControls>("POST", "/admin/sale", body),
  adminSeasonRule: (body: { kind: "SEASON" | "FESTIVAL"; name: string; start: string; end: string; multiplier: number }) =>
    request<AdminControls>("POST", "/admin/season-rule", body),
  adminSeasonRuleRemove: (id: number) => request<AdminControls>("POST", "/admin/season-rule/remove", { id }),
  quotes: (
    route: { flightId: string; from: string; to: string; date?: string },
    needs: Needs,
    signal?: AbortSignal,
  ) => request<QuotesResponse>("POST", "/quotes", { ...route, needs }, signal),
  bestFare: (req: BestFareRequest, signal?: AbortSignal) =>
    request<BestFareResponse>("POST", "/assistant/best-fare", req, signal),
  understandNeeds: (req: { message: string; needs: Needs }, signal?: AbortSignal) =>
    request<UnderstandResponse>("POST", "/assistant/understand", req, signal),
  perkNudge: (signal?: AbortSignal) =>
    request<{ nudge: PerkNudge | null }>(
      "GET",
      "/assistant/perk-nudge",
      undefined,
      signal,
    ),
  perkAdvice: (message?: string, signal?: AbortSignal) =>
    request<PerkAdviceResponse>(
      "POST",
      "/assistant/perk-advice",
      { message },
      signal,
    ),
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
