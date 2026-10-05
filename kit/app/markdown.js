// A tiny Markdown renderer for CONSENT.md: headings, paragraphs, bullet lists and bold. Everything
// else is shown as escaped plain text, so the consent text can't inject markup into the page.
// Headings shift down one level (# -> h2): the screen's own title is the page's h1.

const escape = (s) =>
  s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const inline = (s) => escape(s).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");

/** @param {string} markdown @returns {string} HTML */
export function renderMarkdown(markdown) {
  const lines = markdown.replace(/<!--[\s\S]*?-->/g, "").split(/\r?\n/);
  const out = [];
  let paragraph = [];
  let list = [];
  const flush = () => {
    if (paragraph.length) out.push(`<p>${inline(paragraph.join(" "))}</p>`);
    if (list.length) out.push(`<ul>${list.map((item) => `<li>${inline(item)}</li>`).join("")}</ul>`);
    paragraph = [];
    list = [];
  };
  for (const raw of lines) {
    const line = raw.trim();
    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    const item = line.match(/^[-*+]\s+(.*)$/);
    if (!line) {
      flush();
    } else if (heading) {
      flush();
      const level = Math.min(6, heading[1].length + 1);
      out.push(`<h${level}>${inline(heading[2])}</h${level}>`);
    } else if (item) {
      if (paragraph.length) flush();
      list.push(item[1]);
    } else {
      if (list.length) flush();
      paragraph.push(line);
    }
  }
  flush();
  return out.join("\n");
}
