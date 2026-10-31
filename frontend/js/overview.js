// The dashboard around the inspector: KPI ribbon, Validation & Risk Overview
// charts and the Recent Analyses feed. Everything comes from /api/overview,
// which the server computes from the audit log, so the numbers match the
// Audit log page and include every check, not just this browser's. It refreshes
// after every check and every 30 seconds while the Check view is on screen, and
// a failed refresh keeps the last numbers on screen, marked as stale.

import { getJson } from './api.js';
import {
    el, clear, icon, badge, flagBadge, formatNumber, formatPercent, formatBytes, formatMs,
    formatRelative, formatDateTime, countUp, plural,
} from './ui.js';
import { statusRing, riskHistogram, barList } from './charts.js';

const RECENT = 15;
const REFRESH_MS = 30_000;
const ORIGIN_TEXT = { web: 'Single check', 'web-batch': 'Batch check', pipeline: 'Startup batch' };
const TONE = { INVALID: 'danger', REQUIRES_REVIEW: 'warning' };

// This browser's own checks, so the shared feed can mark them "You" (as the
// original dashboard marked "Your session"). Kept for the tab's session only.
const MINE_KEY = 'supplytrace.mine';
const MINE_LIMIT = 100;

let dom;
let requestId = 0;
let newestSeen = null;
let openKey = null;
let last = null; // { data, at }: the last overview that loaded
let timer = null;

export function initOverview() {
    const $ = id => document.getElementById(id);
    dom = {
        view: $('view-check'),
        kpis: $('kpis'),
        total: $('stat-total'), totalSub: $('stat-total-sub'),
        invalid: $('stat-invalid'), invalidSub: $('stat-invalid-sub'),
        risk: $('stat-risk'), riskSub: $('stat-risk-sub'),
        flags: $('stat-flags'), flagsSub: $('stat-flags-sub'),
        caption: $('stats-caption'),
        updated: $('overview-updated'),
        updatedText: $('overview-updated-text'),
        share: $('chart-share'),
        riskChart: $('chart-risk'),
        reasons: $('chart-reasons'),
        feed: $('history-feed'),
    };
    dom.feed.addEventListener('click', toggleItem);
    document.addEventListener('visibilitychange', () => {
        if (onScreen()) refreshOverview();
    });
}

const onScreen = () => document.visibilityState === 'visible' && !dom.view.hidden;

function scheduleRefresh() {
    clearTimeout(timer);
    timer = setTimeout(() => (onScreen() ? refreshOverview() : scheduleRefresh()), REFRESH_MS);
}

export async function refreshOverview() {
    const id = ++requestId; // only the latest reply may render
    try {
        const data = await getJson(`/api/overview?recent=${RECENT}`);
        if (id !== requestId) return;
        last = { data, at: Date.now() };
        render(data);
    } catch (error) {
        if (id !== requestId) return;
        if (last) renderStale();
        else renderError(error);
    } finally {
        if (id === requestId) scheduleRefresh();
    }
}

// ---------- This browser's checks ----------

export function rememberChecks(results) {
    const stamps = results.filter(r => r.logged_at).map(r => `${r.logged_at}|${r.filename}`);
    if (!stamps.length) return;
    try {
        const mine = JSON.parse(sessionStorage.getItem(MINE_KEY) || '[]');
        sessionStorage.setItem(MINE_KEY, JSON.stringify([...mine, ...stamps].slice(-MINE_LIMIT)));
    } catch {
        // storage unavailable: the feed just doesn't mark this browser's checks
    }
}

function myChecks() {
    try {
        return new Set(JSON.parse(sessionStorage.getItem(MINE_KEY) || '[]'));
    } catch {
        return new Set();
    }
}

// ---------- KPIs and charts ----------

function retryButton() {
    return el('button', { type: 'button', class: 'btn-text', on: { click: refreshOverview } }, icon('refresh'), 'Retry');
}

function setLive() {
    dom.updated.classList.remove('is-stale');
    dom.updatedText.textContent = 'Live · audit log';
}

function render(data) {
    dom.kpis.removeAttribute('aria-busy');
    dom.feed.removeAttribute('aria-busy');
    const pct = v => (v === null || v === undefined ? '–' : formatPercent(v));

    countUp(dom.total, data.total, v => formatNumber(Math.round(v)));
    countUp(dom.invalid, data.invalid_rate ?? 0, v => (data.invalid_rate === null ? '–' : formatPercent(v)));
    countUp(dom.risk, data.average_risk ?? 0, v => (data.average_risk === null ? '–' : formatPercent(v)));
    countUp(dom.flags, data.high_risk, v => formatNumber(Math.round(v)));

    const visitors = (data.origins.web || 0) + (data.origins['web-batch'] || 0);
    dom.totalSub.textContent = `${formatNumber(data.origins.pipeline || 0)} startup · ${formatNumber(visitors)} checked here`;
    dom.invalidSub.textContent = `${formatNumber(data.counts.INVALID)} of ${formatNumber(data.total)} files`;
    dom.riskSub.textContent = data.scored ? `over ${plural(data.scored, 'scored file')}` : 'no scored files';
    dom.flagsSub.textContent = data.scored ? `${pct((data.high_risk / data.scored) * 100)} of scored files` : '–';

    dom.caption.textContent = data.total
        ? `From the audit log: the ${formatNumber(data.origins.pipeline || 0)}-invoice synthetic startup batch plus ${plural(visitors, 'check')} made on this server, by every visitor. Latest entry ${formatRelative(data.latest)}.`
        : 'The audit log is empty. Check a sample and it will appear here.';
    setLive();
    dom.updated.title = `Refreshes every 30 seconds while this page is open.${data.latest ? ` Latest entry ${formatDateTime(data.latest)}.` : ''}`;

    statusRing(dom.share, data.counts, { note: data.total ? `Share of all ${formatNumber(data.total)} files in the audit log.` : null });
    if (data.scored) riskHistogram(dom.riskChart, data.risk_histogram);
    else clear(dom.riskChart).append(el('p', { class: 'chart-empty', text: 'No scored files yet. The model scores every file once it is trained.' }));
    barList(dom.reasons, data.top_reasons.map(r => ({
        label: r.reason, value: r.count, tone: TONE[r.status] || 'primary',
    })), { empty: 'No failures logged yet: every file so far passed.' });

    renderFeed(data.recent);
}

// A refresh failed after an earlier one worked: keep what is on screen and say how old it is.
function renderStale() {
    const loadedAt = new Date(last.at).toISOString();
    dom.updated.classList.add('is-stale');
    dom.updatedText.textContent = `Updated ${formatRelative(loadedAt)}`;
    dom.updated.title = `Could not refresh. Last loaded ${formatDateTime(loadedAt)}.`;
    clear(dom.caption).append(
        icon('triangle'),
        el('span', { text: `Couldn't refresh the totals (offline?). Showing the ones loaded ${formatRelative(loadedAt)}. ` }),
        retryButton());
}

// Nothing has loaded yet: every block says so, with a way to try again.
function renderError(error) {
    dom.kpis.removeAttribute('aria-busy');
    dom.feed.removeAttribute('aria-busy');
    dom.updated.classList.add('is-stale');
    dom.updatedText.textContent = 'Not loaded';
    clear(dom.caption).append(el('span', { text: `Totals could not be loaded: ${error.message} ` }), retryButton());
    [dom.total, dom.invalid, dom.risk, dom.flags].forEach(node => {
        if (node.querySelector('.skeleton')) node.textContent = '–';
    });
    for (const slot of [dom.share, dom.riskChart, dom.reasons]) {
        clear(slot).append(el('p', { class: 'chart-empty' }, 'Could not load. ', retryButton()));
    }
    clear(dom.feed).append(el('div', { class: 'feed-empty-state' },
        el('p', { text: `The recent analyses could not be loaded. ${error.message}` }), retryButton()));
}

// ---------- Recent Analyses (accordion) ----------

function keyOf(entry) {
    return `${entry.timestamp}|${entry.source_file}|${entry.origin}`;
}

function renderFeed(entries) {
    clear(dom.feed);
    if (!entries.length) {
        dom.feed.append(el('div', { class: 'feed-empty-state' },
            el('p', { text: 'No analyses yet.' }),
            el('a', { class: 'btn btn-outline', href: '#/check?sample=valid' }, 'Try a sample')));
        return;
    }
    const now = Date.now();
    const mine = myChecks();
    const previousNewest = newestSeen;
    newestSeen = keyOf(entries[0]);
    entries.forEach((entry, index) => {
        const key = keyOf(entry);
        const fresh = previousNewest !== null && index === 0 && key !== previousNewest;
        const yours = mine.has(`${entry.timestamp}|${entry.source_file}`);
        dom.feed.append(item(entry, { index, now, fresh, yours, open: key === openKey }));
    });
}

function detail(label, value) {
    return el('div', { class: 'detail-field' },
        el('span', { class: 'detail-label', text: label }),
        el('span', { class: 'detail-value', text: value }));
}

function item(entry, { index, now, fresh, yours, open }) {
    const id = `feed-detail-${index}`;
    const origin = ORIGIN_TEXT[entry.origin] || 'Unknown source';
    const hasId = entry.transaction_id && entry.transaction_id !== 'N/A';
    const blank = v => v === undefined || v === null || v === '';
    const errors = entry.errors ? String(entry.errors).split('; ') : [];

    const summary = el('button', {
        type: 'button', class: 'accordion-summary', 'aria-expanded': String(open), 'aria-controls': id,
    },
    el('span', { class: 'file-info' },
        el('span', { class: 'file-line' },
            el('span', { class: 'file-name', text: entry.source_file || '–', title: entry.source_file || '' }),
            yours ? el('span', { class: 'you-tag', title: 'Checked in this browser tab' }, 'You') : null),
        el('span', { class: 'file-id' },
            el('span', { class: 'mono file-id-value', text: hasId ? entry.transaction_id : 'no ID', title: hasId ? entry.transaction_id : null }),
            el('span', { class: `origin-tag origin-${entry.origin}`, text: origin }),
            el('time', { datetime: entry.timestamp, title: formatDateTime(entry.timestamp), text: formatRelative(entry.timestamp, now) }))),
    el('span', { class: 'badge-group' }, badge(entry.validation_status), flagBadge(entry)),
    el('span', { class: 'chevron-icon', 'aria-hidden': 'true' }, icon('chevron-down')));

    const body = el('div', { class: 'accordion-details', id, inert: open ? null : true },
        el('div', { class: 'accordion-inner' },
            el('div', { class: 'detail-grid' },
                detail('Checked', formatDateTime(entry.timestamp)),
                detail('Risk flag', entry.risk_flag && entry.risk_flag !== 'N/A' ? entry.risk_flag : '–'),
                detail('File size', formatBytes(entry.xml_size)),
                detail('Nesting depth', blank(entry.nesting_depth) ? '–' : String(entry.nesting_depth)),
                detail('Missing optional', blank(entry.missing_optional_fields) ? '–' : `${entry.missing_optional_fields} of 4`),
                detail('Server time', typeof entry.processing_ms === 'number' ? formatMs(entry.processing_ms) : '–')),
            errors.length ? el('div', { class: `detail-errors${entry.validation_status === 'REQUIRES_REVIEW' ? ' is-review' : ''}` },
                el('span', { class: 'detail-label', text: entry.validation_status === 'REQUIRES_REVIEW' ? 'Review reason' : 'Reasons' }),
                el('ul', {}, errors.map(e => el('li', { text: e })))) : null));

    const classes = ['accordion-item', open && 'active', fresh && 'is-new', yours && 'is-yours'].filter(Boolean).join(' ');
    return el('div', { class: classes, 'data-key': keyOf(entry) }, summary, body);
}

function toggleItem(event) {
    const summary = event.target.closest('.accordion-summary');
    if (!summary) return;
    const item = summary.parentElement;
    const opening = !item.classList.contains('active');
    dom.feed.querySelectorAll('.accordion-item').forEach(other => {
        other.classList.remove('active');
        other.querySelector('.accordion-summary').setAttribute('aria-expanded', 'false');
        other.querySelector('.accordion-details').inert = true;
    });
    openKey = opening ? item.dataset.key : null;
    if (opening) {
        item.classList.add('active');
        summary.setAttribute('aria-expanded', 'true');
        item.querySelector('.accordion-details').inert = false;
    }
}
