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
  /** How `points` was worked out: base fare x rate, plus the status bonus (percent). */
  rate?: number;
  statusBonus?: number;
};

/** Priority boarding, a premium drink or priority lane. They sit beside the one rewarded bag-or-seat release. */
export type PerkId = "boarding" | "drink" | "lane" | "standby" | "overweight" | "meal";
export type Perk = {
  id: PerkId;
  name: string;
  /** The traveller's fare or status already includes it (decided by the server). */
  included: boolean;
  source: "fare" | "tier" | "";
  released: boolean;
  bought: boolean;
  releasePoints: number;
  /** 0 means it cannot be bought. */
  redeemPoints: number;
  /** The normal price, before any sale on this flight. */
  listPoints?: number;
  /** false once the 300-point small-perk cap has no room for this release. */
  capRoom?: boolean;
};

/** A release the traveller can still take back (5 real minutes, check-in open). */
export type Undoable = {
  benefit: "bag" | "seat" | Exclude<PerkId, "overweight" | "meal">;
  label: string;
  points: number;
  secondsLeft: number;
};

/** What happened to the seat the traveller released. */
export type SeatReuse = { seat: string; reused: boolean; freedAt: string | null; reusedAt: string | null };
export type Reuse = {
  seat: SeatReuse | null;
  /** Other travellers who added a bag on this flight after the traveller released one. */
  bag: { othersAdded: number } | null;
};

/** An in-app message worked out from the traveller's data (never stored). */
export type Notification = {
  id: string;
  kind: "expiry" | "reuse" | "posted" | "price-drop" | "group" | "gift";
  text: string;
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
  perks: Perk[];
  undoable?: Undoable[];
  reuse?: Reuse | null;
  /** What the traveller's benefits cover once check-in is open. */
  checkinEntitlements: Entitlements;
};

/** The two wallets, never mixed. A buy uses PerkFlex first, then Rapid Rewards. */
export type Wallets = {
  perkflex: {
    available: number;
    pending: number;
    /** Points that expire within 60 days, and every unspent lot. */
    expiring?: {
      soonPoints: number;
      soonDate: string | null;
      soonDays: number | null;
      lots: { points: number; expiresOn: string }[];
    };
  };
  rapidRewards: { available: number; pending: number };
};

/** Rapid Rewards points for flying (pending until the trip is completed). */
export type Earning = {
  id: string;
  bookingId: string;
  label: string;
  points: number;
  status: "pending" | "posted";
  createdAt: string;
};

export type Ledger = {
  id: string;
  profileId: string;
  bookingId: string;
  kind: "release" | "redemption" | "expiry" | "bonus" | "gift";
  /** Which wallet this PerkFlex-ledger line touched. */
  wallet?: "perkflex" | "rapid" | "both";
  /** For a purchase: what was taken from each wallet. */
  paidPerkflex?: number;
  paidRapid?: number;
  label: string;
  /** What the benefit costs in cash (list price), for the savings card. */
  cashValue?: number;
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
  wallets?: Wallets;
  earnings?: Earning[];
  /** false (default) = PerkFlex is spent first, then Rapid Rewards. */
  payRapidFirst?: boolean;
  rewards?: Rewards;
  status?: StatusView;
  notifications?: Notification[];
  prices?: Prices;
  group?: Group;
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
  wallets: Wallets;
  earnings: Earning[];
  payRapidFirst: boolean;
  rewards?: Rewards;
  status?: StatusView;
  notifications: Notification[];
  prices?: Prices;
  group?: Group;
  notice: string;
  error: boolean;
};

/** What a release pays this traveller: the base reward plus their status bonus (percent). */
export type Rewards = {
  bonusPct: number;
  bag: number;
  preferred: number;
  extra: number;
  /** FLAT = the fixed numbers; VALUE = a percent of the benefit's cash price. */
  mode?: "FLAT" | "VALUE";
  /** PerkFlex points added when a trip with a posted release is completed. */
  completionBonus?: number;
};

/** Points prices on this traveller's flight after any sale. `sales` maps a benefit to its percent off. */
export type SaleKey = "bag" | "preferred" | "extra" | "boarding" | "drink" | "standby" | "overweight";
export type Prices = {
  bag1: number;
  bag2: number;
  preferred: number;
  extra: number;
  list: { bag1: number; bag2: number; preferred: number; extra: number };
  sales: Partial<Record<SaleKey, number>>;
};

export type GroupMember = {
  id: string;
  name: string;
  tier: string;
  you: boolean;
  organiser: boolean;
  trip: { route: string; date: string; status: string; released: boolean } | null;
};
export type Group = {
  inGroup: boolean;
  organiser: boolean;
  members: GroupMember[];
  pendingInvites: string[];
  invites: { group: string; from: string }[];
  gifts: { direction: "in" | "out"; other: string; points: number; at: string }[];
  limits: { min: number; max: number; daily: number; givenToday: number; left: number; locked: boolean; groupMax: number };
};

/** Read-only 2027 status progress. Qualifying points are invented for the demo. */
export type StatusView = {
  tier: string;
  tqp: number;
  benefits: string[];
  next: { tier: string; at: number; remaining: number } | null;
  milestones: { at: number; reward: string; reached: boolean }[];
  companionPass: string;
  synthetic: boolean;
  /** What the next level would be worth on this traveller's next trip. */
  nudge?: StatusNudge | null;
};
export type StatusNudge = {
  tier: string;
  remaining: number;
  near: boolean;
  releaseBonusPct: number;
  flyingBonusPct: number;
  bagNow: number;
  bagNext: number;
  flyingNow: number;
  flyingNext: number;
};

/** What the screens ask for. `profileId` is accepted for convenience and never sent: the server uses the session. */
export type Action =
  | { type: "profile"; id: string }
  | { type: "demo-reset" }
  | { type: "demo-simulate" }
  | { type: "demo-sale"; benefit: SaleKey }
  | { type: "group-invite"; companion: string }
  | { type: "group-respond"; group: string; accept: boolean }
  | { type: "group-leave" }
  | { type: "gift"; to: string; points: number }
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
  | { type: "release"; profileId?: string; benefit: "bag" | "seat" | Exclude<PerkId, "overweight" | "meal"> }
  | { type: "undo"; profileId?: string; benefit: "bag" | "seat" | Exclude<PerkId, "overweight" | "meal"> }
  | { type: "payment-order"; profileId?: string; rapidFirst: boolean }
  | { type: "redeem"; profileId?: string; benefit: "bag" | SeatClass | Exclude<PerkId, "lane"> }
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

export type OfferId =
  | "RELEASE_BAG"
  | "RELEASE_SEAT"
  | "REDEEM_BAG"
  | "REDEEM_PREFERRED"
  | "REDEEM_EXTRA"
  | "RELEASE_BOARDING"
  | "RELEASE_DRINK"
  | "RELEASE_LANE"
  | "REDEEM_BOARDING"
  | "REDEEM_DRINK"
  | "RELEASE_STANDBY"
  | "REDEEM_STANDBY"
  | "REDEEM_OVERWEIGHT";

export type PerkOffer = {
  id: OfferId;
  kind: "release" | "redeem";
  label: string;
  /** Points earned (release, pending until you fly) or paid (redeem). 0 when already included. */
  points: number;
  included: boolean;
  affordable: boolean;
  shortfall: number;
  needed: boolean;
};

export type PerkAdviceResponse = {
  source: "ai" | "fallback";
  summary: string;
  picks: { offerId: OfferId; why: string }[];
  /** Computed by the rules. The numbers shown come from here, never from the advisor's text. */
  offers: PerkOffer[];
};

export type PerkNudge = {
  offerId: OfferId;
  kind: "release" | "redeem";
  text: string;
  points: number;
};

/** GET and POST /api/me/email: the traveller's email notification settings. */
export type EmailPrefs = {
  email: string;
  verified: boolean;
  enabled: boolean;
  /** false when this deployment has no email service set up. */
  available: boolean;
};

/** GET /api/admin/overview (airline accounts only). */
export type AdminFlight = {
  flightId: string;
  date: string;
  from: string;
  to: string;
  status: "scheduled" | "completed" | "cancelled";
  bookings: number;
  checkedIn: number;
  budget: number;
  reserved: number;
  settled: number;
  remaining: number;
  releases: { bag: number; seat: number; perk: number };
  pointsEarned: number;
  redemptions: { bag: number; seat: number; perk: number };
  pointsSpent: number;
  seatsFreed?: number;
  seatsReused?: number;
  seatResale?: number;
  pool?: BenefitsPool;
  benefits?: FlightBenefit[];
};
/** One benefit on one flight: how many were released and how many bought with points. */
export type FlightBenefit = {
  name: string;
  kind: "bag" | "seat" | "perk";
  released: number;
  bought: number;
  pointsEarned: number;
  pointsSpent: number;
};
/** The flight's benefits inventory: seats by class and bag grants (the reward budget is on the flight itself). */
export type PoolSeats = { total: number; free: number; givenBack: number; reused: number };
export type BenefitsPool = {
  seats: { standard: PoolSeats; preferred: PoolSeats; extra: PoolSeats };
  bagGrants: { total: number; remaining: number };
};
export type AdminFlag = {
  kind: "undo" | "release-and-buy";
  booking: string;
  flightId: string;
  date: string;
  text: string;
};
export type AdminModel = {
  with: { rewardCost: number; seatResale: number; net: number };
  without: { rewardCost: number; seatResale: number; net: number };
  assumptions: string[];
};
export type AdminOverview = {
  /** A simple with/without estimate. Its assumptions are listed in `assumptions`. */
  model?: AdminModel;
  totals: {
    flights: number;
    budget: number;
    owed: number;
    paid: number;
    estimatedCost: number;
    releases: number;
    redemptions: number;
    pointsSpent: number;
    seatsFreed?: number;
    seatsReused?: number;
  };
  flights: AdminFlight[];
  /** Trips worth a second look: prompts for a person, not penalties. */
  flags?: AdminFlag[];
};

/** The airline's settings: reward policy, points sales and the change log. */
export type AdminControls = {
  policy: { mode: "FLAT" | "VALUE"; valuePercent: number; centsPerPoint: number; completionBonus: number };
  flights: { id: string; label: string }[];
  benefits: { key: string; name: string }[];
  sales: { flightId: string; benefit: string; discountPct: number; setBy: string; at: string }[];
  audit: { at: string; by: string; setting: string; from: string | null; to: string | null }[];
};
