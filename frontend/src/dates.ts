/** Display timestamps in Eastern Time (handles EST/EDT). */
export const APP_TIME_ZONE = "America/New_York";

const dtOpts: Intl.DateTimeFormatOptions = {
  timeZone: APP_TIME_ZONE,
  month: "2-digit",
  day: "2-digit",
  year: "numeric",
  hour: "numeric",
  minute: "2-digit",
  hour12: true,
};

const dateOpts: Intl.DateTimeFormatOptions = {
  timeZone: APP_TIME_ZONE,
  month: "2-digit",
  day: "2-digit",
  year: "numeric",
};

function parseUtcLike(iso: string): Date {
  // DB may return naive UTC strings (no trailing Z/offset). Treat those as UTC.
  const hasTz = /([zZ]|[+\-]\d{2}:\d{2})$/.test(iso);
  return new Date(hasTz ? iso : `${iso}Z`);
}

/** ISO instant (e.g. scanned_at) → Eastern date/time string */
export function fmtDateTimeEt(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = parseUtcLike(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("en-US", dtOpts);
}

/**
 * Calendar date YYYY-MM-DD (no timezone) — avoid UTC shift from Date.parse.
 * For DOS / local calendar days stored as date-only.
 */
export function fmtCalendarDateEt(ymd: string | null | undefined): string {
  if (!ymd) return "—";
  const m = String(ymd).match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return "—";
  const y = Number(m[1]);
  const mo = Number(m[2]);
  const day = Number(m[3]);
  const d = new Date(y, mo - 1, day);
  return d.toLocaleDateString("en-US", dateOpts);
}

/** Date-only for DOS in MM-DD-YYYY */
export function fmtCalendarDateMdY(ymd: string | null | undefined): string {
  if (!ymd) return "—";
  const m = String(ymd).match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return "—";
  return `${m[2]}-${m[3]}-${m[1]}`;
}
