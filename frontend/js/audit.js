// The Audit log view: recent entries from the server's JSON Lines log, filtered
// by status, source and a search over file names and transaction IDs. Each row
// opens to its exact JSON line, ready to copy; the shown entries can be exported.

import { getJson } from './api.js';
import {
    el, clear, icon, badge, flagBadge, formatDateTime, formatRelative, formatNumber, formatBytes,
    announce, toast, copyText, downloadFile, fileStamp,
} from './ui.js';
import { splitBar } from './charts.js';

const PAGE_SIZE = 50;
const MAX_PAGE = 500; // the API's upper limit
const SEARCH_DELAY_MS = 250;

const ORIGIN_TEXT = { web: 'Single check', 'web-batch': 'Batch check', pipeline: 'Startup batch' };

let dom;
let filters = { status: '', origin: '', q: '' };
let limit = PAGE_SIZE;
let requestId = 0;
let shown = [];
let searchTimer = null;

export function initAudit() {
    const $ = id => document.getElementById(id);
    dom = {
        output: $('audit-output'), filter: $('audit-filter'), origin: $('audit-origin'),
        search: $('audit-search'), refresh: $('audit-refresh'), exporter: $('audit-export'),
        split: $('audit-split'),
    };
    dom.filter.addEventListener('change', event => {
        filters.status = event.target.value;
        limit = PAGE_SIZE;
        markCheckedFilter();
        load({ announceCount: true });
    });
    dom.origin.addEventListener('change', () => {
        filters.origin = dom.origin.value;
        limit = PAGE_SIZE;
        load({ announceCount: true });
    });
    dom.search.addEventListener('input', () => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => {
            filters.q = dom.search.value.trim();
            limit = PAGE_SIZE;
            load({ announceCount: true });
        }, SEARCH_DELAY_MS);
    });
    dom.refresh.addEventListener('click', () => load({ announceDone: true }));
    dom.exporter.addEventListener('click', exportShown);
    markCheckedFilter();
}

// A class as well as :has(input:checked), for browsers without :has().
function markCheckedFilter() {
    dom.filter.querySelectorAll('label').forEach(label => {
        label.classList.toggle('is-checked', label.querySelector('input').checked);
    });
}

export function showAudit() {
    load();
}

async function load({ announceDone = false, announceCount = false } = {}) {
    const id = ++requestId; // only the latest request may render
    dom.output.setAttribute('aria-busy', 'true');
    dom.refresh.classList.add('is-loading');
    const params = new URLSearchParams({ limit: String(limit) });
    if (filters.status) params.set('status', filters.status);
    if (filters.origin) params.set('origin', filters.origin);
    if (filters.q) params.set('q', filters.q);
    try {
        const data = await getJson(`/api/audit?${params}`);
        if (id !== requestId) return;
        renderCounts(data);
        render(data);
        if (announceDone) {
            announce(`Audit log refreshed: ${formatNumber(data.total)} entries.`);
            toast('Audit log refreshed.', { kind: 'info', duration: 2200 });
        } else if (announceCount) {
            announce(`${formatNumber(data.matching)} matching entries.`);
        }
    } catch (error) {
        if (id !== requestId) return;
        shown = [];
        dom.exporter.disabled = true;
        clear(dom.output).append(el('div', { class: 'error-card', role: 'alert' },
            el('span', { class: 'error-icon', 'aria-hidden': 'true' }, icon('x-circle')),
            el('div', {},
                el('p', { class: 'error-title', text: 'The audit log could not be loaded' }),
                el('p', { text: error.message }),
                el('div', { class: 'error-actions' },
                    el('button', { type: 'button', class: 'btn btn-secondary', on: { click: () => load() } }, icon('refresh'), 'Try again')))));
    } finally {
        if (id === requestId) {
            dom.output.removeAttribute('aria-busy');
            dom.refresh.classList.remove('is-loading');
        }
    }
}

function renderCounts(data) {
    const all = Object.values(data.counts).reduce((sum, n) => sum + n, 0);
    const counts = { ALL: all, ...data.counts };
    dom.filter.querySelectorAll('[data-count]').forEach(slot => {
        slot.textContent = formatNumber(counts[slot.dataset.count] ?? 0);
    });
    splitBar(dom.split, data.counts, { label: 'Entries by status' });
}

function emptyState(title, text, action) {
    return el('div', { class: 'empty-state' },
        el('div', { class: 'empty-icon' }, icon('search')),
        el('p', { class: 'empty-title', text: title }),
        el('p', { text }),
        action || null);
}

function render(data) {
    shown = data.entries;
    dom.exporter.disabled = !shown.length;
    if (data.total === 0) {
        clear(dom.output).append(emptyState('The audit log is empty',
            'Check an invoice and it will appear here.',
            el('a', { class: 'btn btn-outline', href: '#/check?sample=valid' }, 'Check a sample')));
        return;
    }
    if (data.matching === 0) {
        clear(dom.output).append(emptyState('No entries match these filters',
            'Try another status or source, or clear the search.',
            el('button', { type: 'button', class: 'btn btn-secondary', on: { click: resetFilters } }, icon('x'), 'Clear filters')));
        return;
    }

    const now = Date.now();
    const header = el('tr', {},
        el('th', { scope: 'col', class: 'col-time', text: 'Time' }),
        el('th', { scope: 'col', text: 'File' }),
        el('th', { scope: 'col', text: 'Transaction ID' }),
        el('th', { scope: 'col', class: 'col-status', text: 'Status' }),
        el('th', { scope: 'col', class: 'col-risk num', text: 'Risk' }),
        el('th', { scope: 'col', text: 'Reasons' }),
        el('th', { scope: 'col', class: 'col-json' }, el('span', { class: 'visually-hidden', text: 'JSON line' })));

    const body = el('tbody');
    data.entries.forEach(({ entry, line }, index) => {
        const jsonId = `audit-json-${index}`;
        const toggle = el('button', {
            type: 'button', class: 'btn-text', 'aria-expanded': 'false', 'aria-controls': jsonId,
            'aria-label': `Show the JSON line for ${entry.source_file || 'this entry'}`,
        }, icon('code'), el('span', { text: 'JSON' }));
        const copy = el('button', { type: 'button', class: 'btn btn-secondary btn-sm' }, icon('copy'), 'Copy line');
        let pretty = line;
        try {
            pretty = JSON.stringify(JSON.parse(line), null, 2);
        } catch {
            // keep the raw line
        }
        const jsonRow = el('tr', { class: 'json-row', id: jsonId, hidden: true },
            el('td', { colspan: '7', 'data-label': '' },
                el('div', { class: 'json-line' }, el('pre', { text: pretty }), copy)));

        toggle.addEventListener('click', () => {
            const open = jsonRow.hidden;
            jsonRow.hidden = !open;
            toggle.setAttribute('aria-expanded', String(open));
            toggle.classList.toggle('is-open', open);
        });
        copy.addEventListener('click', async () => {
            const ok = await copyText(line);
            toast(ok ? 'JSON line copied.' : 'Could not copy. Select the text instead.', { kind: ok ? 'success' : 'error' });
        });

        const origin = ORIGIN_TEXT[entry.origin];
        body.append(
            el('tr', {},
                el('td', { 'data-label': 'Time' },
                    el('time', { class: 'time-main', datetime: entry.timestamp, text: formatDateTime(entry.timestamp) }),
                    el('span', { class: 'time-ago', text: formatRelative(entry.timestamp, now) })),
                el('td', { 'data-label': 'File' },
                    el('span', { class: 'mono file-cell', text: entry.source_file || '–' }),
                    el('span', { class: 'cell-sub' },
                        origin ? el('span', { class: `origin-tag origin-${entry.origin}`, text: origin }) : null,
                        entry.xml_size ? el('span', { text: formatBytes(entry.xml_size) }) : null)),
                el('td', { 'data-label': 'Transaction ID' }, entry.transaction_id && entry.transaction_id !== 'N/A'
                    ? el('span', { class: 'mono', text: entry.transaction_id })
                    : el('span', { class: 'cell-muted', text: '–' })),
                el('td', { 'data-label': 'Status' }, badge(entry.validation_status)),
                el('td', { class: 'num', 'data-label': 'Risk' }, flagBadge(entry)),
                el('td', { 'data-label': 'Reasons' }, entry.errors
                    ? el('span', { class: 'reasons' }, String(entry.errors).split('; ').map(message => el('span', { text: message })))
                    : el('span', { class: 'cell-muted', text: 'None' })),
                el('td', { 'data-label': 'JSON line' }, toggle)),
            jsonRow,
        );
    });

    const table = el('table', { class: 'data-table audit-table stack-on-mobile' },
        el('caption', { class: 'visually-hidden', text: 'Audit log, newest first' }),
        el('thead', {}, header), body);

    const count = data.entries.length;
    const more = el('div', { class: 'table-more' },
        el('p', { text: `Showing ${formatNumber(count)} of ${formatNumber(data.matching)} ${data.matching === data.total ? '' : 'matching '}entries, newest first.` }));
    if (count < data.matching && limit < MAX_PAGE) {
        more.append(el('button', {
            type: 'button', class: 'btn btn-secondary', on: { click: () => { limit = Math.min(MAX_PAGE, limit + PAGE_SIZE); load(); } },
        }, icon('chevron-down'), `Show ${Math.min(PAGE_SIZE, data.matching - count)} more`));
    } else if (count < data.matching) {
        more.append(el('span', { class: 'muted', text: `The newest ${formatNumber(MAX_PAGE)} are shown. Narrow the filters to see others.` }));
    }

    clear(dom.output).append(el('div', { class: 'table-scroll' }, table), more);
}

function resetFilters() {
    filters = { status: '', origin: '', q: '' };
    dom.filter.querySelector('input[value=""]').checked = true;
    dom.origin.value = '';
    dom.search.value = '';
    markCheckedFilter();
    limit = PAGE_SIZE;
    load();
}

function exportShown() {
    if (!shown.length) return;
    const text = `${shown.map(item => item.line).join('\n')}\n`;
    downloadFile(`supplytrace-audit-${fileStamp()}.jsonl`, [text], 'application/x-ndjson');
    toast(`Exported ${formatNumber(shown.length)} audit lines.`);
}
