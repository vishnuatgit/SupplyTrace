// The "Rules and model" view. Everything on it comes from /api/rules and
// /api/model, so the page can't drift from the code: the rule texts live in
// src/validation/rules.py and every metric is computed by the server.

import { getJson } from './api.js';
import { el, clear, icon, badge, formatNumber } from './ui.js';
import { barList, confusionMatrix } from './charts.js';
import { highlightXml } from './xml-view.js';

let dom;
let loaded = false;
let loading = false;

const pct = share => `${Math.round(share * 100)}%`;
const metric = value => (value === null || value === undefined ? '–' : value.toFixed(2));

function listText(items, joiner = 'or') {
    return items.length > 1 ? `${items.slice(0, -1).join(', ')} ${joiner} ${items[items.length - 1]}` : items.join('');
}

export async function showReference() {
    dom = dom || { output: document.getElementById('rules-output') };
    if (loaded || loading) return;
    loading = true;
    try {
        const [rules, card] = await Promise.all([getJson('/api/rules'), getJson('/api/model')]);
        clear(dom.output).append(rulesSection(rules), modelSection(card));
        loaded = true;
    } catch (error) {
        clear(dom.output).append(el('div', { class: 'error-card glass-panel', role: 'alert' },
            el('span', { class: 'error-icon', 'aria-hidden': 'true' }, icon('x-circle')),
            el('div', {},
                el('p', { class: 'error-title', text: 'The rules and model card could not be loaded' }),
                el('p', { text: error.message }),
                el('div', { class: 'error-actions' },
                    el('button', { type: 'button', class: 'btn btn-secondary', on: { click: () => { showReference(); } } }, icon('refresh'), 'Try again')))));
    } finally {
        loading = false;
    }
}

// ---------- Rules ----------

function rulesSection(data) {
    const cards = data.rules.map((rule, index) => el('li', { class: `rule-card rule-${rule.outcome}` },
        el('div', { class: 'rule-top' },
            el('span', { class: 'rule-num', 'aria-hidden': 'true', text: index + 1 }),
            el('h3', { text: rule.title }),
            badge(rule.outcome)),
        el('p', { class: 'rule-summary', text: rule.summary }),
        el('p', { class: 'rule-message' }, el('span', { class: 'sub-label', text: 'Message ' }), el('code', { text: rule.message })),
        el('div', { class: 'rule-example' },
            el('p', { class: 'sub-label', text: 'A file that breaks it' }),
            el('pre', { class: 'example' }, highlightXml(rule.example)))));

    const idTags = data.id_tags.filter(tag => tag !== 'ID');
    const chips = tags => el('span', { class: 'tag-chips' }, tags.map(tag => el('code', { class: 'tag-chip', text: `<${tag}>` })));
    // Where the fields are looked for completes the grid as a sixth card.
    const whereFound = el('section', { class: 'rule-card where-found', 'aria-labelledby': 'where-found-title' },
        el('div', { class: 'rule-top' },
            el('span', { class: 'rule-num', 'aria-hidden': 'true' }, icon('search')),
            el('h3', { id: 'where-found-title', text: 'Where the ID and the amount are found' })),
        el('p', {}, el('strong', { text: 'Transaction ID: ' }), 'the first non-empty ', chips(idTags), ' at any depth, or a plain ', el('code', { class: 'tag-chip', text: '<ID>' }),
            ` within ${data.generic_id_max_depth} levels of the root, so a nested bank-account ID is never taken for it.`),
        el('p', {}, el('strong', { text: 'Amount: ' }), 'the first non-empty ', chips(data.amount_tags), `. Namespaces are ignored, and the amount must be a plain decimal number. Above ${formatNumber(data.review_threshold)} a person has to review it.`));
    return el('section', { class: 'glass-panel reference-panel', 'aria-labelledby': 'rules-heading' },
        el('div', { class: 'panel-header' },
            el('h2', { id: 'rules-heading', text: 'Validation rules' }),
            el('span', { class: 'section-meta', text: `${data.rules.length} rules, applied in order` })),
        el('p', { class: 'panel-lede' }, `Breaking any of the first ${data.rules.length - 1} makes a file invalid. The last one is only checked when the others pass. Each example is a complete document, and the test suite runs every one through the real pipeline.`),
        el('div', { class: 'rule-grid' }, el('ol', { class: 'rule-list' }, cards), whereFound));
}

// ---------- Model card ----------

function modelSection(card) {
    const parts = [
        el('div', { class: 'panel-header' },
            el('h2', { id: 'model', text: 'Risk model card' }),
            el('span', { class: 'experimental-tag', text: 'Experimental' })),
        el('p', { class: 'callout callout-warning' },
            icon('triangle'),
            el('span', {}, el('strong', { text: 'Trained on synthetic invoices. ' }),
                'The labels are simulated outcomes, so the model is here to show a small ML component end to end, not to predict real supplier failures. The status always comes from the rules.')),
        factsList(card),
    ];
    if (card.trained) {
        parts.push(el('div', { class: 'model-grid' }, featuresBlock(card), card.holdout ? holdoutBlock(card) : null));
        if (card.holdout) parts.push(readingCallout(card));
    }
    parts.push(
        el('h3', { text: 'Limitations' }),
        el('ul', { class: 'plain-list' },
            el('li', { text: 'Synthetic data and simulated outcomes: the scores say nothing about real suppliers.' }),
            el('li', { text: 'The labels follow from the same signals the model sees, so it can only learn the simulation back.' }),
            el('li', { text: 'Retrained from scratch at every startup; there is no saved, versioned model.' }),
            el('li', { text: 'The scores are not calibrated: a higher score means riskier, not a measured probability of failure.' })),
    );
    return el('section', { class: 'glass-panel reference-panel', 'aria-labelledby': 'model' }, parts);
}

function factsList(card) {
    const data = card.synthetic_data;
    const params = Object.entries(card.params).map(([key, value]) => `${key}=${value === null ? 'None' : value}`).join(', ');
    const cases = Object.entries(data.case_weights).filter(([name]) => name !== 'valid');
    const caseNames = {
        missing_id: 'missing ID', missing_amount: 'missing amount', bad_amount: 'non-numeric amount',
        negative_amount: 'negative amount', high_value: 'above the review limit',
    };
    const sameShare = cases.every(([, weight]) => weight === cases[0][1]);
    const caseText = sameShare
        ? `${pct(data.case_weights.valid)} valid; ${pct(cases[0][1])} each ${listText(cases.map(([name]) => caseNames[name] || name), 'and')}.`
        : cases.map(([name, weight]) => `${pct(weight)} ${caseNames[name] || name}`).join(', ');

    const rows = [
        ['Predicts', `The probability that a file fails straight-through processing, a simulated outcome. Scores above ${card.high_risk_threshold}% are flagged HIGH.`],
        ['Model', [el('code', { text: `${card.estimator}(${params})` }), ' from scikit-learn, trained by the server at startup from the batch results.']],
        ['Training data', card.training
            ? `${formatNumber(card.training.rows)} synthetic invoices from the pipeline's own results, ${formatNumber(card.training.failed)} of them labelled failed. Generated with seed ${data.seed}: ${caseText} ${pct(data.sparse_share)} may leave optional fields out, and ${pct(data.envelope_share)} are wrapped in a transport envelope.`
            : 'No batch results on this server, so the model is not trained and no risk scores are shown.'],
        ['Labels', `A file that breaks a rule or needs review always fails. Any other file fails with probability ${pct(data.failure_base)} + ${pct(data.failure_per_missing_optional)} per missing optional field + ${pct(data.failure_large_amount)} if the amount is ${formatNumber(data.large_amount)} or more + ${pct(data.failure_envelope)} if wrapped, capped at ${pct(data.failure_cap)}.`],
        ['Explanations', 'Each score is split into the base rate plus one contribution per feature, by following every tree from its root to the file\'s leaf and crediting each split\'s change to its feature.'],
    ];
    return el('dl', { class: 'card-facts' }, rows.map(([label, value]) => el('div', {}, el('dt', { text: label }), el('dd', {}, value))));
}

function featuresBlock(card) {
    const features = [...card.features].sort((a, b) => (b.importance || 0) - (a.importance || 0));
    const chart = el('div', { class: 'chart-slot' });
    barList(chart, features.map(f => ({
        label: f.label, value: f.importance || 0, display: `${((f.importance || 0) * 100).toFixed(1)}%`,
    })), { max: Math.max(...features.map(f => f.importance || 0)) });
    return el('figure', { class: 'chart-wrapper' },
        el('figcaption', { class: 'chart-title', text: 'Feature importance' }),
        chart,
        el('details', { class: 'feature-details' },
            el('summary', {}, 'What each feature means'),
            el('dl', {}, card.features.map(f => el('div', {}, el('dt', {}, el('code', { text: f.name })), el('dd', { text: f.description }))))),
        el('p', { class: 'chart-note', text: 'Mean decrease in impurity: how much each feature is used to split failed from processed files in this training data. File size is shown on results but deliberately not used.' }));
}

function holdoutBlock(card) {
    const h = card.holdout;
    const m = h.model;
    const b = h.rules_baseline;
    const rows = [
        ['Accuracy', m.accuracy, b.accuracy],
        ['Precision (failed)', m.precision, b.precision],
        ['Recall (failed)', m.recall, b.recall],
        ['ROC AUC', m.roc_auc, b.roc_auc],
    ].map(([name, model, rules]) => el('tr', {},
        el('th', { scope: 'row', text: name }),
        el('td', { class: 'num mono', text: metric(model) }),
        el('td', { class: 'num mono', text: metric(rules) })));

    return el('figure', { class: 'chart-wrapper holdout' },
        el('figcaption', { class: 'chart-title', text: 'Holdout evaluation' }),
        el('p', { class: 'chart-note', text: `A fresh model trained on ${h.train_rows} files and tested on the other ${h.test_rows} (${h.test_failed} failed), stratified split with seed ${card.split_seed}. Computed by the server at startup; none of these numbers are typed in. "Rules only" says a file fails exactly when its status is not VALID.` }),
        el('div', { class: 'table-scroll' }, el('table', { class: 'data-table metrics-table' },
            el('caption', { class: 'visually-hidden', text: 'Holdout metrics, model against rules only' }),
            el('thead', {}, el('tr', {},
                el('th', { scope: 'col', text: 'Metric' }),
                el('th', { scope: 'col', class: 'num', text: 'Model' }),
                el('th', { scope: 'col', class: 'num', text: 'Rules only' }))),
            el('tbody', {}, rows))),
        el('div', { class: 'matrices' }, confusionMatrix('Model', m), confusionMatrix('Rules only', b)));
}

function readingCallout(card) {
    const h = card.holdout;
    const v = h.valid_only;
    let reading = h.same_calls_as_rules
        ? `At the ${card.high_risk_threshold}% threshold the model makes the same call as the rules on every held-out file, so accuracy, precision and recall are identical. `
        : `At the ${card.high_risk_threshold}% threshold the model and the rules disagree on some held-out files. `;
    if (v.roc_auc !== null) {
        reading += `Its only extra information is how it orders the files the rules pass: ROC AUC ${metric(v.roc_auc)} on ${v.rows} valid files, of which ${v.failed} failed`;
        reading += v.failed < 10 ? ', too few failures to rely on. ' : '. ';
    }
    reading += 'And since the labels come from the same signals the model sees, these numbers show that it recovers the simulation, not that it predicts real outcomes.';
    return el('p', { class: 'callout' }, icon('info'), el('span', {}, el('strong', { text: 'What this shows. ' }), reading));
}
