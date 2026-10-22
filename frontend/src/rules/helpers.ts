/** How the screens address a traveller: their full name. */
export const greetingName = (p: { name: string }) => p.name;

import { RULES } from "./data.ts";
import type { Prices, Rewards, SeatClass } from "./types.ts";

/** What a release pays: the server's figure (status bonus included), or the base reward when it sends none. */
export function releaseReward(rewards: Rewards | undefined, kind: "bag" | Exclude<SeatClass, "standard">): number {
  return rewards?.[kind] ?? RULES.release[kind];
}

/** The points price on this flight (after any sale), or the list price when the server sends none. */
export function redeemPrice(prices: Prices | undefined, key: "bag1" | "bag2" | "preferred" | "extra"): number {
  return prices?.[key] ?? RULES.redeem[key];
}

/** What a purchase takes from each wallet: PerkFlex first, then Rapid Rewards (the same rule the database applies). */
export function paySplit(
  cost: number,
  perkflexAvailable: number,
  rapidAvailable = 0,
  rapidFirst = false,
) {
  if (rapidFirst) {
    const rapid = Math.min(cost, Math.max(0, rapidAvailable));
    return { perkflex: cost - rapid, rapid };
  }
  const perkflex = Math.min(cost, Math.max(0, perkflexAvailable));
  return { perkflex, rapid: cost - perkflex };
}

/** "300 PerkFlex + 600 Rapid Rewards", "600 PerkFlex" or "600 Rapid Rewards". */
export function payLabel(split: { perkflex: number; rapid: number }): string {
  const parts = [
    split.perkflex ? `${split.perkflex.toLocaleString("en-US")} PerkFlex` : "",
    split.rapid ? `${split.rapid.toLocaleString("en-US")} Rapid Rewards` : "",
  ].filter(Boolean);
  return parts.join(" + ") || "0";
}
