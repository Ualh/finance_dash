export type AmountResult = { ok: true; value: number } | { ok: false; message: string };

const NUMBER = /^-?\d+(\.\d+)?$/;
const THOUSANDS_SEPARATORS = /['’\s]/g;

/** Reads what the user typed in an amount field: a number, above zero. */
export function parsePositiveAmount(text: string): AmountResult {
  const cleaned = text.replace(THOUSANDS_SEPARATORS, "");
  if (!NUMBER.test(cleaned)) {
    return { ok: false, message: "Enter a number, for example 42500 or 1250.75." };
  }
  const value = Number(cleaned);
  if (value <= 0) {
    return { ok: false, message: "Enter an amount greater than zero." };
  }
  return { ok: true, value };
}
