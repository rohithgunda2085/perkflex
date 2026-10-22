import type { ServerState, Store } from "./types.ts";

/** Keeps the shape the screens were written against, filled with the signed-in traveller only. */
export function toStore(s: ServerState): Store {
  const id = s.profile.id;
  return {
    activeProfile: id,
    balances: { [id]: s.balance },
    bookings: { [id]: s.booking ?? undefined },
    inventories: s.inventory
      ? {
          [s.inventory.flightId]: {
            seats: s.inventory.seats,
            budget: s.inventory.budget,
            bagGrants: s.inventory.bagGrants,
          },
        }
      : {},
    ledger: s.ledger.map((l) => ({ ...l, profileId: id })),
    // Without wallet data, everything counts as Rapid Rewards (the older server answer).
    wallets: s.wallets ?? {
      perkflex: { available: 0, pending: s.pending },
      rapidRewards: { available: s.balance, pending: 0 },
    },
    earnings: s.earnings ?? [],
    payRapidFirst: s.payRapidFirst ?? false,
    rewards: s.rewards,
    status: s.status,
    notifications: s.notifications ?? [],
    prices: s.prices,
    group: s.group,
    notice: s.notice,
    error: s.error,
  };
}

/** Points waiting to post after the trip (release rewards). */
export function pendingPoints(store: Store, profileId: string): number {
  return store.ledger
    .filter((l) => l.profileId === profileId && l.status === "pending")
    .reduce((n, l) => n + l.points, 0);
}
