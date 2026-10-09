const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const href = (s: string) =>
  s
    .replace(/&(?!(?:amp|lt|gt|quot);)/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");

/** Conservative Markdown to Telegram HTML. Tokens are replaced with sentinels so user HTML is always escaped. */
export function markdownToHtml(source: string): string {
  const held: string[] = [];
  const hold = (html: string) => `\u0000${held.push(html) - 1}\u0000`;
  let s = source.replace(/```([\w+-]*)\n?([\s\S]*?)```/g, (_m, lang, code) =>
    hold(
      `<pre><code${lang ? ` class="language-${href(lang)}"` : ""}>${esc(code.replace(/\n$/, ""))}</code></pre>`,
    ),
  );
  s = s.replace(/`([^`\n]+)`/g, (_m, code) => hold(`<code>${esc(code)}</code>`));
  s = esc(s);
  s = s.replace(/^#{1,6}\s+(.+)$/gm, "<b>$1</b>");
  s = s.replace(/^&gt;\s?(.*)$/gm, "<blockquote>$1</blockquote>");
  s = s.replace(
    /\[([^\]\n]+)\]\((https?:\/\/[^\s)]+|tg:\/\/[^\s)]+)\)/g,
    (_m, label, url) => `<a href="${href(url)}">${label}</a>`,
  );
  s = s.replace(/\*\*([^*\n]+)\*\*/g, "<b>$1</b>").replace(/~~([^~\n]+)~~/g, "<s>$1</s>");
  s = s.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<i>$2</i>").replace(/(^|\W)_([^_\n]+)_(?=\W|$)/g, "$1<i>$2</i>");
  return s.replace(/\u0000(\d+)\u0000/g, (_m, i) => held[Number(i)] ?? "");
}

/** Split source before rendering, keeping each fenced-code chunk independently balanced. */
export function splitMarkdown(source: string, target = 3800): string[] {
  if (!source) return [];
  const out: string[] = [];
  let rest = source;
  while (rest.length > target) {
    let cut = Math.max(
      rest.lastIndexOf("\n\n", target),
      rest.lastIndexOf("\n", target),
      rest.lastIndexOf(" ", target),
    );
    if (cut < target / 2) cut = target;
    let part = rest.slice(0, cut);
    rest = rest.slice(cut).replace(/^\s+/, "");
    const fences = (part.match(/```/g) ?? []).length;
    if (fences % 2) {
      const language = /```([^\n]*)\n[^`]*$/.exec(part)?.[1] ?? "";
      part += "\n```";
      rest = `\`\`\`${language}\n${rest}`;
    }
    out.push(part);
  }
  if (rest) out.push(rest);
  return out.flatMap((chunk) =>
    markdownToHtml(chunk).length <= 4096 || chunk.length <= 1
      ? [chunk]
      : splitMarkdown(chunk, Math.max(1, Math.floor(Math.min(target, chunk.length - 1) / 2))),
  );
}

export { esc as escapeHtml };
