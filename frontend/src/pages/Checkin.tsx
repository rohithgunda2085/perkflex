import {
  ArrowRight,
  Armchair,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleHelp,
  Clock3,
  Coins,
  Gift,
  Luggage,
  Plane,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Wallet,
} from "lucide-react";
import type { Action, Profile, SeatClass, Store } from "../rules/types.ts";
import { pendingPoints } from "../rules/store.ts";
import {
  SEAT_NAMES,
  SEAT_ORDER,
  fareById,
  fmt,
  money,
} from "../rules/data.ts";
import { greetingName, payLabel, paySplit, redeemPrice, releaseReward } from "../rules/helpers.ts";
import { AdvisorPanel } from "./AdvisorPanel.tsx";
import { SmallPerks } from "./SmallPerks.tsx";
import {
  EarningsChart,
  ExpiryNotice,
  GoalsCard,
  GroupCard,
  SalesCard,
  Notifications,
  NextFlightPreview,
  PayOrderToggle,
  ReuseCard,
  StatusCard,
  EmailCard,
  UndoBar,
} from "./Extras.tsx";
import {
  BuyRapidRewards,
  DateLabel,
  EmptyState,
  FlightRoute,
  PerkMark,
  Pill,
} from "../components/components.tsx";

export type Confirmation = {
  title: string;
  description: string;
  before: string;
  after: string;
  points: number;
  pending: boolean;
  action: Action;
  label: string;
};
type Props = {
  state: Store;
  profile: Profile;
  dispatch: (a: Action) => void;
  confirm: (c: Confirmation) => void;
  onWallet: () => void;
};
export function CheckinPage({
  state,
  profile,
  dispatch,
  confirm,
  onWallet,
}: Props) {
  // App only renders this page when the traveller has a booking (see NoTripPage).
  const b = state.bookings[profile.id]!,
    inv = state.inventories[b.flightId],
    fare = fareById(b.fare),
    available = state.balances[profile.id],
    pfAvailable = state.wallets.perkflex.available,
    pending = pendingPoints(state, profile.id),
    isOpen = b.status === "booked";
  const bonusPct = state.rewards?.bonusPct ?? 0;
  const completion = state.rewards?.completionBonus ?? 0;
  const award = state.rewards?.flightAward ?? 0;
  const bonusNote =
    (bonusPct ? ` Includes your ${bonusPct}% ${profile.tier} bonus.` : "") +
    (completion ? ` Complete your trip and get ${completion} bonus points.` : "") +
    (award
      ? ` Every completed flight also earns ${award} PerkFlex points${state.rewards?.awardNote ? ` (${state.rewards.awardNote})` : ""}.`
      : "");
  const bagReward = releaseReward(state.rewards, "bag");
  const seatReward =
    b.seatClass === "standard" ? 0 : releaseReward(state.rewards, b.seatClass);
  const canBag =
    b.bags > b.actualBags &&
    b.bags - b.redeemedBags > 0 &&
    !b.released &&
    inv.budget >= bagReward;
  const canSeat =
    b.seatClass !== "standard" &&
    !b.redeemedSeat &&
    !b.released &&
    inv.seats.standard.length > 0 &&
    inv.budget >= seatReward;
  const bagCost = redeemPrice(state.prices, b.bags === 0 ? "bag1" : "bag2");
  const e = b.checkinEntitlements;
  const rrAvailable = state.wallets.rapidRewards.available;
  const pays = (cost: number) =>
    payLabel(paySplit(cost, pfAvailable, rrAvailable, state.payRapidFirst));
  function release(benefit: "bag" | "seat") {
    confirm({
      title:
        benefit === "bag"
          ? "Travel lighter. Get a little back."
          : "A different seat. A little reward.",
      description: (
        benefit === "bag"
          ? "Give up one included standard-size bag allowance on this flight. Your ticket and other benefits stay yours."
          : "Confirm your move to the available Standard seat below. The original seat returns to the airline’s inventory.") + bonusNote,
      before:
        benefit === "bag"
          ? `${b.bags} checked bags included`
          : `${SEAT_NAMES[b.seatClass]} · Seat ${b.seat}`,
      after:
        benefit === "bag"
          ? `${b.bags - 1} checked bag${b.bags - 1 === 1 ? "" : "s"} included`
          : `Standard · Seat ${inv.seats.standard[0]}`,
      points: benefit === "bag" ? bagReward : seatReward,
      pending: true,
      action: { type: "release", profileId: profile.id, benefit },
      label: benefit === "bag" ? "Release bag allowance" : "Confirm seat swap",
    });
  }
  function redeem(benefit: "bag" | SeatClass) {
    const free =
      benefit !== "bag" &&
      SEAT_ORDER.indexOf(e.seat) >= SEAT_ORDER.indexOf(benefit);
    const cost =
      benefit === "bag"
        ? bagCost
        : benefit === "extra"
          ? redeemPrice(state.prices, "extra")
          : redeemPrice(state.prices, "preferred");
    confirm({
      title:
        benefit === "bag"
          ? "Make room for one more bag."
          : "A little more comfort awaits.",
      description: free
        ? "Your member benefits already cover this seat. No points will be charged."
        : `Pays ${pays(cost)} points: ${state.payRapidFirst ? "Rapid Rewards first, then PerkFlex" : "PerkFlex rewards first, then Rapid Rewards"}. Pending rewards cannot be spent before they post.`,
      before:
        benefit === "bag"
          ? `${b.bags} checked bags included`
          : `${SEAT_NAMES[b.seatClass]} · Seat ${b.seat}`,
      after:
        benefit === "bag"
          ? `${b.bags + 1} checked bags included`
          : `${SEAT_NAMES[benefit]} · Seat ${inv.seats[benefit][0]}`,
      points: free ? 0 : -cost,
      pending: false,
      action: { type: "redeem", profileId: profile.id, benefit },
      label: free ? "Use my included benefit" : "Confirm points redemption",
    });
  }
  return (
    <main className="container checkin-page page-enter">
      <div className="checkin-progress" aria-label="Check-in progress">
        <span className="complete">
          <Check size={13} />
          <strong>Flight booked</strong>
        </span>
        <span className={isOpen ? "current" : "complete"}>
          {isOpen ? <span>2</span> : <Check size={13} />}
          <strong>Review your benefits</strong>
        </span>
        <span className={!isOpen ? "current" : ""}>
          {!isOpen ? <Check size={13} /> : <span>3</span>}
          <strong>Boarding pass</strong>
        </span>
      </div>
      <div className="page-title-row">
        <div>
          <div className="eyebrow">CHECK IN FOR YOUR NEXT FLIGHT</div>
          <h1>
            {isOpen
              ? `Let’s get you checked in, ${greetingName(profile)}.`
              : b.status === "flown"
                ? "A great trip. A little more rewarding."
                : "You’re ready for takeoff."}
          </h1>
          <p>
            {isOpen
              ? "Review your trip, flex your perks, and check in. It’s that simple."
              : b.status === "flown"
                ? "Your trip is complete. Your earned PerkFlex rewards have posted."
                : "Your benefits are confirmed and your boarding pass is ready."}
          </p>
        </div>
        <Pill tone={isOpen ? "mint" : "blue"}>
          {isOpen ? <Clock3 size={14} /> : <CheckCircle2 size={14} />}{" "}
          {isOpen
            ? "Check-in is open"
            : b.status === "flown"
              ? "Trip completed"
              : "Checked in"}
        </Pill>
      </div>
      <div className="checkin-layout">
        <div className="checkin-main">
          <section className="trip-card">
            <div className="trip-card-top">
              <span>
                <CalendarIcon />
                <DateLabel date={b.date} />
              </span>
              <span>
                Confirmation <strong>{b.id}</strong>
              </span>
            </div>
            <FlightRoute booking={b} />
            <div className="trip-card-footer">
              <span className={`avatar avatar-small ${profile.color}`}>
                {profile.initials}
              </span>
              <strong>{profile.name}</strong>
              <span>{fare.name}</span>
              <Pill tone="blue">
                {profile.tier === "Member" ? "Rapid Rewards" : profile.tier}
              </Pill>
            </div>
          </section>
          {isOpen ? (
            <>
              <section className="perk-review" id="perkflex-benefits">
                <div className="section-heading">
                  <PerkMark />
                  <div>
                    <h2>Your trip. Your perks. Your call.</h2>
                    <p>Keep what you love. Flex what you don’t need.</p>
                  </div>
                </div>
                <div className="actual-bags">
                  <span>
                    <Luggage size={20} />
                    <strong>How many bags are you actually checking?</strong>
                  </span>
                  <div className="segmented" aria-label="Actual checked bags">
                    {[0, 1, 2, 3].map((n) => (
                      <button
                        key={n}
                        className={b.actualBags === n ? "active" : ""}
                        aria-pressed={b.actualBags === n}
                        onClick={() =>
                          dispatch({
                            type: "bags",
                            profileId: profile.id,
                            count: n,
                          })
                        }
                      >
                        {n}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="owned-perks">
                  <div>
                    <span className="soft-icon">
                      <Armchair size={21} />
                    </span>
                    <span>
                      <strong>{SEAT_NAMES[b.seatClass]}</strong>
                      <small>
                        Seat {b.seat} · {b.seatSource}
                      </small>
                    </span>
                    <CheckCircle2 size={17} />
                  </div>
                  <div>
                    <span className="soft-icon">
                      <Luggage size={21} />
                    </span>
                    <span>
                      <strong>
                        {b.bags} checked bag{b.bags === 1 ? "" : "s"} included
                      </strong>
                      <small>
                        {b.released
                          ? "Adjusted for your accepted offer"
                          : b.redeemedBags > 0
                            ? "Includes your PerkFlex bag grant"
                            : b.bagSource}
                      </small>
                    </span>
                    <CheckCircle2 size={17} />
                  </div>
                  <div>
                    <span className="soft-icon">
                      <ShieldCheck size={21} />
                    </span>
                    <span>
                      <strong>
                        {fare.refundable
                          ? "Refundable fare"
                          : "Nonrefundable fare"}
                      </strong>
                      <small>Ticket conditions remain with your fare</small>
                    </span>
                    <span className="protected-label">Protected</span>
                  </div>
                </div>
                {b.actualBags > b.bags && (
                  <div className="inline-warning">
                    <Luggage size={18} />
                    <span>
                      You’re bringing {b.actualBags - b.bags} more bag
                      {b.actualBags - b.bags === 1 ? "" : "s"} than your
                      allowance. Add a bag below or update your bag count.
                    </span>
                  </div>
                )}
              </section>
              <AdvisorPanel
                refreshKey={`${available}:${pending}:${b.bags}:${b.actualBags}:${b.seat}:${b.released}:${(b.perks ?? []).map((p) => (p.released ? "r" : p.bought ? "b" : "-")).join("")}`}
              />
              <section className="offers-section">
                <div className="offers-heading">
                  <h3>
                    <Gift size={20} /> A little back for what you won’t use
                  </h3>
                  <Pill tone="mint">Earn points</Pill>
                </div>
                {b.released ? (
                  <div className="offer-accepted">
                    <CheckCircle2 size={24} />
                    <div>
                      <strong>Your reward offer is confirmed.</strong>
                      <p>
                        {fmt(pending)} points will post after your completed
                        flight. Your other benefits stay yours.
                      </p>
                    </div>
                    <button className="text-button" onClick={onWallet}>
                      View wallet <ArrowRight size={16} />
                    </button>
                  </div>
                ) : (
                  <>
                    {canBag && (
                      <article className="offer-card">
                        <span className="offer-icon mint">
                          <Luggage size={24} />
                        </span>
                        <div className="offer-copy">
                          <Pill tone="mint">
                            {b.actualBags === 0
                              ? "Travelling light"
                              : "Fits your bag count"}
                          </Pill>
                          <h4>Don’t need that extra bag?</h4>
                          <p>
                            Release 1 unused allowance. Keep {b.bags - 1}{" "}
                            checked bag{b.bags - 1 === 1 ? "" : "s"}.
                          </p>
                          <small>
                            Your{" "}
                            {b.actualBags === 0
                              ? "carry-on plans"
                              : `${b.actualBags} planned bag${b.actualBags === 1 ? "" : "s"}`}{" "}
                            still fit.
                          </small>
                        </div>
                        <div className="offer-action">
                          <strong>
                            +{fmt(bagReward)} <small>pts</small>
                          </strong>
                          <span>after you fly</span>
                          <button
                            className="button secondary small-button"
                            onClick={() => release("bag")}
                          >
                            Give up a bag <ArrowRight size={15} />
                          </button>
                        </div>
                      </article>
                    )}
                    {canSeat && (
                      <article className="offer-card">
                        <span className="offer-icon lavender">
                          <Armchair size={24} />
                        </span>
                        <div className="offer-copy">
                          <Pill tone="lavender">Your choice</Pill>
                          <h4>A new seat. Something in return.</h4>
                          <p>
                            Swap {SEAT_NAMES[b.seatClass]} {b.seat} for Standard{" "}
                            {inv.seats.standard[0]}.
                          </p>
                          <small>
                            {b.seatClass === "extra"
                              ? "You’ll give up the extra legroom."
                              : "You’ll move farther from the front."}{" "}
                            Your fare stays {fare.name}.
                          </small>
                        </div>
                        <div className="offer-action">
                          <strong>
                            +{fmt(seatReward)} <small>pts</small>
                          </strong>
                          <span>after you fly</span>
                          <button
                            className="button secondary small-button"
                            onClick={() => release("seat")}
                          >
                            Review seat swap <RefreshCw size={14} />
                          </button>
                        </div>
                      </article>
                    )}
                    {!canBag && !canSeat && (
                      <EmptyState title="Your perks fit your plans.">
                        No eligible unused benefits right now. Keep enjoying
                        what’s included, or explore an extra below.
                      </EmptyState>
                    )}
                  </>
                )}
                <p className="offer-note">
                  <CircleHelp size={14} /> One voluntary reward offer per
                  traveller, per flight. Accepted rewards are funded by the
                  airline and do not depend on another customer.
                </p>
              </section>
              <section className="offers-section">
                <div className="offers-heading">
                  <h3>
                    <Sparkles size={20} /> Make this trip a little more you
                  </h3>
                  <Pill tone="blue">Use points</Pill>
                </div>
                <div className="redemption-grid">
                  {b.bags < 3 && inv.bagGrants > 0 && (
                    <article className="redeem-card">
                      <Luggage size={24} />
                      <h4>Add a checked bag</h4>
                      <p>
                        {b.actualBags > b.bags
                          ? "Your planned luggage needs another allowance."
                          : "A little more room for what comes with you."}
                      </p>
                      <strong>
                        {fmt(bagCost)} <small>pts</small>
                      </strong>
                      <small className="pay-split">Pays {pays(bagCost)}</small>
                      <button
                        className="button secondary small-button"
                        disabled={available < bagCost}
                        onClick={() => redeem("bag")}
                      >
                        {available < bagCost
                          ? `Need ${fmt(bagCost - available)} more pts`
                          : "Add bag with points"}
                        {available >= bagCost && <ChevronRight size={16} />}
                      </button>
                      {available < bagCost && <BuyRapidRewards />}
                    </article>
                  )}
                  {(["preferred", "extra"] as SeatClass[])
                    .filter(
                      (seat) =>
                        SEAT_ORDER.indexOf(seat) >
                          SEAT_ORDER.indexOf(b.seatClass) &&
                        !b.releasedSeat &&
                        inv.seats[seat].length > 0,
                    )
                    .map((seat) => {
                      const cost =
                          seat === "extra"
                            ? redeemPrice(state.prices, "extra")
                            : redeemPrice(state.prices, "preferred"),
                        free =
                          SEAT_ORDER.indexOf(e.seat) >=
                          SEAT_ORDER.indexOf(seat);
                      return (
                        <article className="redeem-card" key={seat}>
                          <Armchair size={24} />
                          <h4>{SEAT_NAMES[seat]}</h4>
                          <p>
                            {seat === "extra"
                              ? "Stretch out with more space for your legs."
                              : "Sit nearer the front, with standard legroom."}
                          </p>
                          <strong>
                            {free ? "Included" : fmt(cost)}{" "}
                            <small>{free ? "in your benefits" : "pts"}</small>
                          </strong>
                          {!free && (
                            <small className="pay-split">Pays {pays(cost)}</small>
                          )}
                          <button
                            className="button secondary small-button"
                            disabled={!free && available < cost}
                            onClick={() => redeem(seat)}
                          >
                            {!free && available < cost
                              ? `Need ${fmt(cost - available)} more pts`
                              : free
                                ? "Use included benefit"
                                : "Choose this seat"}
                            {(free || available >= cost) && (
                              <ChevronRight size={16} />
                            )}
                          </button>
                          {!free && available < cost && <BuyRapidRewards />}
                        </article>
                      );
                    })}
                  {(profile.tier !== "Member" || profile.card !== "None") && (
                    <div className="benefits-reminder">
                      <ShieldCheck size={26} />
                      <strong>We’ve got your benefits covered.</strong>
                      <p>
                        {profile.tier !== "Member"
                          ? `Your ${profile.tier} benefits`
                          : `Your ${profile.card} card benefits`}{" "}
                        are already included above. No duplicate charges.
                      </p>
                    </div>
                  )}
                </div>
              </section>
              <UndoBar
                undoable={b.undoable ?? []}
                onUndo={(u) =>
                  dispatch({ type: "undo", profileId: profile.id, benefit: u.benefit })
                }
              />
              <Notifications items={state.notifications} />
              <ReuseCard reuse={b.reuse} />
              <ExpiryNotice wallets={state.wallets} />
              <PayOrderToggle
                rapidFirst={state.payRapidFirst}
                wallets={state.wallets}
                onChange={(rapidFirst) =>
                  dispatch({ type: "payment-order", profileId: profile.id, rapidFirst })
                }
              />
              <SalesCard booking={b} prices={state.prices} />
              <SmallPerks
                perks={b.perks ?? []}
                rapidAvailable={rrAvailable}
                rapidFirst={state.payRapidFirst}
                profileId={profile.id}
                available={available}
                perkflexAvailable={pfAvailable}
                budget={inv.budget}
                bonusPct={bonusPct}
                wantsEarlyBoarding={b.needs.early}
                confirm={confirm}
              />
              <div className="checkin-cta">
                <div>
                  <ShieldCheck size={20} />
                  <span>
                    PerkFlex is always optional.
                    <small>You can keep all your benefits and continue.</small>
                  </span>
                </div>
                <button
                  className="button primary"
                  disabled={b.actualBags > b.bags}
                  onClick={() =>
                    dispatch({ type: "checkin", profileId: profile.id })
                  }
                >
                  Complete check-in <ArrowRight size={18} />
                </button>
              </div>
            </>
          ) : (
            <section className="boarding-pass">
              <div className="boarding-head">
                <div>
                  <span className="eyebrow">BOARDING PASS</span>
                  <h2>
                    {b.status === "flown"
                      ? "Thanks for flying,"
                      : "You’re all set,"}{" "}
                    {greetingName(profile)}.
                  </h2>
                  <p>
                    {b.status === "flown"
                      ? "Your PerkFlex story continues on your next trip."
                      : "Your next adventure is just a boarding call away."}
                  </p>
                </div>
                <span className="boarding-check">
                  <Check size={29} />
                </span>
              </div>
              <div className="boarding-details">
                <div>
                  <span>SEAT</span>
                  <strong>{b.seat}</strong>
                </div>
                <div>
                  <span>BOARDING</span>
                  <strong>
                    {b.fare === "extra" || profile.tier !== "Member"
                      ? "Priority"
                      : "Standard"}
                  </strong>
                </div>
                <div>
                  <span>CHECKED BAGS</span>
                  <strong>{b.bags}</strong>
                </div>
                <div>
                  <span>FLIGHT</span>
                  <strong>{b.flightId.replace("WN", "WN ")}</strong>
                </div>
              </div>
              <div className="boarding-bottom">
                <span className="mock-barcode" aria-hidden="true" />
                <small>YOUR JOURNEY. YOUR PERKS.</small>
              </div>
              {b.status === "checked-in" && (
                <div className="flight-demo-action">
                  <p>
                    <Sparkles size={17} /> Your pending reward becomes available
                    after completed travel.
                  </p>
                  <button
                    className="button primary"
                    onClick={() =>
                      dispatch({ type: "complete", profileId: profile.id })
                    }
                  >
                    Complete trip <Plane size={17} />
                  </button>
                </div>
              )}
              {b.status === "flown" && (
                <button className="button secondary" onClick={onWallet}>
                  See my points <ArrowRight size={17} />
                </button>
              )}
            </section>
          )}
        </div>
        <aside className="checkin-sidebar">
          <section className="points-card">
            <div className="points-card-label">
              <Wallet size={19} />
              <span>Your Rapid Rewards</span>
            </div>
            <div className="wallet-balance">
              {fmt(available)}
              <span>available points</span>
            </div>
            <div className="points-pending">
              <Clock3 size={16} />
              <span>Pending from PerkFlex</span>
              <strong>+{fmt(pending)}</strong>
            </div>
            <button onClick={onWallet}>
              View points activity <ArrowRight size={16} />
            </button>
          </section>
          <section className="journey-sidebar">
            <h3>A smoother takeoff.</h3>
            <div className="journey-step">
              <span className="done">
                <Check size={14} />
              </span>
              <div>
                <strong>Find your fare</strong>
                <small>{fare.name}, made for your trip</small>
              </div>
            </div>
            <div className="journey-step">
              <span className={isOpen ? "current" : "done"}>
                {isOpen ? "2" : <Check size={14} />}
              </span>
              <div>
                <strong>Review & check in</strong>
                <small>
                  {isOpen
                    ? "Your perks, on your terms"
                    : "All set for boarding"}
                </small>
              </div>
            </div>
            <div className="journey-step">
              <span className={b.status === "flown" ? "done" : ""}>
                {b.status === "flown" ? <Check size={14} /> : "3"}
              </span>
              <div>
                <strong>Fly & enjoy your rewards</strong>
                <small>Pending points become available</small>
              </div>
            </div>
          </section>
          <div className="demo-clock">
            <Clock3 size={18} />
            <p>
              <strong>Check-in window</strong>
              {b.status === "flown"
                ? "Journey complete"
                : "23 hours before departure"}
              <small>Review your perks before you board.</small>
            </p>
          </div>
        </aside>
      </div>
    </main>
  );
}
function CalendarIcon() {
  return <Clock3 size={15} />;
}
/** Shown on Check in and My trips for a new traveller who has not booked yet. */
export function NoTripPage({
  profile,
  heading,
  onBook,
}: {
  profile: Profile;
  heading: string;
  onBook: () => void;
}) {
  return (
    <main className="container compact-page page-enter">
      <div className="page-title-row">
        <div>
          <div className="eyebrow">
            WELCOME, {greetingName(profile).toUpperCase()}
          </div>
          <h1>{heading}</h1>
          <p>Book your first flight and your benefits will show up here.</p>
        </div>
        <button className="button primary" onClick={onBook}>
          <Plane size={17} /> Book a flight
        </button>
      </div>
      <EmptyState title="No trip yet.">
        Once you book, you can review your benefits and check in from this page.
      </EmptyState>
    </main>
  );
}
export function TripsPage({
  state,
  profile,
  onCheckin,
  onBook,
}: {
  state: Store;
  profile: Profile;
  onCheckin: () => void;
  onBook: () => void;
}) {
  // App only renders this page when the traveller has a booking (see NoTripPage).
  const b = state.bookings[profile.id]!;
  return (
    <main className="container compact-page page-enter">
      <div className="page-title-row">
        <div>
          <div className="eyebrow">SOMETHING TO LOOK FORWARD TO</div>
          <h1>Your trips.</h1>
          <p>One journey. All your details, in one place.</p>
        </div>
        <button className="button secondary" onClick={onBook}>
          <Plane size={17} /> Book a flight
        </button>
      </div>
      <div className="trip-overview">
        <div className="trip-card-top">
          <span>
            <DateLabel date={b.date} />
          </span>
          <Pill tone="mint">
            {b.status === "booked"
              ? "Upcoming"
              : b.status === "checked-in"
                ? "Checked in"
                : "Completed"}
          </Pill>
        </div>
        <FlightRoute booking={b} />
        <div className="trip-overview-details">
          <div>
            <span>TRAVELLER</span>
            <strong>{profile.name}</strong>
          </div>
          <div>
            <span>FARE</span>
            <strong>{fareById(b.fare).name}</strong>
          </div>
          <div>
            <span>CONFIRMATION</span>
            <strong>{b.id}</strong>
          </div>
          <div>
            <span>TOTAL PAID</span>
            <strong>{money(b.total)}</strong>
          </div>
        </div>
        <div className="trip-overview-bottom">
          <p>
            <PerkMark small />
            {b.released
              ? "Your PerkFlex reward is recorded for this trip."
              : "Your PerkFlex review is waiting before check-in."}
          </p>
          <button className="button primary" onClick={onCheckin}>
            {b.status === "booked"
              ? "Review perks & check in"
              : "View trip & boarding pass"}
            <ArrowRight size={17} />
          </button>
        </div>
      </div>
    </main>
  );
}
export function WalletPage({
  state,
  profile,
  onCheckin,
  dispatch,
}: {
  state: Store;
  profile: Profile;
  onCheckin: () => void;
  dispatch?: (a: Action) => void;
}) {
  const pending = pendingPoints(state, profile.id),
    earnings = state.earnings,
    ledger = state.ledger.filter((l) => l.profileId === profile.id),
    credited = ledger
      .filter((l) => l.kind === "release" && l.status === "posted")
      .reduce((n, l) => n + l.points, 0),
    spent = -ledger
      .filter((l) => l.kind === "redemption")
      .reduce((n, l) => n + l.points, 0);
  // What this was worth in cash at list price: benefits added with points, and unused benefits turned into points.
  const added = ledger.filter((l) => l.kind === "redemption"),
    released = ledger.filter((l) => l.kind === "release"),
    addedCash = added.reduce((n, l) => n + (l.cashValue ?? 0), 0),
    releasedCash = released.reduce((n, l) => n + (l.cashValue ?? 0), 0),
    earnedTotal = released.reduce((n, l) => n + l.points, 0);
  return (
    <main className="container wallet-page page-enter">
      <div className="page-title-row">
        <div>
          <div className="eyebrow">GOOD THINGS ADD UP</div>
          <h1>Your points. More possibilities.</h1>
          <p>A clear view of every PerkFlex reward and redemption.</p>
        </div>
        <Pill tone="lavender">
          <Sparkles size={14} /> Your rewards
        </Pill>
      </div>
      <div className="wallet-overview">
        <div className="wallet-pair">
          <div className="wallet-hero" aria-label="Rapid Rewards wallet">
            <div className="points-card-label">
              <Wallet size={21} /> RAPID REWARDS
            </div>
            <strong>{fmt(state.wallets.rapidRewards.available)}</strong>
            <span>available points</span>
            <span>
              {fmt(state.wallets.rapidRewards.pending)} more after you fly
            </span>
            <div>
              <span className={`avatar avatar-small ${profile.color}`}>
                {profile.initials}
              </span>
              {profile.name}
              <Pill tone="white">{profile.tier}</Pill>
            </div>
            <span className="wallet-watermark">
              <Sparkles size={180} strokeWidth={0.7} />
            </span>
          </div>
          <div
            className="wallet-hero perkflex"
            aria-label="PerkFlex Rewards wallet"
          >
            <div className="points-card-label">
              <Gift size={21} /> PERKFLEX REWARDS
            </div>
            <strong>{fmt(state.wallets.perkflex.available)}</strong>
            <span>available points</span>
            <span>
              {fmt(state.wallets.perkflex.pending)} pending until you fly
            </span>
            <div>Spent first on your next purchase, then Rapid Rewards.</div>
          </div>
        </div>
        <div className="wallet-stat">
          <span className="journey-icon yellow">
            <Clock3 size={23} />
          </span>
          <strong>{fmt(pending)}</strong>
          <span>PerkFlex pending</span>
          <small>Available after you complete your flight</small>
        </div>
        <div className="wallet-stat">
          <span className="journey-icon mint">
            <Gift size={23} />
          </span>
          <strong>{fmt(credited)}</strong>
          <span>Rewards earned</span>
          <small>From unused benefits you chose to release</small>
        </div>
        <div className="wallet-stat">
          <span className="journey-icon lavender">
            <Armchair size={23} />
          </span>
          <strong>{fmt(spent)}</strong>
          <span>Points used</span>
          <small>For a trip that fits you a little better</small>
        </div>
      </div>
      <ExpiryNotice wallets={state.wallets} />
      {dispatch && (
        <PayOrderToggle
          rapidFirst={state.payRapidFirst}
          wallets={state.wallets}
          onChange={(rapidFirst) =>
            dispatch({ type: "payment-order", profileId: profile.id, rapidFirst })
          }
        />
      )}
      <Notifications items={state.notifications} />
      {dispatch && (
        <GroupCard group={state.group} perkflexAvailable={state.wallets.perkflex.available} dispatch={dispatch} />
      )}
      <GoalsCard wallets={state.wallets} perks={state.bookings[profile.id]?.perks} />
      <NextFlightPreview
        wallets={state.wallets}
        rapidFirst={state.payRapidFirst}
        perks={state.bookings[profile.id]?.perks}
      />
      <EarningsChart ledger={ledger} earnings={earnings} />
      <StatusCard status={state.status} />
      <EmailCard />
      {(added.length > 0 || released.length > 0) && (
        <section className="value-summary" aria-label="What your points did">
          <h2>What your points did</h2>
          <div className="value-grid">
            <div>
              <strong>{money(addedCash)}</strong>
              <span>
                of extras added with {fmt(spent)} points
              </span>
              <small>
                {added.length} benefit{added.length === 1 ? "" : "s"}, valued at
                the usual add-on price
              </small>
            </div>
            <div>
              <strong>{money(releasedCash)}</strong>
              <span>
                of unused benefits turned into {fmt(earnedTotal)} points
              </span>
              <small>
                {released.length} release{released.length === 1 ? "" : "s"}, some
                still pending until you fly
              </small>
            </div>
          </div>
        </section>
      )}
      <section className="activity-section">
        <div className="section-heading">
          <h2>Your activity</h2>
          <span>
            {ledger.length} PerkFlex transaction{ledger.length === 1 ? "" : "s"}
            {earnings.length > 0 && ` · ${earnings.length} for flying`}
          </span>
        </div>
        {ledger.length > 0 ? (
          <div className="ledger">
            {earnings.map((x) => (
              <div className="ledger-row" key={x.id}>
                <span className="journey-icon blue">
                  <Plane size={21} />
                </span>
                <div>
                  <strong>{x.label}</strong>
                  <small>
                    {x.bookingId} · Rapid Rewards ·{" "}
                    {x.status === "pending"
                      ? "Posts after travel"
                      : "Added to your account"}
                  </small>
                </div>
                <Pill tone={x.status === "pending" ? "yellow" : "mint"}>
                  {x.status === "pending" ? "Pending" : "Posted"}
                </Pill>
                <strong className="positive">
                  +{fmt(x.points)} <small>pts</small>
                </strong>
              </div>
            ))}
            {ledger.map((l) => (
              <div className="ledger-row" key={l.id}>
                <span
                  className={`journey-icon ${l.kind === "release" || l.kind === "bonus" || l.kind === "gift" ? "mint" : l.kind === "expiry" ? "yellow" : "lavender"}`}
                >
                  {l.kind === "release" || l.kind === "bonus" || l.kind === "gift" ? (
                    <Gift size={21} />
                  ) : l.kind === "expiry" ? (
                    <Clock3 size={21} />
                  ) : (
                    <Armchair size={21} />
                  )}
                </span>
                <div>
                  <strong>{l.label}</strong>
                  <small>
                    {l.bookingId ? `${l.bookingId} · ` : ""}
                    {l.kind === "expiry"
                      ? "PerkFlex · expired"
                      : l.kind === "bonus"
                      ? "Trip completed · PerkFlex"
                      : l.kind === "gift"
                      ? "Travel group · PerkFlex"
                      : l.kind === "release"
                      ? "Benefit released · PerkFlex"
                      : `Benefit added · paid ${payLabel({
                          perkflex: l.paidPerkflex ?? 0,
                          rapid: l.paidRapid ?? -l.points,
                        })}`}{" "}
                    ·{" "}
                    {l.status === "pending"
                      ? "Posts after travel"
                      : "Added to your account"}
                  </small>
                </div>
                <Pill tone={l.status === "pending" ? "yellow" : "mint"}>
                  {l.status === "pending" ? "Pending" : "Posted"}
                </Pill>
                <strong className={l.points > 0 ? "positive" : ""}>
                  {l.points > 0 ? "+" : ""}
                  {fmt(l.points)} <small>pts</small>
                </strong>
              </div>
            ))}
            <div className="ledger-row starting-balance">
              <span className="journey-icon blue">
                <Coins size={21} />
              </span>
              <div>
                <strong>Spendable now</strong>
                <small>
                  {fmt(state.wallets.perkflex.available)} PerkFlex +{" "}
                  {fmt(state.wallets.rapidRewards.available)} Rapid Rewards
                </small>
              </div>
              <strong>
                {fmt(state.balances[profile.id])} <small>pts</small>
              </strong>
            </div>
          </div>
        ) : (
          <EmptyState title="Your next reward starts with your next trip.">
            Review your benefits at check-in to see what fits. You can
            participate without an elite tier or a starting points balance.
          </EmptyState>
        )}
      </section>
      <div className="wallet-bottom">
        <p>
          <ShieldCheck size={18} /> PerkFlex rewards post after eligible
          completed travel. They do not count toward tier qualification.
        </p>
        <button className="button secondary" onClick={onCheckin}>
          Go to my trip <ArrowRight size={17} />
        </button>
      </div>
    </main>
  );
}
