import { test } from "node:test";
import assert from "node:assert/strict";
import { codeList, searchCodes, isListed } from "../core/codes.js";

const col = (...xs) => xs.map((x) => [x]);
const list = codeList({ code: col("03-100", "03-300", "03-399", ""), descr: col("Forming", "Cast-in-place concrete", "Odd", ""),
                        listed: col(1, 1, 0, null) });

test("codeList keeps listed and unlisted codes, skipping blanks", () => {
  assert.deepEqual(list.map((c) => [c.code, c.listed]), [["03-100", true], ["03-300", true], ["03-399", false]]);
});

test("search matches code or description, listed codes only", () => {
  assert.deepEqual(searchCodes(list, "concrete").map((c) => c.code), ["03-300"]);
  assert.deepEqual(searchCodes(list, "03-").map((c) => c.code), ["03-100", "03-300"]);
  assert.deepEqual(searchCodes(list, "").map((c) => c.code), ["03-100", "03-300"]);
});

test("isListed", () => {
  assert.equal(isListed(list, "03-300"), true);
  assert.equal(isListed(list, "03-399"), false);
  assert.equal(isListed(list, "99-999"), false);
});
