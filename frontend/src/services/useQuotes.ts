import { useEffect, useState } from "react";
import type { Needs, QuotesResponse } from "../rules/types.ts";
import { api } from "./api.ts";

export type QuoteRoute = {
  flightId: string;
  from: string;
  to: string;
  date?: string;
};

/**
 * All four fares priced by the server for this traveller. Refetches (debounced) when the flight, route, date or needs
 * change, and cancels a request that has been overtaken.
 */
export function useQuotes(route: QuoteRoute, needs: Needs, enabled: boolean) {
  const [data, setData] = useState<QuotesResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const key = JSON.stringify([route, needs]);

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    setLoading(true);
    const timer = window.setTimeout(() => {
      api
        .quotes(route, needs, controller.signal)
        .then((result) => {
          setData(result);
          setFailed(false);
        })
        .catch((error: Error) => {
          if (error.name !== "AbortError") setFailed(true);
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    }, 250);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
    // `key` captures the route and needs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, enabled]);

  return { data, loading, failed };
}
