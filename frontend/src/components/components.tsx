import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import { ArrowRight, Check, Plane, Sparkles, X } from "lucide-react";
import type { Booking } from "../rules/types.ts";
import { AIRPORTS, flightById } from "../rules/data.ts";

export function HeartMark() {
  return (
    <svg
      className="heart-mark"
      width="28"
      height="28"
      viewBox="0 0 32 32"
      aria-hidden="true"
    >
      <defs>
        <clipPath id="heart-clip">
          <path d="M16 28 3.8 15.6C-5 6.3 7.5-2.9 16 6.1c8.5-9 21 0.2 12.2 9.5Z" />
        </clipPath>
      </defs>
      <g clipPath="url(#heart-clip)">
        <path fill="#f7c52c" d="M0 0h32v32H0z" />
        <path fill="#e62d42" d="m-4 0 40 25v12L-4 12z" />
        <path fill="#3456b9" d="M-4 12 30 34H-4z" />
      </g>
    </svg>
  );
}
export function PerkFlexLogo({ compact = false }: { compact?: boolean }) {
  return (
    <span className={`perkflex-logo ${compact ? "compact" : ""}`}>
      <span className="perkflex-wordmark">
        Perk<span>Flex</span>
      </span>
      <span className="perkflex-heart">
        <HeartMark />
      </span>
    </span>
  );
}
export function PerkMark({ small = false }: { small?: boolean }) {
  return (
    <span className={`perk-mark ${small ? "small" : ""}`} aria-hidden="true">
      <Sparkles size={small ? 17 : 23} strokeWidth={1.8} />
    </span>
  );
}
export function Modal({
  title,
  children,
  onClose,
  wide = false,
  className = "",
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
  className?: string;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    dialog?.showModal();
    return () => {
      dialog?.close();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      className={`modal ${wide ? "modal-wide" : ""} ${className}`}
      aria-label={title}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onClick={(e) => {
        if (e.target === ref.current) onClose();
      }}
    >
      <button
        className="icon-button modal-close"
        onClick={onClose}
        aria-label="Close dialog"
      >
        <X size={21} />
      </button>
      {children}
    </dialog>
  );
}
export function Pill({
  children,
  tone = "blue",
}: {
  children: ReactNode;
  tone?: string;
}) {
  return <span className={`pill ${tone}`}>{children}</span>;
}
export function CheckLine({
  children,
  muted = false,
}: {
  children: ReactNode;
  muted?: boolean;
}) {
  return (
    <div className={`check-line ${muted ? "muted" : ""}`}>
      <Check size={16} />
      <span>{children}</span>
    </div>
  );
}
export function EmptyState({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="empty-state">
      <span className="soft-icon">
        <Sparkles size={24} />
      </span>
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}
export function FlightRoute({
  booking,
  compact = false,
}: {
  booking: Booking;
  compact?: boolean;
}) {
  const f = flightById(booking.flightId);
  return (
    <div className={`flight-route ${compact ? "compact" : ""}`}>
      <div>
        <span className="tiny-caps">
          {AIRPORTS.find((a) => a.code === booking.from)?.city}
        </span>
        <strong>{booking.from}</strong>
        <span>{f.departure}</span>
      </div>
      <div className="route-middle">
        <span>{f.duration} · Nonstop</span>
        <div className="route-line">
          <span />
          <Plane size={21} />
          <span />
        </div>
        <span>{booking.flightId.replace("WN", "WN ")}</span>
      </div>
      <div className="route-destination">
        <span className="tiny-caps">
          {AIRPORTS.find((a) => a.code === booking.to)?.city}
        </span>
        <strong>{booking.to}</strong>
        <span>{f.arrival}</span>
      </div>
    </div>
  );
}
export function DateLabel({ date }: { date: string }) {
  return (
    <>
      {new Intl.DateTimeFormat("en-US", {
        weekday: "short",
        month: "short",
        day: "numeric",
        year: "numeric",
        timeZone: "UTC",
      }).format(new Date(`${date}T12:00:00Z`))}
    </>
  );
}
export function LinkButton({
  children,
  onClick,
}: {
  children: ReactNode;
  onClick: () => void;
}) {
  return (
    <button className="text-button" onClick={onClick}>
      {children}
      <ArrowRight size={16} />
    </button>
  );
}
export function SkyIllustration() {
  return (
    <div className="sky-scene" aria-hidden="true">
      <div className="sky-orbit orbit-one" />
      <div className="sky-orbit orbit-two" />
      <svg className="airplane-art" viewBox="0 0 760 410" fill="none">
        <defs>
          <linearGradient
            id="body"
            x1="150"
            y1="120"
            x2="460"
            y2="340"
            gradientUnits="userSpaceOnUse"
          >
            <stop stopColor="#fff" />
            <stop offset=".55" stopColor="#ecf3fc" />
            <stop offset="1" stopColor="#b3c9ef" />
          </linearGradient>
          <linearGradient
            id="wing"
            x1="300"
            y1="120"
            x2="440"
            y2="360"
            gradientUnits="userSpaceOnUse"
          >
            <stop stopColor="#fff" />
            <stop offset="1" stopColor="#7698d6" />
          </linearGradient>
          <linearGradient id="tail" x1="550" y1="70" x2="650" y2="220">
            <stop stopColor="#355ac7" />
            <stop offset="1" stopColor="#153790" />
          </linearGradient>
          <filter
            id="plane-shadow"
            x="0"
            y="0"
            width="760"
            height="410"
            filterUnits="userSpaceOnUse"
          >
            <feDropShadow
              dx="0"
              dy="26"
              stdDeviation="17"
              floodColor="#4266ab"
              floodOpacity=".17"
            />
          </filter>
        </defs>
        <g filter="url(#plane-shadow)" transform="rotate(-12 380 205)">
          <path d="m377 219 78-129 41-5-47 154Z" fill="#bfcee6" />
          <path d="m573 185 44-117 30 1-2 136Z" fill="url(#tail)" />
          <path d="m617 68 12 1-19 124-20-4Z" fill="#e73443" />
          <path d="m629 69 11 0-5 132-25-8Z" fill="#ffca35" />
          <path
            d="M122 216c19-28 60-42 119-44l381 12 58 27-59 35-392 4c-52-1-83-9-107-23-6-4-6-7 0-11Z"
            fill="url(#body)"
          />
          <path
            d="M139 233c45 18 103 14 149 13l336-7 36-18-37 25-392 4c-43 0-73-7-92-17Z"
            fill="#345abc"
          />
          <path d="m178 184 25-4-10 14-27 3Z" fill="#214182" />
          <path d="m207 180 22-1-8 13-20 1Z" fill="#214182" />
          {Array.from({ length: 15 }, (_, i) => (
            <rect
              key={i}
              x={257 + i * 20}
              y={193 + i * 0.2}
              width="8"
              height="10"
              rx="4"
              fill="#6981b0"
            />
          ))}
          <path d="m364 220 57 128 56 11-47-153Z" fill="url(#wing)" />
          <path d="m421 348 56 11 5-25-11-5-2 18Z" fill="#3459b9" />
          <path
            d="m405 262 44 4 9 34-42 1c-17-1-27-10-26-20 1-9 7-15 15-19Z"
            fill="#f1f5fd"
          />
          <ellipse cx="447" cy="283" rx="11" ry="17" fill="#173b89" />
          <ellipse cx="447" cy="283" rx="6" ry="11" fill="#7093ca" />
          <path d="m591 224 54 51 26-1-36-58Z" fill="#a7bce0" />
        </g>
        <path
          d="M46 115c45-41 110-65 166-47"
          stroke="white"
          strokeWidth="2"
          strokeDasharray="5 9"
          opacity=".65"
        />
        <circle cx="47" cy="115" r="5" fill="white" />
      </svg>
      <div className="flying-perk perk-bag">
        <span>✦</span> Your perks. Your choice.
      </div>
      <div className="flying-perk perk-points">
        <span className="points-dot">+</span> A little more rewarding.
      </div>
    </div>
  );
}
