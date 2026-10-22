import { useEffect, useState } from "react";
import { LogOut, RefreshCw } from "lucide-react";
import type { AdminOverview, BenefitsPool } from "../rules/types.ts";
import { fmt, money } from "../rules/data.ts";
import { api } from "../services/api.ts";
import { PerkFlexLogo, Pill } from "../components/components.tsx";
import { AdminControlsSection } from "./AdminControls.tsx";

/**
 * The airline's view of the reward programme: what has been promised to travellers, what has been paid, and what
 * the programme is costing, flight by flight. Read only. The server refuses this data to anyone but an airline account.
 */
export function AdminPage({ onSignOut }: { onSignOut: () => void }) {
  const [data, setData] = useState<AdminOverview | null>(null);
  const [problem, setProblem] = useState("");
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setProblem("");
    api
      .adminOverview(controller.signal)
      .then(setData)
      .catch((e: Error) => {
        if (e.name !== "AbortError") setProblem(e.message);
      });
    return () => controller.abort();
  }, [tick]);

  return (
    <div className="admin-shell">
      <header className="admin-header">
        <div className="container">
          <PerkFlexLogo />
          <Pill tone="lavender">Airline view</Pill>
          <span className="admin-spacer" />
          <button className="text-button" onClick={() => setTick((n) => n + 1)}>
            <RefreshCw size={15} /> Refresh
          </button>
          <button className="text-button" onClick={onSignOut}>
            <LogOut size={15} /> Sign out
          </button>
        </div>
      </header>
      <main className="container admin-page">
        <div className="eyebrow">REWARD PROGRAMME</div>
        <h1>What PerkFlex is costing, flight by flight</h1>
        <p className="admin-lede">
          Points promised to travellers stay pending until the flight is flown.
          The estimated cost uses each flight’s assumed cost per point.
        </p>
        {problem && (
          <p role="alert" className="admin-problem">
            {problem}
          </p>
        )}
        {!data && !problem && <p role="status">Loading the overview…</p>}
        {data && (
          <>
            <section className="admin-cards" aria-label="Totals">
              <Stat label="Reward budget" value={fmt(data.totals.budget)} note={`${data.totals.flights} flights with bookings`} />
              <Stat label="Owed to travellers" value={fmt(data.totals.owed)} note="Pending until flown" />
              <Stat label="Paid out" value={fmt(data.totals.paid)} note="Posted after flights" />
              <Stat label="Estimated cost" value={money(data.totals.estimatedCost)} note="Owed plus paid" />
              <Stat label="Benefits released" value={fmt(data.totals.releases)} note="Bags, seats and small perks" />
              <Stat label="Seats reused" value={fmt(data.totals.seatsReused ?? 0)} note={`of ${fmt(data.totals.seatsFreed ?? 0)} seats released`} />
              <Stat label="Bought with points" value={fmt(data.totals.redemptions)} note={`${fmt(data.totals.pointsSpent)} points used`} />
            </section>
            {data.model && (
              <section className="admin-model" aria-label="With and without PerkFlex">
                <h2>With and without PerkFlex</h2>
                <div className="model-grid" role="table">
                  <div role="row" className="model-head">
                    <span role="columnheader" />
                    <span role="columnheader">Without</span>
                    <span role="columnheader">With PerkFlex</span>
                  </div>
                  <div role="row">
                    <span role="rowheader">Reward cost</span>
                    <span role="cell">{money(data.model.without.rewardCost)}</span>
                    <span role="cell">{money(data.model.with.rewardCost)}</span>
                  </div>
                  <div role="row">
                    <span role="rowheader">Seats resold</span>
                    <span role="cell">{money(data.model.without.seatResale)}</span>
                    <span role="cell">{money(data.model.with.seatResale)}</span>
                  </div>
                  <div role="row" className="model-net">
                    <span role="rowheader">Net</span>
                    <span role="cell">{money(data.model.without.net)}</span>
                    <span role="cell">{money(data.model.with.net)}</span>
                  </div>
                </div>
                <ul className="model-notes">
                  {data.model.assumptions.map((a) => (
                    <li key={a}>{a}</li>
                  ))}
                </ul>
              </section>
            )}
            <section className="admin-flags" aria-label="Trips to review">
              <h2>Trips to review</h2>
              {(data.flags ?? []).length === 0 ? (
                <p>Nothing to review. No trip undid or bought back its own releases.</p>
              ) : (
                <ul>
                  {(data.flags ?? []).map((f) => (
                    <li key={`${f.kind}-${f.booking}`}>
                      <strong>{f.booking}</strong> · {f.flightId} · {f.date} — {f.text}
                    </li>
                  ))}
                </ul>
              )}
              <small>These are prompts for a person to look at, not automatic penalties. Undos are capped at 3 per trip.</small>
            </section>
            <section aria-label="Benefits inventory pool">
              <h2>Benefits inventory pool</h2>
              <p className="admin-lede">
                Under each flight: every benefit travellers released (gave up for points) and every benefit bought with points.
              </p>
              <p className="admin-lede">
                What each flight can still hand out. A traveller who releases a seat puts it back here; a traveller who
                buys one takes it out. Reward budget is the points the flight can still promise.
              </p>
              {data.flights.length === 0 ? (
                <p>No flights have bookings yet.</p>
              ) : (
                <div className="pool-grid">
                  {data.flights.map((f) => (
                    <PoolCard key={`${f.flightId}-${f.date}`} flight={f} />
                  ))}
                </div>
              )}
            </section>
            <section aria-label="Flights">
              <h2>Flights</h2>
              {data.flights.length === 0 ? (
                <p>No flights have bookings yet.</p>
              ) : (
                <div className="admin-table" role="table">
                  <div className="admin-row admin-head" role="row">
                    <span role="columnheader">Flight</span>
                    <span role="columnheader">Travellers</span>
                    <span role="columnheader">Reward budget</span>
                    <span role="columnheader">Released</span>
                    <span role="columnheader">Bought</span>
                  </div>
                  {data.flights.map((f) => {
                    const pct = (n: number) => (f.budget ? Math.min(100, (n / f.budget) * 100) : 0);
                    return (
                      <div className="admin-row" role="row" key={`${f.flightId}-${f.date}`}>
                        <span role="cell">
                          <strong>{f.flightId}</strong>
                          <small>
                            {f.from} → {f.to} · {f.date} · {f.status}
                          </small>
                        </span>
                        <span role="cell">
                          {f.bookings}
                          <small>{f.checkedIn} checked in</small>
                        </span>
                        <span role="cell">
                          <span
                            className="budget-bar"
                            role="img"
                            aria-label={`${fmt(f.settled)} paid, ${fmt(f.reserved)} owed, ${fmt(f.remaining)} left of ${fmt(f.budget)}`}
                          >
                            <i className="paid" style={{ width: `${pct(f.settled)}%` }} />
                            <i className="owed" style={{ width: `${pct(f.reserved)}%` }} />
                          </span>
                          <small>
                            {fmt(f.reserved + f.settled)} of {fmt(f.budget)} used · {fmt(f.remaining)} left
                          </small>
                        </span>
                        <span role="cell">
                          {f.releases.bag + f.releases.seat + f.releases.perk}
                          <small>
                            {f.releases.bag} bag · {f.releases.seat} seat · {f.releases.perk} perk · {fmt(f.pointsEarned)} pts
                          </small>
                        </span>
                        <span role="cell">
                          {f.redemptions.bag + f.redemptions.seat + f.redemptions.perk}
                          <small>
                            {f.redemptions.bag} bag · {f.redemptions.seat} seat · {f.redemptions.perk} perk · {fmt(f.pointsSpent)} pts
                          </small>
                        </span>
                      </div>
                    );
                  })}
                </div>
              )}
            </section>
          </>
        )}
        {data && <AdminControlsSection />}
      </main>
    </div>
  );
}

const SEAT_LABEL = { standard: "Standard seats", preferred: "Preferred seats", extra: "Extra Legroom seats" } as const;

function PoolCard({ flight: f }: { flight: AdminOverview["flights"][number] }) {
  const pool: BenefitsPool | undefined = f.pool;
  return (
    <article className="pool-card" data-flight={f.flightId} aria-label={`Pool for flight ${f.flightId}`}>
      <header>
        <strong>{f.flightId}</strong>
        <small>
          {f.from} → {f.to} · {f.date}
        </small>
      </header>
      <ul>
        <li>
          <span>Reward budget left</span>
          <strong>{fmt(f.remaining)}</strong>
          <small>of {fmt(f.budget)} points</small>
        </li>
        <li>
          <span>Bag grants left</span>
          <strong>{pool ? pool.bagGrants.remaining : "–"}</strong>
          <small>{pool ? `of ${pool.bagGrants.total}` : ""}</small>
        </li>
        {pool &&
          (["standard", "preferred", "extra"] as const).map((k) => (
            <li key={k} data-seat={k}>
              <span>{SEAT_LABEL[k]} free</span>
              <strong>{pool.seats[k].free}</strong>
              <small>
                of {pool.seats[k].total} · {pool.seats[k].givenBack} given back · {pool.seats[k].reused} re-taken
              </small>
            </li>
          ))}
      </ul>
      <small>
        Released by travellers: {f.releases.bag} bag · {f.releases.seat} seat · {f.releases.perk} perk
      </small>
      <div className="pool-benefits" role="table" aria-label={`Benefits on flight ${f.flightId}`}>
        <div className="pool-benefit-row pool-benefit-head" role="row">
          <span role="columnheader">Benefit</span>
          <span role="columnheader">Released</span>
          <span role="columnheader">Bought</span>
        </div>
        {(f.benefits ?? []).length === 0 ? (
          <p role="row">Nothing released or bought yet.</p>
        ) : (
          (f.benefits ?? []).map((b) => (
            <div className="pool-benefit-row" role="row" key={b.name} data-benefit={b.name}>
              <span role="cell">{b.name}</span>
              <span role="cell" title={`${fmt(b.pointsEarned)} points earned`}>
                {b.released}
              </span>
              <span role="cell" title={`${fmt(b.pointsSpent)} points spent`}>
                {b.bought}
              </span>
            </div>
          ))
        )}
      </div>
    </article>
  );
}

function Stat({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className="admin-card">
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{note}</small>
    </div>
  );
}
