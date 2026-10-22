import { useCallback, useEffect, useRef, useState } from "react";
import type { Action, ServerState } from "../rules/types.ts";
import { ApiError, api } from "./api.ts";

export type Status = "loading" | "signed-out" | "ready" | "error" | "admin";

/**
 * The traveller's state, held on the server. Every change is a request; the answer is the new state, so the
 * screen can never disagree with the database.
 */
export function useTravellerState() {
  const [state, setState] = useState<ServerState | null>(null);
  const [status, setStatus] = useState<Status>("loading");
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(0);
  // Bumped by a demo reset so the screen starts over from the restored state.
  const [epoch, setEpoch] = useState(0);

  const load = useCallback(async (): Promise<ServerState | null> => {
    try {
      const next = await api.state();
      setState(next);
      setStatus("ready");
      return next;
    } catch (error) {
      if (error instanceof ApiError && error.status === 403) {
        // Signed in, but not as a traveller: the airline account has its own view.
        setState(null);
        const me = await api.me().catch(() => null);
        setStatus(me?.user.role === "AIRLINE_ADMIN" ? "admin" : "signed-out");
      } else if (error instanceof ApiError && error.status === 401) {
        setState(null);
        setStatus("signed-out");
      } else {
        setProblem(
          error instanceof Error ? error.message : "Something went wrong.",
        );
        setStatus("error");
      }
      return null;
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  /** Runs one action. Always resolves with the state to show (a refusal is a state with `error: true`). */
  const dispatch = useCallback(
    async (
      action: Action,
      idempotencyKey?: string,
    ): Promise<ServerState | null> => {
      if (action.type === "clear-notice") {
        setState((s) => (s ? { ...s, notice: "" } : s));
        return null;
      }
      inFlight.current += 1;
      setBusy(true);
      try {
        if (action.type === "demo-reset") {
          const next = await api.resetDemo();
          setState(next);
          setEpoch((e) => e + 1);
          return next;
        }
        if (action.type === "demo-simulate") {
          const next = await api.simulateOthers();
          setState(next);
          return next;
        }
        if (action.type === "demo-sale") {
          const next = await api.demoSale(action.benefit);
          setState(next);
          return next;
        }
        if (action.type === "profile") {
          await api.switchTraveller(action.id);
          return await load();
        }
        const next = await api.act(action, idempotencyKey);
        setState(next);
        return next;
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          setState(null);
          setStatus("signed-out");
          return null;
        }
        // Keep the screen as it was and say what happened.
        const message =
          error instanceof Error
            ? error.message
            : "Something went wrong. Please try again.";
        setState((s) => (s ? { ...s, notice: message, error: true } : s));
        return null;
      } finally {
        inFlight.current -= 1;
        if (inFlight.current === 0) setBusy(false);
      }
    },
    [load],
  );

  const signedOut = useCallback(() => {
    setState(null);
    setStatus("signed-out");
  }, []);

  return { state, status, problem, busy, epoch, dispatch, reload: load, signedOut };
}
