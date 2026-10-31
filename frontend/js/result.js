// One checked file, shown the same way in the Payload Inspector and in the
// batch drawer: a verdict banner, the rule checklist (each rule jumps to its
// line), the XML with those lines marked, the risk score with what drove it,
// the details, and the actions.

import {
    el, clear, icon, STATUS, formatBytes, formatMs, formatNumber, formatPercent, plural,
    copyText, downloadFile, fileStamp, toast, announce,
} from './ui.js';
import { renderXml, revealLine } from './xml-view.js';
import { riskGauge, riskWaterfall } from './charts.js';
import { pipelineStrip } from './pipeline.js';

const OPTIONAL_FIELD_COUNT = 4;
const REVIEW_LIMIT = 1_000_000;

const CHECK_ICON = { passed: 'check-circle', skipped: 'minus-circle' };

function summaryFor(result, failed) {
    const limit = formatNumber(REVIEW_LIMIT);
    if (result.status === 'VALID') {
        return `Passed every rule. The transaction ID and the amount were found, and the amount is within the ${limit} review limit.`;
    }
    if (result.status === 'REQUIRES_REVIEW') {
        return `Passed the rules, but the amount is above the ${limit} review limit, so a person has to approve it before processing.`;
    }
    return failed === 1
        ? 'Failed 1 rule. The invoice cannot be processed until the problem below is fixed.'
        : `Failed ${failed} rules. The invoice cannot be processed until the problems below are fixed.`;
}

function headline(result, failed) {
    if (result.status === 'VALID') return 'All 5 rules passed';
    if (result.status === 'REQUIRES_REVIEW') return 'Amount above the review limit';
    return failed === 1 ? '1 rule failed' : `${failed} rules failed`;
}

// ---------- Verdict ----------

function verdict(result, failed) {
    const fields = result.fields || {};
    const meta = [
        el('span', { class: 'mono verdict-file', text: result.filename }),
        el('span', {}, 'ID ', fields.ID?.value ? el('span', { class: 'mono', text: fields.ID.value }) : el('span', { class: 'muted', text: 'not found' })),
        el('span', {}, 'Amount ', fields.AMOUNT?.value ? el('span', { class: 'mono', text: fields.AMOUNT.value }) : el('span', { class: 'muted', text: 'not found' })),
    ];
    const score = result.prediction?.risk_score;
    return el('div', { class: `verdict verdict-${result.status}` },
        el('span', { class: 'verdict-icon', 'aria-hidden': 'true' }, icon(STATUS[result.status]?.icon || 'info')),
        el('div', { class: 'verdict-main' },
            el('h3', { class: 'verdict-title' },
                el('span', { class: 'verdict-status', text: result.status }),
                el('span', { class: 'verdict-headline', text: headline(result, failed) })),
            el('p', { class: 'verdict-meta' }, meta)),
        el('div', { class: 'verdict-risk' },
            el('span', { class: 'verdict-risk-label', text: 'Risk score' }),
            typeof score === 'number'
                ? el('span', { class: `verdict-risk-value flag-text-${result.prediction.risk_flag}`, text: formatPercent(score) })
                : el('span', { class: 'verdict-risk-value muted', text: 'N/A' }),
            el('span', { class: 'experimental-tag', text: 'Experimental' })));
}

// ---------- Rule checklist ----------

function checklist(result) {
    const checks = result.checks || [];
    const count = state => checks.filter(c => c.state === state).length;
    const broken = count('broken');
    const summary = [`${count('passed')} passed`, `${broken} ${result.status === 'REQUIRES_REVIEW' ? 'flagged' : 'failed'}`];
    if (count('skipped')) summary.push(`${count('skipped')} not checked`);

    const rows = checks.map((check, index) => {
        const tone = check.state === 'broken' ? (check.outcome === 'REQUIRES_REVIEW' ? 'review' : 'failed') : check.state;
        const iconName = check.state === 'broken' ? STATUS[check.outcome].icon : CHECK_ICON[check.state];
        const content = [
            el('span', { class: 'check-num', 'aria-hidden': 'true', text: index + 1 }),
            el('span', { class: 'check-icon', 'aria-hidden': 'true' }, icon(iconName)),
            el('span', { class: 'check-text' },
                el('span', { class: 'check-title', text: check.title }),
                el('span', { class: 'check-note', text: check.note })),
        ];
        const stateText = { passed: 'passed', failed: 'failed', review: 'needs review', skipped: 'not checked' }[tone];
        if (check.line) {
            content.push(el('span', { class: 'check-line' }, `Line ${check.line}`, icon('jump')));
            return el('li', { class: `check check-${tone}` }, el('button', {
                type: 'button', class: 'check-row', 'data-line': check.line,
                'aria-label': `Rule ${index + 1}, ${check.title}: ${stateText}. ${check.note} Show line ${check.line}.`,
            }, content));
        }
        return el('li', { class: `check check-${tone}` }, el('div', { class: 'check-row', 'aria-label': `Rule ${index + 1}, ${check.title}: ${stateText}. ${check.note}` }, content));
    });

    return el('section', { class: 'result-section' },
        el('div', { class: 'section-head' },
            el('h4', { class: 'sub-label', text: 'Rule checklist' }),
            el('span', { class: 'section-meta', text: summary.join(' · ') })),
        el('ol', { class: 'checklist' }, rows));
}

// ---------- XML panel ----------

function marksFor(result) {
    const marks = [];
    (result.checks || []).forEach((check, index) => {
        if (check.state !== 'broken' || !check.line) return;
        marks.push({
            line: check.line, endLine: check.end_line, badge: String(index + 1), title: check.note,
            kind: check.outcome === 'REQUIRES_REVIEW' ? 'review' : 'invalid',
        });
    });
    for (const [name, label] of [['ID', 'Transaction ID'], ['AMOUNT', 'Amount']]) {
        const field = result.fields?.[name];
        if (field?.line) marks.push({ line: field.line, endLine: field.end_line, kind: 'found', title: `${label} found here` });
    }
    return marks;
}

function xmlPanel(name, text, marks, { onEdit, size } = {}) {
    const view = el('div', { class: 'xml-view', role: 'region', tabindex: '0', 'aria-label': `${name} with line numbers` });
    const { lineCount } = renderXml(view, text, marks);
    const kinds = new Set(marks.map(m => m.kind));
    const legend = [['error', 'Breaks here'], ['invalid', 'Failed rule'], ['review', 'Needs review'], ['found', 'ID and amount']]
        .filter(([kind]) => kinds.has(kind))
        .map(([kind, label]) => el('span', { class: `legend-item legend-${kind}`, text: label }));

    const copy = el('button', { type: 'button', class: 'btn-text', on: { click: async () => {
        const ok = await copyText(text);
        toast(ok ? 'XML copied to the clipboard.' : 'Could not copy. Select the text instead.', { kind: ok ? 'success' : 'error' });
    } } }, icon('copy'), 'Copy');
    const edit = onEdit ? el('button', { type: 'button', class: 'btn-text', on: { click: () => onEdit(text, name) } }, icon('edit'), 'Edit in sandbox') : null;

    const panel = el('section', { class: 'result-section xml-panel' },
        el('div', { class: 'section-head' },
            el('h4', { class: 'sub-label', text: 'Submitted XML' }),
            el('span', { class: 'section-meta mono', text: `${plural(lineCount, 'line')} · ${formatBytes(size ?? new Blob([text]).size)}` }),
            legend.length ? el('span', { class: 'xml-legend' }, legend) : null,
            el('span', { class: 'section-actions' }, copy, edit)),
        view);
    return { panel, view };
}

// ---------- Risk ----------

function riskBlock(result) {
    const prediction = result.prediction || {};
    const head = el('div', { class: 'section-head' },
        el('h4', { class: 'sub-label', text: 'Risk score' }),
        el('span', { class: 'experimental-tag', text: 'Experimental' }));
    if (typeof prediction.risk_score !== 'number') {
        return el('section', { class: 'result-section risk-block' }, head,
            el('p', { class: 'muted', text: 'Not available: this server has no trained model, so only the rules ran.' }));
    }
    const flag = prediction.risk_flag === 'HIGH' ? 'HIGH' : 'LOW';
    const drivers = el('div', { class: 'risk-drivers' });
    if (result.risk_drivers) riskWaterfall(drivers, result.risk_drivers, prediction.risk_score, flag);
    return el('section', { class: 'result-section risk-block' }, head,
        el('div', { class: 'risk-body' },
            el('div', { class: 'risk-gauge' },
                riskGauge(prediction.risk_score, flag),
                el('span', { class: `risk-value flag-text-${flag}`, text: formatPercent(prediction.risk_score) }),
                el('span', { class: `badge flag-${flag}`, text: flag })),
            el('div', { class: 'risk-explain' },
                el('p', { class: 'risk-explain-title', text: 'What drove it' }),
                drivers)),
        el('p', { class: 'risk-note' },
            'A Random Forest trained on 400 synthetic invoices. Each tree\'s path is followed from the base rate to the score, and every split\'s change is credited to its feature. The status above is the decision; this score is advice. ',
            el('a', { href: '#/rules', text: 'Read the model card' })));
}

// ---------- Details and actions ----------

function details(result) {
    const f = result.features || {};
    const t = result.timings_ms;
    const items = [
        ['Missing required', typeof f.missing_fields === 'number' ? `${f.missing_fields} of 2` : '–'],
        ['Missing optional', typeof f.missing_optional_fields === 'number' ? `${f.missing_optional_fields} of ${OPTIONAL_FIELD_COUNT}` : '–'],
        ['Nesting depth', typeof f.nesting_depth === 'number' ? plural(f.nesting_depth, 'level') : '–'],
        ['File size', formatBytes(f.xml_size)],
        ['Server time', formatMs(result.processing_ms), t ? `parse ${formatMs(t.parse)}, rules ${formatMs(t.validate)}, score ${formatMs(t.score)}, lines ${formatMs(t.locate)}` : null],
    ];
    return el('div', { class: 'metrics-subgrid' }, items.map(([label, value, tip]) => el('div', { class: 'sub-metric', 'data-tip': tip || null },
        el('span', { class: 'sub-label', text: label }),
        el('span', { class: 'sub-value', text: value }))));
}

function downloadReport(result) {
    const report = {
        generated_at: new Date().toISOString(),
        tool: 'SupplyTrace',
        note: 'The status comes from deterministic rules. The risk score is experimental: a Random Forest trained on synthetic invoices.',
        result,
    };
    const base = String(result.filename || 'invoice').replace(/\.xml$/i, '').replace(/[^\w.-]+/g, '_').slice(0, 60);
    downloadFile(`supplytrace-${base}-${fileStamp()}.json`, [JSON.stringify(report, null, 2)], 'application/json');
    toast('Report downloaded as JSON.');
}

// Renders a result into `container`. Options: onEdit(text, name), onAnother(),
// and pipeline: 'live' (a strip that follows the run on screen) or 'static'
// (this result's own run, settled). Returns the XML view, so callers can reveal a line.
export function renderResult(container, result, text, { onEdit, onAnother, pipeline } = {}) {
    const failed = (result.checks || []).filter(c => c.state === 'broken').length;
    const { panel, view } = xmlPanel(result.filename, text, marksFor(result), { onEdit, size: result.features?.xml_size });

    const actions = el('div', { class: 'result-actions' },
        el('button', { type: 'button', class: 'btn btn-secondary', on: { click: () => downloadReport(result) } }, icon('download'), 'Download report'),
        onAnother ? el('button', { type: 'button', class: 'btn btn-outline', on: { click: onAnother } }, icon('rotate'), 'Check another') : null);

    const logged = result.logged === false
        ? el('p', { class: 'inline-warning' }, icon('triangle'), 'The check worked, but the server could not write it to the audit log.')
        : null;

    clear(container).append(...[
        pipeline ? pipelineStrip(pipeline === 'live' ? { live: true } : { result }) : null,
        verdict(result, failed),
        el('p', { class: 'result-summary', text: summaryFor(result, failed) }),
        logged,
        checklist(result),
        panel,
        riskBlock(result),
        details(result),
        actions,
    ].filter(Boolean));

    container.querySelector('.checklist').addEventListener('click', event => {
        const row = event.target.closest('button[data-line]');
        if (!row) return;
        container.querySelectorAll('.check-row[aria-current]').forEach(r => r.removeAttribute('aria-current'));
        row.setAttribute('aria-current', 'true');
        revealLine(view, Number(row.dataset.line), { page: true, flash: true });
        announce(`Line ${row.dataset.line} highlighted in the XML.`);
    });

    // Bring the first problem into view inside the code box (a clean file stays at the top).
    const first = (result.checks || []).find(c => c.state === 'broken' && c.line);
    if (first) requestAnimationFrame(() => revealLine(view, first.line));
    return view;
}

// The banner for a file that was not checked. A refused file (4xx) is the
// file's problem and gets the danger tone; a network or server failure is not,
// so it gets the warning tone and says so.
function errorBanner(name, error, where) {
    const unreachable = error.status === 0;
    const serverSide = unreachable || error.status >= 500;
    let headline = 'File could not be read';
    if (unreachable) headline = "Couldn't reach the server";
    else if (serverSide) headline = "The server couldn't finish the check";
    else if (error.status === 413) headline = 'File is too large';
    return el('div', { class: `verdict ${serverSide ? 'verdict-WARN' : 'verdict-ERROR'}`, role: 'alert' },
        el('span', { class: 'verdict-icon', 'aria-hidden': 'true' }, icon(serverSide ? 'refresh' : 'slash')),
        el('div', { class: 'verdict-main' },
            el('h3', { class: 'verdict-title' },
                el('span', { class: 'verdict-status', text: unreachable ? 'NOT REACHED' : 'NOT CHECKED' }),
                el('span', { class: 'verdict-headline', text: headline })),
            el('p', { class: 'verdict-meta' },
                el('span', { class: 'mono verdict-file', text: name }),
                el('span', {}, error.message, where ? el('strong', { class: 'mono', text: ` ${where}` }) : null))));
}

// A file that could not be checked: the reason, where the XML breaks (when the
// parser said), and a way forward. Options: onRetry, onEdit(text, name, problem)
// where problem is { line, column, reason }, onAnother, and pipeline: 'live'.
export function renderError(container, { name, text, error, onRetry, onEdit, onAnother, pipeline }) {
    const problem = error.body?.line ? { line: error.body.line, column: error.body.column, reason: error.body.reason } : null;
    const where = problem
        ? `Line ${problem.line}, column ${problem.column}${problem.reason ? `: ${problem.reason}` : ''}.`
        : null;

    const parts = [pipeline === 'live' ? pipelineStrip({ live: true }) : null, errorBanner(name, error, where)];
    if (text && problem) {
        const marks = [{ line: problem.line, kind: 'error', badge: '!', title: where }];
        const { panel, view } = xmlPanel(name, text, marks, { onEdit: onEdit && (() => onEdit(text, name, problem)) });
        parts.push(panel);
        requestAnimationFrame(() => revealLine(view, problem.line));
    }
    parts.push(el('div', { class: 'result-actions' },
        onRetry ? el('button', { type: 'button', class: 'btn btn-primary', on: { click: onRetry } }, icon('refresh'), 'Try again') : null,
        onEdit && text ? el('button', { type: 'button', class: 'btn btn-secondary', on: { click: () => onEdit(text, name, problem) } }, icon('edit'), 'Fix in sandbox') : null,
        onAnother ? el('button', { type: 'button', class: 'btn btn-outline', on: { click: onAnother } }, icon('rotate'), 'Check another') : null));
    clear(container).append(...parts.filter(Boolean));
}
