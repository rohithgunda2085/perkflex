// Component interaction checks in an in-memory DOM, against a scripted fake API. These do not replace browser visual QA.
// The real rules live in the Python API and are tested there; here we check what the screen sends and shows.
import test, { afterEach, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";
import React from "react";

const dom = new JSDOM("<!doctype html><html><body></body></html>", {
  url: "http://localhost:5173/",
});
for (const key of [
  "window",
  "document",
  "navigator",
  "HTMLElement",
  "HTMLDialogElement",
  "Node",
  "Event",
  "MouseEvent",
  "getComputedStyle",
  "localStorage",
  "sessionStorage",
]) {
  Object.defineProperty(globalThis, key, {
    configurable: true,
    value: (dom.window as unknown as Record<string, unknown>)[key],
  });
}
Object.defineProperty(globalThis, "IS_REACT_ACT_ENVIRONMENT", {
  configurable: true,
  writable: true,
  value: true,
});
dom.window.scrollTo = () => {};
dom.window.HTMLDialogElement.prototype.showModal = function () {
  this.open = true;
};
dom.window.HTMLDialogElement.prototype.close = function () {
  this.open = false;
};

// ------------------------------------------------------------------ a scripted fake API
type Json = Record<string, any>;
type Reply = { status?: number; json: Json } | "network-error";
type Handler = (body: Json | undefined) => Reply | Promise<Reply>;
const calls: { method: string; path: string; body?: Json }[] = [];
const routes = new Map<string, Handler>();
const on = (method: string, path: string, handler: Handler) =>
  routes.set(`${method} ${path}`, handler);
const callsTo = (method: string, path: string) =>
  calls.filter((c) => c.method === method && c.path === path);

Object.defineProperty(globalThis, "fetch", {
  configurable: true,
  writable: true,
  value: async (url: string, init: { method?: string; body?: string } = {}) => {
    const method = init.method ?? "GET";
    const path = url.replace(/^\/api/, "");
    const body = init.body ? (JSON.parse(init.body) as Json) : undefined;
    calls.push({ method, path, body });
    const handler = routes.get(`${method} ${path}`);
    if (!handler)
      return new Response(
        JSON.stringify({ error: `no route ${method} ${path}` }),
        { status: 404 },
      );
    const reply = await handler(body);
    if (reply === "network-error") throw new TypeError("Failed to fetch");
    return new Response(JSON.stringify(reply.json), {
      status: reply.status ?? 200,
    });
  },
});

const { render, screen, cleanup, waitFor, within } =
  await import("@testing-library/react");
const { default: userEvent } = await import("@testing-library/user-event");
const { default: App } = await import("../src/App.tsx");
const { timing } = await import("../src/pages/PresenterGuide.tsx");
timing.pause = 0; // story mode waits between steps; tests do not

// ------------------------------------------------------------------ fixtures
const needs = {
  bags: 0,
  seat: "any",
  refund: false,
  flexible: false,
  seatNow: false,
  early: false,
  budget: 450,
};
const profile = (over: Json = {}) => ({
  id: "rohith",
  name: "Rohith Gunda",
  initials: "RG",
  tier: "Silver",
  card: "None",
  color: "blue",
  description: "Flight booked.",
  points: 12450,
  needs: { ...needs, seat: "extra", refund: true },
  hasTrip: true,
  ...over,
});
const entitlements = {
  bags: 2,
  bagSource: "Choice Extra",
  seat: "extra",
  seatSource: "Choice Extra",
  chooseNow: true,
  refundable: true,
  flexible: true,
  early: true,
};
const trip = (over: Json = {}) => ({
  id: "R8H6WF",
  profileId: "rohith",
  fare: "extra",
  flightId: "WN2418",
  from: "DAL",
  to: "DEN",
  date: "2026-10-22",
  seat: "3A",
  seatClass: "extra",
  seatSource: "Choice Extra",
  bags: 2,
  bagSource: "Choice Extra",
  needs,
  actualBags: 0,
  total: 282.6,
  status: "booked",
  released: false,
  releasedSeat: false,
  redeemedSeat: false,
  redeemedBags: 0,
  clockAdvanced: true,
  checkinEntitlements: entitlements,
  ...over,
});
const everyone = [
  profile(),
  profile({
    id: "ravi",
    name: "Ravi Shah",
    initials: "RS",
    tier: "Member",
    points: 6000,
    description: "Basic fare",
  }),
];
const rohith = (over: Json = {}): Json => ({
  profile: profile(),
  balance: 12450,
  pending: 0,
  booking: trip(),
  inventory: {
    flightId: "WN2418",
    seats: { standard: ["18A", "18B"], preferred: ["4A"], extra: ["1A"] },
    budget: 10000,
    bagGrants: 16,
  },
  ledger: [],
  travellers: everyone,
  demo: true,
  notice: "",
  error: false,
  ...over,
});
const newcomer = (over: Json = {}): Json =>
  rohith({
    profile: profile({
      id: "michael.rankin",
      name: "Michael Rankin",
      initials: "MR",
      tier: "Member",
      points: 0,
      needs,
      hasTrip: false,
    }),
    balance: 0,
    booking: null,
    inventory: null,
    ...over,
  });
const quote = (fare: string, total: number, issues: string[] = []) => ({
  fare,
  base: total - 12.6,
  tax: 12.6,
  total,
  addons: [],
  bags: fare === "extra" ? 2 : 0,
  seat: fare === "extra" ? "extra" : "standard",
  seatSource: "fare",
  bagSource: "No bags included",
  issues,
  points: 1000,
});
const quotesReply = (best = "extra") => ({
  json: {
    needs,
    best,
    flight: { id: "WN2418", date: "2026-10-22", from: "DAL", to: "DEN" },
    quotes: [
      quote("basic", 162.6, ["Not refundable"]),
      quote("choice", 202.6, ["Not refundable"]),
      quote("preferred", 242.6),
      quote("extra", 282.6),
    ],
    entitlements: Object.fromEntries(
      ["basic", "choice", "preferred", "extra"].map((f) => [
        f,
        {
          ...entitlements,
          bags: f === "extra" ? 2 : 0,
          flexible: f !== "basic",
        },
      ]),
    ),
  },
});

// A fake server with a current state and a session, so tests can script a whole conversation.
let current: Json;
let signedIn: boolean;
function server(initial: Json, opts: { signedIn?: boolean } = {}) {
  current = initial;
  signedIn = opts.signedIn ?? true;
  on("GET", "/state", () =>
    signedIn
      ? { json: current }
      : { status: 401, json: { error: "Please sign in again." } },
  );
  on("POST", "/auth/login", (b) =>
    b?.password === "right"
      ? ((signedIn = true),
        {
          json: {
            user: { profileId: current.profile.id, name: current.profile.name },
          },
        })
      : {
          status: 401,
          json: {
            error: "The username or password is incorrect. Please try again.",
          },
        },
  );
  on(
    "POST",
    "/auth/logout",
    () => ((signedIn = false), { json: { ok: true } }),
  );
  on("POST", "/actions", () => ({ json: current }));
}

beforeEach(() => {
  dom.window.history.replaceState(null, "", "/");
  calls.length = 0;
  routes.clear();
  dom.window.localStorage.clear();
  dom.window.sessionStorage.clear();
});
afterEach(() => {
  cleanup();
});

type User = ReturnType<typeof userEvent.setup>;
const setup = () => userEvent.setup({ document: dom.window.document });
const welcome = () =>
  screen.findByRole("dialog", { name: "Welcome to Southwest" });
const nothingStoredInTheBrowser = () => {
  assert.equal(
    dom.window.localStorage.length,
    0,
    "localStorage must stay empty",
  );
  assert.equal(
    dom.window.sessionStorage.length,
    0,
    "sessionStorage must stay empty",
  );
};
async function dismissWelcome(user: User) {
  await welcome();
  await user.click(screen.getByRole("button", { name: "Show my benefits" }));
}

// ------------------------------------------------------------------ signing in and out
test("signed out: the sign-in page; a wrong password is refused; the right one reaches the trip", async () => {
  server(rohith(), { signedIn: false });
  const user = setup();
  render(<App />);
  assert.ok(await screen.findByRole("heading", { name: "Welcome back." }));

  await user.type(screen.getByLabelText("Username"), "rohith");
  await user.type(screen.getByLabelText("Password"), "wrong");
  await user.click(screen.getByRole("button", { name: "Log in & check in" }));
  assert.match((await screen.findByRole("alert")).textContent!, /incorrect/);
  assert.ok(!screen.queryByRole("dialog"));

  await user.clear(screen.getByLabelText("Password"));
  await user.type(screen.getByLabelText("Password"), "right");
  await user.click(screen.getByRole("button", { name: "Log in & check in" }));
  assert.ok(await welcome());
  assert.ok(
    screen.getByRole("heading", { name: /Welcome to Southwest, Rohith Gunda/ }),
  );
  assert.deepEqual(callsTo("POST", "/auth/login")[1].body, {
    loginId: "rohith",
    password: "right",
  });
  nothingStoredInTheBrowser();
});

test("a traveller with a trip lands on check-in with the welcome overlay, greeted by full name", async () => {
  server(rohith());
  render(<App />);
  assert.ok(await welcome());
  assert.ok(
    screen.getByRole("heading", {
      name: /Let’s get you checked in, Rohith Gunda/,
    }),
  );
  assert.equal(
    screen
      .getByRole("button", { name: "Check in", exact: true })
      .getAttribute("aria-current"),
    "page",
  );
  assert.ok(screen.getByRole("button", { name: /Hi, Rohith Gunda/ }));
  assert.ok(screen.getAllByText("12,450").length > 0);
  nothingStoredInTheBrowser();
});

test("a new traveller lands on Book a flight with no dialog, and Check in explains there is no trip", async () => {
  server(newcomer());
  const user = setup();
  render(<App />);
  assert.ok(await screen.findByRole("button", { name: /Hi, Michael Rankin/ }));
  assert.equal(
    screen
      .getByRole("button", { name: "Book a flight", exact: true })
      .getAttribute("aria-current"),
    "page",
  );
  assert.ok(!screen.queryByRole("dialog"));
  await user.click(
    screen.getByRole("button", { name: "Check in", exact: true }),
  );
  assert.ok(screen.getByText("No trip yet."));
  assert.ok(!screen.queryByRole("alert"));
  await user.click(screen.getByRole("button", { name: "My trips" }));
  assert.ok(screen.getByRole("heading", { name: "Your trips." }));
});

// ------------------------------------------------------------------ routes: every page has its own address
test("the home address becomes the check-in address for someone with a trip", async () => {
  server(rohith());
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  assert.equal(window.location.pathname, "/checkin");
});

test("moving between pages changes the address, and Back returns to the page before", async () => {
  server(rohith());
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  await user.click(screen.getByRole("button", { name: "My trips" }));
  assert.equal(window.location.pathname, "/trips");
  await user.click(screen.getByRole("button", { name: "Rapid Rewards" }));
  assert.equal(window.location.pathname, "/wallet");
  dom.window.history.back();
  await waitFor(() => assert.equal(window.location.pathname, "/trips"));
  await waitFor(() => assert.equal(screen.getByRole("button", { name: "My trips" }).getAttribute("aria-current"), "page"));
  dom.window.history.back();
  await waitFor(() => assert.equal(window.location.pathname, "/checkin"));
});

test("opening an address goes straight to that page", async () => {
  dom.window.history.replaceState(null, "", "/wallet");
  server(rohith());
  const user = setup();
  render(<App />);
  await waitFor(() => assert.equal(screen.getByRole("button", { name: "Rapid Rewards" }).getAttribute("aria-current"), "page"));
  assert.equal(window.location.pathname, "/wallet");
  assert.ok(!screen.queryByRole("dialog"));  // a deep link is not greeted with the welcome overlay
  void user;
});

test("an address that does not exist shows the not-found page", async () => {
  dom.window.history.replaceState(null, "", "/no-such-page");
  server(rohith());
  render(<App />);
  assert.ok(await screen.findByRole("heading", { name: "Page not found" }));
  assert.ok(screen.getByRole("button", { name: "Go to PerkFlex" }));
});

test("someone who is signed out sees the sign-in page at any address", async () => {
  dom.window.history.replaceState(null, "", "/wallet");
  server(rohith(), { signedIn: false });
  render(<App />);
  assert.ok(await screen.findByRole("heading", { name: "Welcome back." }));
});

test("signing out calls the server and returns to the sign-in page", async () => {
  server(rohith());
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  await user.click(screen.getByRole("button", { name: "Sign out" }));
  assert.ok(await screen.findByRole("heading", { name: "Welcome back." }));
  assert.equal(callsTo("POST", "/auth/logout").length, 1);
  assert.equal(
    (screen.getByLabelText("Password") as HTMLInputElement).value,
    "",
  );
});

test("an expired session during an action sends the traveller back to sign in", async () => {
  server(rohith());
  on("POST", "/actions", () => ({
    status: 401,
    json: { error: "Please sign in again." },
  }));
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  await user.click(screen.getByRole("button", { name: /Give up a bag/ }));
  await user.click(
    screen.getByRole("button", { name: /Release bag allowance/ }),
  );
  assert.ok(await screen.findByRole("heading", { name: "Welcome back." }));
});

// ------------------------------------------------------------------ actions go to the server
test("releasing a bag sends one request (no traveller id, with an idempotency key) and shows the server's answer", async () => {
  server(rohith());
  on("POST", "/actions", (body) => {
    current = rohith({
      pending: 800,
      notice: "All set! 800 points are pending and will post after you fly.",
      booking: trip({ bags: 1, released: true }),
      ledger: [
        {
          id: "PT040",
          bookingId: "R8H6WF",
          kind: "release",
          label: "Unused checked-bag allowance",
          points: 800,
          status: "pending",
          createdAt: "2027-12-15T23:59:00+00:00",
        },
      ],
    });
    return { json: current };
  });
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  await user.click(screen.getByRole("button", { name: /Give up a bag/ }));
  await user.click(
    screen.getByRole("button", { name: /Release bag allowance/ }),
  );

  assert.match(
    (await screen.findByRole("status")).textContent!,
    /800 points are pending/,
  );
  const [sent, ...rest] = callsTo("POST", "/actions");
  assert.equal(rest.length, 0, "exactly one request");
  assert.deepEqual(Object.keys(sent.body!).sort(), [
    "benefit",
    "idempotencyKey",
    "type",
  ]);
  assert.equal(sent.body!.type, "release");
  assert.equal(sent.body!.benefit, "bag");
  assert.match(sent.body!.idempotencyKey, /^[0-9a-f-]{36}$/);
  assert.ok(
    screen.getAllByText("12,450").length > 0,
    "balance is whatever the server says",
  );
  nothingStoredInTheBrowser();
});

test("a refusal from the server is shown as the server worded it and changes nothing", async () => {
  server(rohith());
  on("POST", "/actions", () => ({
    json: rohith({
      notice: "You have already accepted your one reward offer for this flight",
      error: true,
    }),
  }));
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  await user.click(screen.getByRole("button", { name: /Give up a bag/ }));
  await user.click(
    screen.getByRole("button", { name: /Release bag allowance/ }),
  );
  assert.match(
    (await screen.findByRole("alert")).textContent!,
    /already accepted your one reward offer/,
  );
  assert.ok(screen.getAllByText("12,450").length > 0);
});

test("a network failure during an action keeps the screen and says so", async () => {
  server(rohith());
  on("POST", "/actions", () => "network-error");
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  await user.click(screen.getByRole("button", { name: /Give up a bag/ }));
  await user.click(
    screen.getByRole("button", { name: /Release bag allowance/ }),
  );
  assert.match(
    (await screen.findByRole("alert")).textContent!,
    /couldn’t reach PerkFlex/,
  );
  assert.ok(
    screen.getByRole("heading", {
      name: /Let’s get you checked in, Rohith Gunda/,
    }),
  );
});

// ------------------------------------------------------------------ demo traveller switcher
test("the switcher lists the server's travellers and switches through the server", async () => {
  server(rohith());
  on("POST", "/demo/switch", (b) => {
    current = rohith({
      profile: everyone[1],
      balance: 6000,
      booking: trip({ id: "B02", profileId: "ravi" }),
    });
    return { json: { user: { profileId: b!.profileId } } };
  });
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  await user.click(screen.getByRole("button", { name: /Hi, Rohith Gunda/ }));
  await user.click(screen.getByRole("button", { name: /Ravi Shah/ }));
  assert.ok(await screen.findByRole("button", { name: /Hi, Ravi Shah/ }));
  assert.deepEqual(callsTo("POST", "/demo/switch")[0].body, {
    profileId: "ravi",
  });
});

test("outside demo mode there is no traveller switcher", async () => {
  server(rohith({ demo: false, travellers: [] }));
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  assert.ok(!screen.queryByRole("button", { name: "Traveller profiles" }));
  await user.click(screen.getByRole("button", { name: /Hi, Rohith Gunda/ }));
  assert.ok(!screen.queryByRole("dialog"));
});

// ------------------------------------------------------------------ booking and the assistant
const aiAnswer = {
  json: {
    source: "ai",
    understood: { ...needs, bags: 2, seat: "front", refund: true, budget: 400 },
    recommendation: {
      fare: "extra",
      total: 282.6,
      reasons: ["Two checked bags are included.", "Refundable as you asked."],
    },
    alternatives: [],
    explanation: "Choice Extra covers your bags and refund in one fare.",
    quotes: quotesReply().json.quotes,
  },
};

test("the assistant sends the form and the typed request, and shows the server's recommendation", async () => {
  server(newcomer());
  on("POST", "/assistant/best-fare", () => aiAnswer);
  const user = setup();
  render(<App />);
  await screen.findByRole("button", { name: /Hi, Michael Rankin/ });
  await user.click(screen.getByRole("button", { name: /Meet PerkFlex AI/ }));
  await user.type(
    screen.getByLabelText(/in your own words/),
    "Two bags, near the front, refundable, under $400",
  );
  await user.click(screen.getByRole("button", { name: /Find my best fare/ }));

  assert.ok(
    await screen.findByRole("heading", {
      name: /Choice Extra. That’s your fit/,
    }),
  );
  assert.ok(screen.getByText("Two checked bags are included."));
  assert.ok(
    screen.getByText("Choice Extra covers your bags and refund in one fare."),
  );
  assert.ok(screen.getAllByText("$282.60").length > 0);
  const sent = callsTo("POST", "/assistant/best-fare")[0].body!;
  assert.equal(
    sent.message,
    "Two bags, near the front, refundable, under $400",
  );
  assert.equal(sent.flightId, "WN2418");
  assert.equal(sent.from, "DAL");
  assert.equal(sent.to, "DEN");
  assert.equal(sent.needs.budget, 450);
});

test("if the assistant cannot be reached the traveller can try again", async () => {
  server(newcomer());
  let attempts = 0;
  on("POST", "/assistant/best-fare", () =>
    ++attempts === 1 ? "network-error" : aiAnswer,
  );
  const user = setup();
  render(<App />);
  await screen.findByRole("button", { name: /Hi, Michael Rankin/ });
  await user.click(screen.getByRole("button", { name: /Meet PerkFlex AI/ }));
  await user.click(screen.getByRole("button", { name: /Find my best fare/ }));
  assert.match(
    (await screen.findByRole("alert")).textContent!,
    /couldn’t find your fare/,
  );
  await user.click(screen.getByRole("button", { name: /Try again/ }));
  assert.ok(
    await screen.findByRole("heading", {
      name: /Choice Extra. That’s your fit/,
    }),
  );
});

test("booking: server-priced fares, a review, one book request, then the confirmation code", async () => {
  server(newcomer());
  on("POST", "/quotes", () => quotesReply());
  on("POST", "/actions", () => {
    current = newcomer({
      profile: profile({
        id: "michael.rankin",
        name: "Michael Rankin",
        hasTrip: true,
      }),
      booking: trip({ id: "K7MQ2X", profileId: "michael.rankin" }),
    });
    return {
      json: {
        ...current,
        notice: "Your flight is booked. Next stop: a trip that feels like you.",
      },
    };
  });
  const user = setup();
  render(<App />);
  await screen.findByRole("button", { name: /Hi, Michael Rankin/ });
  await user.click(screen.getByRole("button", { name: /Search flights/ }));

  await user.click(
    await screen.findByRole("button", {
      name: "Select Choice Extra",
      exact: true,
    }),
  );
  assert.ok(screen.getAllByText("$282.60").length > 0);
  await user.click(
    await screen.findByRole("button", { name: "Confirm booking", exact: true }),
  );

  assert.ok(await screen.findByRole("heading", { name: "Next stop: DEN." }));
  assert.ok(screen.getByText("K7MQ2X"));
  const book = callsTo("POST", "/actions")[0].body!;
  assert.deepEqual(
    {
      type: book.type,
      fare: book.fare,
      flightId: book.flightId,
      from: book.from,
      to: book.to,
    },
    { type: "book", fare: "extra", flightId: "WN2418", from: "DAL", to: "DEN" },
  );
  assert.equal(book.profileId, undefined);
  assert.ok(callsTo("POST", "/quotes").length >= 1);
  nothingStoredInTheBrowser();
});

test("a booking the server refuses is reported and no confirmation is shown", async () => {
  server(newcomer());
  on("POST", "/quotes", () => quotesReply());
  on("POST", "/actions", () => ({
    json: {
      ...newcomer(),
      notice: "There is no WN 2418 flight from DAL to DEN.",
      error: true,
    },
  }));
  const user = setup();
  render(<App />);
  await screen.findByRole("button", { name: /Hi, Michael Rankin/ });
  await user.click(screen.getByRole("button", { name: /Search flights/ }));
  await user.click(
    await screen.findByRole("button", {
      name: "Select Choice Extra",
      exact: true,
    }),
  );
  await user.click(
    await screen.findByRole("button", { name: "Confirm booking", exact: true }),
  );
  assert.match(
    (await screen.findByRole("alert")).textContent!,
    /There is no WN 2418 flight from DAL to DEN/,
  );
  assert.ok(!screen.queryByRole("heading", { name: "Next stop: DEN." }));
});

test("any pair of airports can be searched: the chosen route goes to the server for quotes and booking", async () => {
  server(newcomer());
  on("POST", "/quotes", () => quotesReply());
  on("POST", "/actions", () => ({ json: newcomer() }));
  const user = setup();
  render(<App />);
  await screen.findByRole("button", { name: /Hi, Michael Rankin/ });
  await user.selectOptions(screen.getByLabelText(/Depart from/), "LAS");
  await user.selectOptions(screen.getByLabelText(/Arrive at/), "PHX");
  await user.click(screen.getByRole("button", { name: /Search flights/ }));
  await user.click(
    await screen.findByRole("button", {
      name: "Select Choice Extra",
      exact: true,
    }),
  );
  await user.click(
    await screen.findByRole("button", { name: "Confirm booking", exact: true }),
  );

  const asked = callsTo("POST", "/quotes").map((c) => c.body!);
  assert.ok(asked.some((q) => q.from === "LAS" && q.to === "PHX"));
  assert.ok(!asked.some((q) => q.from === "DAL" && q.to === "DEN"));
  const book = callsTo("POST", "/actions")[0].body!;
  assert.deepEqual([book.type, book.from, book.to], ["book", "LAS", "PHX"]);
});

// ------------------------------------------------------------------ the page still works when the server is down
test("if the server is unreachable at start the traveller sees a message and can retry", async () => {
  on("GET", "/state", () => "network-error");
  const user = setup();
  render(<App />);
  assert.match(
    (await screen.findByRole("alert")).textContent!,
    /couldn’t reach PerkFlex/,
  );
  server(rohith());
  await user.click(screen.getByRole("button", { name: /Try again/ }));
  await waitFor(() =>
    assert.ok(screen.getByRole("dialog", { name: "Welcome to Southwest" })),
  );
});

// ------------------------------------------------------------------ the check-in perk advisor (advice only)
const perkOffer = (over: Json = {}) => ({
  id: "RELEASE_SEAT",
  kind: "release",
  label: "Swap Extra Legroom for a Standard seat",
  points: 1500,
  included: false,
  affordable: true,
  shortfall: 0,
  needed: false,
  ...over,
});
const perkAdvice = (over: Json = {}) => ({
  json: {
    source: "ai",
    summary: "Your seat is the best thing to release.",
    picks: [
      {
        offerId: "RELEASE_SEAT",
        why: "Earn 1,500 points, pending until you fly.",
      },
    ],
    offers: [
      perkOffer({
        id: "RELEASE_BAG",
        label: "Release an unused bag",
        points: 800,
      }),
      perkOffer(),
    ],
    ...over,
  },
});
const withNoNudge = () => on("GET", "/assistant/perk-nudge", () => ({ json: { nudge: null } }));
const askButton = () => screen.getByRole("button", { name: "Ask the advisor" });

test("the advisor sends what the traveller typed and shows the server's picks, with numbers from the offers", async () => {
  server(rohith());
  withNoNudge();
  on("POST", "/assistant/perk-advice", () => perkAdvice());
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  await user.type(
    screen.getByLabelText("Message to the advisor"),
    "I only carry a backpack",
  );
  await user.click(askButton());

  assert.ok(await screen.findByText("Your seat is the best thing to release."));
  assert.ok(screen.getByText("Swap Extra Legroom for a Standard seat"));
  assert.ok(screen.getByText("+1,500 pts, pending until you fly"));
  assert.ok(screen.getByText("Earn 1,500 points, pending until you fly."));
  assert.ok(!screen.queryByText("Automatic answer"));
  const sent = callsTo("POST", "/assistant/perk-advice");
  assert.equal(sent.length, 1);
  assert.deepEqual(sent[0].body, { message: "I only carry a backpack" });
  assert.equal(callsTo("POST", "/actions").filter((c) => c.body?.type === "release").length, 0, "advice changes nothing");
  nothingStoredInTheBrowser();
});

test("asking with no message sends an empty request", async () => {
  server(rohith());
  withNoNudge();
  on("POST", "/assistant/perk-advice", () => perkAdvice());
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  await user.click(askButton());
  await screen.findByText("Your seat is the best thing to release.");
  assert.deepEqual(callsTo("POST", "/assistant/perk-advice")[0].body, {});
});

test("an automatic (rules-only) answer is labelled, and an included seat says so", async () => {
  server(rohith());
  withNoNudge();
  on("POST", "/assistant/perk-advice", () =>
    perkAdvice({
      source: "fallback",
      picks: [{ offerId: "REDEEM_EXTRA", why: "Your own benefits already cover this seat." }],
      offers: [perkOffer({ id: "REDEEM_EXTRA", kind: "redeem", label: "Extra Legroom seat", points: 0, included: true })],
    }),
  );
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  await user.click(askButton());
  assert.ok(await screen.findByText("Automatic answer"));
  assert.ok(screen.getByText("Included in your benefits"));
});

test("if the advisor cannot be reached the traveller is told and the offers are still there", async () => {
  server(rohith());
  withNoNudge();
  on("POST", "/assistant/perk-advice", () => ({ status: 500, json: { error: "Something went wrong." } }));
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  await user.click(askButton());
  assert.match((await screen.findByRole("alert")).textContent!, /could not be reached/);
  assert.ok(screen.getByRole("button", { name: /Give up a bag/ }));
  assert.ok(askButton(), "they can try again");
});

test("a proactive tip from the server is shown without asking, and goes away once the advice is shown", async () => {
  server(rohith());
  on("GET", "/assistant/perk-nudge", () => ({
    json: {
      nudge: {
        offerId: "RELEASE_SEAT",
        kind: "release",
        points: 1500,
        text: "You could swap to a Standard seat and earn 1,500 points, pending until you fly.",
      },
    },
  }));
  on("POST", "/assistant/perk-advice", () => perkAdvice());
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  assert.match((await screen.findByRole("note")).textContent!, /Tip: You could swap to a Standard seat/);
  assert.equal(callsTo("POST", "/assistant/perk-advice").length, 0, "the tip needs no AI call from the page");
  await user.click(askButton());
  await screen.findByText("Your seat is the best thing to release.");
  assert.ok(!screen.queryByRole("note"));
});

test("if the tip cannot be loaded the page still works and shows no tip", async () => {
  server(rohith());
  on("GET", "/assistant/perk-nudge", () => "network-error");
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  await waitFor(() => assert.ok(callsTo("GET", "/assistant/perk-nudge").length > 0));
  assert.ok(!screen.queryByRole("note"));
  assert.ok(askButton());
});

test("advice is hidden once the traveller acts, and the tip is loaded again", async () => {
  server(rohith());
  withNoNudge();
  on("POST", "/assistant/perk-advice", () => perkAdvice());
  on("POST", "/actions", () => {
    current = rohith({
      pending: 800,
      notice: "All set! 800 points are pending and will post after you fly.",
      booking: trip({ bags: 1, released: true }),
    });
    return { json: current };
  });
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  await user.click(askButton());
  await screen.findByText("Your seat is the best thing to release.");
  const before = callsTo("GET", "/assistant/perk-nudge").length;

  await user.click(screen.getByRole("button", { name: /Give up a bag/ }));
  await user.click(screen.getByRole("button", { name: /Release bag allowance/ }));
  assert.match((await screen.findByRole("status")).textContent!, /800 points are pending/);
  await waitFor(() => assert.ok(!screen.queryByText("Your seat is the best thing to release.")));
  await waitFor(() => assert.ok(callsTo("GET", "/assistant/perk-nudge").length > before));
});

// ------------------------------------------------------------------ small perks (beside the one bag-or-seat reward)
const smallPerk = (id: string, name: string, over: Json = {}) => ({
  id,
  name,
  included: false,
  source: "",
  released: false,
  bought: false,
  releasePoints: { boarding: 100, drink: 150, lane: 50 }[id],
  redeemPoints: { boarding: 900, drink: 600, lane: 0 }[id],
  ...over,
});
const perksFor = (over: Record<string, Json> = {}) => [
  smallPerk("boarding", "Priority boarding", over.boarding),
  smallPerk("drink", "Premium drink", over.drink),
  smallPerk("lane", "Priority lane", over.lane),
];

test("small perks the traveller has can be released and each shows its points, pending until they fly", async () => {
  server(
    rohith({
      booking: trip({
        perks: perksFor({
          drink: { included: true, source: "fare" },
          lane: { included: true, source: "fare" },
        }),
      }),
    }),
  );
  withNoNudge();
  on("POST", "/actions", () => {
    current = rohith({
      pending: 150,
      notice: "All set! 150 points are pending and will post after you fly.",
      booking: trip({
        perks: perksFor({
          drink: { included: true, source: "fare", released: true },
          lane: { included: true, source: "fare" },
        }),
      }),
    });
    return { json: current };
  });
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  const section = screen.getByRole("region", { name: "Small perks" });
  assert.ok(within(section).getByText("+150"));
  assert.ok(within(section).getByText("+50"));
  await user.click(within(section).getAllByRole("button", { name: /Release for points/ })[0]);
  await user.click(screen.getByRole("button", { name: /Release premium drink/ }));
  const sent = callsTo("POST", "/actions").filter((c) => c.body?.type === "release");
  assert.equal(sent.length, 1);
  assert.deepEqual(sent[0].body, { type: "release", benefit: "drink", idempotencyKey: sent[0].body?.idempotencyKey });
  assert.match((await screen.findByRole("status")).textContent!, /150 points are pending/);
  nothingStoredInTheBrowser();
});

test("a perk the traveller lacks is bought with points; the lane cannot be bought; too few points says how many more", async () => {
  server(rohith({ balance: 700, booking: trip({ perks: perksFor() }) }));
  withNoNudge();
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  const section = screen.getByRole("region", { name: "Small perks" });
  assert.ok(within(section).getByText("Need 200 more pts"), "boarding is 900 points and the balance is 700");
  assert.ok(within(section).getByRole("button", { name: "Add with points" }), "the 600-point drink is affordable");
  assert.ok(!within(section).queryByText("Priority lane"), "priority lane is not for sale");
});

test("the airport meal voucher is for sale, never offered for release, and says it is a concept add-on", async () => {
  server(
    rohith({
      balance: 5000,
      booking: trip({
        perks: [smallPerk("meal", "Airport meal voucher", { releasePoints: 0, redeemPoints: 1500 })],
      }),
    }),
  );
  withNoNudge();
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  const section = screen.getByRole("region", { name: "Small perks" });
  assert.ok(within(section).getByText("Airport meal voucher"));
  assert.ok(within(section).getByText(/participating airport vendors/));
  assert.ok(within(section).getByRole("button", { name: "Add with points" }));
  assert.ok(!within(section).queryByRole("button", { name: /Release/ }), "a meal voucher cannot be released");
});

test("a released or bought perk is shown as done and offers nothing more", async () => {
  server(
    rohith({
      booking: trip({
        perks: perksFor({
          boarding: { bought: true },
          drink: { included: true, source: "tier", released: true },
        }),
      }),
    }),
  );
  withNoNudge();
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  const section = screen.getByRole("region", { name: "Small perks" });
  assert.ok(within(section).getByText("Added"));
  assert.ok(within(section).getByText("Released"));
  assert.equal(within(section).queryAllByRole("button").length, 0);
});

// ------------------------------------------------------------------ demo reset
test("Reset demo needs a second click, then restores the starting state and says so", async () => {
  server(rohith({ pending: 800, booking: trip({ released: true }) }));
  withNoNudge();
  on("POST", "/demo/reset", () => {
    current = rohith({ notice: "Demo reset. Everything is back to its starting point." });
    return { json: current };
  });
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  await user.click(screen.getByRole("button", { name: "Reset demo" }));
  assert.equal(callsTo("POST", "/demo/reset").length, 0, "one click only arms it");
  await user.click(screen.getByRole("button", { name: "Click again to reset the demo" }));
  assert.match((await screen.findByRole("status")).textContent!, /Demo reset/);
  assert.equal(callsTo("POST", "/demo/reset").length, 1);
  nothingStoredInTheBrowser();
});

test("outside demo mode there is no Reset demo button", async () => {
  server(rohith({ demo: false, travellers: [] }));
  withNoNudge();
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  assert.ok(!screen.queryByRole("button", { name: /Reset demo/ }));
});

// ------------------------------------------------------------------ airline view, wallet value, presenter guide
test("an airline account sees the programme overview and no traveller screens", async () => {
  on("GET", "/state", () => ({ status: 403, json: { error: "This account does not have a traveller view." } }));
  on("GET", "/auth/me", () => ({ json: { user: { role: "AIRLINE_ADMIN" } } }));
  on("GET", "/admin/overview", () => ({
    json: {
      totals: { flights: 1, budget: 10000, owed: 950, paid: 0, estimatedCost: 9.5, releases: 2, redemptions: 1, pointsSpent: 3000 },
      flights: [
        {
          flightId: "WN2418", date: "2027-12-16", from: "DAL", to: "DEN", status: "scheduled", bookings: 18, checkedIn: 0,
          budget: 10000, reserved: 950, settled: 0, remaining: 9050,
          releases: { bag: 1, seat: 0, perk: 1 }, pointsEarned: 950,
          redemptions: { bag: 1, seat: 0, perk: 0 }, pointsSpent: 3000,
        },
      ],
    },
  }));
  render(<App />);
  assert.ok(await screen.findByText("What PerkFlex is costing, flight by flight"));
  const totals = screen.getByRole("region", { name: "Totals" });
  assert.ok(within(totals).getByText("$9.50"));
  assert.ok(within(totals).getByText("Owed to travellers"));
  assert.ok(screen.getByRole("img", { name: /0 paid, 950 owed, 9,050 left of 10,000/ }));
  assert.ok(!screen.queryByRole("button", { name: "Show my benefits" }));
  assert.equal(callsTo("GET", "/admin/overview").length, 1);
});

test("the airline page shows each flight's benefits inventory pool", async () => {
  on("GET", "/state", () => ({ status: 403, json: { error: "This account does not have a traveller view." } }));
  on("GET", "/auth/me", () => ({ json: { user: { role: "AIRLINE_ADMIN" } } }));
  const seats = (total: number, free: number, givenBack: number, reused: number) => ({ total, free, givenBack, reused });
  on("GET", "/admin/overview", () => ({
    json: {
      totals: { flights: 1, budget: 10000, owed: 0, paid: 0, estimatedCost: 0, releases: 0, redemptions: 0, pointsSpent: 0 },
      flights: [
        {
          flightId: "WN2418", date: "2027-12-16", from: "DAL", to: "DEN", status: "scheduled", bookings: 18, checkedIn: 0,
          budget: 10000, reserved: 950, settled: 0, remaining: 9050,
          releases: { bag: 1, seat: 0, perk: 1 }, pointsEarned: 950, redemptions: { bag: 0, seat: 0, perk: 0 }, pointsSpent: 0,
          benefits: [
            { name: "Extra Legroom seat", kind: "seat", released: 2, bought: 1, pointsEarned: 3000, pointsSpent: 4000 },
            { name: "Second bag", kind: "bag", released: 1, bought: 0, pointsEarned: 800, pointsSpent: 0 },
          ],
          pool: { seats: { standard: seats(120, 40, 2, 1), preferred: seats(30, 6, 0, 0), extra: seats(12, 3, 1, 0) }, bagGrants: { total: 8, remaining: 5 } },
        },
      ],
    },
  }));
  render(<App />);
  const pool = await screen.findByRole("region", { name: "Benefits inventory pool" });
  const card = within(pool).getByRole("article", { name: "Pool for flight WN2418" });
  assert.ok(within(card).getByText("Bag grants left"));
  assert.ok(within(card).getByText("of 8"));
  assert.ok(within(card).getByText("Standard seats free"));
  assert.ok(within(card).getByText(/of 120 · 2 given back · 1 re-taken/));
  assert.ok(within(card).getByText("Reward budget left"));
  const table = within(card).getByRole("table", { name: "Benefits on flight WN2418" });
  const seatRow = within(table).getByText("Extra Legroom seat").closest("[role=row]") as HTMLElement;
  assert.deepEqual(within(seatRow).getAllByRole("cell").map((c) => c.textContent), ["Extra Legroom seat", "2", "1"]);
  const bagRow = within(table).getByText("Second bag").closest("[role=row]") as HTMLElement;
  assert.deepEqual(within(bagRow).getAllByRole("cell").map((c) => c.textContent), ["Second bag", "1", "0"]);
});

test("signing in as the airline puts /admin in the address bar, and a traveller is sent away from /admin", async () => {
  window.history.replaceState(null, "", "/");
  on("GET", "/state", () => ({ status: 403, json: { error: "This account does not have a traveller view." } }));
  on("GET", "/auth/me", () => ({ json: { user: { role: "AIRLINE_ADMIN" } } }));
  on("GET", "/admin/overview", () => ({ json: { totals: { flights: 0, budget: 0, owed: 0, paid: 0, estimatedCost: 0, releases: 0, redemptions: 0, pointsSpent: 0 }, flights: [] } }));
  render(<App />);
  assert.ok(await screen.findByText("What PerkFlex is costing, flight by flight"));
  assert.equal(window.location.pathname, "/admin");
});

test("after the airline signs out, the next traveller to sign in lands on their own page, never /admin", async () => {
  window.history.replaceState(null, "", "/");
  let airline = true;
  on("GET", "/state", () => (airline ? { status: 403, json: { error: "This account does not have a traveller view." } } : { json: rohith() }));
  on("GET", "/auth/me", () => ({ json: { user: { role: "AIRLINE_ADMIN" } } }));
  on("GET", "/admin/overview", () => ({ json: { totals: { flights: 0, budget: 0, owed: 0, paid: 0, estimatedCost: 0, releases: 0, redemptions: 0, pointsSpent: 0 }, flights: [] } }));
  on("GET", "/admin/controls", () => ({ status: 500, json: { error: "not needed" } }));
  on("POST", "/auth/logout", () => ({ json: { ok: true } }));
  on("POST", "/auth/login", () => {
    airline = false;
    return { json: { user: { role: "PASSENGER" } } };
  });
  withNoNudge();
  const user = setup();
  render(<App />);
  await user.click(await screen.findByRole("button", { name: /Sign out/ }));
  assert.ok(await screen.findByRole("heading", { name: "Welcome back." }));
  assert.equal(window.location.pathname, "/", "signing out clears the airline address");
  await user.type(screen.getByLabelText("Username"), "rohith");
  await user.type(screen.getByLabelText("Password"), "a-password");
  await user.click(screen.getByRole("button", { name: "Log in & check in" }));
  await dismissWelcome(user);
  assert.ok(!screen.queryByText("What PerkFlex is costing, flight by flight"), "a traveller never sees the airline page");
  assert.notEqual(window.location.pathname, "/admin");
});

test("a signed-in traveller who opens /admin is sent to the home address", async () => {
  window.history.replaceState(null, "", "/admin");
  server(rohith());
  withNoNudge();
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  assert.equal(window.location.pathname, "/checkin");  // not /admin: a traveller lands on their own page
});

test("a 403 for someone who is not the airline goes back to sign-in", async () => {
  on("GET", "/state", () => ({ status: 403, json: { error: "nope" } }));
  on("GET", "/auth/me", () => ({ json: { user: { role: "PASSENGER" } } }));
  render(<App />);
  assert.ok(await screen.findByRole("heading", { name: "Welcome back." }));
});

test("the wallet says what points bought and what released benefits were worth", async () => {
  server(
    rohith({
      pending: 800,
      ledger: [
        { id: "PT1", bookingId: "R8H6WF", kind: "release", label: "Unused checked-bag allowance", cashValue: 45, points: 800, status: "pending", createdAt: "2027-12-15T23:59:00+00:00" },
        { id: "T2", bookingId: "R8H6WF", kind: "redemption", label: "Premium drink", cashValue: 8, points: -600, status: "posted", createdAt: "2027-12-15T23:58:00+00:00" },
      ],
    }),
  );
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  await user.click(screen.getAllByRole("button", { name: /Rapid Rewards/ })[0]);
  const card = await screen.findByRole("region", { name: "What your points did" });
  assert.ok(within(card).getByText("$8.00"));
  assert.ok(within(card).getByText("of extras added with 600 points"));
  assert.ok(within(card).getByText("$45.00"));
  assert.ok(within(card).getByText("of unused benefits turned into 800 points"));
});

test("the presenter guide steps through scenes and switches traveller on request, only in demo mode", async () => {
  server(rohith());
  withNoNudge();
  on("POST", "/demo/switch", () => ({ json: { user: { profileId: "kabir" } } }));
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  await user.click(screen.getByRole("button", { name: "Presenter guide" }));
  const panel = screen.getByRole("complementary", { name: "Presenter guide" });
  assert.ok(within(panel).getByText("Scene 1 of 18"));
  await user.click(within(panel).getByRole("button", { name: "Next scene" }));
  assert.ok(within(panel).getByText("Release an unused bag"));
  await user.click(within(panel).getByRole("button", { name: "Go to Kabir" }));
  assert.equal(callsTo("POST", "/demo/switch")[0].body?.profileId, "kabir");
  nothingStoredInTheBrowser();
});

test("outside demo mode there is no presenter guide", async () => {
  server(rohith({ demo: false, travellers: [] }));
  withNoNudge();
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  assert.ok(!screen.queryByRole("button", { name: "Presenter guide" }));
});

// ------------------------------------------------------------------ two wallets: PerkFlex and Rapid Rewards
const twoWallets = (over: Json = {}) =>
  rohith({
    balance: 1000,
    pending: 800,
    wallets: {
      perkflex: { available: 400, pending: 800 },
      rapidRewards: { available: 600, pending: 2700 },
    },
    earnings: [
      { id: "PT10", bookingId: "R8H6WF", label: "Points for flying", points: 2700, status: "pending", createdAt: "2027-12-15T10:00:00+00:00" },
    ],
    ...over,
  });

test("the wallet keeps PerkFlex and Rapid Rewards apart, with flying points as their own line", async () => {
  server(twoWallets());
  withNoNudge();
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  await user.click(screen.getAllByRole("button", { name: /Rapid Rewards/ })[0]);
  const rapid = await screen.findByLabelText("Rapid Rewards wallet");
  const perkflex = screen.getByLabelText("PerkFlex Rewards wallet");
  assert.ok(within(rapid).getByText("600"));
  assert.ok(within(rapid).getByText("2,700 more after you fly"));
  assert.ok(within(perkflex).getByText("400"));
  assert.ok(within(perkflex).getByText("800 pending until you fly"));
  assert.ok(screen.getByText("Points for flying"));
  assert.ok(screen.getByText("+2,700"));
});

test("the wallet has email settings: save an address, be told to confirm it, and nothing shows when email is not set up", async () => {
  server(twoWallets());
  withNoNudge();
  let saved: Json = { email: "", verified: false, enabled: false, available: true };
  on("GET", "/me/email", () => ({ json: saved }));
  on("POST", "/me/email", (b) => {
    saved = { email: b!.email, verified: false, enabled: b!.enabled, available: true };
    return { json: saved };
  });
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  await user.click(screen.getAllByRole("button", { name: /Rapid Rewards/ })[0]);
  const card = await screen.findByRole("region", { name: "Email notifications" });
  await user.type(within(card).getByLabelText("Email address"), "rohith@example.com");
  await user.click(within(card).getByRole("checkbox", { name: /Send me emails/ }));
  await user.click(within(card).getByRole("button", { name: "Save" }));
  assert.ok(await within(card).findByText("Saved. We sent a link to confirm this address."));
  assert.deepEqual(callsTo("POST", "/me/email")[0].body, { email: "rohith@example.com", enabled: true });
  assert.ok(within(card).getByText("Waiting for confirmation"));
});

test("without an email service the wallet shows no email settings", async () => {
  server(twoWallets());
  withNoNudge();
  on("GET", "/me/email", () => ({ json: { email: "", verified: false, enabled: false, available: false } }));
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  await user.click(screen.getAllByRole("button", { name: /Rapid Rewards/ })[0]);
  await screen.findByLabelText("Rapid Rewards wallet");
  await waitFor(() => assert.equal(callsTo("GET", "/me/email").length, 1));
  assert.ok(!screen.queryByRole("region", { name: "Email notifications" }));
});

test("a purchase says which wallet pays: PerkFlex first, then Rapid Rewards", async () => {
  server(twoWallets({ balance: 1000, booking: trip({ perks: [
    { id: "drink", name: "Premium drink", included: false, source: "", released: false, bought: false, releasePoints: 150, redeemPoints: 600 },
  ] }) }));
  withNoNudge();
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  const section = screen.getByRole("region", { name: "Small perks" });
  assert.ok(within(section).getByText("Pays 400 PerkFlex + 200 Rapid Rewards"));
  await user.click(within(section).getByRole("button", { name: "Add with points" }));
  assert.match(
    screen.getByRole("dialog", { name: /./ }).textContent!,
    /Pays 400 PerkFlex \+ 200 Rapid Rewards points: PerkFlex rewards first, then Rapid Rewards/,
  );
});

test("when PerkFlex covers the whole price, only PerkFlex is charged", async () => {
  server(twoWallets({ wallets: { perkflex: { available: 900, pending: 0 }, rapidRewards: { available: 600, pending: 0 } }, balance: 1500, booking: trip({ perks: [
    { id: "drink", name: "Premium drink", included: false, source: "", released: false, bought: false, releasePoints: 150, redeemPoints: 600 },
  ] }) }));
  withNoNudge();
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  assert.ok(within(screen.getByRole("region", { name: "Small perks" })).getByText("Pays 600 PerkFlex"));
});


// ------------------------------------------------------------------ undo, reuse, spend order, expiry, wallet extras
test("a recent release shows an Undo button that sends one undo action", async () => {
  server(rohith({ booking: trip({ undoable: [{ benefit: "bag", label: "Checked bag", points: 800, secondsLeft: 240 }] }) }));
  withNoNudge();
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  const bar = screen.getByRole("region", { name: "Undo a release" });
  assert.ok(within(bar).getByText(/800 pending points/));
  await user.click(within(bar).getByRole("button", { name: /Undo/ }));
  const sent = callsTo("POST", "/actions").at(-1)!.body!;
  assert.equal(sent.type, "undo");
  assert.equal(sent.benefit, "bag");
  assert.ok(!("profileId" in sent));
});

test("a seat that was released and taken by someone else says so", async () => {
  server(rohith({ booking: trip({ reuse: { bag: null, seat: { seat: "3A", reused: true, freedAt: "2027-12-15T10:00:00+00:00", reusedAt: "2027-12-15T11:00:00+00:00" } } }) }));
  withNoNudge();
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  const card = screen.getByRole("region", { name: "Your released benefits" });
  assert.ok(within(card).getByText("Seat 3A was taken by another traveller."));
});

test("the spend order can be switched and the choice is sent to the server", async () => {
  server(twoWallets());
  withNoNudge();
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  const group = screen.getByRole("group", { name: "Spend order" });
  await user.click(within(group).getByRole("button", { name: /Rapid Rewards first/ }));
  const sent = callsTo("POST", "/actions").at(-1)!.body!;
  assert.equal(sent.type, "payment-order");
  assert.equal(sent.rapidFirst, true);
});

test("with Rapid Rewards first, a purchase is split that way", async () => {
  server(twoWallets({ payRapidFirst: true, booking: trip({ perks: [
    { id: "drink", name: "Premium drink", included: false, source: "", released: false, bought: false, releasePoints: 150, redeemPoints: 600 },
  ] }) }));
  withNoNudge();
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  assert.ok(within(screen.getByRole("region", { name: "Small perks" })).getByText("Pays 600 Rapid Rewards"));
});

test("points that are about to expire are announced", async () => {
  server(twoWallets({ wallets: {
    perkflex: { available: 1500, pending: 0, expiring: { soonPoints: 1500, soonDate: "2027-12-27", soonDays: 12, lots: [{ points: 1500, expiresOn: "2027-12-27" }] } },
    rapidRewards: { available: 600, pending: 0 },
  } }));
  withNoNudge();
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  assert.ok(screen.getByText(/1,500 PerkFlex points expire on 2027-12-27 \(12 days\)/));
});

test("the wallet adds a next-flight preview, an earned-and-used chart and a read-only status card", async () => {
  server(twoWallets({
    ledger: [
      { id: "PT1", bookingId: "R8H6WF", kind: "release", wallet: "perkflex", label: "Unused checked-bag allowance", cashValue: 45, points: 800, status: "posted", createdAt: "2027-12-15T09:00:00+00:00" },
      { id: "T2", bookingId: "R8H6WF", kind: "redemption", wallet: "perkflex", label: "Premium drink", cashValue: 8, points: -600, status: "posted", createdAt: "2027-12-15T09:30:00+00:00" },
    ],
    status: {
      tier: "Silver", tqp: 38000, benefits: ["1 free checked bag"], next: { tier: "Gold", at: 65000, remaining: 27000 },
      milestones: [{ at: 20000, reward: "2,000 bonus points", reached: true }, { at: 95000, reward: "3 Companion Pass trips", reached: false }],
      companionPass: "Shown for context only.", synthetic: true,
    },
  }));
  withNoNudge();
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  await user.click(screen.getAllByRole("button", { name: /Rapid Rewards/ })[0]);
  const next = await screen.findByRole("region", { name: "Next flight preview" });
  assert.ok(within(next).getByText("Checked bag"));
  assert.ok(within(next).getAllByText("Covered").length > 0);
  assert.ok(screen.getByRole("img", { name: "Bars of points earned and used for each trip" }));
  const status = screen.getByRole("region", { name: "Rapid Rewards status" });
  assert.ok(within(status).getByText(/27,000 to Gold/));
  assert.ok(within(status).getByText("3 Companion Pass trips"));
});

test("a released bag says how many other travellers added a bag on the flight", async () => {
  server(rohith({ booking: trip({ reuse: { seat: null, bag: { othersAdded: 2 } } }) }));
  withNoNudge();
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  const card = screen.getByRole("region", { name: "Your released benefits" });
  assert.ok(within(card).getByText("2 other travellers added a bag on this flight after you released yours."));
});

test("notifications from the server are listed", async () => {
  server(rohith({ notifications: [
    { id: "expiry", kind: "expiry", text: "1,500 PerkFlex points expire on 2027-12-27. Spend them on this trip to keep their value." },
    { id: "posted", kind: "posted", text: "800 PerkFlex points from released benefits have posted to your wallet." },
  ] }));
  withNoNudge();
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  const box = screen.getByRole("region", { name: "Notifications" });
  assert.equal(within(box).getAllByRole("listitem").length, 2);
  assert.ok(within(box).getByText(/expire on 2027-12-27/));
});

test("no notifications means no notifications box", async () => {
  server(rohith());
  withNoNudge();
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  assert.ok(!screen.queryByRole("region", { name: "Notifications" }));
});

test("the wallet names the nearest goal and how far away it is", async () => {
  server(twoWallets());  // 400 PerkFlex + 600 Rapid Rewards = 1,000 spendable; the cheapest thing not covered is the 1,800-point standby
  withNoNudge();
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  await user.click(screen.getAllByRole("button", { name: /Rapid Rewards/ })[0]);
  const goal = await screen.findByRole("region", { name: "Your next goal" });
  assert.ok(within(goal).getByText("You are 800 points from same-day standby."));
});

test("the airline overview lists trips to review without naming travellers", async () => {
  on("GET", "/state", () => ({ status: 403, json: { error: "x" } }));
  on("GET", "/auth/me", () => ({ json: { user: { role: "AIRLINE_ADMIN" } } }));
  on("GET", "/admin/overview", () => ({
    json: {
      totals: { flights: 0, budget: 0, owed: 0, paid: 0, estimatedCost: 0, releases: 0, redemptions: 0, pointsSpent: 0 },
      flights: [],
      flags: [{ kind: "undo", booking: "ABC123", flightId: "WN2418", date: "2027-12-16", text: "Undid 3 releases (the limit)" }],
    },
  }));
  render(<App />);
  const box = await screen.findByRole("region", { name: "Trips to review" });
  assert.ok(within(box).getByText(/Undid 3 releases \(the limit\)/));
  assert.ok(within(box).getByText("ABC123"));
});

// ------------------------------------------------------------------ story mode, simulation, with/without
async function openGuide(user: User) {
  await user.click(screen.getByRole("button", { name: "Presenter guide" }));
  return screen.getByRole("complementary", { name: "Presenter guide" });
}

test("Run this scene switches traveller and sends the scene's real actions in order", async () => {
  server(rohith());
  withNoNudge();
  on("POST", "/demo/switch", () => ({ json: { user: { profileId: "kabir" } } }));
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  const panel = await openGuide(user);
  await user.click(within(panel).getByRole("button", { name: "Scene 2: Release an unused bag" }));
  await user.click(within(panel).getByRole("button", { name: "Run this scene" }));
  await waitFor(() => assert.equal(callsTo("POST", "/actions").length, 2));
  assert.equal(callsTo("POST", "/demo/switch")[0].body?.profileId, "kabir");
  const sent = callsTo("POST", "/actions").map((c) => c.body);
  assert.deepEqual(sent.map((b) => b?.type), ["open-checkin", "release"]);
  assert.equal(sent[1]?.benefit, "bag");
  assert.ok(sent.every((b) => typeof b?.idempotencyKey === "string" || b?.idempotencyKey === undefined));
});

test("a step the server refuses stops the run and shows the server's words", async () => {
  server(rohith());
  withNoNudge();
  on("POST", "/demo/switch", () => ({ json: { user: { profileId: "kabir" } } }));
  let n = 0;
  on("POST", "/actions", () => {
    n += 1;
    return { json: n === 1 ? current : { ...current, error: true, notice: "You have already accepted your one reward offer for this flight" } };
  });
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  const panel = await openGuide(user);
  await user.click(within(panel).getByRole("button", { name: "Scene 3: Swap a premium seat" }));
  await user.click(within(panel).getByRole("button", { name: "Run this scene" }));
  await waitFor(() => assert.match(within(panel).getByRole("status").textContent!, /already accepted your one reward/));
  assert.equal(callsTo("POST", "/actions").length, 2, "nothing runs after the refusal");
});

test("a scene with nothing to run has no Run button", async () => {
  server(rohith());
  withNoNudge();
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  const panel = await openGuide(user);
  await user.click(within(panel).getByRole("button", { name: "Scene 1: Start clean" }));
  assert.ok(!within(panel).queryByRole("button", { name: "Run this scene" }));
});

test("Play the whole story starts with a demo reset", async () => {
  server(rohith());
  withNoNudge();
  on("POST", "/demo/reset", () => ({ json: current }));
  on("POST", "/demo/switch", () => ({ json: { user: { profileId: "x" } } }));
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  const panel = await openGuide(user);
  await user.click(within(panel).getByRole("button", { name: "Play the whole story" }));
  await waitFor(() => assert.equal(callsTo("POST", "/demo/reset").length, 1));
  await waitFor(() => assert.ok(callsTo("POST", "/actions").length >= 2));
});

test("the fills-up scene asks the server to simulate other travellers", async () => {
  server(rohith());
  withNoNudge();
  on("POST", "/demo/switch", () => ({ json: { user: { profileId: "harshini" } } }));
  on("POST", "/demo/simulate", () => ({ json: { ...current, notice: "Another traveller was given seat 3A, the one you released." } }));
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  const panel = await openGuide(user);
  await user.click(within(panel).getByRole("button", { name: "Scene 9: The flight fills up" }));
  await user.click(within(panel).getByRole("button", { name: "Run this scene" }));
  await waitFor(() => assert.equal(callsTo("POST", "/demo/simulate").length, 2));
});

test("the airline sees a with-and-without estimate and its assumptions", async () => {
  on("GET", "/state", () => ({ status: 403, json: { error: "x" } }));
  on("GET", "/auth/me", () => ({ json: { user: { role: "AIRLINE_ADMIN" } } }));
  on("GET", "/admin/overview", () => ({
    json: {
      totals: { flights: 0, budget: 0, owed: 0, paid: 0, estimatedCost: 0, releases: 0, redemptions: 0, pointsSpent: 0 },
      flights: [],
      model: {
        with: { rewardCost: 10, seatResale: 110, net: 100 },
        without: { rewardCost: 0, seatResale: 0, net: 0 },
        assumptions: ["A seat that another traveller takes is valued at its list add-on price."],
      },
    },
  }));
  render(<App />);
  const box = await screen.findByRole("region", { name: "With and without PerkFlex" });
  assert.ok(within(box).getByText("$110.00"));
  assert.ok(within(box).getByText("$100.00"));
  assert.ok(within(box).getByText(/valued at its list add-on price/));
});

// ------------------------------------------------------------------ round 6: sale prices, groups, status nudge, airline settings
const salePrices = (over: Json = {}) => ({
  bag1: 2400,
  bag2: 3500,
  preferred: 2200,
  extra: 4500,
  list: { bag1: 3000, bag2: 3500, preferred: 2200, extra: 4500 },
  sales: { bag: 20 },
  ...over,
});
const standardTrip = () => trip({ seatClass: "standard", bags: 0, perks: perksFor() });

test("a sale on the traveller's flight is listed with the old and new price and nothing to switch on", async () => {
  server(rohith({ booking: standardTrip(), prices: salePrices() }));
  withNoNudge();
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  const card = screen.getByRole("region", { name: "On sale for your flight" });
  assert.ok(within(card).getByText("20% off"));
  const bag = card.querySelector('[data-sale="bag"]') as HTMLElement;
  assert.ok(within(bag).getByText("3,000") && within(bag).getByText(/2,400 pts/));
  assert.equal(within(card).queryAllByRole("button").length, 0);
});

test("nothing is shown when nothing is on sale or the server sends no prices", async () => {
  server(rohith({ booking: standardTrip(), prices: salePrices({ sales: {} }) }));
  withNoNudge();
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  assert.ok(!screen.queryByRole("region", { name: "On sale for your flight" }));
});

test("without prices from the server there is no sale card", async () => {
  server(rohith({ booking: standardTrip() }));
  withNoNudge();
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  assert.ok(!screen.queryByRole("region", { name: "On sale for your flight" }));
});

test("a price-drop notification is listed", async () => {
  server(rohith({ notifications: [{ id: "drop-bag", kind: "price-drop", text: "Sale: Checked bag is 20% off on your flight, 2,400 points instead of 3,000. You have enough points." }] }));
  withNoNudge();
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  assert.ok(within(screen.getByRole("region", { name: "Notifications" })).getByText(/2,400 points instead of 3,000/));
});

const nudge = { tier: "Gold", remaining: 27000, near: false, releaseBonusPct: 20, flyingBonusPct: 60, bagNow: 880, bagNext: 960, flyingNow: 3780, flyingNext: 4320 };
test("the status card says what the next level would be worth on the next trip", async () => {
  server(twoWallets({
    status: {
      tier: "Silver", tqp: 38000, benefits: ["1 free checked bag"], next: { tier: "Gold", at: 65000, remaining: 27000 },
      milestones: [], companionPass: "Shown for context only.", synthetic: true, nudge,
    },
  }));
  withNoNudge();
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  await user.click(screen.getAllByRole("button", { name: /Rapid Rewards/ })[0]);
  const line = await screen.findByTestId("status-nudge");
  assert.match(line.textContent!, /Gold would pay 960 points for a bag release \(now 880\)/);
  assert.match(line.textContent!, /\+60% on flying points/);
  assert.match(line.textContent!, /about 4,320 Rapid Rewards points instead of 3,780/);
});

const emptyGroup = (over: Json = {}) => ({
  inGroup: false,
  organiser: false,
  members: [],
  pendingInvites: [],
  invites: [],
  gifts: [],
  limits: { min: 100, max: 2000, daily: 3000, givenToday: 0, left: 3000, locked: false, groupMax: 6 },
  ...over,
});
const openWallet = async (user: User) => {
  await dismissWelcome(user);
  await user.click(screen.getAllByRole("button", { name: /Rapid Rewards/ })[0]);
  return screen.findByRole("region", { name: "Travel group" });
};

test("a traveller without a group can invite someone by sign-in name or Rapid Rewards number", async () => {
  server(twoWallets({ group: emptyGroup() }));
  withNoNudge();
  const user = setup();
  render(<App />);
  const card = await openWallet(user);
  await user.type(within(card).getByLabelText("Invite a traveller"), "kabir");
  await user.click(within(card).getByRole("button", { name: "Send invitation" }));
  const sent = callsTo("POST", "/actions").at(-1)!.body!;
  assert.deepEqual([sent.type, sent.companion], ["group-invite", "kabir"]);
});

test("an invitation can be accepted or declined", async () => {
  server(twoWallets({ group: emptyGroup({ invites: [{ group: "manish", from: "Manish Galigini" }] }) }));
  withNoNudge();
  const user = setup();
  render(<App />);
  const card = await openWallet(user);
  assert.ok(within(card).getByText("Manish Galigini"));
  await user.click(within(card).getByRole("button", { name: "Join" }));
  const sent = callsTo("POST", "/actions").at(-1)!.body!;
  assert.deepEqual([sent.type, sent.group, sent.accept], ["group-respond", "manish", true]);
  await user.click(within(card).getByRole("button", { name: "Decline" }));
  assert.equal(callsTo("POST", "/actions").at(-1)!.body!.accept, false);
});

const members = [
  { id: "rohith", name: "Rohith Gunda", tier: "Silver", you: true, organiser: true, trip: { route: "DAL → DEN", date: "2027-12-16", status: "BOOKED", released: false } },
  { id: "kabir", name: "Kabir Sethi", tier: "Platinum", you: false, organiser: false, trip: { route: "DAL → DEN", date: "2027-12-16", status: "BOOKED", released: true } },
];

test("group members are listed with their trips and a gift is sent for the chosen amount", async () => {
  server(twoWallets({ group: emptyGroup({ inGroup: true, organiser: true, members, gifts: [{ direction: "in", other: "Kabir Sethi", points: 200, at: "2027-12-15T10:00:00+00:00" }] }) }));
  withNoNudge();
  const user = setup();
  render(<App />);
  const card = await openWallet(user);
  assert.ok(within(card).getByText(/DAL → DEN · 2027-12-16 · booked · released a benefit/));
  assert.ok(within(card).getByText("Kabir Sethi gave you 200 points"));
  await user.selectOptions(within(card).getByLabelText("Points to give"), "100");
  await user.click(within(card).getByRole("button", { name: "Give 100" }));
  const sent = callsTo("POST", "/actions").at(-1)!.body!;
  assert.deepEqual([sent.type, sent.to, sent.points], ["gift", "kabir", 100]);
});

test("gifts are off while the traveller holds points they were just given", async () => {
  server(twoWallets({ group: emptyGroup({ inGroup: true, members, limits: { ...emptyGroup().limits, locked: true } }) }));
  withNoNudge();
  const user = setup();
  render(<App />);
  const card = await openWallet(user);
  assert.ok(within(card).getByText(/cannot be passed on yet/));
  assert.ok(within(card).getByRole("button", { name: /^Give/ }).hasAttribute("disabled"));
});

test("leaving a group is one click", async () => {
  server(twoWallets({ group: emptyGroup({ inGroup: true, organiser: false, members }) }));
  withNoNudge();
  const user = setup();
  render(<App />);
  const card = await openWallet(user);
  await user.click(within(card).getByRole("button", { name: "Leave this group" }));
  assert.equal(callsTo("POST", "/actions").at(-1)!.body!.type, "group-leave");
});

test("completion bonus and gift lines in the PerkFlex history have their own wording", async () => {
  server(twoWallets({ ledger: [
    { id: "PT9", bookingId: "", kind: "bonus", wallet: "perkflex", label: "Completion bonus", cashValue: 0, points: 50, status: "posted", createdAt: "2027-12-15T11:00:00+00:00" },
    { id: "PT8", bookingId: "", kind: "gift", wallet: "perkflex", label: "Gift received", cashValue: 0, points: 500, status: "posted", createdAt: "2027-12-15T10:00:00+00:00" },
  ] }));
  withNoNudge();
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  await user.click(screen.getAllByRole("button", { name: /Rapid Rewards/ })[0]);
  assert.ok(await screen.findByText("Completion bonus"));
  assert.ok(screen.getByText(/Trip completed · PerkFlex/));
  assert.ok(screen.getByText(/Travel group · PerkFlex/));
});

test("a sale price is what the check-in screen charges", async () => {
  server(rohith({ booking: standardTrip(), prices: salePrices(), balance: 2500, wallets: { perkflex: { available: 2500, pending: 0 }, rapidRewards: { available: 0, pending: 0 } } }));
  withNoNudge();
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  const card = screen.getByRole("heading", { name: "Add a checked bag" }).closest("article")!;
  assert.ok(within(card as HTMLElement).getByText("2,400"));
  assert.ok(within(card as HTMLElement).getByRole("button", { name: /Add bag with points/ }));
});

test("the sale scene asks the server for a sale on the Preferred seat", async () => {
  server(rohith());
  withNoNudge();
  on("POST", "/demo/switch", () => ({ json: { user: { profileId: "dev" } } }));
  on("POST", "/demo/sale", () => ({ json: current }));
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  const panel = await openGuide(user);
  await user.click(within(panel).getByRole("button", { name: "Scene 15: A points sale" }));
  await user.click(within(panel).getByRole("button", { name: "Run this scene" }));
  await waitFor(() => assert.equal(callsTo("POST", "/demo/sale").length, 1));
  assert.equal(callsTo("POST", "/demo/sale")[0].body?.benefit, "preferred");
  assert.deepEqual(callsTo("POST", "/actions").map((c) => c.body?.type), ["open-checkin"]);
});

test("the group scene invites, switches to the companion to accept, and switches back to give points", async () => {
  server(rohith());
  withNoNudge();
  on("POST", "/demo/switch", () => ({ json: { user: { profileId: "x" } } }));
  const user = setup();
  render(<App />);
  await dismissWelcome(user);
  const panel = await openGuide(user);
  await user.click(within(panel).getByRole("button", { name: "Scene 16: A travel group and a gift" }));
  await user.click(within(panel).getByRole("button", { name: "Run this scene" }));
  await waitFor(() => assert.equal(callsTo("POST", "/actions").length, 3));
  assert.deepEqual(callsTo("POST", "/actions").map((c) => c.body?.type), ["group-invite", "group-respond", "gift"]);
  assert.ok(callsTo("POST", "/demo/switch").length >= 2);
});

// ---- the airline's settings
const controls = (over: Json = {}) => ({
  policy: { mode: "FLAT", valuePercent: 18, centsPerPoint: 1, completionBonus: 50 },
  flights: [{ id: "F01", label: "WN2418 DAL → DEN, 2027-12-16" }],
  benefits: [{ key: "bag", name: "Checked bag" }, { key: "preferred", name: "Preferred seat" }],
  sales: [],
  audit: [],
  ...over,
});
function airline(c: Json = controls()) {
  on("GET", "/state", () => ({ status: 403, json: { error: "x" } }));
  on("GET", "/auth/me", () => ({ json: { user: { role: "AIRLINE_ADMIN" } } }));
  on("GET", "/admin/overview", () => ({
    json: { totals: { flights: 0, budget: 0, owed: 0, paid: 0, estimatedCost: 0, releases: 0, redemptions: 0, pointsSpent: 0 }, flights: [] },
  }));
  on("GET", "/admin/controls", () => ({ json: c }));
}

test("the airline can switch rewards to a percent of value and the change is sent", async () => {
  airline();
  on("POST", "/admin/policy", () => ({ json: controls({ policy: { mode: "VALUE", valuePercent: 18, centsPerPoint: 1, completionBonus: 50 }, audit: [{ at: "2027-12-15T10:00:00+00:00", by: "airline", setting: "release_mode", from: "FLAT", to: "VALUE" }] }) }));
  const user = setup();
  render(<App />);
  const box = await screen.findByRole("region", { name: "Airline settings" });
  assert.ok(within(box).getByText(/Bags and seats pay fixed amounts/));
  await user.click(within(box).getByRole("button", { name: "Percent of value" }));
  assert.deepEqual(callsTo("POST", "/admin/policy")[0].body, { mode: "VALUE" });
  assert.ok(await within(box).findByText(/Bags and seats pay 18% of their cash price/));
  assert.ok(within(box).getByText(/release_mode: FLAT → VALUE/));
});

test("the airline can set the completion bonus and run or end a sale", async () => {
  airline();
  on("POST", "/admin/policy", () => ({ json: controls() }));
  on("POST", "/admin/sale", () => ({ json: controls({ sales: [{ flightId: "F01", benefit: "bag", discountPct: 20, setBy: "airline", at: "x" }] }) }));
  const user = setup();
  render(<App />);
  const box = await screen.findByRole("region", { name: "Airline settings" });
  const bonus = within(box).getByLabelText("Bonus points");
  await user.clear(bonus);
  await user.type(bonus, "75");
  await user.click(within(box).getByRole("button", { name: "Save bonus" }));
  assert.deepEqual(callsTo("POST", "/admin/policy")[0].body, { completionBonus: 75 });
  await user.click(within(box).getByRole("button", { name: "Start sale" }));
  assert.deepEqual(callsTo("POST", "/admin/sale")[0].body, { flightId: "F01", benefit: "bag", discountPct: 20 });
  assert.ok(await within(box).findByText("20% off"));
  await user.click(within(box).getByRole("button", { name: "End sale" }));
  assert.equal(callsTo("POST", "/admin/sale")[1].body?.discountPct, 0);
});

test("a refused setting shows the server's message", async () => {
  airline();
  on("POST", "/admin/sale", () => ({ status: 422, json: { error: "A sale is 5 to 50 percent off." } }));
  const user = setup();
  render(<App />);
  const box = await screen.findByRole("region", { name: "Airline settings" });
  await user.click(within(box).getByRole("button", { name: "Start sale" }));
  assert.match((await within(box).findByRole("alert")).textContent!, /5 to 50 percent off/);
});

test("if the settings cannot be loaded the overview still works", async () => {
  airline();
  on("GET", "/admin/controls", () => ({ status: 500, json: { error: "boom" } }));
  render(<App />);
  await screen.findByText("What PerkFlex is costing, flight by flight");
  assert.ok(!screen.queryByRole("region", { name: "Airline settings" }));
});
