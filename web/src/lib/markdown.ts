/** Minimal safe renderer: escapes ALL HTML first, then supports **bold**, *italic*, `code`, line breaks and "- " lists. */
const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const inline = (s: string) => esc(s).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>").replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
export function renderMarkdown(text: string): string {
  const out: string[] = []; let list = false;
  for (const line of text.split("\n")) {
    const m = /^\s*[-*]\s+(.*)$/.exec(line);
    if (m) { if (!list) { out.push("<ul>"); list = true; } out.push(`<li>${inline(m[1])}</li>`); continue; }
    if (list) { out.push("</ul>"); list = false; }
    out.push(line.trim() ? `<p>${inline(line)}</p>` : "");
  }
  if (list) out.push("</ul>");
  return out.join("");
}
