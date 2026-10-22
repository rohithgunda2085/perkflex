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

const { render, screen, cleanup, waitFor } =
  await import("@testing-library/react");
const { default: userEvent } = await import("@testing-library/user-event");
const { default: App } = await import("../src/App.tsx");

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
