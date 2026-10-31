// The "How it works" pipeline. One run of a check drives two views of it: the
// panel at the top of the page, and a compact strip inside the Payload
// Inspector (on the loading placeholder, then at the top of the result), so the
// run stays visible wherever the visitor is looking. Parse is active while the
// file is on its way and being read; when the server answers, the steps settle
// in order with the time the server measured for each stage, and Log says
// whether the audit line was written. A failure stops it at the step that failed.

import { el, icon, delay, formatMs, prefersReducedMotion, statusText } from './ui.js';

const STEPS = [
    { name: 'parse', label: 'Parse', icon: 'code' },
    { name: 'validate', label: 'Validate', icon: 'check-square' },
    { name: 'score', label: 'Score', icon: 'activity' },
    { name: 'log', label: 'Log', icon: 'database' },
];
const IDLE_TEXT = 'Pick a sample to watch it run.';

let panel;
let strips = []; // compact strips that follow the live run
const state = Object.fromEntries(STEPS.map(({ name }) => [name, ['idle', '', '']]));
let current = 0; // id of the run on screen; older runs may not touch it

export function initPipeline() {
    panel = { root: document.getElementById('pipeline'), status: document.getElementById('pipeline-status') };
    document.getElementById('inspector-loading').prepend(pipelineStrip({ live: true }));
}

// What each step ends as for a finished result: [name, state, time, title].
function settledSteps(result) {
    const t = result.timings_ms || {};
    const scored = typeof result.prediction?.risk_score === 'number';
    return [
        ['parse', 'done', formatMs(t.parse), 'Parsed with defusedxml and flattened'],
        ['validate', 'done', formatMs((t.validate || 0) + (t.locate || 0)),
            `Rules ${formatMs(t.validate)}, locating lines ${formatMs(t.locate)}`],
        scored
            ? ['score', 'done', formatMs(t.score), 'Features extracted and scored by the Random Forest']
            : ['score', 'warn', 'no model', 'The server has no trained model, so there is no risk score'],
        result.logged === false
            ? ['log', 'warn', 'not written', 'The audit log could not be written (the check itself is fine)']
            : ['log', 'done', 'written', 'One JSON line appended to the audit log'],
    ];
}

function paint(root, name, [stepState, time, title]) {
    const step = root.querySelector(`[data-step="${name}"]`);
    step.dataset.state = stepState;
    step.querySelector('[data-time]').textContent = time;
    if (title) step.title = title;
    else step.removeAttribute('title');
}

function setStep(name, stepState, time = '', title = '') {
    state[name] = [stepState, time, title];
    strips = strips.filter(strip => strip.isConnected);
    for (const root of [panel.root, ...strips]) paint(root, name, state[name]);
}

// A compact strip: Parse 0.6 ms, Validate 0.8 ms, Score 71 ms, Log written.
// live: it follows the current run; result: it shows that result's run, settled.
export function pipelineStrip({ live = false, result = null } = {}) {
    const strip = el('ol', { class: 'pipeline-mini', 'aria-label': 'Pipeline run' },
        STEPS.map(step => el('li', { class: 'mini-step', 'data-step': step.name, 'data-state': 'idle' },
            el('span', { class: 'mini-dot', 'aria-hidden': 'true' }, icon(step.icon)),
            el('span', { class: 'mini-text' },
                el('span', { class: 'mini-name', text: step.label }),
                el('span', { class: 'mini-time', 'data-time': '' })))));
    if (live) {
        strips.push(strip);
        STEPS.forEach(({ name }) => paint(strip, name, state[name]));
    } else if (result) {
        settledSteps(result).forEach(([name, ...rest]) => paint(strip, name, rest));
    }
    return strip;
}

export function pipelineStart(filename) {
    current += 1;
    STEPS.forEach(({ name }) => setStep(name, 'idle'));
    setStep('parse', 'active');
    panel.root.dataset.state = 'running';
    panel.status.textContent = `Checking ${filename}…`;
    return current;
}

export async function pipelineDone(run, result) {
    if (run !== current) return;
    const pause = prefersReducedMotion() ? 0 : 150;
    for (const [name, stepState, time, title] of settledSteps(result)) {
        setStep(name, 'active');
        await delay(pause);
        if (run !== current) return;
        setStep(name, stepState, time, title);
    }
    panel.root.dataset.state = 'done';
    panel.status.textContent = `${statusText(result.status)} · ${formatMs(result.processing_ms)} on the server`;
}

export function pipelineFail(run, error) {
    if (run !== current) return;
    let label = 'refused';
    if (error.status === 0) label = 'offline';
    else if (error.status === 413) label = 'too large';
    else if (error.status >= 500) label = 'server error';
    else if (error.body?.line) label = `line ${error.body.line}`;
    setStep('parse', 'failed', label, error.message);
    STEPS.slice(1).forEach(({ name }) => setStep(name, 'skipped'));
    panel.root.dataset.state = 'failed';
    panel.status.textContent = error.status > 0 && error.status < 500
        ? 'Stopped: the file was refused before any rule ran.'
        : 'Stopped: the server could not finish the check.';
}

export function pipelineReset() {
    current += 1;
    STEPS.forEach(({ name }) => setStep(name, 'idle'));
    delete panel.root.dataset.state;
    panel.status.textContent = IDLE_TEXT;
}
