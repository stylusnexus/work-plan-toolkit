/**
 * Track recency: when a track last saw activity, whether it has gone stale, and
 * how to say so (#428). Pure — no vscode import, and "now" is always a parameter
 * so every result is deterministic and a threshold change needs no refetch.
 *
 * Timestamps come from the CLI export as the strings written in frontmatter:
 * "YYYY-MM-DD" or "YYYY-MM-DDTHH:MM[:SS]", local time. Anything else (missing,
 * blank, malformed, an impossible date) is UNKNOWN: it never throws, never makes
 * a track stale, and sorts after every known time.
 */

import type { Track } from "./model.ts";

export const DEFAULT_STALE_DAYS = 14;

const DAY_MS = 86_400_000;

/** Statuses a stale flag is meaningful for; shipped/parked/abandoned are done by design. */
const LIVE_STATUSES = new Set(["active", "in-progress", "blocked"]);

export interface StaleOpts {
  staleDays: number;
  /** Epoch milliseconds. */
  now: number;
}

/** A usable stale threshold: a whole number of days, at least 1; else the default. */
export function normalizeStaleDays(value: unknown): number {
  return typeof value === "number" && Number.isInteger(value) && value >= 1
    ? value
    : DEFAULT_STALE_DAYS;
}

/** Parses a frontmatter timestamp to epoch ms (local time), or null if unusable. */
export function parseTrackTimestamp(value: unknown): number | null {
  if (typeof value !== "string") return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2})(?::(\d{2}))?)?$/.exec(value.trim());
  if (m === null) return null;
  const [y, mo, d, h, mi, s] = [m[1], m[2], m[3], m[4], m[5], m[6]].map(x =>
    x === undefined ? 0 : Number(x),
  );
  const date = new Date(y, mo - 1, d, h, mi, s);
  // Date silently rolls impossible values over (month 13, Feb 30, hour 25);
  // reject anything that did not round-trip.
  if (
    date.getFullYear() !== y || date.getMonth() !== mo - 1 || date.getDate() !== d ||
    date.getHours() !== h || date.getMinutes() !== mi || date.getSeconds() !== s
  ) {
    return null;
  }
  return date.getTime();
}

/**
 * When the track last saw activity: `last_touched`, falling back to
 * `last_handoff` when that is missing or unusable. null when neither parses.
 */
export function lastActivityMs(track: Pick<Track, "last_touched" | "last_handoff">): number | null {
  return parseTrackTimestamp(track.last_touched) ?? parseTrackTimestamp(track.last_handoff);
}

/** The raw timestamp string `lastActivityMs` used (trimmed), or null. For display next to an age. */
export function lastActivityRaw(track: Pick<Track, "last_touched" | "last_handoff">): string | null {
  for (const raw of [track.last_touched, track.last_handoff]) {
    if (parseTrackTimestamp(raw) !== null) return (raw as string).trim();
  }
  return null;
}

/** Whole-or-fractional days since last activity, or null when unknown. May be negative (clock skew). */
export function trackAgeDays(
  track: Pick<Track, "last_touched" | "last_handoff">,
  now: number,
): number | null {
  const ms = lastActivityMs(track);
  return ms === null ? null : (now - ms) / DAY_MS;
}

/**
 * Stale = a live track (active / in-progress / blocked, not archived) whose last
 * activity is at least `staleDays` old. Unknown activity is never stale: absence
 * of a timestamp is not evidence of neglect.
 */
export function isStaleTrack(
  track: Pick<Track, "status" | "archived" | "last_touched" | "last_handoff">,
  staleDays: number,
  now: number,
): boolean {
  if (!LIVE_STATUSES.has(track.status) || track.archived === true) return false;
  const age = trackAgeDays(track, now);
  return age !== null && age >= staleDays;
}

/**
 * Orders two tracks oldest-activity first; unknown after known; `name` breaks
 * ties so the order is total and deterministic.
 */
export function compareByLeastRecent(
  a: Pick<Track, "name" | "last_touched" | "last_handoff">,
  b: Pick<Track, "name" | "last_touched" | "last_handoff">,
): number {
  const am = lastActivityMs(a);
  const bm = lastActivityMs(b);
  if (am !== bm) {
    if (am === null) return 1;
    if (bm === null) return -1;
    return am - bm;
  }
  return a.name.localeCompare(b.name);
}

/** "today" · "1 day ago" · "5 days ago" · "3 weeks ago" · "4 months ago". */
export function formatAge(days: number): string {
  const d = Math.floor(days);
  if (d < 1) return "today"; // also covers a timestamp slightly in the future
  if (d < 14) return d === 1 ? "1 day ago" : `${d} days ago`;
  if (d < 60) return `${Math.floor(d / 7)} weeks ago`;
  return `${Math.floor(d / 30)} months ago`;
}

/** "last touched 3 weeks ago", or null when the track has no usable timestamp. */
export function describeActivity(
  track: Pick<Track, "last_touched" | "last_handoff">,
  now: number,
): string | null {
  const age = trackAgeDays(track, now);
  return age === null ? null : `last touched ${formatAge(age)}`;
}
