// The Payload Inspector: pick a sample, upload a file or edit XML in the
// sandbox, then read the result in place of the input, as in the original
// dashboard. One check runs at a time, and the compact pipeline strip at the
// top of the inspector shows it running.

import { getJson, getText, postFiles, precheckFile } from './api.js';
import {
    el, clear, icon, statusText, announce, toast, delay, setupTabs, setupDropzone,
    prefersReducedMotion, setLoading,
} from './ui.js';
import { renderResult, renderError } from './result.js';
import { pipelineStart, pipelineDone, pipelineFail, pipelineReset } from './pipeline.js';

const MIN_LOADING_MS = 300; // long enough to see the pipeline start, short enough not to feel slow
const SANDBOX_NAME = 'sandbox_invoice.xml';
const HINT_DEFAULT = 'Each sample is a synthetic UBL-style invoice. The dot shows the status it is built to get.';

let dom;
let tabs;
let hooks = { onBatchFiles: () => {}, onChecked: () => {} };
let samples = [];
let samplesLoading = null;
let busy = false;
let editorName = SANDBOX_NAME;
let editorProblem = null; // { line, column, reason } shown in the sandbox until the next edit

const sentence = text => (/[.!?]$/.test(text) ? text : `${text}.`);
const smooth = () => (prefersReducedMotion() ? 'auto' : 'smooth');

export function initCheck(options) {
    hooks = { ...hooks, ...options };
    const $ = id => document.getElementById(id);
    dom = {
        inspector: $('inspector'),
        chips: $('sample-chips'),
        hint: $('sample-hint'),
        error: $('inspector-error'),
        paneUpload: $('pane-upload'),
        paneSandbox: $('pane-sandbox'),
        loading: $('inspector-loading'),
        result: $('result'),
        fileInput: $('file-input'),
        editor: $('xml-editor'),
        gutter: $('editor-gutter'),
        band: $('editor-band'),
        note: $('editor-note'),
        filename: $('editor-filename'),
        checkButton: $('analyze-sandbox-btn'),
        controls: [$('browse-btn'), $('analyze-sandbox-btn'), $('load-template-btn'), $('tab-upload'), $('tab-sandbox')],
    };

    tabs = setupTabs(dom.inspector.querySelector('[role="tablist"]'), () => {
        hideError();
        showInput();
    });
    $('browse-btn').addEventListener('click', () => dom.fileInput.click());
    setupDropzone($('drop-zone'), handleFiles, { input: dom.fileInput, isBusy: () => busy });
    $('load-template-btn').addEventListener('click', loadTemplate);
    dom.checkButton.addEventListener('click', checkSandbox);

    dom.editor.addEventListener('input', () => {
        clearEditorProblem();
        updateGutter();
        // Edited content is the visitor's own file, not the sample it started from.
        setEditorName(SANDBOX_NAME);
    });
    dom.editor.addEventListener('scroll', () => {
        dom.gutter.scrollTop = dom.editor.scrollTop;
        placeBand();
    });
    dom.editor.addEventListener('keydown', event => {
        if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
            event.preventDefault();
            checkSandbox();
        }
    });

    showInput();
    samplesLoading = loadSamples();
}

// ---------- View state: input pane, loading, or result ----------

function showInput() {
    const tab = tabs.selected();
    dom.paneUpload.hidden = tab !== 'tab-upload';
    dom.paneSandbox.hidden = tab !== 'tab-sandbox';
    dom.loading.hidden = true;
    dom.result.hidden = true;
}

function showLoading() {
    dom.paneUpload.hidden = true;
    dom.paneSandbox.hidden = true;
    dom.result.hidden = true;
    dom.loading.hidden = false;
    revealRun();
}

function showResultPane() {
    dom.paneUpload.hidden = true;
    dom.paneSandbox.hidden = true;
    dom.loading.hidden = true;
    dom.result.hidden = false;
    dom.result.classList.remove('fade-in');
    void dom.result.offsetWidth; // restart the reveal animation
    dom.result.classList.add('fade-in');
}

function setBusy(value) {
    busy = value;
    dom.controls.forEach(control => { control.disabled = value; });
    dom.chips.querySelectorAll('button').forEach(chip => { chip.disabled = value; });
    dom.inspector.classList.toggle('is-busy', value);
}

function showError(message, action) {
    clear(dom.error).append(icon('triangle'), el('span', { text: message }));
    if (action) dom.error.append(action);
    dom.error.hidden = false;
}

function hideError() {
    dom.error.hidden = true;
    clear(dom.error);
}

function bringIntoView(node) {
    const top = node.getBoundingClientRect().top;
    if (top < 70 || top > window.innerHeight * 0.72) {
        window.scrollTo({ top: window.scrollY + top - 16, behavior: smooth() });
    }
}

// When a check starts, scroll so the run can be watched: the inspector's header
// and chips at the top, the pipeline strip and then the result below them. If
// the header and chips would push the run too far down, the run goes first.
function revealRun() {
    const viewport = window.innerHeight;
    const runTop = dom.loading.getBoundingClientRect().top;
    if (runTop >= 70 && runTop <= viewport * 0.6) return;
    const inspectorTop = dom.inspector.getBoundingClientRect().top;
    const fromInspector = runTop - inspectorTop;
    const offset = fromInspector + 16 <= viewport * 0.6 ? inspectorTop - 16 : runTop - viewport * 0.2;
    window.scrollTo({ top: Math.max(0, window.scrollY + offset), behavior: smooth() });
}

// ---------- Samples ----------

async function loadSamples() {
    try {
        samples = await getJson('/api/samples');
        renderSamples();
    } catch (error) {
        samples = [];
        clear(dom.chips).append(el('span', { class: 'sample-placeholder' },
            `Samples could not be loaded. ${error.message} `,
            el('button', { type: 'button', class: 'btn-text', text: 'Retry', on: { click: () => { samplesLoading = loadSamples(); } } })));
    }
    dom.chips.removeAttribute('aria-busy');
}

const EXPECTED_TEXT = { VALID: 'Built to pass.', INVALID: 'Built to fail.', REQUIRES_REVIEW: 'Built to need a review.' };

function describe(sample) {
    return `${sample.label}: ${sample.description}. ${EXPECTED_TEXT[sample.expected] || ''}`.trim();
}

function renderSamples() {
    clear(dom.chips);
    for (const sample of samples) {
        const chip = el('button', {
            type: 'button',
            class: 'sample-chip',
            'data-sample': sample.id,
            'aria-pressed': 'false',
            'aria-describedby': 'sample-hint',
            title: describe(sample),
            disabled: busy,
            on: {
                click: () => runSample(sample),
                mouseenter: () => { dom.hint.textContent = describe(sample); },
                focus: () => { dom.hint.textContent = describe(sample); },
                mouseleave: restoreHint,
                blur: restoreHint,
            },
        },
        el('span', { class: `sample-dot dot-${sample.expected}`, 'aria-hidden': 'true' }),
        sample.label);
        dom.chips.append(chip);
    }
}

function restoreHint() {
    const active = samples.find(s => dom.chips.querySelector(`[data-sample="${CSS.escape(s.id)}"][aria-pressed="true"]`));
    dom.hint.textContent = active ? describe(active) : HINT_DEFAULT;
}

function markSample(id) {
    dom.chips.querySelectorAll('.sample-chip').forEach(chip => {
        chip.setAttribute('aria-pressed', String(chip.dataset.sample === id));
    });
    restoreHint();
}

export async function getSamples() {
    await samplesLoading;
    if (!samples.length) {
        samplesLoading = loadSamples();
        await samplesLoading;
    }
    if (!samples.length) throw new Error('The sample invoices could not be loaded. Please try again.');
    return samples;
}

export async function runSampleById(id) {
    const list = await getSamples().catch(() => []);
    const sample = list.find(s => s.id === id);
    if (sample) runSample(sample);
}

async function runSample(sample) {
    if (busy) return;
    hideError();
    markSample(sample.id);
    setBusy(true);
    const run = pipelineStart(sample.filename);
    showLoading();
    let text;
    try {
        text = await getText(`/api/samples/${encodeURIComponent(sample.id)}`);
    } catch (error) {
        setBusy(false);
        pipelineFail(run, error);
        showResultPane();
        renderError(dom.result, {
            name: sample.filename, error, pipeline: 'live', onRetry: () => runSample(sample), onAnother: checkAnother,
        });
        return;
    }
    // Like the original dashboard, the sample also lands in the sandbox editor.
    setEditor(text, sample.filename);
    const file = new File([text], sample.filename, { type: 'text/xml' });
    const result = await check({ name: sample.filename, text, file, run });
    if (result) history.replaceState(null, '', `#/check?sample=${encodeURIComponent(sample.id)}`);
}

// ---------- Your own file ----------

function handleFiles(files) {
    if (busy || !files.length) return;
    hideError();
    if (files.length > 1) {
        showInput();
        showError(`That's ${files.length} files.`, el('button', {
            type: 'button', class: 'btn-text', text: 'Check them as a batch',
            on: { click: () => { hideError(); hooks.onBatchFiles(files); } },
        }));
        return;
    }
    const [file] = files;
    const problem = precheckFile(file);
    if (problem) {
        showInput(); // a rejected file must not leave the previous result under the error
        const next = /\.xml/.test(problem) ? ' Only XML invoices (UBL) are accepted. Try a sample above, or download one to edit.' : '';
        showError(`${file.name}: ${sentence(problem)}${next}`);
        return;
    }
    (async () => {
        markSample(null);
        const text = await file.text();
        if (await check({ name: file.name, text, file })) history.replaceState(null, '', '#/check');
    })();
}

function checkSandbox() {
    if (busy) return;
    hideError();
    const text = dom.editor.value;
    if (!text.trim()) {
        showError('The sandbox editor is empty. Paste some XML or load the valid template.');
        dom.editor.focus();
        return;
    }
    const file = new File([text], editorName, { type: 'text/xml' });
    const problem = precheckFile(file);
    if (problem) {
        showInput();
        showError(sentence(problem));
        return;
    }
    markSample(null);
    check({ name: editorName, text, file }).then(result => {
        if (result) history.replaceState(null, '', '#/check');
    });
}

async function loadTemplate() {
    if (busy) return;
    const button = document.getElementById('load-template-btn');
    setLoading(button, true);
    try {
        setEditor(await getText('/api/samples/valid'), 'valid_invoice.xml');
        dom.editor.focus();
        toast('Valid template loaded into the sandbox.');
    } catch (error) {
        showError(error.message);
    } finally {
        setLoading(button, false);
    }
}

// ---------- Sandbox editor ----------

function setEditorName(name) {
    editorName = name;
    dom.filename.textContent = name;
}

function setEditor(text, name) {
    dom.editor.value = text;
    setEditorName(name);
    clearEditorProblem();
    updateGutter();
}

function updateGutter() {
    const lines = dom.editor.value.split(/\r\n|\r|\n/).length;
    if (Number(dom.gutter.dataset.lines) !== lines) {
        dom.gutter.dataset.lines = String(lines);
        dom.gutter.replaceChildren(...Array.from({ length: lines }, (_, i) => el('span', { text: i + 1 })));
    }
    dom.gutter.querySelector('.is-error')?.classList.remove('is-error');
    if (editorProblem) dom.gutter.children[editorProblem.line - 1]?.classList.add('is-error');
    dom.gutter.scrollTop = dom.editor.scrollTop;
}

function lineHeight() {
    return parseFloat(getComputedStyle(dom.editor).lineHeight) || 20;
}

// The band behind the textarea that marks the line the parser stopped at.
function placeBand() {
    if (!editorProblem) return;
    const padTop = parseFloat(getComputedStyle(dom.editor).paddingTop) || 0;
    dom.band.style.transform = `translateY(${padTop + (editorProblem.line - 1) * lineHeight() - dom.editor.scrollTop}px)`;
}

function showEditorProblem(problem) {
    editorProblem = problem;
    clear(dom.note).append(icon('triangle'), el('span', {},
        el('strong', { text: `Line ${problem.line}, column ${problem.column}` }),
        problem.reason ? `: ${problem.reason}. ` : '. ',
        'The caret is on that line; fix it and check again.'));
    dom.note.hidden = false;
    dom.band.hidden = false;
    updateGutter();
    placeBand();
}

function clearEditorProblem() {
    if (!editorProblem) return;
    editorProblem = null;
    dom.note.hidden = true;
    dom.band.hidden = true;
    dom.gutter.querySelector('.is-error')?.classList.remove('is-error');
}

// Opens text in the sandbox. With a problem ({ line, column, reason }, from a
// parse error) the caret goes to that line, and the line and the reason stay
// marked until the next edit.
export function editInSandbox(text, name, problem = null) {
    setEditor(text, name || SANDBOX_NAME);
    tabs.select('tab-sandbox');
    hideError();
    showInput();
    const line = problem?.line || 1;
    const offset = text.split('\n').slice(0, line - 1).reduce((sum, l) => sum + l.length + 1, 0);
    dom.editor.focus({ preventScroll: true });
    dom.editor.setSelectionRange(offset, offset);
    dom.editor.scrollTop = Math.max(0, (line - 4) * lineHeight());
    if (problem) showEditorProblem(problem);
    bringIntoView(dom.paneSandbox);
}

function checkAnother() {
    hideError();
    markSample(null);
    pipelineReset();
    showInput();
    bringIntoView(dom.inspector);
    dom.inspector.querySelector('[role="tab"][aria-selected="true"]').focus({ preventScroll: true });
}

// ---------- Checking ----------

// Sends one file, shows the result or a recoverable error. Returns the result, or null.
async function check({ name, text, file, run = null }) {
    setBusy(true);
    const id = run ?? pipelineStart(name);
    showLoading();
    try {
        const [result] = await Promise.all([postFiles('/api/analyze', 'file', [file]), delay(MIN_LOADING_MS)]);
        showResultPane();
        renderResult(dom.result, result, text, { onEdit: editInSandbox, onAnother: checkAnother, pipeline: 'live' });
        bringIntoView(dom.result);
        pipelineDone(id, result);
        announce(`${result.filename}: ${statusText(result.status)}. ${result.errors.join('. ')}`);
        hooks.onChecked(result);
        return result;
    } catch (error) {
        pipelineFail(id, error);
        showResultPane();
        // Retrying only helps when the server or the network failed, not when the file is bad.
        const retryable = !(error.status > 0 && error.status < 500);
        renderError(dom.result, {
            name, text, error,
            pipeline: 'live',
            onRetry: retryable ? () => check({ name, text, file }) : null,
            onEdit: editInSandbox,
            onAnother: checkAnother,
        });
        announce(`${name} could not be checked. ${error.message}`);
        bringIntoView(dom.result);
        return null;
    } finally {
        setBusy(false);
    }
}
