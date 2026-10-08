export const PAPER_TAG = '(paper trading)';

export function bragText(text: string, live: boolean): string {
  if (live) return text;
  if (text.includes(PAPER_TAG)) return text;
  const i = text.indexOf('Krypt Trader');
  if (i < 0) return `${PAPER_TAG} ${text}`;
  const at = i + 'Krypt Trader'.length;
  return `${text.slice(0, at)} ${PAPER_TAG}${text.slice(at)}`;
}
