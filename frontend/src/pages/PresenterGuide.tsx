import { useRef, useState } from "react";
import type { Action, ServerState } from "../rules/types.ts";

/**
 * A presenter's script for the live demo, shown only in demo mode. It lives above the traveller screens, so it
 * keeps its place when "Go to" switches traveller. It changes nothing by itself: "Go to" uses the demo switcher.
 */
export type Scene = {
  id: string;
  title: string;
  /** The demo traveller to show, or null when the scene is not tied to one. */
  login: string | null;
  who: string;
  say: string;
  doThis: string;
  /** What "Run this scene" does, step by step, through the same API the screens use. */
  steps?: Step[];
};

export type Step = {
  action: Action;
  /** Shown while the step runs when the server gives no notice of its own. */
  say: string;
  /** The aria-label of the region to scroll to and highlight afterwards. */
  show?: string;
};

/** Pauses between steps, in milliseconds. Tests set this to 0. */
export const timing = { pause: 1300 };

export const SCENES: Scene[] = [
  {
    id: "reset",
    title: "Start clean",
    login: null,
    who: "Everyone",
    say: "Every run starts from the same trips, points and rewards.",
    doThis: "Press Reset demo and confirm. Then go to the first scene.",
  },
  {
    id: "release-bag",
    title: "Release an unused bag",
    login: "kabir",
    who: "Kabir (Platinum)",
    say: "Kabir’s status covers three bags, but he is only bringing two.",
    doThis: "On Check in, give up a bag. 1,040 points are pending until he flies: 800 plus his 30% Platinum bonus.",
    steps: [
      { action: { type: "open-checkin" }, say: "Opening check-in." },
      { action: { type: "release", benefit: "bag" }, say: "Releasing the unused bag.", show: "Undo a release" },
    ],
  },
  {
    id: "release-seat",
    title: "Swap a premium seat",
    login: "neha",
    who: "Neha (Choice Preferred)",
    say: "Neha does not mind where she sits, so her Preferred seat can earn points.",
    doThis: "Choose the seat swap. 700 points are pending. Only one bag-or-seat reward per flight.",
    steps: [
      { action: { type: "open-checkin" }, say: "Opening check-in." },
      { action: { type: "release", benefit: "seat" }, say: "Swapping to a Standard seat.", show: "Undo a release" },
    ],
  },
  {
    id: "buy-bag",
    title: "Buy a bag with points",
    login: "ravi",
    who: "Ravi (Basic fare)",
    say: "Ravi needs a checked bag his Basic fare does not include.",
    doThis: "Add a checked bag. It costs 3,000 of his 6,000 points.",
    steps: [
      { action: { type: "open-checkin" }, say: "Opening check-in." },
      { action: { type: "redeem", benefit: "bag" }, say: "Adding a checked bag with points." },
    ],
  },
  {
    id: "buy-seat",
    title: "Buy a better seat",
    login: "dev",
    who: "Dev (Choice)",
    say: "Dev wants to sit near the front.",
    doThis: "Choose the Preferred seat for 2,200 points.",
    steps: [
      { action: { type: "open-checkin" }, say: "Opening check-in." },
      { action: { type: "redeem", benefit: "preferred" }, say: "Buying the Preferred seat." },
    ],
  },
  {
    id: "small-release",
    title: "Small perks: release",
    login: "rohith",
    who: "Rohith (Silver, Choice Extra)",
    say: "Small perks sit beside the one reward. They never use it up.",
    doThis: "In Small perks, release the drink and the lane. 200 points, pending.",
    steps: [
      { action: { type: "open-checkin" }, say: "Opening check-in." },
      { action: { type: "release", benefit: "drink" }, say: "Releasing the premium drink.", show: "Small perks" },
      { action: { type: "release", benefit: "lane" }, say: "Releasing priority lane access.", show: "Small perks" },
    ],
  },
  {
    id: "small-buy",
    title: "Small perks: buy",
    login: "manish",
    who: "Manish (25,000 points)",
    say: "Manish has no status, so boarding and a drink are for sale.",
    doThis: "Add priority boarding (900 points) and a premium drink (600 points).",
    steps: [
      { action: { type: "open-checkin" }, say: "Opening check-in." },
      { action: { type: "redeem", benefit: "boarding" }, say: "Adding priority boarding.", show: "Small perks" },
      { action: { type: "redeem", benefit: "drink" }, say: "Adding a premium drink.", show: "Small perks" },
    ],
  },
  {
    id: "undo",
    title: "Changed your mind? Undo",
    login: "leena",
    who: "Leena (Choice Preferred)",
    say: "A release can be taken back for 10 seconds, while check-in is open and nobody has taken the seat.",
    doThis: "Release the seat, then press Undo. The seat and the pending points come back.",
    steps: [
      { action: { type: "open-checkin" }, say: "Opening check-in." },
      { action: { type: "release", benefit: "seat" }, say: "Releasing the Extra Legroom seat.", show: "Undo a release" },
      { action: { type: "undo", benefit: "seat" }, say: "Changing her mind: undoing the release." },
    ],
  },
  {
    id: "fills",
    title: "The flight fills up",
    login: "harshini",
    who: "Harshini (Choice)",
    say: "Released seats and bag space do not go to waste. Other travellers on the flight use them.",
    doThis: "Release the seat, then let other travellers act and watch the reuse card.",
    steps: [
      { action: { type: "open-checkin" }, say: "Opening check-in." },
      { action: { type: "release", benefit: "seat" }, say: "Releasing the Extra Legroom seat.", show: "Undo a release" },
      { action: { type: "demo-simulate" }, say: "Another traveller takes the open seat.", show: "Your released benefits" },
      { action: { type: "demo-simulate" }, say: "Another traveller adds a bag.", show: "Notifications" },
    ],
  },
  {
    id: "spend-order",
    title: "Choose what to spend first",
    login: "manish",
    who: "Manish (PerkFlex and Rapid Rewards)",
    say: "Points can be spent PerkFlex first, or Rapid Rewards first. It is the traveller’s choice.",
    doThis: "Switch the spend order, then add the overweight allowance and watch which wallet pays.",
    steps: [
      { action: { type: "open-checkin" }, say: "Opening check-in." },
      { action: { type: "payment-order", rapidFirst: true }, say: "Spending Rapid Rewards first.", show: "Spend order" },
      { action: { type: "redeem", benefit: "overweight" }, say: "Adding the overweight allowance.", show: "Small perks" },
    ],
  },
  {
    id: "expiry",
    title: "Points that expire",
    login: "manish",
    who: "Manish (1,500 PerkFlex expiring)",
    say: "PerkFlex points last 12 months from when they post. The oldest are spent first.",
    doThis: "Open Wallet and point at the expiry notice. Spending the points first avoids the loss.",
  },
  {
    id: "next-flight",
    title: "Plan the next flight",
    login: "rohith",
    who: "Rohith (Silver)",
    say: "The wallet shows what the points held now would cover on the next flight, plus status progress and the earned-and-used chart.",
    doThis: "Open Wallet and scroll through the next-flight preview, the chart and the status card.",
  },
  {
    id: "advisor",
    title: "Ask the advisor",
    login: "harshini",
    who: "Harshini (Platinum, Priority card)",
    say: "The advisor only suggests. The rules decide what is possible and what it costs.",
    doThis: "Press Ask the advisor. It should point at the bag she is not using.",
  },
  {
    id: "completion-bonus",
    title: "A bonus for completing the trip",
    login: "sean.lynch",
    who: "Sean (Platinum)",
    say: "Sean releases a bag, flies, and completes the trip. A small bonus is added on top of the points for the release.",
    doThis: "Run the scene, then open Wallet: the release points and a 50-point completion bonus are both in his history.",
    steps: [
      { action: { type: "open-checkin" }, say: "Opening check-in." },
      { action: { type: "release", benefit: "bag" }, say: "Releasing the unused bag.", show: "Undo a release" },
      { action: { type: "checkin" }, say: "Checking in." },
      { action: { type: "complete" }, say: "Completing the trip.", show: "Notifications" },
    ],
  },
  {
    id: "price-drop",
    title: "A points sale",
    login: "dev",
    who: "Dev (Choice fare)",
    say: "Dev wants a seat near the front. The airline puts the Preferred seat on sale on his flight.",
    doThis: "Run the scene. The Preferred seat shows the old and new price, and a sale message appears in Notifications.",
    steps: [
      { action: { type: "open-checkin" }, say: "Opening check-in." },
      { action: { type: "demo-sale", benefit: "preferred" }, say: "The airline puts the Preferred seat on sale.", show: "On sale for your flight" },
    ],
  },
  {
    id: "group-gift",
    title: "A travel group and a gift",
    login: "manish",
    who: "Manish and Kabir",
    say: "Manish invites Kabir to a travel group. Kabir accepts. Manish then gives him 500 PerkFlex points.",
    doThis: "Run the scene, then open Wallet to see the travel group and the gift.",
    steps: [
      { action: { type: "group-invite", companion: "kabir" }, say: "Manish invites Kabir." },
      { action: { type: "profile", id: "kabir" }, say: "Switching to Kabir." },
      { action: { type: "group-respond", group: "manish", accept: true }, say: "Kabir joins the group." },
      { action: { type: "profile", id: "manish" }, say: "Back to Manish." },
      { action: { type: "gift", to: "kabir", points: 500 }, say: "Manish gives Kabir 500 PerkFlex points.", show: "Travel group" },
    ],
  },
  {
    id: "finish",
    title: "Fly and see the value",
    login: null,
    who: "Any traveller who acted",
    say: "Points post only after the flight.",
    doThis: "Complete check-in, press Complete trip, then open Wallet to see what the points did.",
  },
  {
    id: "airline",
    title: "The airline’s view",
    login: null,
    who: "Airline account",
    say: "The airline funds the rewards, so it sees budget, points owed and cost per flight.",
    doThis: "Sign out and sign in with the airline account (see the credentials file).",
  },
];

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

/** Scrolls to a region and flashes it, so the audience sees where to look. */
function highlight(label?: string) {
  if (!label) return;
  const el = document.querySelector(`[aria-label="${label}"]`);
  if (!el) return;
  el.scrollIntoView?.({ behavior: "smooth", block: "center" });
  el.classList.add("flash");
  window.setTimeout(() => el.classList.remove("flash"), 1800);
}

export function PresenterGuide({
  currentLogin,
  onGo,
  onReset,
  busy,
  dispatch,
}: {
  currentLogin: string;
  onGo: (login: string) => void;
  onReset: () => void;
  busy: boolean;
  /** Runs a real action through the API. Resolves with the state to show, or null when the request failed. */
  dispatch: (action: Action, idempotencyKey?: string) => Promise<ServerState | null>;
}) {
  const [open, setOpen] = useState(false);
  const [index, setIndex] = useState(0);
  const [running, setRunning] = useState(false);
  const [caption, setCaption] = useState("");
  const stop = useRef(false);
  const login = useRef(currentLogin);
  login.current = currentLogin;
  const scene = SCENES[index];
  const here = scene.login !== null && scene.login === currentLogin;
  const runnable = Boolean(scene.steps?.length);

  /** Runs one scene's steps through the API. Returns false if a step was refused or the run was stopped. */
  async function runScene(sc: Scene): Promise<boolean> {
    if (sc.login && sc.login !== login.current) {
      setCaption(`Switching to ${sc.who.split(" (")[0]}.`);
      if (!(await dispatch({ type: "profile", id: sc.login }))) return false;
      await sleep(timing.pause);
    }
    for (const [i, step] of (sc.steps ?? []).entries()) {
      if (stop.current) return false;
      setCaption(step.say);
      const next = await dispatch(step.action, `story-${sc.id}-${i}-${Date.now()}`);
      if (!next || next.error) {
        setCaption(next?.notice || "That step did not go through, so the run stopped.");
        return false;
      }
      if (next.notice) setCaption(next.notice);
      await sleep(80);
      highlight(step.show);
      await sleep(timing.pause);
    }
    return true;
  }

  async function run(job: () => Promise<boolean>, doneText: string) {
    stop.current = false;
    setRunning(true);
    try {
      const ok = await job();
      if (ok) setCaption(doneText);
      else if (stop.current) setCaption("Stopped.");
    } finally {
      setRunning(false);
    }
  }

  const runThis = () => run(() => runScene(scene), "Scene complete.");
  const playStory = () =>
    run(async () => {
      setCaption("Resetting the demo.");
      if (!(await dispatch({ type: "demo-reset" }))) return false;
      await sleep(timing.pause);
      for (const sc of SCENES) {
        if (!sc.steps?.length) continue;
        setIndex(SCENES.indexOf(sc));
        if (!(await runScene(sc))) return false;
      }
      return true;
    }, "Story complete. Open Wallet, then sign in as the airline to finish.");

  return (
    <>
      <button
        className="presenter-toggle"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        {open ? "Hide guide" : "Presenter guide"}
      </button>
      {open && (
        <aside className="presenter-panel" aria-label="Presenter guide">
          <h2>Presenter guide</h2>
          <div className="presenter-story">
            <button className="button primary small-button" disabled={busy || running} onClick={() => void playStory()}>
              Play the whole story
            </button>
            {running && (
              <button className="button secondary small-button" onClick={() => (stop.current = true)}>
                Stop
              </button>
            )}
          </div>
          {caption && (
            <p className="presenter-caption" role="status">
              {caption}
            </p>
          )}
          <div className="presenter-step">
            Scene {index + 1} of {SCENES.length}
          </div>
          <div className="presenter-list" role="group" aria-label="Scenes">
            {SCENES.map((s, i) => (
              <button
                key={s.id}
                aria-current={i === index}
                aria-label={`Scene ${i + 1}: ${s.title}`}
                onClick={() => setIndex(i)}
              >
                {i + 1}
              </button>
            ))}
          </div>
          <div className="presenter-scene current">
            <strong>{scene.title}</strong>
            <small>{scene.who}</small>
            <p>{scene.say}</p>
            <p>
              <strong>Do:</strong> {scene.doThis}
            </p>
            <div className="presenter-actions">
              {scene.id === "reset" && (
                <button className="button primary small-button" disabled={busy || running} onClick={onReset}>
                  Reset demo now
                </button>
              )}
              {scene.login && (
                <button
                  className="button primary small-button"
                  disabled={busy || running || here}
                  onClick={() => onGo(scene.login as string)}
                >
                  {here ? "Already here" : `Go to ${scene.who.split(" (")[0]}`}
                </button>
              )}
              {runnable && (
                <button
                  className="button secondary small-button"
                  disabled={busy || running}
                  onClick={() => void runThis()}
                >
                  Run this scene
                </button>
              )}
            </div>
          </div>
          <div className="presenter-actions">
            <button
              className="button secondary small-button"
              disabled={index === 0}
              onClick={() => setIndex(index - 1)}
            >
              Back
            </button>
            <button
              className="button secondary small-button"
              disabled={index === SCENES.length - 1}
              onClick={() => setIndex(index + 1)}
            >
              Next scene
            </button>
          </div>
        </aside>
      )}
    </>
  );
}
