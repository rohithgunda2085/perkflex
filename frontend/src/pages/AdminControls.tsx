import { useEffect, useState } from "react";
import type { AdminControls } from "../rules/types.ts";
import { fmt } from "../rules/data.ts";
import { api } from "../services/api.ts";
import { Pill } from "../components/components.tsx";

/**
 * The airline's settings. What a release pays (flat numbers, or a percent of the benefit's cash price), the
 * completion bonus, and points sales on one flight. Each change is written to a log shown below.
 */
export function AdminControlsSection() {
  const [data, setData] = useState<AdminControls | null>(null);
  const [problem, setProblem] = useState("");
  const [percent, setPercent] = useState("18");
  const [cents, setCents] = useState("1");
  const [bonus, setBonus] = useState("50");
  const [flight, setFlight] = useState("");
  const [benefit, setBenefit] = useState("bag");
  const [discount, setDiscount] = useState("20");
  const [ruleKind, setRuleKind] = useState<"SEASON" | "FESTIVAL">("FESTIVAL");
  const [ruleName, setRuleName] = useState("");
  const [ruleStart, setRuleStart] = useState("");
  const [ruleEnd, setRuleEnd] = useState("");
  const [ruleMult, setRuleMult] = useState("2");

  useEffect(() => {
    const controller = new AbortController();
    api
      .adminControls(controller.signal)
      .then((d) => {
        setData(d);
        setPercent(String(d.policy.valuePercent));
        setCents(String(d.policy.centsPerPoint));
        setBonus(String(d.policy.completionBonus));
        setFlight((f) => f || d.flights[0]?.id || "");
      })
      .catch(() => undefined); // the overview above already reports a server problem
    return () => controller.abort();
  }, []);

  async function run(call: Promise<AdminControls>) {
    setProblem("");
    try {
      const next = await call;
      setData(next);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That did not save.");
    }
  }

  if (!data) return null;
  const { policy } = data;
  return (
    <section className="admin-controls" aria-label="Airline settings">
      <h2>Settings</h2>
      <p className="admin-lede">
        Changes apply to new releases and purchases straight away and are written to the log below. Rewards already
        promised do not change.
      </p>
      {problem && (
        <p role="alert" className="admin-problem">
          {problem}
        </p>
      )}
      <div className="control-grid">
        <div className="control-card">
          <h3>What a release pays</h3>
          <div className="control-row" role="group" aria-label="Reward mode">
            <button
              className={`button small-button ${policy.mode === "FLAT" ? "" : "secondary"}`}
              aria-pressed={policy.mode === "FLAT"}
              onClick={() => void run(api.adminPolicy({ mode: "FLAT" }))}
            >
              Flat numbers
            </button>
            <button
              className={`button small-button ${policy.mode === "VALUE" ? "" : "secondary"}`}
              aria-pressed={policy.mode === "VALUE"}
              onClick={() => void run(api.adminPolicy({ mode: "VALUE" }))}
            >
              Percent of value
            </button>
          </div>
          <p>
            {policy.mode === "FLAT"
              ? "Bags and seats pay fixed amounts. Small perks are always fixed."
              : `Bags and seats pay ${policy.valuePercent}% of their cash price, at ${policy.centsPerPoint} cent per point.`}
          </p>
          <div className="control-row">
            <label>
              Percent of value
              <input inputMode="numeric" value={percent} onChange={(e) => setPercent(e.target.value)} />
            </label>
            <label>
              Cents per point
              <input inputMode="decimal" value={cents} onChange={(e) => setCents(e.target.value)} />
            </label>
            <button
              className="button secondary small-button"
              onClick={() =>
                void run(api.adminPolicy({ valuePercent: Number(percent), centsPerPoint: Number(cents) }))
              }
            >
              Save value settings
            </button>
          </div>
        </div>
        <div className="control-card">
          <h3>Completion bonus</h3>
          <p>PerkFlex points added when a traveller completes a trip on which a release posted. Paid from the flight’s budget.</p>
          <div className="control-row">
            <label>
              Bonus points
              <input inputMode="numeric" value={bonus} onChange={(e) => setBonus(e.target.value)} />
            </label>
            <button
              className="button secondary small-button"
              onClick={() => void run(api.adminPolicy({ completionBonus: Number(bonus) }))}
            >
              Save bonus
            </button>
          </div>
        </div>
        <div className="control-card">
          <h3>Points sale on one flight</h3>
          <div className="control-row">
            <label>
              Flight
              <select value={flight} onChange={(e) => setFlight(e.target.value)}>
                {data.flights.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Benefit
              <select value={benefit} onChange={(e) => setBenefit(e.target.value)}>
                {data.benefits.map((b) => (
                  <option key={b.key} value={b.key}>
                    {b.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Percent off
              <input inputMode="numeric" value={discount} onChange={(e) => setDiscount(e.target.value)} />
            </label>
          </div>
          <div className="control-row">
            <button
              className="button secondary small-button"
              onClick={() => void run(api.adminSale({ flightId: flight, benefit, discountPct: Number(discount) }))}
            >
              Start sale
            </button>
            <button
              className="button secondary small-button"
              onClick={() => void run(api.adminSale({ flightId: flight, benefit, discountPct: 0 }))}
            >
              End sale
            </button>
          </div>
          {data.sales.length === 0 ? (
            <p>No sales running.</p>
          ) : (
            <ul>
              {data.sales.map((s) => (
                <li key={`${s.flightId}-${s.benefit}`}>
                  {s.flightId} · {s.benefit} · <Pill tone="mint">{s.discountPct}% off</Pill>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
      <div className="control-card season-card">
        <h3>Seasons and festivals</h3>
        <p>
          The flight award ({fmt(policy.flightAward ?? 25)} points) is multiplied for flights on these dates, so slow periods
          and holidays can earn more. Where two rules overlap, the higher one applies. The most is x3.
        </p>
        <ul aria-label="Season and festival rules">
          {data.seasonRules.map((r) => (
            <li key={r.id}>
              <Pill tone={r.kind === "FESTIVAL" ? "lavender" : "mint"}>{r.kind === "FESTIVAL" ? "Festival" : "Season"}</Pill>{" "}
              {r.name} · {r.start} to {r.end} · x{r.multiplier} · {r.bookings} open booking{r.bookings === 1 ? "" : "s"} in this window{" "}
              <button
                className="text-button"
                aria-label={`Remove ${r.name} ${r.start}`}
                onClick={() => void run(api.adminSeasonRuleRemove(r.id))}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
        <div className="control-row">
          <label>
            Type
            <select value={ruleKind} onChange={(e) => setRuleKind(e.target.value as "SEASON" | "FESTIVAL")}>
              <option value="FESTIVAL">Festival</option>
              <option value="SEASON">Season</option>
            </select>
          </label>
          <label>
            Name
            <input value={ruleName} onChange={(e) => setRuleName(e.target.value)} />
          </label>
          <label>
            From
            <input type="date" value={ruleStart} onChange={(e) => setRuleStart(e.target.value)} />
          </label>
          <label>
            To
            <input type="date" value={ruleEnd} onChange={(e) => setRuleEnd(e.target.value)} />
          </label>
          <label>
            Multiplier (1 to 3)
            <input inputMode="decimal" value={ruleMult} onChange={(e) => setRuleMult(e.target.value)} />
          </label>
        </div>
        <button
          className="button secondary small-button"
          onClick={() =>
            void run(
              api.adminSeasonRule({ kind: ruleKind, name: ruleName, start: ruleStart, end: ruleEnd, multiplier: Number(ruleMult) }),
            )
          }
        >
          Add rule
        </button>
      </div>
      <h3>Change log</h3>
      {data.audit.length === 0 ? (
        <p>No changes yet.</p>
      ) : (
        <ul className="audit-list">
          {data.audit.map((a, i) => (
            <li key={`${a.at}-${i}`}>
              {new Date(a.at).toLocaleString()} · {a.by} · {a.setting}: {a.from ?? "none"} → {a.to ?? "none"}
            </li>
          ))}
        </ul>
      )}
      <small>Completion bonus today: {fmt(policy.completionBonus)} points.</small>
    </section>
  );
}
