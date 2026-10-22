import { useEffect, useState } from "react";
import { Bell, Clock3, Mail, Coins, Plane, RefreshCw, Sparkles, Target } from "lucide-react";
import { redeemPrice } from "../rules/helpers.ts";
import { api } from "../services/api.ts";
import type {
  Action,
  EmailPrefs,
  Booking,
  Earning,
  Group,
  Ledger,
  Notification,
  Perk,
  Prices,
  Reuse,
  StatusView,
  Undoable,
  Wallets,
  SaleKey,
} from "../rules/types.ts";
import { RULES, fmt } from "../rules/data.ts";
import { payLabel, paySplit } from "../rules/helpers.ts";
import { Pill } from "../components/components.tsx";

/** A release can be taken back for a few minutes. The countdown is cosmetic: the database enforces the window. */
export function UndoBar({
  undoable,
  onUndo,
}: {
  undoable: Undoable[];
  onUndo: (u: Undoable) => void;
}) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    setElapsed(0);
    const id = window.setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => window.clearInterval(id);
  }, [undoable]);
  const live = undoable.filter((u) => u.secondsLeft - elapsed > 0);
  if (live.length === 0) return null;
  return (
    <section className="undo-bar" aria-label="Undo a release">
      {live.map((u) => {
        const left = u.secondsLeft - elapsed;
        return (
          <div className="undo-row" key={u.benefit}>
            <span>
              Released <strong>{u.label.toLowerCase()}</strong> for{" "}
              {fmt(u.points)} pending points.
            </span>
            <button className="button secondary small-button" onClick={() => onUndo(u)}>
              <RefreshCw size={15} /> Undo ({Math.floor(left / 60)}:
              {String(left % 60).padStart(2, "0")})
            </button>
          </div>
        );
      })}
    </section>
  );
}

/** Shows that what a traveller gave up came back into use. */
export function ReuseCard({ reuse }: { reuse?: Reuse | null }) {
  if (!reuse || (!reuse.seat && !reuse.bag)) return null;
  const { seat, bag } = reuse;
  return (
    <section className="reuse-card" aria-label="Your released benefits">
      <RefreshCw size={20} />
      <div>
        {seat && (
          <>
            <strong>
              {seat.reused
                ? `Seat ${seat.seat} was taken by another traveller.`
                : `Seat ${seat.seat} is back with the airline.`}
            </strong>
            <small>
              {seat.reused
                ? "Your release made room for someone else. It can no longer be undone."
                : "It can be sold again while it stays open, so your release is working."}
            </small>
          </>
        )}
        {bag && (
          <>
            <strong>
              {bag.othersAdded > 0
                ? `${bag.othersAdded} other traveller${bag.othersAdded === 1 ? "" : "s"} added a bag on this flight after you released yours.`
                : "Your released bag is available to other travellers on this flight."}
            </strong>
            <small>Bag space is shared across the flight, so unused allowances get used.</small>
          </>
        )}
      </div>
      <Pill tone={seat?.reused || (bag && bag.othersAdded > 0) ? "mint" : "yellow"}>
        {seat?.reused || (bag && bag.othersAdded > 0) ? "Reused" : "Freed"}
      </Pill>
    </section>
  );
}

/** Messages worked out from the traveller's own data. Email or push would need a sender, which is not built. */
export function Notifications({ items }: { items: Notification[] }) {
  if (items.length === 0) return null;
  return (
    <section className="notifications" aria-label="Notifications">
      <h2>
        <Bell size={18} /> Notifications <Pill tone="lavender">{items.length}</Pill>
      </h2>
      <ul>
        {items.map((n) => (
          <li key={n.id} data-kind={n.kind}>
            {n.text}
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Which wallet a purchase uses first. */
export function PayOrderToggle({
  rapidFirst,
  wallets,
  onChange,
}: {
  rapidFirst: boolean;
  wallets: Wallets;
  onChange: (rapidFirst: boolean) => void;
}) {
  return (
    <div className="pay-order" role="group" aria-label="Spend order">
      <span>Spend order</span>
      <button
        className={`seg ${!rapidFirst ? "on" : ""}`}
        aria-pressed={!rapidFirst}
        onClick={() => rapidFirst && onChange(false)}
      >
        PerkFlex first ({fmt(wallets.perkflex.available)})
      </button>
      <button
        className={`seg ${rapidFirst ? "on" : ""}`}
        aria-pressed={rapidFirst}
        onClick={() => !rapidFirst && onChange(true)}
      >
        Rapid Rewards first ({fmt(wallets.rapidRewards.available)})
      </button>
    </div>
  );
}

export function ExpiryNotice({ wallets }: { wallets: Wallets }) {
  const e = wallets.perkflex.expiring;
  if (!e || e.soonPoints <= 0) return null;
  return (
    <p className="expiry-notice" role="status">
      <Clock3 size={16} /> {fmt(e.soonPoints)} PerkFlex points expire on{" "}
      {e.soonDate} ({e.soonDays} day{e.soonDays === 1 ? "" : "s"}). The oldest
      points are spent first.
    </p>
  );
}

/** 2027 status, read-only. Qualifying points are invented for the demo. */
export function StatusCard({ status }: { status?: StatusView }) {
  if (!status) return null;
  const goal = status.next?.at ?? status.tqp;
  const pct = goal > 0 ? Math.min(100, Math.round((status.tqp / goal) * 100)) : 100;
  return (
    <section className="status-card" aria-label="Rapid Rewards status">
      <div className="section-heading">
        <h2>
          <Sparkles size={20} /> Your status: {status.tier}
        </h2>
        <Pill tone="lavender">Read-only</Pill>
      </div>
      <div className="status-bar" aria-label={`${fmt(status.tqp)} qualifying points`}>
        <div style={{ width: `${pct}%` }} />
      </div>
      <p>
        {fmt(status.tqp)} qualifying points
        {status.next
          ? ` · ${fmt(status.next.remaining)} to ${status.next.tier} (${fmt(status.next.at)})`
          : " · highest level"}
      </p>
      <StatusNudgeLine nudge={status.nudge} />
      <ul className="status-benefits">
        {status.benefits.map((b) => (
          <li key={b}>{b}</li>
        ))}
      </ul>
      <div className="milestones">
        {status.milestones.map((m) => (
          <div key={m.at} className={m.reached ? "reached" : ""}>
            <strong>{fmt(m.at)}</strong>
            <span>{m.reward}</span>
          </div>
        ))}
      </div>
      <small>
        {status.companionPass}
        {status.synthetic && " Qualifying points here are sample data for the demo."} PerkFlex rewards
        do not count toward status.
      </small>
    </section>
  );
}

type TripBars = { id: string; earned: number; spent: number; flying: number };

/** Earned versus spent per trip, drawn from the ledger. Plain SVG; a table below carries the same numbers. */
export function EarningsChart({
  ledger,
  earnings,
}: {
  ledger: Ledger[];
  earnings: Earning[];
}) {
  const trips = new Map<string, TripBars>();
  const row = (id: string) => {
    if (!id) return null;
    if (!trips.has(id)) trips.set(id, { id, earned: 0, spent: 0, flying: 0 });
    return trips.get(id)!;
  };
  for (const l of ledger) {
    const t = row(l.bookingId);
    if (!t) continue;
    if (l.kind === "release") t.earned += l.points;
    else if (l.kind === "redemption") t.spent += -l.points;
  }
  for (const e of earnings) {
    const t = row(e.bookingId);
    if (t) t.flying += e.points;
  }
  const data = [...trips.values()];
  if (data.length === 0) return null;
  const max = Math.max(1, ...data.flatMap((d) => [d.earned, d.spent, d.flying]));
  const W = 560,
    H = 190,
    pad = 28,
    group = (W - pad * 2) / data.length,
    bar = Math.min(26, (group - 14) / 3);
  const y = (v: number) => H - pad - (v / max) * (H - pad * 2);
  const series = [
    { key: "earned", label: "PerkFlex earned", cls: "c-earned" },
    { key: "spent", label: "Points used", cls: "c-spent" },
    { key: "flying", label: "Rapid Rewards for flying", cls: "c-flying" },
  ] as const;
  return (
    <section className="chart-card" aria-label="Earned and used per trip">
      <div className="section-heading">
        <h2>
          <Coins size={20} /> Earned and used, trip by trip
        </h2>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Bars of points earned and used for each trip">
        <line x1={pad} y1={H - pad} x2={W - pad} y2={H - pad} className="axis" />
        {data.map((d, i) => {
          const x0 = pad + i * group + (group - bar * 3 - 8) / 2;
          return (
            <g key={d.id}>
              {series.map((s, j) => {
                const v = d[s.key];
                return (
                  <g key={s.key}>
                    <rect
                      x={x0 + j * (bar + 4)}
                      y={y(v)}
                      width={bar}
                      height={Math.max(0, H - pad - y(v))}
                      className={s.cls}
                      rx={3}
                    >
                      <title>{`${d.id} · ${s.label}: ${fmt(v)}`}</title>
                    </rect>
                    {v > 0 && (
                      <text x={x0 + j * (bar + 4) + bar / 2} y={y(v) - 4} textAnchor="middle" className="val">
                        {fmt(v)}
                      </text>
                    )}
                  </g>
                );
              })}
              <text x={pad + i * group + group / 2} y={H - 8} textAnchor="middle" className="lab">
                {d.id}
              </text>
            </g>
          );
        })}
      </svg>
      <div className="chart-legend">
        {series.map((s) => (
          <span key={s.key}>
            <i className={s.cls} /> {s.label}
          </span>
        ))}
      </div>
      <table className="sr-only">
        <caption>Points earned and used per trip</caption>
        <thead>
          <tr>
            <th>Trip</th>
            <th>PerkFlex earned</th>
            <th>Points used</th>
            <th>Rapid Rewards for flying</th>
          </tr>
        </thead>
        <tbody>
          {data.map((d) => (
            <tr key={d.id}>
              <td>{d.id}</td>
              <td>{d.earned}</td>
              <td>{d.spent}</td>
              <td>{d.flying}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

const FALLBACK_PRICES = { boarding: 900, drink: 600, standby: 1800 };

/** What the next flight's add-ons cost in points (prices come from the traveller's perks when there is a trip). */
export function priceList(perks?: Perk[]) {
  const price = (id: keyof typeof FALLBACK_PRICES) =>
    perks?.find((p) => p.id === id)?.redeemPoints || FALLBACK_PRICES[id];
  return [
    { name: "Checked bag", cost: RULES.redeem.bag1 },
    { name: "Preferred seat", cost: RULES.redeem.preferred },
    { name: "Extra Legroom seat", cost: RULES.redeem.extra },
    { name: "Priority boarding", cost: price("boarding") },
    { name: "Premium drink", cost: price("drink") },
    { name: "Same-day standby", cost: price("standby") },
  ];
}

/** The closest thing the traveller cannot yet afford, with the points still needed. Pending points are counted apart. */
export function nearestGoal(
  items: { name: string; cost: number }[],
  spendable: number,
  pending: number,
) {
  const short = items
    .filter((i) => i.cost > spendable)
    .sort((a, b) => a.cost - b.cost)[0];
  if (!short) return null;
  return {
    ...short,
    remaining: short.cost - spendable,
    afterFlying: spendable + pending >= short.cost,
    progress: Math.round((spendable / short.cost) * 100),
  };
}

/** "You are 600 points from a Preferred seat." */
export function GoalsCard({
  wallets,
  perks,
}: {
  wallets: Wallets;
  perks?: Perk[];
}) {
  const spendable = wallets.perkflex.available + wallets.rapidRewards.available;
  const pending = wallets.perkflex.pending + wallets.rapidRewards.pending;
  const goal = nearestGoal(priceList(perks), spendable, pending);
  return (
    <section className="goal-card" aria-label="Your next goal">
      <Target size={20} />
      <div>
        {goal ? (
          <>
            <strong>
              You are {fmt(goal.remaining)} points from {goal.name.toLowerCase()}.
            </strong>
            <div className="status-bar" aria-hidden="true">
              <div style={{ width: `${goal.progress}%` }} />
            </div>
            <small>
              {goal.afterFlying
                ? "Your pending points will cover it once you fly."
                : "Release an unused benefit at check-in to get closer."}
            </small>
          </>
        ) : (
          <strong>Your points cover everything on the list for your next flight.</strong>
        )}
      </div>
    </section>
  );
}

/** What the points held now could buy on the next flight, following the traveller's spend order. */
export function NextFlightPreview({
  wallets,
  rapidFirst,
  perks,
}: {
  wallets: Wallets;
  rapidFirst: boolean;
  perks?: Perk[];
}) {
  const items = priceList(perks);
  const pf = wallets.perkflex.available,
    rr = wallets.rapidRewards.available;
  return (
    <section className="next-flight" aria-label="Next flight preview">
      <div className="section-heading">
        <h2>
          <Plane size={20} /> On your next flight
        </h2>
        <span>
          {fmt(pf)} PerkFlex + {fmt(rr)} Rapid Rewards
          {wallets.perkflex.pending > 0 && ` · ${fmt(wallets.perkflex.pending)} PerkFlex pending`}
        </span>
      </div>
      <ul>
        {items.map((i) => {
          const can = pf + rr >= i.cost;
          const split = paySplit(i.cost, pf, rr, rapidFirst);
          return (
            <li key={i.name} className={can ? "can" : "cannot"}>
              <span>{i.name}</span>
              <small>
                {can
                  ? `${fmt(i.cost)} pts · pays ${payLabel(split)}`
                  : `${fmt(i.cost - pf - rr)} pts short`}
              </small>
              <Pill tone={can ? "mint" : "white"}>
                {can ? "Covered" : "Not yet"}
              </Pill>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** What the next status level would be worth on the next trip. Shown plainly; the strong version appears when it is close. */
export function StatusNudgeLine({ nudge }: { nudge?: StatusView["nudge"] }) {
  if (!nudge) return null;
  return (
    <p className={`status-nudge${nudge.near ? " near" : ""}`} data-testid="status-nudge">
      <strong>
        {fmt(nudge.remaining)} qualifying points to {nudge.tier}.
      </strong>{" "}
      {nudge.tier} would pay {fmt(nudge.bagNext)} points for a bag release (now {fmt(nudge.bagNow)}) and +
      {nudge.flyingBonusPct}% on flying points
      {nudge.flyingNow > 0
        ? `, so your next trip would earn about ${fmt(nudge.flyingNext)} Rapid Rewards points instead of ${fmt(nudge.flyingNow)}`
        : ""}
      .
    </p>
  );
}

const SALE_LABEL: Record<SaleKey, string> = {
  bag: "Checked bag",
  preferred: "Preferred seat",
  extra: "Extra Legroom seat",
  boarding: "Priority boarding",
  drink: "Premium drink",
  standby: "Same-day standby",
  overweight: "Overweight bag allowance",
};

/** What the airline has put on sale for your flight, with the old and new price. Nothing to set up; hidden when nothing is on sale. */
export function SalesCard({ booking, prices }: { booking?: Booking; prices?: Prices }) {
  if (!booking || !prices || booking.status === "flown") return null;
  const rank = { standard: 0, preferred: 1, extra: 2 } as const;
  const perk = (id: Perk["id"]) => booking.perks?.find((p) => p.id === id);
  const rows: { key: SaleKey; price: number; list: number; pct: number }[] = [];
  const bagSlot = booking.bags === 0 ? "bag1" : "bag2";
  const sale = (k: SaleKey) => prices.sales[k] ?? 0;
  if (booking.bags < 3 && sale("bag")) rows.push({ key: "bag", pct: sale("bag"), price: redeemPrice(prices, bagSlot), list: prices.list[bagSlot] ?? redeemPrice(undefined, bagSlot) });
  for (const seat of ["preferred", "extra"] as const) {
    if (rank[seat] > rank[booking.seatClass] && sale(seat))
      rows.push({ key: seat, pct: sale(seat), price: redeemPrice(prices, seat), list: prices.list[seat] ?? redeemPrice(undefined, seat) });
  }
  for (const key of ["boarding", "drink", "standby", "overweight"] as const) {
    const p = perk(key);
    if (sale(key) && p && !p.included && !p.bought && p.redeemPoints > 0) rows.push({ key, pct: sale(key), price: p.redeemPoints, list: p.listPoints ?? p.redeemPoints });
  }
  if (rows.length === 0) return null;
  return (
    <section className="sale-card" aria-label="On sale for your flight">
      <h2>
        <Bell size={18} /> On sale for your flight
      </h2>
      <p>The airline has lowered these prices. They are already applied when you add them below.</p>
      <ul>
        {rows.map((r) => (
          <li key={r.key} data-sale={r.key}>
            <span>
              <strong>{SALE_LABEL[r.key]}</strong>
            </span>
            <span>
              <s>{fmt(r.list)}</s> {fmt(r.price)} pts <Pill tone="mint">{r.pct}% off</Pill>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Travel group: invitations, members with their trips, and giving PerkFlex points inside the group. */
export function GroupCard({
  group,
  perkflexAvailable,
  dispatch,
}: {
  group?: Group;
  perkflexAvailable: number;
  dispatch: (a: Action) => void;
}) {
  const [who, setWho] = useState("");
  const [amount, setAmount] = useState(500);
  if (!group) return null;
  const { limits } = group;
  const others = group.members.filter((m) => !m.you);
  const canGive = !limits.locked && limits.left >= limits.min && perkflexAvailable >= limits.min;
  const amounts = [100, 500, 1000, 2000].filter((a) => a <= limits.max && a <= limits.left && a <= perkflexAvailable);
  const chosen = amounts.includes(amount) ? amount : (amounts[0] ?? limits.min);
  const room = group.members.length + group.pendingInvites.length < limits.groupMax;
  return (
    <section className="group-card" aria-label="Travel group">
      <h2>
        <Plane size={18} /> Travel group
      </h2>
      {group.invites.map((inv) => (
        <div className="group-invite" key={inv.group}>
          <span>
            <strong>{inv.from}</strong> invited you to a travel group.
          </span>
          <button className="button small-button" onClick={() => dispatch({ type: "group-respond", group: inv.group, accept: true })}>
            Join
          </button>
          <button className="button secondary small-button" onClick={() => dispatch({ type: "group-respond", group: inv.group, accept: false })}>
            Decline
          </button>
        </div>
      ))}
      {group.inGroup && (
        <ul className="group-members">
          {group.members.map((m) => (
            <li key={m.id}>
              <span>
                <strong>{m.name}</strong> {m.you && <Pill tone="lavender">You</Pill>} {m.organiser && <Pill tone="white">Organiser</Pill>}{" "}
                <Pill tone="white">{m.tier}</Pill>
                <small>
                  {m.trip
                    ? `${m.trip.route} · ${m.trip.date} · ${m.trip.status.toLowerCase().replace("_", " ")}${m.trip.released ? " · released a benefit" : ""}`
                    : "No trip yet"}
                </small>
              </span>
              {!m.you && (
                <button
                  className="button secondary small-button"
                  disabled={!canGive}
                  onClick={() => dispatch({ type: "gift", to: m.id, points: chosen })}
                >
                  Give {fmt(chosen)}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {group.pendingInvites.length > 0 && <p>Waiting for: {group.pendingInvites.join(", ")}.</p>}
      {group.inGroup && others.length > 0 && (
        <div className="gift-controls">
          <label>
            Points to give
            <select value={chosen} onChange={(e) => setAmount(Number(e.target.value))} disabled={amounts.length === 0}>
              {(amounts.length ? amounts : [limits.min]).map((a) => (
                <option key={a} value={a}>
                  {fmt(a)}
                </option>
              ))}
            </select>
          </label>
          <small>
            {limits.locked
              ? "Points you were given in the last 24 hours cannot be passed on yet."
              : `PerkFlex points only. Up to ${fmt(limits.max)} per gift, ${fmt(limits.left)} left to give in 24 hours.`}
          </small>
        </div>
      )}
      {(!group.inGroup || (group.organiser && room)) && (
        <form
          className="group-invite-form"
          onSubmit={(e) => {
            e.preventDefault();
            if (who.trim()) {
              dispatch({ type: "group-invite", companion: who.trim() });
              setWho("");
            }
          }}
        >
          <label>
            Invite a traveller
            <input value={who} onChange={(e) => setWho(e.target.value)} placeholder="Sign-in name or Rapid Rewards number" />
          </label>
          <button className="button secondary small-button" type="submit" disabled={!who.trim()}>
            Send invitation
          </button>
        </form>
      )}
      {group.gifts.length > 0 && (
        <ul className="gift-list" aria-label="Recent gifts">
          {group.gifts.map((g) => (
            <li key={g.at + g.other}>
              {g.direction === "out" ? `You gave ${g.other}` : `${g.other} gave you`} {fmt(g.points)} points
            </li>
          ))}
        </ul>
      )}
      {group.inGroup && (
        <button className="text-button" onClick={() => dispatch({ type: "group-leave" })}>
          {group.organiser ? "End this group" : "Leave this group"}
        </button>
      )}
    </section>
  );
}

/**
 * Email notifications. The address is only used after its owner opens the link in the confirmation email.
 * Hidden when this deployment has no email service (the server says so with `available: false`).
 */
export function EmailCard() {
  const [prefs, setPrefs] = useState<EmailPrefs | null>(null);
  const [email, setEmail] = useState("");
  const [enabled, setEnabled] = useState(false);
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    api
      .emailPrefs(controller.signal)
      .then((p) => {
        setPrefs(p);
        setEmail(p.email);
        setEnabled(p.enabled);
      })
      .catch(() => {});
    return () => controller.abort();
  }, []);

  if (!prefs || !prefs.available) return null;

  async function save() {
    setSaving(true);
    setMessage("");
    try {
      const next = await api.setEmailPrefs({ email: email.trim(), enabled });
      const changed = next.email !== prefs?.email;
      setPrefs(next);
      setEmail(next.email);
      setEnabled(next.enabled);
      setMessage(
        !next.email
          ? "Email removed."
          : changed && !next.verified
            ? "Saved. We sent a link to confirm this address."
            : "Saved.",
      );
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="email-card" aria-label="Email notifications">
      <div className="section-heading">
        <h2>
          <Mail size={20} /> Email notifications
        </h2>
        {prefs.email && (prefs.verified ? <Pill tone="mint">Confirmed</Pill> : <Pill tone="lavender">Waiting for confirmation</Pill>)}
      </div>
      <p>Get an email when you book, release a benefit, buy with points, or finish a trip. Nothing is sent until you confirm the address.</p>
      <div className="email-form">
        <label htmlFor="email-address">Email address</label>
        <input id="email-address" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" />
        <label className="email-toggle">
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /> Send me emails
        </label>
        <button className="button primary" onClick={() => void save()} disabled={saving}>
          Save
        </button>
      </div>
      {message && (
        <p role="status" className="email-message">
          {message}
        </p>
      )}
    </section>
  );
}
