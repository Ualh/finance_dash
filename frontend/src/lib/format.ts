const LOCALE = "de-CH";

export function formatMoney(amount: number, currency = "CHF"): string {
  return new Intl.NumberFormat(LOCALE, {
    style: "currency",
    currency,
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(amount);
}

/** "+1’500 CHF", "−200 CHF", "±0 CHF": the sign is always shown. */
export function formatChange(amount: number, currency = "CHF"): string {
  const rounded = Math.round(amount);
  const sign = rounded > 0 ? "+" : rounded < 0 ? "−" : "±";
  return `${sign}${formatMoney(Math.abs(rounded), currency)}`;
}

/** "2026-11" → "Nov". */
export function formatMonthShort(month: string): string {
  const [year, mon] = month.split("-").map(Number);
  return new Date(Date.UTC(year, mon - 1, 1)).toLocaleString("en-GB", { month: "short", timeZone: "UTC" });
}

/** "2026-11" → "November 2026". */
export function formatMonthLong(month: string): string {
  const [year, mon] = month.split("-").map(Number);
  return new Date(Date.UTC(year, mon - 1, 1)).toLocaleString("en-GB", { month: "long", year: "numeric", timeZone: "UTC" });
}

/** "2026-06-03" → "3 Jun"; adds the year when it is not `currentYear`. */
export function formatDay(isoDate: string, currentYear: number): string {
  const [year, mon, day] = isoDate.slice(0, 10).split("-").map(Number);
  const date = new Date(Date.UTC(year, mon - 1, day));
  return date.toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    ...(year !== currentYear ? { year: "numeric" } : {}),
    timeZone: "UTC",
  });
}

/** Whole days from `iso` to `now`, by calendar day in local time. */
export function daysAgo(iso: string, now: Date): number {
  const then = new Date(iso);
  const day = (d: Date) => Date.UTC(d.getFullYear(), d.getMonth(), d.getDate());
  return Math.round((day(now) - day(then)) / 86_400_000);
}

/** A past moment in local time: "today 06:00", "yesterday 06:00", else "3 Jun" (with the year when it differs). */
export function formatMoment(iso: string, now: Date): string {
  const then = new Date(iso);
  const days = daysAgo(iso, now);
  const time = then.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  if (days <= 0) return `today ${time}`;
  if (days === 1) return `yesterday ${time}`;
  const local = `${then.getFullYear()}-${String(then.getMonth() + 1).padStart(2, "0")}-${String(then.getDate()).padStart(2, "0")}`;
  return formatDay(local, now.getFullYear());
}
