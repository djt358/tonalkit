import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = (rel) => readFileSync(new URL(rel, import.meta.url), "utf8");

function csp(html) {
  const meta = html.match(/<meta http-equiv="Content-Security-Policy" content="([^"]+)">/);
  assert.ok(meta, "no CSP meta tag");
  return Object.fromEntries(
    meta[1].split(";").map((d) => d.trim().split(/\s+/)).map(([name, ...sources]) => [name, sources]),
  );
}

test("the kit's page allows only its own origin (and blob: playback, data: icon)", () => {
  assert.deepEqual(csp(read("../../app/index.html")), {
    "default-src": ["'self'"],
    "connect-src": ["'self'"],
    "media-src": ["'self'", "blob:"],
    "img-src": ["'self'", "data:"],
    "script-src": ["'self'"],
    "worker-src": ["'self'"],
    "style-src": ["'self'"],
    "form-action": ["'none'"],
    "base-uri": ["'none'"],
  });
});

test("the site root's redirect has its own CSP and no inline script", () => {
  const policy = csp(read("../../index.html"));
  assert.deepEqual(policy["default-src"], ["'none'"]);
  assert.deepEqual(policy["script-src"], ["'self'"]);
});

test("no page has an inline script, style or event handler (the CSP would block them)", () => {
  for (const page of ["../../index.html", "../../app/index.html"]) {
    const html = read(page);
    for (const tag of html.match(/<script\b[^>]*>/g) ?? []) assert.match(tag, /\bsrc="/, `${page}: ${tag}`);
    assert.doesNotMatch(html, /<style\b|\sstyle="|\son[a-z]+="/, page);
  }
});
