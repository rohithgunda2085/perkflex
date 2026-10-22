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
