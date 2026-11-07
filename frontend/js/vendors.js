// The Vendors view: every supplier seen in the checked invoices with its statistics
// (a sortable, searchable table), and one vendor opened from it: its numbers,
// editable notes and trusted flag, and its invoices. Routes: #/vendors for the
// directory, #/vendors?id=... for one vendor.
//
// Trusted is a note for people. It is shown on results and never changes validation.

import { getJson, putJson } from './api.js';
import {
    el, clear, icon, badge, flagBadge, duplicateTag, formatDateTime, formatRelative, formatNumber,
    announce, toast,
} from './ui.js';
import { splitBar } from './charts.js';
import { getReviewerName, setReviewerName } from './reviewer.js';

const SEARCH_DELAY_MS = 250;
const SORTS = [
    ['name', 'Name'], ['invoices', 'Most invoices'], ['total', 'Largest total'],
    ['duplicates', 'Most duplicates'], ['risk', 'Highest risk'], ['last_seen', 'Seen most recently'],
];

let dom;
let filters = { q: '', trusted: '', sort: 'name' };
let requestId = 0;
let searchTimer = null;

export function initVendors() {
    const $ = id => document.getElementById(id);
    dom = {
        list: $('vendor-list'), detail: $('vendor-detail'), output: $('vendor-output'),
        filter: $('vendor-filter'), sort: $('vendor-sort'), search: $('vendor-search'),
        refresh: $('vendor-refresh'),
    };
    clear(dom.sort).append(...SORTS.map(([value, label]) => el('option', { value, text: label })));
    dom.filter.addEventListener('change', event => {
        filters.trusted = event.target.value;
        markCheckedFilter();
        loadList({ announceCount: true });
    });
    dom.sort.addEventListener('change', () => {
        filters.sort = dom.sort.value;
        loadList();
    });
    dom.search.addEventListener('input', () => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => {
            filters.q = dom.search.value.trim();
            loadList({ announceCount: true });
        }, SEARCH_DELAY_MS);
    });
    dom.refresh.addEventListener('click', () => loadList({ announceDone: true }));
    markCheckedFilter();
}

function markCheckedFilter() {
    dom.filter.querySelectorAll('label').forEach(label => {
        label.classList.toggle('is-checked', label.querySelector('input').checked);
    });
}

export function showVendors(params) {
    const id = params.get('id');
    dom.list.hidden = Boolean(id);
    dom.detail.hidden = !id;
    if (id) loadDetail(id);
    else loadList();
}

function errorCard(title, message, retry) {
    return el('div', { class: 'error-card', role: 'alert' },
        el('span', { class: 'error-icon', 'aria-hidden': 'true' }, icon('x-circle')),
        el('div', {},
            el('p', { class: 'error-title', text: title }),
            el('p', { text: message }),
            el('div', { class: 'error-actions' },
                retry ? el('button', { type: 'button', class: 'btn btn-secondary', on: { click: retry } }, icon('refresh'), 'Try again') : null,
                el('a', { class: 'btn btn-outline', href: '#/vendors' }, 'Back to the vendors'))));
}

function trustedTag(vendor) {
    if (!vendor.trusted) return null;
    return el('span', { class: 'badge trusted-tag', title: 'Marked as trusted by a person. It does not change validation.' }, icon('shield'), 'Trusted');
}

// An amount with its currency.
function money(value, currency) {
    if (value === null || value === undefined) return '–';
    const text = formatNumber(value, 2);
    return currency ? `${text} ${currency}` : text;
}

// The vendor's headline amount (in the currency of most of its invoices) and a
// "+N" marker when it has invoices in other currencies, which are never added in.
function vendorMoney(vendor, field) {
    const [main, ...others] = vendor.currencies;
    if (!main) return '–';
    return [money(main[field], main.currency),
        others.length ? el('span', { class: 'more-currencies', title: `Also ${others.map(c => money(c[field], c.currency)).join(', ')}`, text: ` +${others.length}` }) : null];
}

function statusCounts(vendor) {
    const s = vendor.statuses;
    return el('span', { class: 'status-counts' },
        el('span', { class: 'sc sc-VALID', title: 'Valid', text: s.VALID }),
        el('span', { class: 'sc sc-REQUIRES_REVIEW', title: 'Needs review', text: s.REQUIRES_REVIEW }),
        el('span', { class: 'sc sc-INVALID', title: 'Invalid', text: s.INVALID }));
}

// ---------- The directory ----------

async function loadList({ announceDone = false, announceCount = false } = {}) {
    const id = ++requestId; // only the latest request may render
    dom.output.setAttribute('aria-busy', 'true');
    dom.refresh.classList.add('is-loading');
    const params = new URLSearchParams({ sort: filters.sort });
    if (filters.q) params.set('q', filters.q);
    if (filters.trusted) params.set('trusted', filters.trusted);
    try {
        const data = await getJson(`/api/vendors?${params}`);
        if (id !== requestId) return;
        dom.filter.querySelectorAll('[data-count]').forEach(slot => {
            slot.textContent = formatNumber(slot.dataset.count === 'trusted' ? data.trusted : data.total);
        });
        renderList(data);
        if (announceDone) {
            announce('Vendors refreshed.');
            toast('Vendors refreshed.', { kind: 'info', duration: 2200 });
        } else if (announceCount) {
            announce(`${formatNumber(data.matching)} matching vendors.`);
        }
    } catch (error) {
        if (id !== requestId) return;
        clear(dom.output).append(errorCard('The vendors could not be loaded', error.message, () => loadList()));
    } finally {
        if (id === requestId) {
            dom.output.removeAttribute('aria-busy');
            dom.refresh.classList.remove('is-loading');
        }
    }
}

function resetFilters() {
    filters = { q: '', trusted: '', sort: filters.sort };
    dom.filter.querySelector('input[value=""]').checked = true;
    dom.search.value = '';
    markCheckedFilter();
    loadList();
}

function renderList(data) {
    if (data.matching === 0) {
        const nothingYet = data.total === 0;
        clear(dom.output).append(el('div', { class: 'empty-state' },
            el('div', { class: 'empty-icon' }, icon('user')),
            el('p', { class: 'empty-title', text: nothingYet ? 'No vendors yet' : 'No vendors match these filters' }),
            el('p', { text: nothingYet
                ? 'A vendor appears here once an invoice with a supplier has been checked. Invoices without a supplier name or ID are not attributed to anyone.'
                : 'Try another search, or show every vendor.' }),
            nothingYet
                ? el('a', { class: 'btn btn-outline', href: '#/check?sample=valid' }, 'Check a sample')
                : el('button', { type: 'button', class: 'btn btn-secondary', on: { click: resetFilters } }, icon('x'), 'Show all vendors')));
        return;
    }
    const now = Date.now();
    const header = el('tr', {},
        el('th', { scope: 'col', text: 'Vendor' }),
        el('th', { scope: 'col', class: 'num', text: 'Invoices' }),
        el('th', { scope: 'col', text: 'Valid · review · invalid' }),
        el('th', { scope: 'col', class: 'num', text: 'Total' }),
        el('th', { scope: 'col', class: 'num', text: 'Average' }),
        el('th', { scope: 'col', class: 'num', text: 'Duplicates' }),
        el('th', { scope: 'col', class: 'num', text: 'Avg risk' }),
        el('th', { scope: 'col', text: 'Last seen' }));
    const body = el('tbody');
    data.vendors.forEach(vendor => {
        body.append(el('tr', {},
            el('td', { 'data-label': 'Vendor' },
                el('a', { class: 'review-link', href: `#/vendors?id=${vendor.id}`, text: vendor.name }),
                el('span', { class: 'cell-sub' }, trustedTag(vendor), vendor.notes ? el('span', { class: 'note-hint', text: 'Has notes' }) : null)),
            el('td', { class: 'num mono', 'data-label': 'Invoices', text: formatNumber(vendor.invoice_count) }),
            el('td', { 'data-label': 'Valid · review · invalid' }, statusCounts(vendor)),
            el('td', { class: 'num mono', 'data-label': 'Total' }, vendorMoney(vendor, 'total')),
            el('td', { class: 'num mono', 'data-label': 'Average' }, vendorMoney(vendor, 'average')),
            el('td', { class: 'num mono', 'data-label': 'Duplicates', text: formatNumber(vendor.duplicates) }),
            el('td', { class: 'num', 'data-label': 'Avg risk' }, flagBadge(vendor.average_risk === null ? null : { risk_score: vendor.average_risk, risk_flag: vendor.average_risk > 50 ? 'HIGH' : 'LOW' })),
            el('td', { 'data-label': 'Last seen' }, el('time', { class: 'time-main', datetime: vendor.last_seen, text: formatRelative(vendor.last_seen, now) || 'just now' }))));
    });
    const table = el('table', { class: 'data-table vendor-table stack-on-mobile' },
        el('caption', { class: 'visually-hidden', text: 'Vendors' }), el('thead', {}, header), body);
    clear(dom.output).append(el('div', { class: 'table-scroll' }, table),
        el('div', { class: 'table-more' }, el('p', { text: `${formatNumber(data.matching)} of ${formatNumber(data.total)} vendors. Amounts are added as written on the invoices, in the vendor's currency.` })));
}

// ---------- One vendor ----------

async function loadDetail(id) {
    const token = ++requestId;
    clear(dom.detail).append(el('div', { class: 'glass-panel' }, el('div', { class: 'skeleton skeleton-line' }), el('div', { class: 'skeleton skeleton-block' })));
    try {
        const vendor = await getJson(`/api/vendors/${encodeURIComponent(id)}`);
        if (token !== requestId) return;
        renderDetail(vendor);
        document.title = `${vendor.name} · SupplyTrace`;
    } catch (error) {
        if (token !== requestId) return;
        const missing = error.status === 404;
        clear(dom.detail).append(errorCard(missing ? 'This vendor does not exist' : 'The vendor could not be loaded',
            missing ? 'It may have been on a demo server that restarted.' : error.message,
            missing ? null : () => loadDetail(id)));
    }
}

// "Also 1,200.00 EUR" for the currencies other than the main one.
function otherTotals(vendor) {
    const others = vendor.currencies.slice(1);
    return others.length ? `Also ${others.map(c => money(c.total, c.currency)).join(', ')}` : null;
}

function stat(label, value, sub) {
    return el('div', { class: 'sub-metric' },
        el('span', { class: 'sub-label', text: label }),
        el('span', { class: 'sub-value' }, value),
        sub ? el('span', { class: 'stat-sub', text: sub }) : null);
}

function renderDetail(vendor) {
    const split = el('div', { class: 'split-bar-wrap' });
    splitBar(split, vendor.statuses, { label: 'Invoices by status' });
    const head = el('section', { class: 'glass-panel review-head' },
        el('a', { class: 'back-link', href: '#/vendors' }, icon('arrow-right', 'flip'), 'Back to the vendors'),
        el('div', { class: 'review-title-row' },
            el('h2', { class: 'review-title', text: vendor.name }),
            el('div', { class: 'badge-group' }, trustedTag(vendor))),
        el('p', { class: 'review-reason muted', text: vendor.supplier_id ? `Supplier ID ${vendor.supplier_id}` : 'No supplier ID in the invoices: the vendor is recognised by name.' }),
        el('div', { class: 'metrics-subgrid' },
            stat('Invoices', formatNumber(vendor.invoice_count)),
            stat('Total', money(vendor.total_amount, vendor.currency), otherTotals(vendor)),
            stat('Average', money(vendor.average_amount, vendor.currency), vendor.currencies.length > 1 ? 'In the main currency' : null),
            stat('Duplicates flagged', formatNumber(vendor.duplicates)),
            stat('Average risk', vendor.average_risk === null ? 'N/A' : `${vendor.average_risk}%`),
            stat('Last seen', formatDateTime(vendor.last_seen))),
        split,
        el('p', { class: 'muted legend-line' },
            `${vendor.statuses.VALID} valid · ${vendor.statuses.REQUIRES_REVIEW} need review · ${vendor.statuses.INVALID} invalid`));

    clear(dom.detail).append(head, el('div', { class: 'review-grid' },
        el('div', { class: 'review-side' }, profilePanel(vendor)),
        el('div', { class: 'review-main' }, invoicesPanel(vendor))));
}

function profilePanel(vendor) {
    const error = el('p', { class: 'inline-error', role: 'alert', hidden: true });
    const name = el('input', { id: 'vendor-actor', type: 'text', class: 'text-input', maxlength: '60', value: getReviewerName(), placeholder: 'e.g. Asha', autocomplete: 'nickname' });
    const notes = el('textarea', { id: 'vendor-notes', class: 'text-input', rows: '5', maxlength: '2000', placeholder: 'Payment terms, contacts, anything the next person should know' });
    notes.value = vendor.notes;
    const trusted = el('input', { id: 'vendor-trusted', type: 'checkbox' });
    trusted.checked = vendor.trusted;
    const save = el('button', { type: 'button', class: 'btn btn-primary' }, icon('check'), 'Save');

    save.addEventListener('click', async () => {
        error.hidden = true;
        const actor = name.value.trim();
        if (!actor) {
            error.textContent = 'Enter your name so the audit log shows who made the change.';
            error.hidden = false;
            name.focus();
            return;
        }
        setReviewerName(actor);
        save.disabled = true;
        try {
            const updated = await putJson(`/api/vendors/${encodeURIComponent(vendor.id)}`, { actor, notes: notes.value, trusted: trusted.checked });
            renderDetail(updated);
            toast('Vendor saved. The change is in the audit log.');
            announce('Vendor saved.');
        } catch (e) {
            save.disabled = false;
            error.textContent = e.message;
            error.hidden = false;
        }
    });

    return el('section', { class: 'glass-panel review-actions' },
        el('h3', { class: 'sub-label', text: 'Notes and trust' }),
        el('label', { class: 'check-field', for: 'vendor-trusted' }, trusted,
            el('span', {}, el('strong', { text: 'Trusted vendor' }),
                el('span', { class: 'muted', text: ' Shown on this vendor\'s results. It never changes validation, the risk score or duplicate checks.' }))),
        el('div', { class: 'form-row' }, el('label', { class: 'field-label', for: 'vendor-notes', text: 'Notes' }), notes),
        el('div', { class: 'form-row' }, el('label', { class: 'field-label', for: 'vendor-actor', text: 'Your name' }), name),
        error,
        el('div', { class: 'result-actions review-buttons' }, save),
        vendor.updated_by ? el('p', { class: 'muted history-note', text: `Last changed by ${vendor.updated_by}, ${formatRelative(vendor.updated_at)}.` }) : null);
}

function invoicesPanel(vendor) {
    const panel = el('section', { class: 'glass-panel vendor-invoices' });
    const status = el('select', { id: 'vendor-inv-status' },
        ['', 'VALID', 'INVALID', 'REQUIRES_REVIEW'].map(value => el('option', { value, text: { '': 'Any status', VALID: 'Valid', INVALID: 'Invalid', REQUIRES_REVIEW: 'Needs review' }[value] })));
    const dupes = el('input', { id: 'vendor-inv-dupes', type: 'checkbox' });
    const output = el('div', { class: 'vendor-invoices-output' }, el('div', { class: 'skeleton skeleton-row' }));

    async function load() {
        output.setAttribute('aria-busy', 'true');
        const params = new URLSearchParams();
        if (status.value) params.set('status', status.value);
        if (dupes.checked) params.set('duplicates', 'true');
        try {
            const data = await getJson(`/api/vendors/${encodeURIComponent(vendor.id)}/invoices?${params}`);
            renderInvoices(output, data);
        } catch (error) {
            clear(output).append(errorCard('The invoices could not be loaded', error.message, load));
        } finally {
            output.removeAttribute('aria-busy');
        }
    }
    status.addEventListener('change', load);
    dupes.addEventListener('change', load);
    panel.append(
        el('div', { class: 'section-head' },
            el('h3', { class: 'sub-label', text: 'Invoices' }),
            el('span', { class: 'invoice-filters' },
                el('label', { class: 'select-wrap' }, el('span', { class: 'visually-hidden', text: 'Status' }), status, icon('chevron-down')),
                el('label', { class: 'check-inline', for: 'vendor-inv-dupes' }, dupes, 'Duplicates only'))),
        output);
    load();
    return panel;
}

function renderInvoices(container, data) {
    if (!data.invoices.length) {
        clear(container).append(el('p', { class: 'muted empty-line', text: 'No invoices match.' }));
        return;
    }
    const now = Date.now();
    const rows = data.invoices.map(invoice => el('tr', {},
        el('td', { 'data-label': 'File' },
            el('span', { class: 'mono file-cell', text: invoice.filename }),
            el('span', { class: 'cell-sub' }, invoice.invoice_id ? el('span', { class: 'mono', text: invoice.invoice_id }) : el('span', { text: 'No ID' }))),
        el('td', { 'data-label': 'Status' }, badge(invoice.validation_status), duplicateTag(invoice.duplicate_kind)),
        el('td', { class: 'num mono', 'data-label': 'Amount', text: invoice.amount ? `${invoice.amount}${invoice.currency ? ` ${invoice.currency}` : ''}` : '–' }),
        el('td', { class: 'num', 'data-label': 'Risk' }, flagBadge(typeof invoice.risk_score === 'number' ? { risk_score: invoice.risk_score, risk_flag: invoice.risk_score > 50 ? 'HIGH' : 'LOW' } : null)),
        el('td', { 'data-label': 'Checked' }, el('time', { datetime: invoice.seen_at, text: formatRelative(invoice.seen_at, now) || 'just now' })),
        el('td', { 'data-label': 'Review' }, invoice.review_id
            ? el('a', { class: 'review-link', href: `#/review?id=${invoice.review_id}`, text: `Review #${invoice.review_id}` })
            : el('span', { class: 'cell-muted', text: '–' }))));
    const table = el('table', { class: 'data-table stack-on-mobile' },
        el('caption', { class: 'visually-hidden', text: 'Invoices of this vendor, newest first' }),
        el('thead', {}, el('tr', {},
            ['File', 'Status', 'Amount', 'Risk', 'Checked', 'Review'].map(label => el('th', { scope: 'col', class: ['Amount', 'Risk'].includes(label) ? 'num' : null, text: label })))),
        el('tbody', {}, rows));
    clear(container).append(el('div', { class: 'table-scroll' }, table),
        el('p', { class: 'muted table-note', text: data.matching > data.invoices.length ? `Showing the newest ${data.invoices.length} of ${formatNumber(data.matching)} invoices.` : `${formatNumber(data.matching)} ${data.matching === 1 ? 'invoice' : 'invoices'}, newest first.` }));
}
