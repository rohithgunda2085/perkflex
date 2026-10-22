import { useState } from "react";
import {
  ArrowRight,
  Armchair,
  Check,
  ChevronRight,
  Coins,
  Eye,
  EyeOff,
  LockKeyhole,
  Luggage,
  Plane,
  ShieldCheck,
  Sparkles,
  UserRound,
} from "lucide-react";
import { PerkFlexLogo, Modal, Pill } from "../components/components.tsx";
import { fmt, fareById, SEAT_NAMES } from "../rules/data.ts";
import { greetingName } from "../rules/helpers.ts";
import type { Booking, Profile } from "../rules/types.ts";
import { ApiError, api } from "../services/api.ts";

export function LoginPage({
  onLogin,
}: {
  onLogin: () => void | Promise<void>;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [visible, setVisible] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit() {
    setBusy(true);
    try {
      const { user } = await api.login(username, password);
      if (!user.profileId) {
        setError("This account does not have a traveller view in this demo.");
        return;
      }
      setPassword("");
      await onLogin();
    } catch (e) {
      setError(
        e instanceof ApiError || e instanceof Error
          ? e.message
          : "Please try again.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="login-shell">
      <header className="login-header">
        <div className="container">
          <PerkFlexLogo />
          <span>
            <ShieldCheck size={15} /> Your journey starts here.
          </span>
        </div>
      </header>
      <main className="container login-layout">
        <section className="login-story">
          <span className="eyebrow">
            A LITTLE MORE YOU, EVERY TIME YOU FLY.
          </span>
          <h1>
            Your next flight. <br />
            All your perks.
          </h1>
          <p>
            Your flight is booked. Let’s get you checked in and make the most of
            the benefits that come with it.
          </p>
          <div className="login-ticket">
            <div className="login-ticket-top">
              <span>
                <Plane size={17} /> YOUR NEXT ADVENTURE
              </span>
              <span>
                <Check size={12} /> Confirmed
              </span>
            </div>
            <div className="login-route">
              <div>
                <strong>DAL</strong>
                <span>Dallas (Love Field)</span>
              </div>
              <div>
                <span />
                <Plane size={22} />
                <span />
              </div>
              <div>
                <strong>DEN</strong>
                <span>Denver</span>
              </div>
            </div>
            <div className="login-ticket-bottom">
              <span>
                <Armchair size={16} /> Extra Legroom
              </span>
              <span>
                <Luggage size={16} /> 2 checked bags
              </span>
              <span>
                <Sparkles size={15} /> PerkFlex ready
              </span>
            </div>
          </div>
          <div className="login-story-note">
            <ShieldCheck size={18} />
            <span>
              The benefits you have. The choices you want.
              <br />
              <strong>All in one place.</strong>
            </span>
          </div>
        </section>
        <section className="login-card">
          <span className="login-lock">
            <LockKeyhole size={24} />
          </span>
          <h2>Welcome back.</h2>
          <p>Log in to view your trip and check in.</p>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void submit();
            }}
          >
            <label htmlFor="login-username">Username</label>
            <div className="login-input">
              <UserRound size={18} />
              <input
                id="login-username"
                name="username"
                autoComplete="username"
                placeholder="Enter your username"
                required
                value={username}
                onChange={(e) => {
                  setUsername(e.target.value);
                  setError("");
                }}
              />
            </div>
            <label htmlFor="login-password">Password</label>
            <div className="login-input">
              <LockKeyhole size={17} />
              <input
                id="login-password"
                name="password"
                autoComplete="current-password"
                placeholder="Enter your password"
                required
                type={visible ? "text" : "password"}
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                  setError("");
                }}
              />
              <button
                type="button"
                aria-label={visible ? "Hide password" : "Show password"}
                onClick={() => setVisible(!visible)}
              >
                {visible ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>
            {error && (
              <p className="login-error" role="alert">
                {error}
              </p>
            )}
            <button
              className="button primary full-width"
              type="submit"
              disabled={busy}
            >
              Log in & check in <ArrowRight size={18} />
            </button>
          </form>
          <div className="login-card-foot">
            <ShieldCheck size={15} />
            <span>Your points, perks, and trip in one account.</span>
          </div>
        </section>
      </main>
      <footer className="login-footer">
        <PerkFlexLogo compact />
        <span>A little more rewarding. A lot more you.</span>
      </footer>
    </div>
  );
}

export function WelcomeOverlay({
  profile,
  booking,
  balance,
  onClose,
  onReview,
}: {
  profile: Profile;
  booking: Booking;
  balance: number;
  onClose: () => void;
  onReview: () => void;
}) {
  return (
    <Modal
      title="Welcome to Southwest"
      onClose={onClose}
      wide
      className="welcome-modal"
    >
      <div className="welcome-layout">
        <aside className="welcome-aside">
          <PerkFlexLogo />
          <div className="welcome-aside-copy">
            <span>YOUR TRIP IS ALREADY BOOKED.</span>
            <h2>
              Now, let’s make <br />
              every perk <br />
              count.
            </h2>
            <p>
              Good choices before takeoff.
              <br />A little more value after.
            </p>
          </div>
          <div className="welcome-trip">
            <div>
              <Plane size={19} />
              <span>
                {booking.from} <ChevronRight size={13} /> {booking.to}
              </span>
              <Pill tone="white">Confirmed</Pill>
            </div>
            <strong>{fareById(booking.fare).name}</strong>
            <small>Confirmation {booking.id}</small>
          </div>
          <div className="welcome-aside-footer">
            <span className={`avatar ${profile.color}`}>
              {profile.initials}
            </span>
            <span>
              {profile.name}
              <small>
                {profile.tier === "Member"
                  ? "Rapid Rewards Member"
                  : `${profile.tier} member`}
              </small>
            </span>
          </div>
        </aside>
        <section className="welcome-main">
          <Pill tone="lavender">
            <Sparkles size={14} /> YOUR PERSONAL TRAVEL ASSISTANT
          </Pill>
          <h1>
            Welcome to Southwest, <br />
            <span>{greetingName(profile)}.</span>
          </h1>
          <h2>I’m PerkFlex, your travel assistant.</h2>
          <p>
            I’m here to help you get the most from your benefits and choose the
            right fare for every trip.
          </p>
          <p>
            You’ve already booked. Let’s review what’s included and find the
            perks that work best for you before check-in.
          </p>
          <div className="welcome-perks">
            <div>
              <Luggage size={22} />
              <strong>{booking.bags} checked bags</strong>
              <span>Included with this trip</span>
            </div>
            <div>
              <Armchair size={22} />
              <strong>{SEAT_NAMES[booking.seatClass]}</strong>
              <span>Your seat: {booking.seat}</span>
            </div>
            <div>
              <Coins size={22} />
              <strong>{fmt(balance)} points</strong>
              <span>Ready when you need them</span>
            </div>
          </div>
          <div className="welcome-insight">
            <Sparkles size={19} />
            <span>
              {booking.released
                ? "Your accepted offer is saved. Review your updated benefits before you continue."
                : booking.bags > booking.actualBags
                  ? `Travelling light? You may be able to turn an unused bag allowance into points.`
                  : "Want a little more comfort? I’ll show you the benefits available for this flight."}
            </span>
          </div>
          <button className="button primary full-width" onClick={onReview}>
            Show my benefits <ArrowRight size={18} />
          </button>
          <button className="welcome-skip" onClick={onClose}>
            Continue to check-in
          </button>
        </section>
      </div>
    </Modal>
  );
}
