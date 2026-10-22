import { useEffect, useState } from "react";
import { Sparkles } from "lucide-react";
import type { PerkAdviceResponse, PerkNudge } from "../rules/types.ts";
import { fmt } from "../rules/data.ts";
import { api } from "../services/api.ts";

/**
 * "Ask the advisor": advice only. The server computes the offers and checks the AI's answer; this panel shows it.
 * Every number below comes from the offers, so it matches the buttons further down the page. It changes nothing.
 * A one-line hint (the "nudge") is loaded without asking. It is written by the rules, so it costs no AI call.
 */
export function AdvisorPanel({ refreshKey }: { refreshKey: string }) {
  const [text, setText] = useState("");
  const [ai, setAi] = useState<{
    status: "idle" | "loading" | "done" | "failed";
    data?: PerkAdviceResponse;
    key?: string;
  }>({ status: "idle" });

  const [nudge, setNudge] = useState<PerkNudge | null>(null);
  useEffect(() => {
    // The hint is a bonus: if it cannot be loaded, the panel simply shows no hint.
    const controller = new AbortController();
    setNudge(null);
    api
      .perkNudge(controller.signal)
      .then((r) => setNudge(r.nudge))
      .catch(() => {});
    return () => controller.abort();
  }, [refreshKey]);

  function ask() {
    setAi({ status: "loading" });
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 35000);
    api
      .perkAdvice(text.trim() || undefined, controller.signal)
      .then((data) => setAi({ status: "done", data, key: refreshKey }))
      .catch(() => setAi({ status: "failed" }))
      .finally(() => window.clearTimeout(timer));
  }

  // Advice goes stale once the traveller acts (points, bags or seats change), so hide it until they ask again.
  const data = ai.status === "done" && ai.key === refreshKey ? ai.data : undefined;
  const offerFor = (id: string) => data?.offers.find((o) => o.id === id);

  return (
    <section className="advisor-panel" aria-label="PerkFlex advisor">
      <div className="advisor-head">
        <h3>
          <Sparkles size={18} /> Not sure what to do with your bags and seat?
        </h3>
        <p>
          Ask the PerkFlex advisor. It only suggests; you choose with the
          buttons below.
        </p>
      </div>
      {nudge && !data && (
        <p className="advisor-nudge" role="note">
          <strong>Tip:</strong> {nudge.text}
        </p>
      )}
      <div className="advisor-ask">
        <input
          value={text}
          maxLength={500}
          onChange={(e) => setText(e.target.value)}
          placeholder="Optional: tell us anything that matters, e.g. “I only carry a backpack”"
          aria-label="Message to the advisor"
        />
        <button
          className="button secondary small-button"
          onClick={ask}
          disabled={ai.status === "loading"}
        >
          {ai.status === "loading" ? "Thinking…" : "Ask the advisor"}
        </button>
      </div>
      {ai.status === "failed" && (
        <p className="advisor-note" role="alert">
          The advisor could not be reached. Your offers are listed below.
        </p>
      )}
      {data && (
        <div className="advisor-answer" aria-live="polite">
          <p>{data.summary}</p>
          {data.picks.length > 0 && (
            <ul>
              {data.picks.map((p) => {
                const offer = offerFor(p.offerId);
                return (
                  <li key={p.offerId}>
                    <strong>{offer?.label ?? p.offerId}</strong>
                    {offer && (
                      <span className="advisor-points">
                        {offer.included
                          ? "Included in your benefits"
                          : offer.kind === "release"
                            ? `+${fmt(offer.points)} pts, pending until you fly`
                            : `${fmt(offer.points)} pts`}
                      </span>
                    )}
                    <small>{p.why}</small>
                  </li>
                );
              })}
            </ul>
          )}
          {data.source === "fallback" && (
            <small className="advisor-note">Automatic answer</small>
          )}
        </div>
      )}
    </section>
  );
}
