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
