import type { HistoryGap, MonthPoint } from "./types";

/** A month-end net-worth value placed at its real moment on a time axis. */
export interface CurvePoint extends MonthPoint {
  /** The point's date as a UTC timestamp (ms). */
  at: number;
  /** The value on the solid line: recorded by the app. Null elsewhere. */
  recorded: number | null;
  /** The value on the dashed line: partly rebuilt from past activity, plus the recorded points it joins. */
  rebuilt: number | null;
}

const MAX_TICKS = 6;
const MAX_MONTH_TICKS = 12;

function utcDay(isoDate: string): number {
  const [year, mon, day] = isoDate.slice(0, 10).split("-").map(Number);
  return Date.UTC(year, mon - 1, day);
}

/**
 * Puts each month's value at its date, so gaps between recorded months stay visible, and splits it
 * into a solid recorded line and a dashed rebuilt one that meet where one hands over to the other.
 * A month with no value is null on both, so the curve breaks there.
 */
export function toCurvePoints(history: MonthPoint[]): CurvePoint[] {
  const rebuilt = (i: number) => history[i]?.reconstructed === true && history[i].total_chf !== null;
  return history.map((point, i) => ({
    ...point,
    at: utcDay(point.date),
    recorded: point.reconstructed ? null : point.total_chf,
    rebuilt: rebuilt(i) || rebuilt(i - 1) || rebuilt(i + 1) ? point.total_chf : null,
  }));
}

/** The labels of the sources a point leaves out, in the order the gaps list them. */
export function missingLabels(point: MonthPoint, gaps: HistoryGap[]): string[] {
  const labels = new Map(gaps.map((gap) => [gap.source, gap.label]));
  return point.missing.map((source) => labels.get(source) ?? source);
}

/** The first day of every `stepMonths`-month period after `from`, up to `end`, aligned to month or year starts. */
function periodStarts(from: Date, end: number, stepMonths: 1 | 12): number[] {
  const year = from.getUTCFullYear();
  const month = stepMonths === 12 ? 0 : from.getUTCMonth();
  const starts: number[] = [];
  for (let k = 1; Date.UTC(year, month + k * stepMonths, 1) <= end; k++) {
    starts.push(Date.UTC(year, month + k * stepMonths, 1));
  }
  return starts;
}

/**
 * Where the time axis is labelled: month starts for up to a year of history, year starts (`byYear`) beyond,
 * thinned to at most six evenly spaced ticks.
 */
export function curveAxis(points: CurvePoint[]): { ticks: number[]; byYear: boolean } {
  const start = new Date(points[0].at);
  const end = points[points.length - 1].at;
  const monthStarts = periodStarts(start, end, 1);
  const byYear = monthStarts.length > MAX_MONTH_TICKS;
  const candidates = byYear ? periodStarts(start, end, 12) : monthStarts;
  const step = Math.max(1, Math.ceil(candidates.length / MAX_TICKS));
  return { ticks: candidates.filter((_, i) => i % step === 0), byYear };
}
