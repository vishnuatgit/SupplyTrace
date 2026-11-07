// Small DOM, formatting and feedback helpers shared by every view.

const SVG_NS = 'http://www.w3.org/2000/svg';

// Creates an element. Text always goes in through textContent, never as HTML,
// so file names and XML from uploads can't inject markup.
//   el('a', { class: 'x', href: '/docs', text: 'API docs' })
//   el('p', {}, 'Some ', el('strong', { text: 'bold' }), ' text')
export function el(tag, props = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
        if (value === undefined || value === null || value === false) continue;
        if (key === 'class') node.className = value;
        else if (key === 'text') node.textContent = value;
        else if (key === 'on') Object.entries(value).forEach(([type, fn]) => node.addEventListener(type, fn));
        else if (key === 'style') {
            Object.entries(value).forEach(([name, v]) => {
                if (name.startsWith('--')) node.style.setProperty(name, v);
                else node.style[name] = v;
            });
        }
        else if (key === 'dataset') Object.assign(node.dataset, value);
        else node.setAttribute(key, value === true ? '' : value);
    }
    for (const child of children.flat()) {
        if (child === undefined || child === null || child === false) continue;
        node.append(child instanceof Node ? child : String(child));
    }
    return node;
}

// The same for SVG elements (attributes only; colours come from CSS classes).
export function svg(tag, attrs = {}, ...children) {
    const node = document.createElementNS(SVG_NS, tag);
    for (const [key, value] of Object.entries(attrs)) {
        if (value === undefined || value === null || value === false) continue;
        if (key === 'text') node.textContent = value;
        else node.setAttribute(key, value);
    }
    children.flat().forEach(child => child && node.append(child));
    return node;
}

// An icon from the sprite in index.html, e.g. icon('check').
export function icon(name, extraClass = '') {
    return svg('svg', { class: `icon ${extraClass}`.trim(), 'aria-hidden': 'true', focusable: 'false' },
        svg('use', { href: `#i-${name}` }));
}

export function clear(node) {
    node.replaceChildren();
    return node;
}

// ---------- Statuses ----------

export const STATUS = {
    VALID: { text: 'Valid', icon: 'check-circle', tone: 'success' },
    INVALID: { text: 'Invalid', icon: 'x-circle', tone: 'danger' },
    REQUIRES_REVIEW: { text: 'Needs review', icon: 'triangle', tone: 'warning' },
    REJECTED: { text: 'Rejected', icon: 'slash', tone: 'neutral' },
};

export function statusText(status) {
    return STATUS[status]?.text || String(status || 'Unknown');
}

// A status badge with an icon, so the status never depends on colour alone.
export function badge(status, { large = false } = {}) {
    const known = status in STATUS ? status : 'REJECTED';
    return el('span', { class: `badge status-${known}${large ? ' badge-lg' : ''}`, title: status },
        icon(STATUS[known].icon), STATUS[known].text);
}

// A small tag for an invoice flagged as a duplicate: kind is 'exact' or 'likely'.
export function duplicateTag(kind) {
    if (!kind) return null;
    return el('span', { class: `badge dup-tag dup-${kind}`, title: kind === 'exact' ? 'The same file was checked before' : 'Probably the same invoice as an earlier one' },
        icon('copy'), kind === 'exact' ? 'Duplicate' : 'Likely duplicate');
}

export function flagBadge(prediction) {
    const score = prediction?.risk_score;
    if (typeof score !== 'number') return el('span', { class: 'badge flag-NA', text: 'No score' });
    const flag = prediction.risk_flag === 'HIGH' ? 'HIGH' : 'LOW';
    return el('span', { class: `badge flag-${flag}`, title: `Experimental risk score, ${flag}` }, formatPercent(score));
}

// ---------- Formatting ----------

export function formatNumber(value, digits = 0) {
    return Number(value).toLocaleString('en-US', {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
    });
}

export function formatPercent(value, digits = 1) {
    return `${Number(Number(value).toFixed(digits))}%`;
}

export function formatMs(value) {
    if (typeof value !== 'number') return '–';
    return value < 10 ? `${value.toFixed(1)} ms` : `${Math.round(value)} ms`;
}

export function formatBytes(bytes) {
    const n = Number(bytes);
    if (bytes === null || bytes === undefined || bytes === '' || !Number.isFinite(n)) return '–';
    if (n < 1000) return `${n} B`;
    if (n < 1_000_000) return `${(n / 1000).toFixed(1)} KB`;
    return `${(n / 1_000_000).toFixed(1)} MB`;
}

export function formatDateTime(iso) {
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return String(iso || '–');
    return new Intl.DateTimeFormat(undefined, {
        day: 'numeric', month: 'short', year: 'numeric',
        hour: '2-digit', minute: '2-digit', second: '2-digit',
    }).format(date);
}

const RELATIVE_STEPS = [
    ['year', 365 * 24 * 3600], ['month', 30 * 24 * 3600], ['day', 24 * 3600],
    ['hour', 3600], ['minute', 60], ['second', 1],
];

export function formatRelative(iso, now = Date.now()) {
    const seconds = (new Date(iso).getTime() - now) / 1000;
    if (!Number.isFinite(seconds)) return '';
    if (Math.abs(seconds) < 45) return 'just now';
    const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });
    for (const [unit, size] of RELATIVE_STEPS) {
        if (Math.abs(seconds) >= size || unit === 'second') {
            return rtf.format(Math.round(seconds / size), unit);
        }
    }
    return '';
}

export function plural(count, one, many = `${one}s`) {
    return `${formatNumber(count)} ${count === 1 ? one : many}`;
}

export const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

export function prefersReducedMotion() {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

// Animates a number from the value it shows now to `to` (a short ease-out),
// or sets it at once when motion is reduced or it is the first value.
export function countUp(node, to, format) {
    const from = Number(node.dataset.value);
    node.dataset.value = String(to);
    if (!Number.isFinite(from) || from === to || prefersReducedMotion()) {
        node.textContent = format(to);
        return;
    }
    const start = performance.now();
    const duration = 450;
    const step = now => {
        const t = Math.min(1, (now - start) / duration);
        const eased = 1 - (1 - t) ** 3;
        node.textContent = format(from + (to - from) * eased);
        if (t < 1 && node.dataset.value === String(to)) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
}

// ---------- Feedback: screen-reader announcements and toasts ----------

export function announce(message) {
    const region = document.getElementById('announcer');
    if (!region) return;
    region.textContent = '';
    // a new text node after a tick makes screen readers read repeated messages
    setTimeout(() => { region.textContent = message; }, 30);
}

const TOAST_ICONS = { success: 'check-circle', error: 'x-circle', info: 'info' };

export function toast(message, { kind = 'success', duration = 3600 } = {}) {
    const region = document.getElementById('toasts');
    const close = el('button', { type: 'button', class: 'toast-close', 'aria-label': 'Dismiss' }, icon('x'));
    const node = el('div', { class: `toast toast-${kind}` }, icon(TOAST_ICONS[kind] || 'info'), el('span', { text: message }), close);
    const dismiss = () => {
        node.classList.add('is-leaving');
        setTimeout(() => node.remove(), prefersReducedMotion() ? 0 : 180);
    };
    close.addEventListener('click', dismiss);
    region.append(node);
    while (region.children.length > 3) region.firstElementChild.remove();
    setTimeout(dismiss, duration);
}

// ---------- Clipboard and downloads ----------

export async function copyText(text) {
    try {
        await navigator.clipboard.writeText(text);
        return true;
    } catch {
        // Clipboard API unavailable (http, old browser): fall back to a selection copy.
        const area = el('textarea', { readonly: true, class: 'offscreen' });
        area.value = text;
        document.body.append(area);
        area.select();
        let ok = false;
        try {
            ok = document.execCommand('copy');
        } catch {
            ok = false;
        }
        area.remove();
        return ok;
    }
}

export function downloadFile(name, parts, type) {
    const url = URL.createObjectURL(new Blob(parts, { type }));
    const link = el('a', { href: url, download: name, class: 'offscreen' });
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// A file-name-safe stamp such as 20261031-2104.
export function fileStamp(date = new Date()) {
    const pad = n => String(n).padStart(2, '0');
    return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}-${pad(date.getHours())}${pad(date.getMinutes())}`;
}

// ---------- Tabs (WAI-ARIA tabs pattern, manual activation by click or arrows) ----------

export function setupTabs(tablist, onSelect) {
    const tabs = Array.from(tablist.querySelectorAll('[role="tab"]'));

    function select(tab, { focus = false } = {}) {
        tabs.forEach(t => {
            const selected = t === tab;
            t.setAttribute('aria-selected', String(selected));
            t.tabIndex = selected ? 0 : -1;
            document.getElementById(t.getAttribute('aria-controls')).hidden = !selected;
        });
        if (focus) tab.focus();
        onSelect?.(tab.id);
    }

    tabs.forEach(tab => tab.addEventListener('click', () => select(tab)));
    tablist.addEventListener('keydown', event => {
        const index = tabs.indexOf(document.activeElement);
        if (index < 0) return;
        const moves = {
            ArrowRight: (index + 1) % tabs.length,
            ArrowLeft: (index - 1 + tabs.length) % tabs.length,
            Home: 0,
            End: tabs.length - 1,
        };
        if (!(event.key in moves)) return;
        event.preventDefault();
        select(tabs[moves[event.key]], { focus: true });
    });

    return {
        select: (id, options) => select(tabs.find(t => t.id === id), options),
        selected: () => tabs.find(t => t.getAttribute('aria-selected') === 'true')?.id,
    };
}

// ---------- Drop zones ----------

export function setupDropzone(zone, onFiles, { input, isBusy = () => false } = {}) {
    ['dragenter', 'dragover'].forEach(type => zone.addEventListener(type, event => {
        event.preventDefault();
        if (!isBusy()) zone.classList.add('is-dragover');
    }));
    ['dragleave', 'drop'].forEach(type => zone.addEventListener(type, event => {
        event.preventDefault();
        if (type === 'drop' || !zone.contains(event.relatedTarget)) zone.classList.remove('is-dragover');
    }));
    zone.addEventListener('drop', event => {
        const files = Array.from(event.dataTransfer?.files || []);
        if (files.length && !isBusy()) onFiles(files);
    });
    if (input) {
        // A click anywhere on the zone opens the file picker (the button inside is the keyboard route).
        zone.addEventListener('click', event => {
            if (!isBusy() && !event.target.closest('button, input, a')) input.click();
        });
        input.addEventListener('change', () => {
            const files = Array.from(input.files);
            input.value = ''; // lets the same file be chosen again
            if (files.length) onFiles(files);
        });
    }
}

// ---------- Buttons with a loading state ----------

export function setLoading(button, loading) {
    button.disabled = loading;
    button.classList.toggle('is-loading', loading);
    if (loading) button.setAttribute('aria-busy', 'true');
    else button.removeAttribute('aria-busy');
}
