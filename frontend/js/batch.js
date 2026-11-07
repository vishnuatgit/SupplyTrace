// The Batch view: check up to 20 files in one request, watch them come back one
// by one (the server streams a line per file), then read the summary, the risk
// chart and a sortable table, drill into any file, and download CSV or JSON.

import { MAX_BATCH_FILES, getText, postFilesStream, precheckFile } from './api.js';
import {
    el, clear, icon, badge, flagBadge, statusText, STATUS, formatNumber, formatPercent, formatMs,
    plural, announce, toast, setupDropzone, setLoading, downloadFile, fileStamp,
} from './ui.js';
import { STATUS_ORDER, splitBar, riskStrip, barList } from './charts.js';
import { renderResult, renderError } from './result.js';

let dom;
let deps; // { getSamples, openInSandbox, onChecked }
let busy = false;
let lastRun = null; // { rows: [{ result, text }], finishedAt, serverMs }
let sort = { key: 'index', dir: 1 };
let drawerIndex = 0;
let live = null; // the table rows while a batch streams in

export function initBatch(dependencies) {
    deps = dependencies;
    const $ = id => document.getElementById(id);
    dom = {
        output: $('batch-output'),
        input: $('batch-input'),
        samplesButton: $('batch-samples'),
        samplesLabel: $('batch-samples-label'),
        samplesHint: $('batch-samples-hint'),
        chooseButton: $('batch-choose'),
        progress: $('batch-progress'),
        progressText: $('batch-progress-text'),
        progressCount: $('batch-progress-count'),
        progressBar: $('batch-progressbar'),
        progressFill: $('batch-progress-fill'),
        drawer: $('drawer'),
        drawerTitle: $('drawer-title'),
        drawerEyebrow: $('drawer-eyebrow'),
        drawerBody: $('drawer-body'),
    };
    dom.samplesButton.addEventListener('click', runSamples);
    dom.chooseButton.addEventListener('click', () => dom.input.click());
    setupDropzone($('batch-dropzone'), runFiles, { input: dom.input, isBusy: () => busy });

    $('drawer-close').addEventListener('click', () => dom.drawer.close());
    $('drawer-prev').addEventListener('click', () => stepDrawer(-1));
    $('drawer-next').addEventListener('click', () => stepDrawer(1));
    // A click on the backdrop (the dialog element itself, outside its content) closes it.
    dom.drawer.addEventListener('click', event => {
        if (event.target === dom.drawer) dom.drawer.close();
    });
    dom.drawer.addEventListener('keydown', event => {
        if (event.target.closest('input, textarea')) return;
        if (event.key === 'ArrowRight' && event.altKey) stepDrawer(1);
        if (event.key === 'ArrowLeft' && event.altKey) stepDrawer(-1);
    });

    // The sample button says how many samples there are and what they are built to get.
    deps.getSamples().then(describeSamples).catch(() => {});
}

const listText = items => (items.length > 1 ? `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}` : items.join(''));

function describeSamples(samples) {
    const count = status => samples.filter(sample => sample.expected === status).length;
    const review = count('REQUIRES_REVIEW');
    const parts = [
        count('VALID') ? `${count('VALID')} valid` : null,
        count('INVALID') ? `${count('INVALID')} invalid` : null,
        review ? `${review} that ${review === 1 ? 'needs' : 'need'} review` : null,
    ].filter(Boolean);
    dom.samplesLabel.textContent = `Check the ${samples.length} sample invoices`;
    dom.samplesHint.textContent = `${listText(parts)}, all synthetic.`;
}

// Runs one batch at a time. A failure shows an error card whose Try again
// repeats the same action (the same samples or the same files).
async function guarded(button, task, { retry, kind }) {
    if (busy) return;
    busy = true;
    dom.samplesButton.disabled = true;
    dom.chooseButton.disabled = true;
    if (button) setLoading(button, true);
    try {
        await task();
    } catch (error) {
        hideProgress();
        live = null;
        showError(error, { retry, kind });
        announce(`The batch could not be checked. ${error.message}`);
    } finally {
        busy = false;
        dom.samplesButton.disabled = false;
        dom.chooseButton.disabled = false;
        if (button) setLoading(button, false);
    }
}

export function runSamples() {
    return guarded(dom.samplesButton, async () => {
        showProgress('Fetching the sample invoices…', 0, 0);
        showWaiting();
        const samples = await deps.getSamples();
        const files = await Promise.all(samples.map(async sample => {
            const text = await getText(`/api/samples/${encodeURIComponent(sample.id)}`);
            return new File([text], sample.filename, { type: 'text/xml' });
        }));
        await check(files);
    }, { retry: runSamples, kind: 'samples' });
}

export function runFiles(files) {
    if (!files.length) return Promise.resolve();
    return guarded(null, () => check(files), { retry: () => runFiles(files), kind: 'files' });
}

// A row for a file refused in the browser, worded like the server's own refusal.
function rejectedRow(name, message) {
    return {
        filename: name, id: '', status: 'REJECTED', errors: [message], findings: [], checks: [],
        fields: null, features: null, prediction: { risk_score: 'N/A', risk_flag: 'N/A' },
        risk_drivers: null, processing_ms: null, timings_ms: null, parse_error: null,
    };
}

async function check(files) {
    if (files.length > MAX_BATCH_FILES) {
        const error = new Error(`That's ${files.length} files. A batch can hold up to ${MAX_BATCH_FILES}; choose fewer and try again.`);
        error.status = 400;
        throw error;
    }
    // Files the server would refuse anyway (not .xml, over 1 MB, empty) are not uploaded.
    const entries = files.map(file => ({ file, problem: precheckFile(file) }));
    const sent = entries.map((entry, index) => ({ ...entry, index })).filter(entry => !entry.problem);
    const texts = await Promise.all(entries.map(entry => (entry.problem ? null : entry.file.text())));
    const sentResults = new Array(sent.length);
    const started = performance.now();

    showLive(entries);
    showProgress(`Uploading ${plural(sent.length, 'file')}…`, 0, sent.length);
    if (sent.length) {
        let done = 0;
        await postFilesStream('/api/analyze/batch/stream', 'files', sent.map(entry => entry.file), line => {
            if (line.type !== 'result') return;
            sentResults[line.index] = line.result;
            done += 1;
            showProgress(`Checked ${line.result.filename}`, done, sent.length);
            liveResult(sent[line.index].index, line.result, sent[line.index + 1]?.index);
        });
        if (sentResults.some(result => !result)) {
            const error = new Error('The server stopped before every file was checked. Please try again.');
            error.status = 0;
            throw error;
        }
    }

    let next = 0;
    const rows = entries.map((entry, index) => (entry.problem
        ? { result: rejectedRow(entry.file.name, entry.problem), text: null }
        : { result: sentResults[next++], text: texts[index] }));
    const serverMs = rows.reduce((sum, row) => sum + (row.result.processing_ms || 0), 0);
    lastRun = { rows, finishedAt: new Date(), serverMs, wallMs: performance.now() - started };
    sort = { key: 'index', dir: 1 };
    live = null;
    hideProgress();
    render();
    deps.onChecked?.(rows.map(row => row.result));
    const counts = countStatuses(rows);
    announce(`Batch checked: ${totalsText(counts)}.`);
    toast(`Checked ${plural(rows.length, 'file')}.`);
}

// ---------- Progress and the live table ----------

function showProgress(text, done, total) {
    dom.progress.hidden = false;
    dom.progressText.textContent = text;
    dom.progressCount.textContent = total ? `${done} / ${total}` : '';
    const percent = total ? Math.round((done / total) * 100) : 0;
    dom.progressBar.setAttribute('aria-valuenow', String(percent));
    dom.progressFill.style.width = `${percent}%`;
    dom.progress.classList.toggle('is-indeterminate', !done);
}

function hideProgress() {
    dom.progress.hidden = true;
}

const LIVE_HEADERS = ['#', 'File', 'Transaction ID', 'Status', 'Reasons', 'Risk', 'Server time'];
const NUMERIC = new Set(['#', 'Risk', 'Server time']);

function liveTable(rows, caption) {
    return el('div', { class: 'table-scroll' }, el('table', { class: 'data-table batch-table stack-on-mobile' },
        el('caption', { class: 'visually-hidden', text: caption }),
        el('thead', {}, el('tr', {}, LIVE_HEADERS.map(label => el('th', { scope: 'col', class: NUMERIC.has(label) ? 'num' : null, text: label })))),
        el('tbody', {}, rows)));
}

function livePanel(title, note, rows, caption) {
    return el('section', { class: 'glass-panel batch-results batch-live', 'aria-busy': 'true' },
        el('div', { class: 'batch-head' }, el('div', {}, el('h2', { text: title }), el('p', { class: 'muted', text: note }))),
        liveTable(rows, caption));
}

// Before the files are known (the samples are still being fetched).
function showWaiting() {
    const rows = Array.from({ length: 3 }, () => el('tr', { class: 'row-waiting' },
        LIVE_HEADERS.map(label => el('td', { 'data-label': label }, el('span', { class: 'skeleton skeleton-cell' })))));
    clear(dom.output).append(livePanel('Getting the sample invoices…', 'They are checked as soon as they arrive.', rows, 'Batch in progress'));
}

// One row per file: refused files are final at once, the rest wait for the stream.
function showLive(entries) {
    const firstSent = entries.findIndex(entry => !entry.problem);
    live = entries.map((entry, index) => (entry.problem
        ? resultRow(rejectedRow(entry.file.name, entry.problem), index)
        : waitingRow(entry.file.name, index, index === firstSent)));
    clear(dom.output).append(livePanel(`Checking ${plural(entries.length, 'file')}…`,
        'Each row fills in as soon as the server has checked that file.', live, 'Batch in progress, one row per file'));
}

function queueState(checking) {
    return el('span', { class: `queue-state${checking ? ' is-checking' : ''}` },
        checking ? el('span', { class: 'spinner spinner-sm', 'aria-hidden': 'true' }) : null,
        checking ? 'Checking' : 'Queued');
}

function waitingRow(name, index, checking) {
    return el('tr', { class: 'row-waiting' },
        el('td', { class: 'num cell-muted', 'data-label': '#', text: index + 1 }),
        el('td', { 'data-label': 'File' }, el('span', { class: 'mono file-cell', text: name })),
        el('td', { 'data-label': 'Transaction ID' }, el('span', { class: 'skeleton skeleton-cell' })),
        el('td', { 'data-label': 'Status' }, queueState(checking)),
        el('td', { 'data-label': 'Reasons' }, el('span', { class: 'skeleton skeleton-cell wide' })),
        el('td', { class: 'num', 'data-label': 'Risk' }, el('span', { class: 'skeleton skeleton-cell' })),
        el('td', { class: 'num', 'data-label': 'Server time' }, el('span', { class: 'skeleton skeleton-cell' })));
}

// A file's result arrived: its row fills in, and the next file shows as checking.
function liveResult(index, result, nextIndex) {
    if (!live) return;
    const row = resultRow(result, index);
    row.classList.add('row-in');
    live[index].replaceWith(row);
    live[index] = row;
    if (nextIndex !== undefined) live[nextIndex].querySelector('.queue-state')?.replaceWith(queueState(true));
}

function showError(error, { retry, kind }) {
    // A network or server failure can be retried; a refusal (4xx) needs other files.
    const retryable = !(error.status >= 400 && error.status < 500);
    const actions = [];
    if (retryable) {
        actions.push(el('button', { type: 'button', class: 'btn btn-primary', on: { click: retry } }, icon('refresh'), 'Try again'));
    }
    if (kind === 'files') {
        actions.push(el('button', { type: 'button', class: 'btn btn-secondary', on: { click: runSamples } }, icon('play'), 'Check the samples instead'));
    }
    clear(dom.output).append(el('div', { class: `error-card glass-panel${retryable ? ' is-warning' : ''}`, role: 'alert' },
        el('span', { class: 'error-icon', 'aria-hidden': 'true' }, icon(retryable ? 'refresh' : 'x-circle')),
        el('div', {},
            el('p', { class: 'error-title', text: retryable ? 'The batch did not finish' : 'The batch could not be checked' }),
            el('p', { text: error.message }),
            actions.length ? el('div', { class: 'error-actions' }, actions) : null)));
}

// ---------- Summary ----------

function countStatuses(rows) {
    const counts = Object.fromEntries(STATUS_ORDER.map(status => [status, 0]));
    rows.forEach(({ result }) => { counts[result.status] = (counts[result.status] || 0) + 1; });
    return counts;
}

function totalsText(counts) {
    const total = Object.values(counts).reduce((sum, n) => sum + n, 0);
    const parts = STATUS_ORDER.map(status => `${formatNumber(counts[status])} ${statusText(status).toLowerCase()}`);
    return `${plural(total, 'file')}: ${parts.join(', ')}`;
}

function statTiles(counts, total) {
    const tiles = [el('div', { class: 'stat-tile' },
        el('span', { class: 'stat-icon tone-primary', 'aria-hidden': 'true' }, icon('file')),
        el('span', { class: 'stat-label', text: 'Files' }),
        el('span', { class: 'stat-value', text: formatNumber(total) }),
        el('span', { class: 'stat-sub', text: `${formatMs(lastRun.serverMs)} on the server` }))];
    for (const status of STATUS_ORDER) {
        tiles.push(el('div', { class: `stat-tile tile-${status}` },
            el('span', { class: `stat-icon tone-${STATUS[status].tone}`, 'aria-hidden': 'true' }, icon(STATUS[status].icon)),
            el('span', { class: 'stat-label', text: statusText(status) }),
            el('span', { class: 'stat-value', text: formatNumber(counts[status]) }),
            el('span', { class: 'stat-sub', text: total ? `${formatPercent((counts[status] / total) * 100)} of the batch` : '–' })));
    }
    return el('div', { class: 'stat-tiles' }, tiles);
}

function rulesBroken(rows) {
    const byRule = new Map();
    rows.forEach(({ result }) => (result.checks || []).forEach(check => {
        if (check.state !== 'broken') return;
        const entry = byRule.get(check.rule) || { label: check.title, value: 0, tone: check.outcome === 'REQUIRES_REVIEW' ? 'warning' : 'danger' };
        entry.value += 1;
        byRule.set(check.rule, entry);
    }));
    const rejected = rows.filter(({ result }) => result.status === 'REJECTED').length;
    const items = [...byRule.values()].sort((a, b) => b.value - a.value);
    if (rejected) items.push({ label: 'Could not be read (rejected)', value: rejected, tone: 'neutral' });
    return items;
}

function render() {
    const { rows, finishedAt } = lastRun;
    const counts = countStatuses(rows);
    const time = finishedAt.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });

    const head = el('div', { class: 'batch-head' },
        el('div', {},
            el('h2', { text: `Checked ${plural(rows.length, 'file')}` }),
            el('p', { class: 'muted', text: `Finished at ${time}. Every accepted file is now in the audit log.` })),
        el('div', { class: 'batch-downloads' },
            el('button', { type: 'button', class: 'btn btn-secondary', on: { click: downloadCsv } }, icon('download'), 'CSV'),
            el('button', { type: 'button', class: 'btn btn-secondary', on: { click: downloadJson } }, icon('download'), 'JSON')));

    const split = el('div', { class: 'split-bar-wrap' });
    splitBar(split, counts, { label: 'Batch status split' });

    const strip = el('div', { class: 'chart-slot' });
    const broken = el('div', { class: 'chart-slot' });
    barList(broken, rulesBroken(rows), { empty: 'No rule was broken: every file passed.' });

    const tableWrap = el('div', { class: 'table-scroll', id: 'batch-table-wrap' });
    clear(dom.output).append(el('section', { class: 'glass-panel batch-results' },
        head,
        statTiles(counts, rows.length),
        split,
        el('div', { class: 'batch-charts' },
            el('figure', { class: 'chart-wrapper' },
                el('figcaption', { class: 'chart-title' }, 'Risk score per file ', el('span', { class: 'experimental-tag', text: 'Experimental' })),
                strip,
                el('p', { class: 'chart-note', text: 'Each dot is one file, coloured by status. Select a dot to open it.' })),
            el('figure', { class: 'chart-wrapper' },
                el('figcaption', { class: 'chart-title', text: 'Rules broken in this batch' }),
                broken)),
        tableWrap));
    riskStrip(strip, rows.map(({ result }) => ({
        score: result.prediction?.risk_score, status: result.status, label: result.filename,
    })), { onSelect: openDrawer });
    renderTable();
}

// ---------- Sortable table ----------

const STATUS_RANK = { INVALID: 0, REQUIRES_REVIEW: 1, VALID: 2, REJECTED: 3 };
const COLUMNS = [
    { key: 'index', label: '#', num: true, value: (_r, i) => i },
    { key: 'file', label: 'File', value: r => r.filename.toLowerCase() },
    { key: 'id', label: 'Transaction ID', value: r => r.id || '￿' },
    { key: 'status', label: 'Status', value: r => STATUS_RANK[r.status] ?? 9 },
    { key: 'reasons', label: 'Reasons', value: r => -(r.errors?.length || 0) },
    { key: 'risk', label: 'Risk', num: true, value: r => (typeof r.prediction?.risk_score === 'number' ? r.prediction.risk_score : -1) },
    { key: 'time', label: 'Server time', num: true, value: r => r.processing_ms ?? -1 },
];

function sortedRows() {
    const column = COLUMNS.find(c => c.key === sort.key);
    return lastRun.rows
        .map((row, index) => ({ ...row, index }))
        .sort((a, b) => {
            const va = column.value(a.result, a.index);
            const vb = column.value(b.result, b.index);
            return (va < vb ? -1 : va > vb ? 1 : a.index - b.index) * sort.dir;
        });
}

// One table row. With onOpen the file name is a button that opens the drawer;
// while a batch is still streaming in it is plain text.
function resultRow(result, index, onOpen = null) {
    const file = onOpen
        ? el('button', { type: 'button', class: 'link-btn mono file-cell', 'aria-label': `Open ${result.filename}`, on: { click: () => onOpen(index) } },
            result.filename, icon('chevron-right'))
        : el('span', { class: 'mono file-cell', text: result.filename });
    return el('tr', { class: `row-${result.status}` },
        el('td', { class: 'num cell-muted', 'data-label': '#', text: index + 1 }),
        el('td', { 'data-label': 'File' }, file),
        el('td', { 'data-label': 'Transaction ID' }, result.id ? el('span', { class: 'mono', text: result.id }) : el('span', { class: 'cell-muted', text: '–' })),
        el('td', { 'data-label': 'Status' }, badge(result.status)),
        el('td', { 'data-label': 'Reasons' }, result.errors?.length
            ? el('span', { class: 'reasons' }, result.errors.map(message => el('span', { text: message })))
            : el('span', { class: 'cell-muted', text: 'None' })),
        el('td', { class: 'num', 'data-label': 'Risk' }, flagBadge(result.prediction)),
        el('td', { class: 'num mono', 'data-label': 'Server time', text: formatMs(result.processing_ms) }));
}

function renderTable() {
    const wrap = document.getElementById('batch-table-wrap');
    const header = el('tr', {}, COLUMNS.map(column => {
        const active = sort.key === column.key;
        return el('th', {
            scope: 'col', class: column.num ? 'num' : null,
            'aria-sort': active ? (sort.dir === 1 ? 'ascending' : 'descending') : 'none',
        }, el('button', {
            type: 'button', class: `sort-btn${active ? ' is-active' : ''}`,
            on: { click: () => {
                sort = { key: column.key, dir: active ? -sort.dir : 1 };
                renderTable();
                wrap.querySelector(`th [data-key="${column.key}"]`)?.focus();
            } },
            'data-key': column.key,
        }, column.label, icon(active ? 'chevron-down' : 'sort', active && sort.dir === 1 ? 'flip-y' : '')));
    }));

    const body = sortedRows().map(({ result, index }) => resultRow(result, index, openDrawer));
    const counts = countStatuses(lastRun.rows);
    // On phones the table turns into cards and its header row is hidden, so this menu sorts instead.
    const sortMenu = el('label', { class: 'batch-sort' }, el('span', { text: 'Sort by' }),
        el('select', { on: { change: event => {
            const [key, dir] = event.target.value.split(':');
            sort = { key, dir: Number(dir) };
            renderTable();
            wrap.querySelector('.batch-sort select')?.focus();
        } } }, COLUMNS.flatMap(column => [1, -1].map(dir => el('option', {
            value: `${column.key}:${dir}`,
            selected: sort.key === column.key && sort.dir === dir,
            text: `${column.key === 'index' ? 'File order' : column.label}, ${dir === 1 ? 'ascending' : 'descending'}`,
        })))));
    clear(wrap).append(sortMenu, el('table', { class: 'data-table batch-table stack-on-mobile' },
        el('caption', { class: 'visually-hidden', text: 'Batch results. Column headers sort the table.' }),
        el('thead', {}, header),
        el('tbody', {}, body),
        el('tfoot', {}, el('tr', {}, el('td', { colspan: String(COLUMNS.length), text: `Total ${totalsText(counts)}` })))));
}

// ---------- Drawer: one file in full ----------

// Previous and next follow the table as it is sorted on screen.
function stepDrawer(delta) {
    if (!lastRun) return;
    const order = sortedRows().map(row => row.index);
    const position = order.indexOf(drawerIndex);
    openDrawer(order[(position + delta + order.length) % order.length]);
}

function openDrawer(index) {
    if (!lastRun) return;
    const count = lastRun.rows.length;
    drawerIndex = index;
    const { result, text } = lastRun.rows[index];
    const position = sortedRows().findIndex(row => row.index === index);
    const sorted = sort.key === 'index' ? '' : ` · sorted by ${COLUMNS.find(c => c.key === sort.key).label.toLowerCase()}`;
    dom.drawerTitle.textContent = result.filename;
    dom.drawerEyebrow.textContent = `File ${position + 1} of ${count}${sorted}`;
    const openInSandbox = (xml, name, problem) => {
        dom.drawer.close();
        deps.openInSandbox(xml, name, problem);
    };
    if (result.status === 'REJECTED') {
        const error = new Error(result.errors[0]);
        error.status = 400;
        error.body = result.parse_error;
        renderError(dom.drawerBody, { name: result.filename, text, error, onEdit: text ? openInSandbox : null });
    } else {
        renderResult(dom.drawerBody, result, text, { onEdit: openInSandbox, pipeline: 'static' });
    }
    if (!dom.drawer.open) dom.drawer.showModal();
    dom.drawerBody.scrollTop = 0;
    document.getElementById('drawer-prev').disabled = count < 2;
    document.getElementById('drawer-next').disabled = count < 2;
}

// ---------- Downloads ----------

const CSV_COLUMNS = [
    ['file', r => r.filename],
    ['transaction_id', r => r.id],
    ['status', r => r.status],
    ['reasons', r => (r.errors || []).join('; ')],
    ['risk_score', r => (typeof r.prediction?.risk_score === 'number' ? r.prediction.risk_score : '')],
    ['risk_flag', r => (typeof r.prediction?.risk_score === 'number' ? r.prediction.risk_flag : '')],
    ['missing_optional_fields', r => r.features?.missing_optional_fields ?? ''],
    ['nesting_depth', r => r.features?.nesting_depth ?? ''],
    ['xml_size_bytes', r => r.features?.xml_size ?? ''],
    ['processing_ms', r => r.processing_ms ?? ''],
];

// Quotes a cell when needed, and stops spreadsheet apps from running text
// that starts like a formula (a file could be named "=HYPERLINK(...).xml").
function csvCell(value) {
    let text = String(value ?? '');
    if (typeof value === 'string' && /^[=+\-@\t\r]/.test(text)) text = `'${text}`;
    return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function toCsv(results) {
    const lines = [CSV_COLUMNS.map(([name]) => name).join(',')];
    results.forEach(result => lines.push(CSV_COLUMNS.map(([, get]) => csvCell(get(result))).join(',')));
    return `${lines.join('\r\n')}\r\n`;
}

function downloadCsv() {
    if (!lastRun) return;
    // The byte-order mark lets Excel read the file as UTF-8.
    downloadFile(`supplytrace-batch-${fileStamp(lastRun.finishedAt)}.csv`, ['﻿', toCsv(lastRun.rows.map(r => r.result))], 'text/csv;charset=utf-8');
    toast('Batch downloaded as CSV.');
}

function downloadJson() {
    if (!lastRun) return;
    const results = lastRun.rows.map(r => r.result);
    const body = {
        generated_at: lastRun.finishedAt.toISOString(),
        tool: 'SupplyTrace',
        note: 'Statuses come from deterministic rules. Risk scores are experimental: a Random Forest trained on synthetic invoices.',
        summary: countStatuses(lastRun.rows),
        results,
    };
    downloadFile(`supplytrace-batch-${fileStamp(lastRun.finishedAt)}.json`, [JSON.stringify(body, null, 2)], 'application/json');
    toast('Batch downloaded as JSON.');
}
