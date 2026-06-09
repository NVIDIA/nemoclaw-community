import DOMPurify from "dompurify";
import MarkdownIt from "markdown-it";
import { useMemo } from "react";

const markdown = new MarkdownIt({
  breaks: true,
  html: true,
  linkify: true,
  typographer: true,
});

const defaultLinkOpen =
  markdown.renderer.rules.link_open ??
  ((tokens, index, options, _env, self) =>
    self.renderToken(tokens, index, options));

markdown.renderer.rules.link_open = (tokens, index, options, env, self) => {
  const token = tokens[index];
  token.attrSet("target", "_blank");
  token.attrSet("rel", "noreferrer noopener");
  return defaultLinkOpen(tokens, index, options, env, self);
};

function splitTableCells(line: string): string[] {
  const trimmed = line.trim().replace(/^\|/, "").replace(/\|$/, "");
  return trimmed.split("|").map((cell) => cell.trim());
}

function isTableLine(line: string): boolean {
  if (!line.includes("|")) return false;
  const cells = splitTableCells(line);
  return cells.length >= 2 && cells.every(Boolean);
}

function isTableSeparator(line: string): boolean {
  return splitTableCells(line).every((cell) => /^:?-{3,}:?$/.test(cell));
}

function normalizeLooseTables(text: string): string {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const normalized: string[] = [];
  let index = 0;

  while (index < lines.length) {
    if (!isTableLine(lines[index])) {
      normalized.push(lines[index]);
      index += 1;
      continue;
    }

    const tableLines: string[] = [];
    while (index < lines.length && isTableLine(lines[index])) {
      tableLines.push(lines[index]);
      index += 1;
    }

    if (tableLines.length < 2 || isTableSeparator(tableLines[1])) {
      normalized.push(...tableLines);
      continue;
    }

    const columnCount = splitTableCells(tableLines[0]).length;
    const sameShape = tableLines.every(
      (line) => splitTableCells(line).length === columnCount,
    );

    if (!sameShape) {
      normalized.push(...tableLines);
      continue;
    }

    normalized.push(
      tableLines[0],
      Array.from({ length: columnCount }, () => "---").join(" | "),
      ...tableLines.slice(1),
    );
  }

  return normalized.join("\n");
}

export function Markdown({ text }: { text: string }) {
  const html = useMemo(() => {
    const rendered = markdown.render(normalizeLooseTables(text));
    return DOMPurify.sanitize(rendered, {
      USE_PROFILES: { html: true },
    });
  }, [text]);

  return (
    <div
      className="markdown-body"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
