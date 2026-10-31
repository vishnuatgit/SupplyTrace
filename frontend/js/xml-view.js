// Renders an XML document with syntax colours and line numbers, and marks the
// lines behind each rule. Only textContent is used, so an uploaded file can't
// inject markup.

import { el, clear, prefersReducedMotion } from './ui.js';

// Very large files are cut off in the preview to keep the page responsive.
const MAX_LINES = 4000;
const LINE_BREAK = /\r\n|\r|\n/;

// Higher wins when two marks share a line.
const MARK_PRIORITY = { found: 1, review: 2, invalid: 3, error: 4 };

// Splits a tag such as <PayableAmount currencyID="USD"> into coloured pieces.
function tokenizeTag(tag) {
    const match = tag.match(/^(<\/?)([^\s/>]*)([\s\S]*?)(\/?>)?$/);
    if (!match) return [{ type: 'punct', text: tag }];
    const [, open, name, rest, close = ''] = match;
    const tokens = [{ type: 'punct', text: open }, { type: 'tag', text: name }];
    for (const [part, attr, equals, value] of rest.matchAll(/([^\s=]+)(\s*=\s*)?("[^"]*"?|'[^']*'?)?|\s+|[\s\S]/g)) {
        if (attr) {
            tokens.push({ type: 'attr', text: attr });
            if (equals) tokens.push({ type: 'punct', text: equals });
            if (value) tokens.push({ type: 'val', text: value });
        } else {
            tokens.push({ type: /^\s+$/.test(part) ? 'space' : 'punct', text: part });
        }
    }
    tokens.push({ type: 'punct', text: close });
    // Safety net: if the pieces don't add up to the tag, show it uncoloured.
    return tokens.map(t => t.text).join('') === tag ? tokens : [{ type: 'punct', text: tag }];
}

// Splits XML text into [{type, text}] pieces that together cover every character.
function tokenize(text) {
    const tokens = [];
    const pattern = /<!\[CDATA\[[\s\S]*?(?:\]\]>|$)|<!--[\s\S]*?(?:-->|$)|<[?!][\s\S]*?(?:>|$)|<\/?[^>]*>?|[^<]+/g;
    for (const [piece] of text.matchAll(pattern)) {
        if (piece.startsWith('<![CDATA[')) tokens.push({ type: 'text', text: piece });
        else if (piece.startsWith('<!') || piece.startsWith('<?')) tokens.push({ type: 'meta', text: piece });
        else if (piece.startsWith('<')) tokens.push(...tokenizeTag(piece));
        else tokens.push({ type: 'text', text: piece });
    }
    return tokens;
}

// Regroups tokens into lines (a token can span several lines).
function toLines(tokens) {
    const lines = [[]];
    for (const token of tokens) {
        token.text.split(LINE_BREAK).forEach((part, i) => {
            if (i > 0) lines.push([]);
            if (part) lines[lines.length - 1].push({ type: token.type, text: part });
        });
    }
    return lines;
}

// marks: [{ line, endLine, kind: 'invalid' | 'review' | 'found' | 'error', badge, title }]
function marksByLine(marks) {
    const byLine = new Map();
    for (const mark of marks) {
        if (!mark.line) continue;
        for (let n = mark.line; n <= (mark.endLine || mark.line); n++) {
            const current = byLine.get(n) || { kind: null, badges: [], titles: [] };
            if (!current.kind || MARK_PRIORITY[mark.kind] > MARK_PRIORITY[current.kind]) current.kind = mark.kind;
            if (n === mark.line && mark.badge) current.badges.push(mark.badge);
            if (mark.title) current.titles.push(mark.title);
            byLine.set(n, current);
        }
    }
    return byLine;
}

function renderCode(tokens) {
    return tokens.map(token => {
        if (token.type === 'space' || (token.type === 'text' && !token.text.trim())) return token.text;
        return el('span', { class: `t-${token.type}`, text: token.text });
    });
}

// Syntax colours for a short snippet (the examples on the rules page).
export function highlightXml(text) {
    return toLines(tokenize(text)).flatMap((tokens, i) => (i ? ['\n', ...renderCode(tokens)] : renderCode(tokens)));
}

export function renderXml(container, text, marks = []) {
    const allLines = text.split(LINE_BREAK);
    const truncated = allLines.length > MAX_LINES;
    const shown = truncated ? allLines.slice(0, MAX_LINES).join('\n') : text;
    const lines = toLines(tokenize(shown));
    const byLine = marksByLine(marks);

    const box = el('div', { class: 'xml-lines' });
    lines.forEach((tokens, index) => {
        const n = index + 1;
        const mark = byLine.get(n);
        const row = el('div', {
            class: mark ? `xml-line is-${mark.kind}` : 'xml-line',
            'data-line': n,
            tabindex: mark ? '-1' : null,
            title: mark?.titles.length ? mark.titles.join('\n') : null,
        });
        const markCell = el('span', { class: 'xml-mark', 'aria-hidden': 'true' });
        if (mark?.badges.length) markCell.append(el('span', { class: 'xml-badge', text: mark.badges.join(',') }));
        row.append(
            markCell,
            el('span', { class: 'xml-ln', 'aria-hidden': 'true', text: n }),
            el('span', { class: 'xml-code' }, renderCode(tokens)),
        );
        box.append(row);
    });

    clear(container).append(box);
    if (truncated) {
        container.append(el('p', {
            class: 'xml-truncated',
            text: `Preview shows the first ${MAX_LINES.toLocaleString('en-US')} of ${allLines.length.toLocaleString('en-US')} lines.`,
        }));
    }
    container.scrollTop = 0;
    container.scrollLeft = 0;
    return { lineCount: allLines.length };
}

// Scrolls the code box so `line` sits about a third of the way down, and with
// page: true also brings the box itself into view (for the checklist links).
export function revealLine(container, line, { page = false, flash = false, focus = false } = {}) {
    const row = container.querySelector(`[data-line="${Number(line)}"]`);
    if (!row) return false;
    const behavior = prefersReducedMotion() ? 'auto' : 'smooth';
    container.scrollTo({ top: Math.max(0, row.offsetTop - container.clientHeight / 3), behavior });
    if (page) {
        const box = container.getBoundingClientRect();
        if (box.top < 0 || box.bottom > window.innerHeight) container.scrollIntoView({ block: 'nearest', behavior });
    }
    if (flash) {
        row.classList.remove('is-flash');
        void row.offsetWidth; // restart the animation
        row.classList.add('is-flash');
    }
    if (focus && row.tabIndex === -1) row.focus({ preventScroll: true });
    return true;
}
