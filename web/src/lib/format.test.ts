import { test } from "node:test";
import assert from "node:assert/strict";
import {
  activeFilterCount,
  daysUntil,
  deadlineLabel,
  filtersToQuery,
  formatDate,
  formatSalary,
  htmlToText,
  kzToday,
  queryToFilters,
} from "./format.ts";

test("unknown values are shown as Unknown, never guessed", () => {
  assert.equal(formatDate(null), "Unknown");
  assert.equal(formatSalary(null), "Unknown");
  assert.equal(deadlineLabel(null).text, "Deadline unknown");
});

test("salary formats", () => {
  assert.equal(formatSalary({ min: 150000, max: 200000, currency: "KZT" }), "150 000–200 000 KZT");
  assert.equal(formatSalary({ min: 150000, currency: "KZT" }), "from 150 000 KZT");
  assert.equal(formatSalary({ max: 600, currency: "USD", period: "month" }), "up to 600 USD / month");
  assert.equal(formatSalary({ unpaid: true }), "Unpaid");
});

test("deadlines count calendar days in Kazakhstan time", () => {
  assert.equal(daysUntil("2026-12-01", "2026-11-26"), 5);
  assert.deepEqual(deadlineLabel("2026-11-26", "2026-11-26"), { text: "Closes today", urgent: true });
  assert.equal(deadlineLabel("2026-11-20", "2026-11-26").text, "Closed 20 Nov 2026");
  assert.equal(deadlineLabel("2027-01-10", "2026-11-26").text, "Apply by 10 Jan 2027");
  // 20:00 UTC on Nov 26 is already Nov 27 in Astana
  assert.equal(kzToday(new Date("2026-11-26T20:00:00Z")), "2026-11-27");
});

test("filters round-trip through the URL", () => {
  const f = { q: "python", skill: ["Python", "SQL"], city: ["Almaty"], internship_only: true, sort: "deadline" as const };
  const back = queryToFilters(filtersToQuery(f));
  assert.deepEqual(back, f);
  assert.equal(activeFilterCount(back), 4);
});

test("html to text keeps structure and drops tags", () => {
  assert.equal(htmlToText("<p>Hi&nbsp;there</p><ul><li>SQL</li><li>Git</li></ul><script>x</script>"), "Hi there\n• SQL\n• Git");
});
