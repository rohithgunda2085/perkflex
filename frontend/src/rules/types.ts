// Shapes of the data the API returns. The frontend only displays these: it does not compute them.

export type FareId = "basic" | "choice" | "preferred" | "extra";
export type SeatClass = "standard" | "preferred" | "extra";
export type Tier = "Member" | "Silver" | "Gold" | "Platinum";
export type Card = "None" | "Plus" | "Premier" | "Priority";

export type Fare = {
  id: FareId;
  name: string;
  price: number;
  bags: number;
  seat: SeatClass;
  refundable: boolean;
  multiplier: number;
  description: string;
};

export type Needs = {
  bags: number;
  seat: "any" | "front" | "extra";
  refund: boolean;
  flexible: boolean;
  seatNow: boolean;
  early: boolean;
  budget: number;
};

export const defaultNeeds: Needs = {
  bags: 0,
  seat: "any",
  refund: false,
  flexible: false,
  seatNow: false,
  early: false,
  budget: 450,
};

export type Profile = {
  id: string;
  name: string;
  initials: string;
  tier: Tier;
  card: Card;
  color: string;
  description: string;
  points: number;
  needs: Needs;
  hasTrip: boolean;
};

export type Entitlements = {
  bags: number;
  bagSource: string;
  seat: SeatClass;
  seatSource: string;
  chooseNow: boolean;
  refundable: boolean;
  flexible: boolean;
  early: boolean;
};

export type Quote = {
  fare: FareId;
  base: number;
  tax: number;
  total: number;
  addons: { label: string; price: number }[];
  bags: number;
  seat: SeatClass;
  seatSource: string;
  bagSource: string;
  issues: string[];
  points: number;
};

export type Booking = {
  id: string; // the confirmation code
  profileId: string;
  fare: FareId;
  flightId: string;
  from: string;
  to: string;
  date: string;
  seat: string;
  seatClass: SeatClass;
  seatSource: string;
  bags: number;
  bagSource: string;
  needs: Needs;
  actualBags: number;
  total: number;
  status: "booked" | "checked-in" | "flown";
  released: boolean;
  releasedSeat: boolean;
  redeemedSeat: boolean;
  redeemedBags: number;
  clockAdvanced: boolean;
  /** What the traveller's benefits cover once check-in is open. */
  checkinEntitlements: Entitlements;
};

export type Ledger = {
  id: string;
  profileId: string;
  bookingId: string;
  kind: "release" | "redemption";
  label: string;
  points: number;
  status: "pending" | "posted";
  createdAt: string;
};

export type Inventory = {
  seats: Record<SeatClass, string[]>;
  budget: number;
  bagGrants: number;
};

/** GET /api/state and the response of every action. */
export type ServerState = {
  profile: Profile;
  balance: number;
  pending: number;
  booking: Booking | null;
  inventory: (Inventory & { flightId: string }) | null;
  ledger: Omit<Ledger, "profileId">[];
  /** Everyone in the demo switcher (empty outside demo mode). */
  travellers: Profile[];
  demo: boolean;
  notice: string;
  error: boolean;
};

/**
 * The screens were written against a store keyed by traveller. This keeps that shape, filled with the signed-in
 * traveller only, so the components did not need to change.
 */
export type Store = {
  activeProfile: string;
  balances: Record<string, number>;
  bookings: Record<string, Booking | undefined>;
  inventories: Record<string, Inventory>;
  ledger: Ledger[];
  notice: string;
  error: boolean;
};

/** What the screens ask for. `profileId` is accepted for convenience and never sent: the server uses the session. */
export type Action =
  | { type: "profile"; id: string }
  | {
      type: "book";
      profileId?: string;
      fare: FareId;
      flightId: string;
      from: string;
      to: string;
      date: string;
      needs: Needs;
    }
  | { type: "open-checkin"; profileId?: string }
  | { type: "bags"; profileId?: string; count: number }
  | { type: "release"; profileId?: string; benefit: "bag" | "seat" }
  | { type: "redeem"; profileId?: string; benefit: "bag" | SeatClass }
  | { type: "checkin"; profileId?: string }
  | { type: "complete"; profileId?: string }
  | { type: "clear-notice" };

export type QuotesResponse = {
  needs: Needs;
  quotes: Quote[];
  best: FareId | null;
  entitlements: Record<FareId, Entitlements>;
  flight: { id: string; date: string; from: string; to: string };
};

export type BestFareRequest = {
  message?: string;
  needs?: Partial<Needs>;
  flightId: string;
  from: string;
  to: string;
  date?: string;
};

export type BestFareResponse = {
  source: "ai" | "fallback";
  understood: Needs;
  recommendation: {
    fare: FareId | null;
    total: number | null;
    reasons: string[];
  };
  alternatives: { fare: FareId; total: number; tradeoff: string }[];
  explanation: string;
  quotes: Quote[];
};
