import { useState } from "react";
import {
  ArrowDownUp,
  ArrowLeft,
  ArrowRight,
  Armchair,
  CalendarDays,
  Check,
  ChevronRight,
  CircleCheck,
  Clock3,
  Luggage,
  Plane,
  RefreshCw,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Ticket,
  Wallet,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import {
  AIRPORTS,
  FARES,
  FLIGHTS,
  SEAT_NAMES,
  fareById,
  fmt,
  money,
} from "../rules/data.ts";
import { greetingName } from "../rules/helpers.ts";
import type {
  BestFareResponse,
  FareId,
  Needs,
  Profile,
  QuotesResponse,
} from "../rules/types.ts";
import { api } from "../services/api.ts";
import {
  CheckLine,
  DateLabel,
  Modal,
  PerkMark,
  Pill,
  SkyIllustration,
} from "../components/components.tsx";

export type Search = {
  from: string;
  to: string;
  date: string;
  flightId: string;
};
export function BookingPage({
  profile,
  needs,
  search,
  onSearchChange,
  results,
  onSearch,
  onAssistant,
  onBook,
  onBack,
  data,
  quotesFailed,
}: {
  profile: Profile;
  needs: Needs;
  search: Search;
  onSearchChange: (s: Search) => void;
  results: boolean;
  onSearch: () => void;
  onAssistant: () => void;
  onBook: (id: FareId) => void;
  onBack: () => void;
  /** Fares priced by the server for this traveller; null until the first answer arrives. */
  data: QuotesResponse | null;
  quotesFailed: boolean;
}) {
  const quotes = data?.quotes ?? [];
  const best = quotes.find((q) => q.fare === data?.best);
  const destination = AIRPORTS.find((a) => a.code === search.to)!;
  if (results && !data)
    return (
      <main className="container results-page page-enter">
        <button className="text-button back-link" onClick={onBack}>
          <ArrowLeft size={17} /> Change search
        </button>
        <p role={quotesFailed ? "alert" : "status"} className="fine-print">
          {quotesFailed
            ? "We couldn’t load fares just now. Please go back and try again."
            : "Finding your fares…"}
        </p>
      </main>
    );
  if (results)
    return (
      <main className="container results-page page-enter">
        <button className="text-button back-link" onClick={onBack}>
          <ArrowLeft size={17} /> Change search
        </button>
        <div className="results-heading">
          <div>
            <div className="eyebrow">LET’S GET YOU THERE</div>
            <h1>
              {AIRPORTS.find((a) => a.code === search.from)?.city}{" "}
              <span className="heading-arrow">→</span> {destination.city}
            </h1>
            <p>
              <DateLabel date={search.date} />{" "}
              <span className="dot-separator">•</span> One-way{" "}
              <span className="dot-separator">•</span> 1 adult
            </p>
          </div>
          <button className="button secondary" onClick={onAssistant}>
            <SlidersHorizontal size={17} /> Edit my preferences
          </button>
        </div>
        <div className="recommendation-banner">
          <PerkMark />
          <div>
            <strong>
              {best
                ? `${fareById(best.fare).name} is your best fit.`
                : "Let’s adjust your preferences."}
            </strong>
            <p>
              {best
                ? "The lowest total that meets your selected needs, including benefits you already have."
                : "No fare meets every requirement within your budget. Open PerkFlex to change your needs or budget."}
            </p>
          </div>
          <Pill tone="white">
            <Sparkles size={13} /> PerkFlex pick
          </Pill>
        </div>
        <div className="flight-selector" aria-label="Choose a departure">
          {FLIGHTS.map((f) => (
            <button
              key={f.id}
              className={`flight-option ${search.flightId === f.id ? "selected" : ""}`}
              onClick={() => onSearchChange({ ...search, flightId: f.id })}
              aria-pressed={search.flightId === f.id}
            >
              <span className="flight-radio">
                {search.flightId === f.id && <span />}
              </span>
              <span>
                <strong>
                  {f.departure} <span>→</span> {f.arrival}
                </strong>
                <small>
                  Nonstop · {f.duration} · {f.id.replace("WN", "WN ")}
                </small>
              </span>
              <Plane size={19} />
            </button>
          ))}
        </div>
        <div className="comparison-caption">
          <span>All totals include taxes and your requested extras.</span>
          <span>Prices in USD</span>
        </div>
        <div className="fare-grid">
          {FARES.map((fare) => {
            const q = quotes.find((q) => q.fare === fare.id)!,
              isBest = best?.fare === fare.id,
              e = data!.entitlements[fare.id];
            return (
              <article
                key={fare.id}
                className={`fare-card ${isBest ? "recommended" : ""}`}
              >
                {isBest && (
                  <div className="recommended-ribbon">
                    <Sparkles size={14} /> YOUR BEST FIT
                  </div>
                )}
                <div className={`fare-color fare-color-${fare.id}`} />
                <div className="fare-card-body">
                  <span className="fare-label">
                    {fare.id === "extra"
                      ? "THE FULL EXPERIENCE"
                      : fare.id === "preferred"
                        ? "A LITTLE MORE COMFORT"
                        : fare.id === "choice"
                          ? "MORE FLEXIBILITY"
                          : "JUST THE ESSENTIALS"}
                  </span>
                  <h2>{fare.name}</h2>
                  <p className="fare-description">{fare.description}</p>
                  <div className="fare-price">
                    {money(q.total)}
                    <small>total / person</small>
                  </div>
                  <div className="price-subline">
                    {money(q.base)} fare + {money(q.tax)} taxes
                    {q.addons.length > 0 ? " + extras" : ""}
                  </div>
                  <div className="fare-divider" />
                  <CheckLine>
                    {SEAT_NAMES[q.seat]}
                    {fare.id === "basic" &&
                    !needs.seatNow &&
                    needs.seat === "any" &&
                    profile.tier === "Member"
                      ? " assigned at check-in"
                      : " seat"}
                  </CheckLine>
                  <CheckLine muted={q.bags === 0}>
                    {q.bags === 0
                      ? "Checked bags cost extra"
                      : `${q.bags} checked bag${q.bags === 1 ? "" : "s"} included`}
                  </CheckLine>
                  <CheckLine muted={!fare.refundable}>
                    {fare.refundable ? "Refundable fare" : "Nonrefundable fare"}
                  </CheckLine>
                  <CheckLine muted={!e.flexible}>
                    {e.flexible
                      ? "Changes with fare difference"
                      : "Flight changes not included"}
                  </CheckLine>
                  <CheckLine>
                    {fare.id === "extra"
                      ? "Group 1 boarding"
                      : e.early
                        ? "Priority boarding"
                        : "Standard boarding"}
                  </CheckLine>
                  <CheckLine>
                    {fmt(q.points)} estimated flight points
                    {q.rate ? (
                      <small className="earn-working">
                        {" "}
                        ({q.rate}x on {money(q.base)}
                        {q.statusBonus ? `, +${q.statusBonus}% status bonus` : ""})
                      </small>
                    ) : null}
                  </CheckLine>
                  {q.addons.length > 0 && (
                    <div className="add-on-box">
                      <span>YOUR REQUESTED EXTRAS</span>
                      {q.addons.map((a) => (
                        <div key={a.label}>
                          {a.label}
                          <b>{money(a.price)}</b>
                        </div>
                      ))}
                    </div>
                  )}
                  {(profile.tier !== "Member" || profile.card !== "None") && (
                    <div className="entitlement-note">
                      <ShieldCheck size={15} />
                      <span>
                        {e.bags > 0
                          ? `${e.bags} bag${e.bags === 1 ? "" : "s"} via ${e.bagSource}`
                          : "Your existing benefits are included"}
                        {e.seatSource !== fare.name
                          ? ` · ${SEAT_NAMES[e.seat]} via ${e.seatSource}`
                          : ""}
                      </span>
                    </div>
                  )}
                  <div className="fare-bottom">
                    {q.issues.length > 0 ? (
                      <div className="unmet">
                        <X size={14} />
                        {q.issues.join(" · ")}
                      </div>
                    ) : (
                      <div className="matched">
                        <Check size={14} /> Meets your selected needs
                      </div>
                    )}
                    <button
                      className={`button ${isBest ? "primary" : "secondary"}`}
                      disabled={q.issues.length > 0}
                      onClick={() => onBook(fare.id)}
                    >
                      Select {fare.name}
                      <ChevronRight size={17} />
                    </button>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
        <p className="fine-print">
          Future exchange rewards are never deducted from today’s fare.
          Preferred seats are nearer the front with standard legroom. Seat
          selection is subject to availability.
        </p>
      </main>
    );
  return (
    <main className="page-enter">
      <section className="booking-hero">
        <div className="container hero-layout">
          <form
            className="search-card"
            onSubmit={(e) => {
              e.preventDefault();
              onSearch();
            }}
          >
            <div className="search-tabs">
              <span>
                <Plane size={18} /> Flights
              </span>
            </div>
            <div className="search-fields">
              <div className="search-meta">
                <strong>Let’s book your next trip.</strong>
                <span>One-way · 1 adult</span>
              </div>
              <div className="airport-row">
                <label>
                  Depart from
                  <select
                    value={search.from}
                    onChange={(e) =>
                      onSearchChange({ ...search, from: e.target.value })
                    }
                  >
                    {AIRPORTS.map((a) => (
                      <option key={a.code} value={a.code}>
                        {a.city} · {a.code}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  type="button"
                  className="swap-airports"
                  onClick={() =>
                    onSearchChange({
                      ...search,
                      from: search.to,
                      to: search.from,
                    })
                  }
                  aria-label="Swap departure and destination"
                >
                  <ArrowDownUp size={17} />
                </button>
                <label>
                  Arrive at
                  <select
                    value={search.to}
                    onChange={(e) =>
                      onSearchChange({ ...search, to: e.target.value })
                    }
                  >
                    {AIRPORTS.map((a) => (
                      <option key={a.code} value={a.code}>
                        {a.city} · {a.code}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="date-row">
                <label>
                  Departure date
                  <div className="input-icon">
                    <CalendarDays size={17} />
                    <input
                      type="date"
                      value={search.date}
                      min="2026-10-21"
                      required
                      onChange={(e) =>
                        onSearchChange({ ...search, date: e.target.value })
                      }
                    />
                  </div>
                </label>
                <label>
                  Passengers
                  <div className="static-input">
                    <span>1 Adult</span>
                    <span className="passenger-dot">1</span>
                  </div>
                </label>
              </div>
              <div className="search-person">
                <span className={`avatar avatar-small ${profile.color}`}>
                  {profile.initials}
                </span>
                <span>
                  Flying as <strong>{greetingName(profile)}</strong>
                  <small>
                    {profile.tier === "Member"
                      ? "Rapid Rewards Member"
                      : `${profile.tier} member`}
                    {profile.card !== "None" ? ` · ${profile.card} card` : ""}
                  </small>
                </span>
                <ShieldCheck size={19} />
              </div>
              <button className="button primary search-submit" type="submit">
                Search flights <ArrowRight size={19} />
              </button>
              <p className="search-footnote">
                Your next adventure starts with the right fare.
              </p>
            </div>
          </form>
          <div className="hero-story">
            <div className="eyebrow">
              A LITTLE MORE PERSONAL. A LOT MORE YOU.
            </div>
            <h1>
              Your next trip.
              <br />
              Your kind of perks.
            </h1>
            <p>
              The right fare for the way you fly.
              <br />
              And a little something back for the perks you don’t need.
            </p>
            <button className="hero-ai-button" onClick={onAssistant}>
              <PerkMark small /> Meet PerkFlex AI <ArrowRight size={17} />
            </button>
            <SkyIllustration />
          </div>
        </div>
      </section>
      <section className="container intro-section">
        <div className="intro-heading">
          <div>
            <div className="eyebrow">MEET YOUR NEW TRAVEL SIDEKICK</div>
            <h2>A better fit, from booking to boarding.</h2>
          </div>
          <Pill tone="lavender">
            <Sparkles size={14} /> Made for your journey
          </Pill>
        </div>
        <div className="journey-cards">
          <button className="journey-card" onClick={onAssistant}>
            <span className="journey-icon lavender">
              <SlidersHorizontal size={24} />
            </span>
            <div>
              <span className="step-label">01 · BEFORE YOU BOOK</span>
              <h3>Tell us what matters.</h3>
              <p>
                Extra room? A bag? Flexible plans? Pick the perks that make your
                trip.
              </p>
            </div>
            <ArrowRight size={19} />
          </button>
          <button className="journey-card" onClick={onAssistant}>
            <span className="journey-icon blue">
              <Ticket size={24} />
            </span>
            <div>
              <span className="step-label">02 · FIND YOUR FIT</span>
              <h3>A fare that gets you.</h3>
              <p>
                See a clear recommendation, with your member benefits already
                included.
              </p>
            </div>
            <ArrowRight size={19} />
          </button>
          <div className="journey-card">
            <span className="journey-icon yellow">
              <RefreshCw size={24} />
            </span>
            <div>
              <span className="step-label">03 · BEFORE CHECK-IN</span>
              <h3>Flex what you won’t use.</h3>
              <p>
                Explore points offers for eligible unused perks, or add a little
                more comfort.
              </p>
            </div>
          </div>
        </div>
      </section>
      <section className="container member-strip">
        <span className="member-strip-icon">
          <ShieldCheck size={24} />
        </span>
        <div>
          <h3>Already have perks? We’ll remember.</h3>
          <p>
            Fare, tier, and card benefits work together. You won’t pay again for
            a benefit you already have.
          </p>
        </div>
        <div className="tier-pills">
          <Pill tone="silver">Silver</Pill>
          <Pill tone="gold">Gold</Pill>
          <Pill tone="platinum">Platinum</Pill>
        </div>
      </section>
    </main>
  );
}

type BenefitProps = {
  icon: LucideIcon;
  title: string;
  description: string;
  selected: boolean;
  onClick: () => void;
};
function BenefitChoice({
  icon: Icon,
  title,
  description,
  selected,
  onClick,
}: BenefitProps) {
  return (
    <button
      className={`benefit-choice ${selected ? "selected" : ""}`}
      aria-pressed={selected}
      onClick={onClick}
    >
      <span className="benefit-choice-icon">
        <Icon size={22} />
      </span>
      <span>
        <strong>{title}</strong>
        <small>{description}</small>
      </span>
      <span className="choice-check">{selected && <Check size={13} />}</span>
    </button>
  );
}
export function Assistant({
  profile,
  needs,
  onNeeds,
  flightId,
  from,
  to,
  date,
  step,
  onStep,
  onClose,
  onApply,
}: {
  profile: Profile;
  needs: Needs;
  onNeeds: (n: Needs) => void;
  flightId: string;
  from: string;
  to: string;
  date?: string;
  step: number;
  onStep: (s: number) => void;
  onClose: () => void;
  onApply: () => void;
}) {
  // The server runs the AI agent, prices every fare, and checks the agent's answer; this screen only shows it.
  const [text, setText] = useState("");
  const [ai, setAi] = useState<{
    status: "idle" | "loading" | "done" | "failed";
    data?: BestFareResponse;
  }>({ status: "idle" });
  const data = ai.status === "done" ? ai.data : undefined;
  const quotes = data?.quotes ?? [];
  const recommended = data?.recommendation.fare ?? null;
  const best = recommended
    ? quotes.find((q) => q.fare === recommended)
    : undefined;
  const fare = best ? fareById(best.fare) : undefined;
  function findFare() {
    setAi({ status: "loading" });
    onStep(1);
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 35000);
    api
      .bestFare(
        {
          message: text.trim() || undefined,
          needs,
          flightId,
          from,
          to,
          date,
        },
        controller.signal,
      )
      .then((result) => {
        if (text.trim()) onNeeds(result.understood);
        setAi({ status: "done", data: result });
      })
      .catch(() => setAi({ status: "failed" }))
      .finally(() => window.clearTimeout(timer));
  }
  return (
    <Modal
      title="PerkFlex fare assistant"
      onClose={onClose}
      wide
      className="assistant-modal"
    >
      <div className="assistant-layout">
        <aside className="assistant-aside">
          <div className="assistant-brand">
            <PerkMark />
            <span>
              PerkFlex<span className="ai-label">AI</span>
            </span>
          </div>
          <div className="aside-copy">
            <span className="tiny-caps">YOUR TRIP. YOUR PRIORITIES.</span>
            <h2>
              Let’s find
              <br />
              your kind
              <br />
              of flying.
            </h2>
            <p>
              A little more legroom.
              <br />A little less guesswork.
            </p>
          </div>
          <div className="assistant-member">
            <span className={`avatar ${profile.color}`}>
              {profile.initials}
            </span>
            <div>
              <strong>{profile.name}</strong>
              <span>
                {profile.tier === "Member"
                  ? "Rapid Rewards Member"
                  : `${profile.tier} member`}
              </span>
            </div>
          </div>
          <div className="known-benefits">
            <ShieldCheck size={17} />
            <p>
              {profile.tier === "Gold" || profile.tier === "Platinum"
                ? `We already know your ${profile.tier} seat and bag benefits.`
                : profile.card !== "None"
                  ? `Your ${profile.card} card’s included bag is already counted.`
                  : profile.tier === "Silver"
                    ? "We’ll include your Silver bag and seat benefits."
                    : "Every member can find their fit. No tier or points balance required."}
            </p>
          </div>
          <div className="assistant-demo">
            <span /> Your personal travel assistant
          </div>
        </aside>
        <section className="assistant-main">
          <div className="assistant-progress">
            <span className={step === 0 ? "active" : ""}>
              1 <span>Your preferences</span>
            </span>
            <div />
            <span className={step === 1 ? "active" : ""}>
              2 <span>Your best fit</span>
            </span>
          </div>
          {step === 0 ? (
            <>
              <div className="assistant-title">
                <h2>What makes a great flight for you?</h2>
                <p>
                  Select what you need on this trip. We’ll do the comparing.
                </p>
              </div>
              <label className="ai-prompt" htmlFor="ai-message">
                <span>Or tell us in your own words (optional)</span>
                <textarea
                  id="ai-message"
                  rows={2}
                  maxLength={500}
                  placeholder="e.g. Two bags, a seat near the front, refundable, under $400"
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                />
              </label>
              <div className="bag-picker">
                <span className="soft-icon">
                  <Luggage size={23} />
                </span>
                <div>
                  <strong>How many bags are coming along?</strong>
                  <small>Checked bags only. Your carry-on is separate.</small>
                </div>
                <div className="segmented" aria-label="Checked bag preference">
                  {[0, 1, 2].map((n) => (
                    <button
                      key={n}
                      aria-pressed={needs.bags === n}
                      className={needs.bags === n ? "active" : ""}
                      onClick={() => onNeeds({ ...needs, bags: n })}
                    >
                      {n}
                    </button>
                  ))}
                </div>
              </div>
              <div className="benefit-choices">
                <BenefitChoice
                  icon={Armchair}
                  title="Extra legroom"
                  description="A little more room to stretch"
                  selected={needs.seat === "extra"}
                  onClick={() =>
                    onNeeds({
                      ...needs,
                      seat: needs.seat === "extra" ? "any" : "extra",
                    })
                  }
                />
                <BenefitChoice
                  icon={Plane}
                  title="Sit near the front"
                  description="Preferred seat, standard legroom"
                  selected={needs.seat === "front"}
                  onClick={() =>
                    onNeeds({
                      ...needs,
                      seat: needs.seat === "front" ? "any" : "front",
                    })
                  }
                />
                <BenefitChoice
                  icon={ShieldCheck}
                  title="Refundable ticket"
                  description="Peace of mind if plans change"
                  selected={needs.refund}
                  onClick={() => onNeeds({ ...needs, refund: !needs.refund })}
                />
                <BenefitChoice
                  icon={RefreshCw}
                  title="Change my flight"
                  description="Fare difference may apply"
                  selected={needs.flexible}
                  onClick={() =>
                    onNeeds({ ...needs, flexible: !needs.flexible })
                  }
                />
                <BenefitChoice
                  icon={Ticket}
                  title="Choose my seat now"
                  description="Have a seat picked at booking"
                  selected={needs.seatNow}
                  onClick={() => onNeeds({ ...needs, seatNow: !needs.seatNow })}
                />
                <BenefitChoice
                  icon={Clock3}
                  title="Board earlier"
                  description="Priority boarding for this trip"
                  selected={needs.early}
                  onClick={() => onNeeds({ ...needs, early: !needs.early })}
                />
              </div>
              <div className="budget-picker">
                <label htmlFor="budget">
                  <Wallet size={18} /> My total budget{" "}
                  <strong>{money(needs.budget)}</strong>
                </label>
                <input
                  id="budget"
                  type="range"
                  min="160"
                  max="600"
                  step="10"
                  value={needs.budget}
                  onChange={(e) =>
                    onNeeds({ ...needs, budget: Number(e.target.value) })
                  }
                />
                <div>
                  <span>$160</span>
                  <span>Including taxes and extras</span>
                  <span>$600</span>
                </div>
              </div>
              <div className="assistant-bottom">
                <p>
                  <ShieldCheck size={14} /> Your selections stay in this
                  browser.
                </p>
                <button className="button primary" onClick={findFare}>
                  <Sparkles size={17} /> Find my best fare{" "}
                  <ArrowRight size={18} />
                </button>
              </div>
            </>
          ) : ai.status === "loading" ? (
            <div className="no-match" role="status" aria-live="polite">
              <Sparkles size={40} />
              <p>Finding your best fit…</p>
              <p>Checking your benefits against every fare.</p>
            </div>
          ) : ai.status === "failed" ? (
            <>
              <div className="no-match" role="alert">
                <Wallet size={40} />
                <p>We couldn’t find your fare just now.</p>
                <p>Please check your connection and try again.</p>
              </div>
              <div className="assistant-bottom">
                <button className="text-button" onClick={() => onStep(0)}>
                  <ArrowLeft size={16} /> Edit preferences
                </button>
                <button className="button primary" onClick={findFare}>
                  Try again <ArrowRight size={18} />
                </button>
              </div>
            </>
          ) : (
            <>
              <div className="assistant-title">
                <Pill tone="mint">
                  <CircleCheck size={14} /> Your preferences, considered
                </Pill>
                <h2>
                  {fare
                    ? `${fare.name}. That’s your fit.`
                    : "Let’s make a small adjustment."}
                </h2>
                <p>
                  {fare
                    ? "Here’s how your needs and existing benefits come together."
                    : "No fare meets all your needs within this budget. Try a larger budget or remove an optional preference."}
                </p>
              </div>
              {best && fare ? (
                <>
                  <div className="best-fit-card">
                    <div>
                      <span>YOUR RECOMMENDED FARE</span>
                      <h3>{fare.name}</h3>
                      <p>
                        {data?.source === "ai"
                          ? "Chosen for your needs and benefits"
                          : "Lowest total meeting your selections"}
                      </p>
                    </div>
                    <div>
                      <strong>{money(best.total)}</strong>
                      <small>total, including taxes & extras</small>
                    </div>
                  </div>
                  <div className="why-list">
                    <h3>Why this works for you</h3>
                    {(data?.recommendation.reasons ?? []).map((reason) => (
                      <CheckLine key={reason}>{reason}</CheckLine>
                    ))}
                    <CheckLine>
                      {money(needs.budget - best.total)} below your chosen
                      budget.
                    </CheckLine>
                  </div>
                  <div className="mini-comparison">
                    {quotes.map((q) => (
                      <div
                        key={q.fare}
                        className={q.fare === best.fare ? "best" : ""}
                      >
                        <span>{fareById(q.fare).name}</span>
                        <b>{money(q.total)}</b>
                        <small>
                          {q.fare === best.fare
                            ? "Best fit"
                            : q.issues.length
                              ? q.issues[0]
                              : "Meets your needs"}
                        </small>
                      </div>
                    ))}
                  </div>
                  <div className="assistant-tip">
                    <Sparkles size={17} />
                    <span>{data?.explanation}</span>
                  </div>
                </>
              ) : (
                <div className="no-match">
                  <Wallet size={40} />
                  <p>
                    Selected budget: <strong>{money(needs.budget)}</strong>
                  </p>
                  <p>Every selected preference is treated as a requirement.</p>
                  {data && <p>{data.explanation}</p>}
                  {data &&
                    data.alternatives.map((a) => (
                      <p key={a.fare}>
                        <strong>
                          {fareById(a.fare).name} · {money(a.total)}
                        </strong>{" "}
                        {a.tradeoff}
                      </p>
                    ))}
                </div>
              )}
              <div className="assistant-bottom">
                <button className="text-button" onClick={() => onStep(0)}>
                  <ArrowLeft size={16} /> Edit preferences
                </button>
                {best ? (
                  <button className="button primary" onClick={onApply}>
                    See flights & fares <ArrowRight size={18} />
                  </button>
                ) : (
                  <button className="button primary" onClick={() => onStep(0)}>
                    Adjust my needs
                  </button>
                )}
              </div>
            </>
          )}
        </section>
      </div>
    </Modal>
  );
}
