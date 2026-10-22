import { useEffect, useMemo, useState } from "react";
import {
  ArrowDown,
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronDown,
  CircleHelp,
  Clock3,
  Coins,
  Heart,
  Info,
  LogOut,
  Menu,
  Plane,
  ShieldCheck,
  Sparkles,
  Wallet,
  X,
} from "lucide-react";
import { AIRPORTS, fareById, fmt, money, SEAT_NAMES } from "./rules/data.ts";
import { greetingName } from "./rules/helpers.ts";
import { toStore } from "./rules/store.ts";
import type { Action, FareId, ServerState } from "./rules/types.ts";
import { api } from "./services/api.ts";
import { useQuotes } from "./services/useQuotes.ts";
import { useTravellerState } from "./services/useTravellerState.ts";
import {
  DateLabel,
  Modal,
  PerkMark,
  PerkFlexLogo,
  Pill,
} from "./components/components.tsx";
import { LoginPage, WelcomeOverlay } from "./auth/Auth.tsx";
import { AdminPage } from "./pages/AdminPage.tsx";
import { PresenterGuide } from "./pages/PresenterGuide.tsx";
import { Assistant, BookingPage } from "./pages/Booking.tsx";
import type { Search } from "./pages/Booking.tsx";
import {
  CheckinPage,
  NoTripPage,
  TripsPage,
  WalletPage,
} from "./pages/Checkin.tsx";
import type { Confirmation } from "./pages/Checkin.tsx";

type Page = "book" | "checkin" | "trips" | "wallet";

/** The address of each page. Real paths mean a page can be linked to, refreshed, and left with the Back button. */
const PAGE_PATH: Record<Page, string> = {
  book: "/book",
  checkin: "/checkin",
  trips: "/trips",
  wallet: "/wallet",
};
const ADMIN_PATH = "/admin";

function cleanPath(path: string): string {
  const p = path.replace(/\/+$/, "");
  return p === "" ? "/" : p;
}
export function pageFromPath(path: string): Page | null {
  const p = cleanPath(path);
  const hit = (Object.keys(PAGE_PATH) as Page[]).find((k) => PAGE_PATH[k] === p);
  return hit ?? null;
}
/** Every address the app answers. Anything else shows the not-found page. */
function isKnownPath(path: string): boolean {
  const p = cleanPath(path);
  return p === "/" || p === ADMIN_PATH || p === "/index.html" || pageFromPath(p) !== null;
}

function NotFoundPage() {
  return (
    <div role="alert" className="app-status">
      <h1>Page not found</h1>
      <p>That address does not exist in PerkFlex.</p>
      <button className="button primary" onClick={() => window.location.assign("/")}>
        Go to PerkFlex
      </button>
    </div>
  );
}
const cityOf = (code: string) =>
  AIRPORTS.find((a) => a.code === code)?.city ?? code;

type OpenModal =
  | "welcome"
  | "suggest"
  | "assistant"
  | "profile"
  | "info"
  | "confirmation"
  | "book"
  | "booked"
  | null;
/** Loads the signed-in traveller from the server, or shows the sign-in page. */
export default function App() {
  const t = useTravellerState();
  // The airline account lives at /admin and nobody else does. This is decided from who is signed in, before anything
  // is drawn, so a traveller never sees the airline address (even straight after the airline signed out):
  //   airline signed in -> the address is /admin;  traveller signed in at /admin -> the address is "/";
  //   nobody signed in  -> the address is "/" too, so the next person to sign in starts clean.
  // Setting the address twice does nothing, so doing it while drawing is safe.
  const here = cleanPath(window.location.pathname);
  if (t.status === "admin" && here !== ADMIN_PATH) window.history.replaceState(null, "", ADMIN_PATH);
  else if ((t.status === "ready" || t.status === "signed-out") && here === ADMIN_PATH) window.history.replaceState(null, "", "/");
  if (t.status === "loading")
    return (
      <p role="status" className="app-status">
        Loading PerkFlex…
      </p>
    );
  if (t.status === "error")
    return (
      <div role="alert" className="app-status">
        <p>{t.problem}</p>
        <button className="button primary" onClick={() => void t.reload()}>
          Try again
        </button>
      </div>
    );
  if (t.status === "admin")
    return (
      <AdminPage
        onSignOut={async () => {
          await api.logout().catch(() => {});
          t.signedOut();
        }}
      />
    );
  if (t.state && !isKnownPath(window.location.pathname)) return <NotFoundPage />;
  if (!t.state)
    return (
      <LoginPage
        onLogin={async () => {
          await t.reload();
        }}
      />
    );
  return (
    <>
      <TravellerApp
        // A new traveller (demo switch) or a demo reset gets a fresh screen.
        key={`${t.state.profile.id}:${t.epoch}`}
        server={t.state}
        busy={t.busy}
        dispatch={t.dispatch}
        onSignOut={async () => {
          await api.logout().catch(() => {});
          t.signedOut();
        }}
      />
      {t.state.demo && (
        <PresenterGuide
          currentLogin={t.state.profile.id}
          busy={t.busy}
          onGo={(id) => void t.dispatch({ type: "profile", id })}
          onReset={() => void t.dispatch({ type: "demo-reset" })}
          dispatch={t.dispatch}
        />
      )}
    </>
  );
}

function TravellerApp({
  server,
  busy,
  dispatch,
  onSignOut,
}: {
  server: ServerState;
  busy: boolean;
  dispatch: (action: Action, key?: string) => Promise<ServerState | null>;
  onSignOut: () => void;
}) {
  const state = useMemo(() => toStore(server), [server]);
  const profile = server.profile;
  const booking = state.bookings[profile.id];
  const hasTrip = Boolean(booking);
  const canSwitch = server.demo && server.travellers.length > 0;
  // "Reset demo" asks for a second click within five seconds, so it cannot be hit by accident.
  const [resetArmed, setResetArmed] = useState(false);
  // Someone with a trip starts at check-in; a new traveller starts on Book a flight.
  // The address decides the page on load; "/" falls back to check-in (with a trip) or Book a flight.
  const [startPage] = useState<Page>(() => pageFromPath(window.location.pathname) ?? (hasTrip ? "checkin" : "book"));
  const [page, setPage] = useState<Page>(startPage),
    [modal, setModal] = useState<OpenModal>(hasTrip && startPage === "checkin" ? "welcome" : null),
    [assistantStep, setAssistantStep] = useState(0),
    [results, setResults] = useState(false),
    [mobileNav, setMobileNav] = useState(false);
  const [needs, setNeeds] = useState({ ...profile.needs });
  const [search, setSearch] = useState<Search>({
    from: "DAL",
    to: "DEN",
    date: "2026-10-22",
    flightId: "WN2418",
  });
  const [confirm, setConfirm] = useState<Confirmation | null>(null),
    [confirmKey, setConfirmKey] = useState(""),
    [selectedFare, setSelectedFare] = useState<FareId>("extra");
  useEffect(() => {
    if (!state.notice) return;
    const timer = window.setTimeout(
      () => dispatch({ type: "clear-notice" }),
      7500,
    );
    return () => window.clearTimeout(timer);
  }, [state.notice]);
  // Keep the address in step with the page: push a new entry for a move between pages, replace an unknown address.
  useEffect(() => {
    const want = PAGE_PATH[page];
    if (cleanPath(window.location.pathname) === want) return;
    const known = pageFromPath(window.location.pathname) !== null;
    if (known) window.history.pushState(null, "", want);
    else window.history.replaceState(null, "", want);
  }, [page]);
  // The Back and Forward buttons move between pages.
  useEffect(() => {
    const onPop = () => {
      const next = pageFromPath(window.location.pathname);
      if (next) {
        setPage(next);
        setModal(null);
        setMobileNav(false);
      }
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  // Fares priced by the server for the flight and needs on screen.
  const quotes = useQuotes(
    {
      flightId: search.flightId,
      from: search.from,
      to: search.to,
      date: search.date,
    },
    needs,
    page === "book" &&
      (results || modal === "book") &&
      search.from !== search.to,
  );
  function navigate(next: Page) {
    if (next === "checkin")
      dispatch({ type: "open-checkin", profileId: profile.id });
    setPage(next);
    setMobileNav(false);
    if (next === "book") setAssistantStep(0);
    // Book a flight shows the search form; the assistant is offered after Search flights.
    setModal(null);
    window.scrollTo({ top: 0, behavior: "instant" });
  }
  function openAssistant() {
    setAssistantStep(0);
    setModal(page === "book" || !hasTrip ? "assistant" : "welcome");
  }
  // Search flights first recommends the assistant; "Skip" goes straight to fares.
  function askSearch() {
    if (search.from === search.to) searchFlights();
    else setModal("suggest");
  }
  function searchFlights() {
    if (search.from === search.to) {
      setConfirm(null);
      dispatch({
        type: "book",
        profileId: profile.id,
        fare: "basic",
        ...search,
        needs,
      });
      return;
    }
    setResults(true);
    setPage("book");
    setModal(null);
    window.scrollTo({ top: 0, behavior: "instant" });
  }
  function pickProfile(id: string) {
    setModal(null);
    void dispatch({ type: "profile", id });
  }
  async function book() {
    const next = await dispatch({
      type: "book",
      fare: selectedFare,
      ...search,
      needs,
    });
    setModal(next && !next.error ? "booked" : null);
  }
  const selectedQuote = quotes.data?.quotes.find(
    (q) => q.fare === selectedFare,
  );
  return (
    <>
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <header className="site-header">
        <div className="container header-top">
          <button
            className="brand"
            onClick={() => navigate("checkin")}
            aria-label="PerkFlex home"
          >
            <PerkFlexLogo />
          </button>
          <div className="header-right">
            <button className="help-button" onClick={() => setModal("info")}>
              <CircleHelp size={16} /> Help
            </button>
            <button className="header-signout" onClick={onSignOut}>
              <LogOut size={15} /> Sign out
            </button>
            <button
              className="header-wallet"
              onClick={() => navigate("wallet")}
            >
              <Coins size={16} />
              <strong>{fmt(state.wallets.rapidRewards.available)}</strong>
              <span>Rapid Rewards</span>
              <strong>{fmt(state.wallets.perkflex.available)}</strong>
              <span>PerkFlex</span>
            </button>
            <button
              className="profile-button"
              onClick={() => canSwitch && setModal("profile")}
            >
              <span className={`avatar avatar-small ${profile.color}`}>
                {profile.initials}
              </span>
              <span>
                Hi, {greetingName(profile)}
                <small>
                  {profile.tier === "Member"
                    ? "Rapid Rewards Member"
                    : `${profile.tier} member`}
                </small>
              </span>
              <ChevronDown size={15} />
            </button>
            <button
              className="icon-button mobile-menu"
              onClick={() => setMobileNav(!mobileNav)}
              aria-label="Toggle navigation"
              aria-expanded={mobileNav}
            >
              <Menu size={23} />
            </button>
          </div>
        </div>
        <div className="container nav-row">
          <nav className={mobileNav ? "open" : ""} aria-label="Main navigation">
            {(
              [
                { id: "book", label: "Book a flight" },
                { id: "checkin", label: "Check in" },
                { id: "trips", label: "My trips" },
                { id: "wallet", label: "Rapid Rewards" },
              ] as { id: Page; label: string }[]
            ).map((item) => (
              <button
                key={item.id}
                className={page === item.id ? "active" : ""}
                aria-current={page === item.id ? "page" : undefined}
                onClick={() => navigate(item.id)}
              >
                {item.label}
                {item.id === "checkin" && booking?.status === "booked" && (
                  <span className="nav-notification" />
                )}
              </button>
            ))}
          </nav>
        </div>
      </header>
      <div className="announcement">
        <div className="container">
          <Heart size={15} />
          <span>
            Your benefits, working together. Explore a more personal way to fly
            with <strong>PerkFlex.</strong>
          </span>
          <button onClick={openAssistant}>
            {page === "book" ? "Find my fit" : "Meet my assistant"}{" "}
            <ChevronDown size={14} />
          </button>
        </div>
      </div>
      <div id="main-content" tabIndex={-1}>
        {page === "book" ? (
          <BookingPage
            profile={profile}
            needs={needs}
            data={quotes.data}
            promos={state.promos}
            quotesFailed={quotes.failed}
            search={search}
            onSearchChange={setSearch}
            results={results}
            onSearch={askSearch}
            onAssistant={openAssistant}
            onBook={(id) => {
              setSelectedFare(id);
              setModal("book");
            }}
            onBack={() => setResults(false)}
          />
        ) : (page === "checkin" || page === "trips") && !hasTrip ? (
          <NoTripPage
            profile={profile}
            heading={page === "checkin" ? "Check in." : "Your trips."}
            onBook={() => navigate("book")}
          />
        ) : page === "checkin" ? (
          <CheckinPage
            state={state}
            profile={profile}
            dispatch={dispatch}
            confirm={(c) => {
              setConfirm(c);
              setConfirmKey(crypto.randomUUID());
              setModal("confirmation");
            }}
            onWallet={() => navigate("wallet")}
          />
        ) : page === "trips" ? (
          <TripsPage
            state={state}
            profile={profile}
            onCheckin={() => navigate("checkin")}
            onBook={() => navigate("book")}
          />
        ) : (
          <WalletPage
            state={state}
            profile={profile}
            onCheckin={() => navigate("checkin")}
            dispatch={dispatch}
          />
        )}
      </div>
      <footer className="site-footer">
        <div className="container footer-main">
          <div>
            <div className="footer-brand">
              <PerkFlexLogo compact />
              <span>A little more you.</span>
            </div>
            <p>Make more of every trip, from booking to boarding.</p>
          </div>
          <div className="footer-actions">
            {canSwitch && (
              <button onClick={() => setModal("profile")}>
                Traveller profiles
              </button>
            )}
            {server.demo && (
              <button
                disabled={busy}
                onClick={() => {
                  if (!resetArmed) {
                    setResetArmed(true);
                    window.setTimeout(() => setResetArmed(false), 5000);
                    return;
                  }
                  setResetArmed(false);
                  void dispatch({ type: "demo-reset" });
                }}
              >
                {resetArmed ? "Click again to reset the demo" : "Reset demo"}
              </button>
            )}
            <button onClick={() => setModal("info")}>How it works</button>
          </div>
        </div>
        <div className="container footer-bottom">
          <p>PerkFlex. Your journey. Your choices. A little more rewarding.</p>
          <span>
            Built with a little <Heart size={12} />
          </span>
        </div>
      </footer>
      {state.notice && (
        <div
          className={`toast ${state.error ? "error" : ""}`}
          role={state.error ? "alert" : "status"}
        >
          {state.error ? <Info size={21} /> : <CheckCircle2 size={21} />}
          <span>{state.notice}</span>
          <button
            className="icon-button"
            onClick={() => dispatch({ type: "clear-notice" })}
            aria-label="Dismiss notification"
          >
            <X size={17} />
          </button>
        </div>
      )}
      {modal === "welcome" && booking && (
        <WelcomeOverlay
          profile={profile}
          booking={booking}
          balance={state.balances[profile.id]}
          wallets={state.wallets}
          onClose={() => setModal(null)}
          onReview={() => {
            setModal(null);
            window.setTimeout(
              () =>
                document
                  .getElementById("perkflex-benefits")
                  ?.scrollIntoView?.({ behavior: "smooth", block: "start" }),
              0,
            );
          }}
        />
      )}
      {modal === "suggest" && (
        <Modal title="Before you search" onClose={() => setModal(null)}>
          <div className="modal-padding suggest-modal">
            <Pill tone="lavender">
              <Sparkles size={14} /> Recommended
            </Pill>
            <p className="suggest-route">
              {cityOf(search.from)} ({search.from}) to {cityOf(search.to)} (
              {search.to}) · <DateLabel date={search.date} />
            </p>
            <p className="modal-intro">
              PerkFlex AI can swap benefits you don’t need for points, or use
              points for ones you do, and suggest the seat and fare that fit
              your trip best.
            </p>
            <div className="suggest-actions">
              <button
                className="button primary"
                onClick={() => {
                  setAssistantStep(0);
                  setModal("assistant");
                }}
              >
                <PerkMark small /> Meet PerkFlex AI (recommended)
              </button>
              <button className="button secondary" onClick={searchFlights}>
                Skip, show fares
              </button>
            </div>
          </div>
        </Modal>
      )}
      {modal === "assistant" && (
        <Assistant
          profile={profile}
          needs={needs}
          onNeeds={setNeeds}
          flightId={search.flightId}
          from={search.from}
          to={search.to}
          date={search.date}
          step={assistantStep}
          onStep={setAssistantStep}
          onClose={() => setModal(null)}
          onApply={searchFlights}
        />
      )}
      {modal === "profile" && (
        <Modal
          title="Choose a traveller"
          onClose={() => setModal(null)}
          wide
          className="profile-modal"
        >
          <div className="modal-padding">
            <Pill tone="lavender">
              <Sparkles size={14} /> Traveller profiles
            </Pill>
            <h2>Same journey. Different kinds of you.</h2>
            <p className="modal-intro">
              View a traveller’s saved trip, points, and included benefits.
            </p>
            <div className="profile-grid">
              {server.travellers.map((p) => (
                <button
                  key={p.id}
                  className={`profile-option ${p.id === profile.id ? "selected" : ""}`}
                  onClick={() => pickProfile(p.id)}
                >
                  <div>
                    <span className={`avatar ${p.color}`}>{p.initials}</span>
                    {p.id === profile.id ? (
                      <CheckCircle2 size={18} />
                    ) : (
                      <ArrowRight size={17} />
                    )}
                  </div>
                  <h3>{p.name}</h3>
                  <Pill
                    tone={
                      p.tier === "Gold"
                        ? "gold"
                        : p.tier === "Platinum"
                          ? "platinum"
                          : p.tier === "Silver"
                            ? "silver"
                            : "blue"
                    }
                  >
                    {p.tier === "Member" ? "No elite tier" : p.tier}
                    {p.card !== "None" ? ` · ${p.card} card` : ""}
                  </Pill>
                  <p>{p.description}</p>
                  <span className="profile-points">
                    <Coins size={14} />
                    {fmt(p.points)} available points
                  </span>
                </button>
              ))}
            </div>
          </div>
        </Modal>
      )}
      {modal === "confirmation" && confirm && (
        <Modal title={confirm.title} onClose={() => setModal(null)}>
          <div className="modal-padding confirm-modal">
            <span className="confirmation-icon">
              <RefreshIcon points={confirm.points} />
            </span>
            <Pill tone={confirm.points >= 0 ? "mint" : "blue"}>
              {confirm.pending
                ? "A PerkFlex reward offer"
                : "A PerkFlex benefit offer"}
            </Pill>
            <h2>{confirm.title}</h2>
            <p className="modal-intro">{confirm.description}</p>
            <div className="before-after">
              <div>
                <span>BEFORE</span>
                <strong>{confirm.before}</strong>
              </div>
              <ArrowDown size={20} />
              <div>
                <span>AFTER</span>
                <strong>{confirm.after}</strong>
              </div>
            </div>
            <div className="confirm-points">
              <Coins size={23} />
              <strong>
                {confirm.points > 0 ? "+" : ""}
                {fmt(confirm.points)} points
              </strong>
              <span>
                {confirm.pending
                  ? "Pending until completed travel"
                  : confirm.points === 0
                    ? "Already included in your benefits"
                    : "Deducted from your available balance"}
              </span>
            </div>
            <p className="confirm-terms">
              {confirm.pending
                ? "This is voluntary and applies only to this flight. Your fare refundability is unchanged. An accepted reward does not require another traveller to buy the released benefit."
                : "Your updated allowance or seat will be added to this trip. Your available points balance will update when you confirm."}
            </p>
            <div className="confirm-buttons">
              <button
                className="button secondary"
                onClick={() => setModal(null)}
              >
                Keep things as they are
              </button>
              <button
                className="button primary"
                disabled={busy}
                onClick={() => {
                  void dispatch(confirm.action, confirmKey);
                  setModal(null);
                }}
              >
                {confirm.label}
                <Check size={16} />
              </button>
            </div>
          </div>
        </Modal>
      )}
      {modal === "book" && selectedQuote && (
        <Modal title="Review your booking" onClose={() => setModal(null)}>
          <div className="modal-padding">
            <Pill tone="blue">
              <Plane size={14} /> One step to your next trip
            </Pill>
            <h2>Looking good, {greetingName(profile)}.</h2>
            <p className="modal-intro">
              Review your fare and benefits before you confirm.
            </p>
            <div className="booking-summary-route">
              <strong>{search.from}</strong>
              <Plane size={23} />
              <strong>{search.to}</strong>
              <span>
                <DateLabel date={search.date} />
              </span>
            </div>
            <div className="summary-fare">
              <TicketIcon />
              <div>
                <strong>{fareById(selectedFare).name}</strong>
                <span>
                  {SEAT_NAMES[selectedQuote.seat]} · {selectedQuote.bags}{" "}
                  checked bag{selectedQuote.bags === 1 ? "" : "s"}
                </span>
              </div>
            </div>
            <div className="price-breakdown">
              <div>
                <span>Base fare</span>
                <strong>{money(selectedQuote.base)}</strong>
              </div>
              {selectedQuote.addons.map((a) => (
                <div key={a.label}>
                  <span>{a.label}</span>
                  <strong>{money(a.price)}</strong>
                </div>
              ))}
              <div>
                <span>Taxes & fees</span>
                <strong>{money(selectedQuote.tax)}</strong>
              </div>
              <div className="price-total">
                <span>Your total</span>
                <strong>{money(selectedQuote.total)}</strong>
              </div>
            </div>
            <p className="confirm-terms">
              <ShieldCheck size={15} /> Your selected fare and benefits will
              appear in My trips.
            </p>
            <button
              className="button primary full-width"
              disabled={busy || !selectedQuote}
              onClick={() => void book()}
            >
              Confirm booking <ArrowRight size={18} />
            </button>
          </div>
        </Modal>
      )}
      {modal === "booked" && (
        <Modal title="Your flight is booked" onClose={() => setModal(null)}>
          <div className="modal-padding booked-modal">
            <div className="success-ring">
              <Check size={35} />
            </div>
            <Pill tone="mint">You’re going places</Pill>
            <h2>Next stop: {search.to}.</h2>
            <p>
              Your <strong>{fareById(selectedFare).name}</strong> trip is
              booked. Let’s jump ahead to check-in and see what PerkFlex can do
              for your unused benefits.
            </p>
            <div className="confirmation-number">
              <span>YOUR CONFIRMATION</span>
              <strong>{booking?.id}</strong>
            </div>
            <button
              className="button primary full-width"
              onClick={() => navigate("checkin")}
            >
              <Clock3 size={18} /> Jump to web check-in <ArrowRight size={18} />
            </button>
            <button className="text-button" onClick={() => navigate("trips")}>
              View my trip
            </button>
            <small>Review your benefits before completing check-in.</small>
          </div>
        </Modal>
      )}
      {modal === "info" && (
        <Modal title="How PerkFlex works" onClose={() => setModal(null)}>
          <div className="modal-padding info-modal">
            <PerkMark />
            <h2>
              Good perks.
              <br />
              An even better fit.
            </h2>
            <p className="modal-intro">
              Get more from the benefits that fit the way you travel.
            </p>
            <ol>
              <li>
                <strong>Before booking</strong>
                <p>
                  Tell PerkFlex what you need. Compare fares with your existing
                  tier and card benefits included.
                </p>
              </li>
              <li>
                <strong>Before check-in</strong>
                <p>
                  Voluntarily release an eligible unused bag allowance or swap a
                  premium seat for a Standard seat. A reward becomes pending.
                </p>
              </li>
              <li>
                <strong>After flying</strong>
                <p>
                  Accepted rewards post after completed travel. Use your
                  available points for eligible benefits on a trip.
                </p>
              </li>
            </ol>
            {canSwitch && (
              <button
                className="button primary full-width"
                onClick={() => {
                  setModal("profile");
                }}
              >
                View traveller profiles <ArrowRight size={17} />
              </button>
            )}
          </div>
        </Modal>
      )}
    </>
  );
}
function RefreshIcon({ points }: { points: number }) {
  return points >= 0 ? <Sparkles size={30} /> : <Wallet size={30} />;
}
function TicketIcon() {
  return <Plane size={24} />;
}
