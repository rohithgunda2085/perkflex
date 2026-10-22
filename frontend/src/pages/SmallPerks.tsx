import { ChevronRight, GlassWater, Luggage, PlaneTakeoff, RefreshCw, Ticket, UtensilsCrossed, Zap } from "lucide-react";
import type { Perk, PerkId } from "../rules/types.ts";
import { fmt } from "../rules/data.ts";
import { payLabel, paySplit } from "../rules/helpers.ts";
import { Pill } from "../components/components.tsx";
import type { Confirmation } from "./Checkin.tsx";

const ICON = { boarding: PlaneTakeoff, drink: GlassWater, lane: Zap, standby: RefreshCw, overweight: Luggage, meal: UtensilsCrossed } as const;
const BLURB: Record<PerkId, string> = {
  boarding: "Board earlier and settle in before the crowd.",
  drink: "A premium drink on board.",
  lane: "Shorter queues at the airport.",
  standby: "Move to an earlier or later flight on the same day, when seats are open.",
  overweight: "Check a bag between 51 and 70 lb without the overweight fee.",
  meal: "A meal voucher to use at participating airport vendors. A PerkFlex concept add-on.",
};

type Props = {
  perks: Perk[];
  profileId: string;
  available: number;
  /** PerkFlex rewards available: a buy takes these first, then Rapid Rewards. */
  perkflexAvailable: number;
  rapidAvailable?: number;
  rapidFirst?: boolean;
  /** What is left of this flight's reward budget. */
  budget: number;
  /** The traveller's status bonus on releases (percent), already included in each perk's points. */
  bonusPct?: number;
  wantsEarlyBoarding: boolean;
  confirm: (c: Confirmation) => void;
};

/**
 * Small perks. Releasing one does not use the flight's one rewarded bag-or-seat release.
 * Whether the traveller already has a perk comes from the server (their fare and status), not from this page.
 */
export function SmallPerks({
  perks,
  profileId,
  available,
  perkflexAvailable,
  rapidAvailable = 0,
  rapidFirst = false,
  budget,
  bonusPct = 0,
  wantsEarlyBoarding,
  confirm,
}: Props) {
  const rows = perks.filter(
    (p) =>
      (p.included && !p.released && p.releasePoints > 0) ||
      (!p.included && !p.bought && p.redeemPoints > 0) ||
      p.released ||
      p.bought,
  );
  if (rows.length === 0) return null;

  function release(p: Perk) {
    if (p.id === "overweight" || p.id === "meal") return; // for sale only
    confirm({
      title: `Not using ${p.name.toLowerCase()}?`,
      description:
        `Give it up on this flight and earn points. This is separate from your one bag-or-seat reward, and the points stay pending until you fly.${bonusPct ? ` Includes your ${bonusPct}% status bonus.` : ""}`,
      before: `${p.name} included`,
      after: `${p.name} released`,
      points: p.releasePoints,
      pending: true,
      action: { type: "release", profileId, benefit: p.id },
      label: `Release ${p.name.toLowerCase()}`,
    });
  }
  function redeem(p: Perk) {
    if (p.id === "lane") return;
    confirm({
      title: `Add ${p.name.toLowerCase()}.`,
      description:
        `Pays ${payLabel(paySplit(p.redeemPoints, perkflexAvailable, rapidAvailable, rapidFirst))} points: ${rapidFirst ? "Rapid Rewards first, then PerkFlex" : "PerkFlex rewards first, then Rapid Rewards"}. Pending rewards cannot be spent before they post.`,
      before: `No ${p.name.toLowerCase()}`,
      after: `${p.name} added`,
      points: -p.redeemPoints,
      pending: false,
      action: { type: "redeem", profileId, benefit: p.id },
      label: "Confirm points redemption",
    });
  }

  return (
    <section className="offers-section small-perks" aria-label="Small perks">
      <div className="offers-heading">
        <h3>
          <Ticket size={20} /> Small perks
        </h3>
        <Pill tone="mint">Separate from your one reward</Pill>
      </div>
      <div className="redemption-grid">
        {rows.map((p) => {
          const Icon = ICON[p.id];
          const done = p.released || p.bought;
          const canRelease = p.included && !p.released && budget >= p.releasePoints && p.capRoom !== false;
          const keep = p.id === "boarding" && wantsEarlyBoarding;
          return (
            <article className="redeem-card" key={p.id} data-perk={p.id}>
              <Icon size={24} />
              <h4>{p.name}</h4>
              <p>{BLURB[p.id]}</p>
              {done ? (
                <strong>
                  {p.released ? "Released" : "Added"} <small>this flight</small>
                </strong>
              ) : p.included ? (
                <>
                  <strong>
                    +{fmt(p.releasePoints)} <small>pts, pending</small>
                  </strong>
                  <button
                    className="button secondary small-button"
                    disabled={!canRelease}
                    onClick={() => release(p)}
                  >
                    {keep ? "Keep it (you asked for it)" : canRelease ? "Release for points" : p.capRoom === false ? "Small-perk limit reached" : "Rewards fully claimed"}
                    {canRelease && !keep && <ChevronRight size={16} />}
                  </button>
                </>
              ) : (
                <>
                  <strong>
                    {p.listPoints && p.listPoints > p.redeemPoints && <s>{fmt(p.listPoints)}</s>}{" "}
                    {fmt(p.redeemPoints)} <small>pts</small>
                  </strong>
                  <small className="pay-split">
                    Pays {payLabel(paySplit(p.redeemPoints, perkflexAvailable, rapidAvailable, rapidFirst))}
                  </small>
                  <button
                    className="button secondary small-button"
                    disabled={available < p.redeemPoints}
                    onClick={() => redeem(p)}
                  >
                    {available < p.redeemPoints
                      ? `Need ${fmt(p.redeemPoints - available)} more pts`
                      : "Add with points"}
                    {available >= p.redeemPoints && <ChevronRight size={16} />}
                  </button>
                </>
              )}
            </article>
          );
        })}
      </div>
      <p className="offer-note">
        Small perks earn at most 300 points per flight in total.
      </p>
    </section>
  );
}
