import { test } from "node:test";
import assert from "node:assert/strict";
import { renderMarkdown } from "../../app/markdown.js";

test("headings, paragraphs, bullet lists and bold; nothing else", () => {
  const md = [
    "<!-- consent: v1 -->",
    "# What we record",
    "",
    "Your voice reading",
    "the cards.",
    "",
    "- **No names**, ever",
    "* three optional answers",
    "",
    "## Your choice",
    "You can stop **anytime**.",
  ].join("\n");
  assert.equal(
    renderMarkdown(md),
    [
      "<h2>What we record</h2>",
      "<p>Your voice reading the cards.</p>",
      "<ul><li><strong>No names</strong>, ever</li><li>three optional answers</li></ul>",
      "<h3>Your choice</h3>",
      "<p>You can stop <strong>anytime</strong>.</p>",
    ].join("\n"),
  );
});

test("HTML in the source is escaped, never rendered", () => {
  assert.equal(
    renderMarkdown('<script>alert("x")</script> & <b>bold</b>'),
    "<p>&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; &amp; &lt;b&gt;bold&lt;/b&gt;</p>",
  );
});

test("comments (including multi-line ones) are dropped; CRLF works", () => {
  assert.equal(renderMarkdown("<!--\nnote\n-->\r\nHello\r\n"), "<p>Hello</p>");
});

test("unsupported syntax stays as plain text", () => {
  assert.equal(renderMarkdown("1. one\n[link](http://x) *em* `code`"), "<p>1. one [link](http://x) *em* `code`</p>");
  assert.equal(renderMarkdown("**unclosed bold"), "<p>**unclosed bold</p>");
});

test("a list ends at a blank line or a non-list line", () => {
  assert.equal(renderMarkdown("- a\n- b\nafter"), "<ul><li>a</li><li>b</li></ul>\n<p>after</p>");
});
