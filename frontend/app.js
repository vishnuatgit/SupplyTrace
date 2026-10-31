document.addEventListener('DOMContentLoaded', () => {
    // Keep in step with SUPPLYTRACE_MAX_UPLOAD_BYTES on the server (default 1 MB).
    const MAX_UPLOAD_BYTES = 1000000;
    const MAX_PREVIEW_CHARS = 20000;
    const MAX_SESSION_ITEMS = 50;
    const MAX_FEED_SESSION_ITEMS = 15;
    const MIN_SPINNER_MS = 250; // avoids a flash of the spinner on fast responses
    const SESSION_KEY = 'supplytrace.session.v1';
    const OPTIONAL_FIELD_COUNT = 4;

    // Tab Selectors
    const tabUploadBtn = document.getElementById('tab-upload-btn');
    const tabSandboxBtn = document.getElementById('tab-sandbox-btn');
    const paneUpload = document.getElementById('pane-upload');
    const paneSandbox = document.getElementById('pane-sandbox');

    // UI Elements
    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('file-input');
    const browseBtn = document.getElementById('browse-btn');
    const loading = document.getElementById('loading');
    const results = document.getElementById('results');
    const resetBtn = document.getElementById('reset-btn');
    const xmlEditor = document.getElementById('xml-editor');
    const editorFilename = document.getElementById('editor-filename');
    const loadTemplateBtn = document.getElementById('load-template-btn');
    const analyzeSandboxBtn = document.getElementById('analyze-sandbox-btn');
    const sampleChips = document.getElementById('sample-chips');
    const inspectorError = document.getElementById('inspector-error');

    // Results UI Elements
    const elXml = document.getElementById('res-xml');
    const elXmlMeta = document.getElementById('res-xml-meta');
    const editXmlBtn = document.getElementById('edit-xml-btn');
    const elFilename = document.getElementById('res-filename');
    const elStatus = document.getElementById('res-status');
    const elSummary = document.getElementById('res-summary');
    const elRiskScore = document.getElementById('res-risk-score');
    const elRiskFlag = document.getElementById('res-risk-flag');
    const elRiskBar = document.getElementById('res-risk-bar');
    const elMissing = document.getElementById('res-missing');
    const elOptional = document.getElementById('res-optional');
    const elDepth = document.getElementById('res-depth');
    const elSize = document.getElementById('res-size');
    const elTime = document.getElementById('res-time');
    const elErrorsContainer = document.getElementById('res-errors-container');
    const elErrorsTitle = document.getElementById('res-errors-title');
    const elErrors = document.getElementById('res-errors');

    // Dashboard Stats Cards
    const statTotal = document.getElementById('stat-total');
    const statFailure = document.getElementById('stat-failure');
    const statRisk = document.getElementById('stat-risk');
    const statFlags = document.getElementById('stat-flags');
    const statsCaption = document.getElementById('stats-caption');

    // Charts Elements
    const gaugeFill = document.getElementById('gauge-fill');
    const gaugeVal = document.getElementById('gauge-val');
    const distBarLow = document.getElementById('dist-bar-low');
    const distBarHigh = document.getElementById('dist-bar-high');
    const distValLow = document.getElementById('dist-val-low');
    const distValHigh = document.getElementById('dist-val-high');

    // Accordion History Feed
    const historyFeed = document.getElementById('history-feed');

    // XML Template for Sandbox Editor
    const xmlTemplate = `<?xml version="1.0" ?>
<StandardBusinessDocument xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2">
    <StandardBusinessDocumentHeader>
        <HeaderVersion>1.0</HeaderVersion>
        <Sender>
            <Identifier Authority="DUNS">123456789</Identifier>
        </Sender>
        <Receiver>
            <Identifier Authority="GLN">987654321</Identifier>
        </Receiver>
    </StandardBusinessDocumentHeader>
    <Invoice>
        <DocumentReference>
            <TransactionID>TXN-48180</TransactionID>
        </DocumentReference>
        <IssueDate>2026-06-20</IssueDate>
        <DocumentCurrencyCode>USD</DocumentCurrencyCode>
        <AccountingSupplierParty>
            <Party>
                <PartyName>
                    <Name>Acme Corp Global</Name>
                </PartyName>
            </Party>
        </AccountingSupplierParty>
        <PaymentMeans>
            <PayeeFinancialAccount>
                <ID>IBAN-XYZ</ID>
            </PayeeFinancialAccount>
        </PaymentMeans>
        <LegalMonetaryTotal>
            <PayableAmount currencyID="USD">2867.70</PayableAmount>
        </LegalMonetaryTotal>
    </Invoice>
</StandardBusinessDocument>`;
    const templateFilename = 'sandbox_invoice.xml';

    // Inspector state: which input tab is chosen, and what the panel shows
    // ('input' = the chosen tab's pane, 'loading', or 'result').
    let activeTab = 'upload';
    let view = 'input';
    let busy = false;
    let samples = [];
    let lastSubmission = null;

    // Dashboard state: last batch run from the server, plus this visitor's analyses.
    let batchStats = null;
    let batchHistory = [];
    let batchError = null;
    let sessionItems = loadSession();

    // Initial Load
    xmlEditor.value = xmlTemplate;
    render();
    renderDashboard();
    loadSamples();
    loadDashboard();

    // ---------- Networking ----------

    function statusMessage(status) {
        if (status === 413) return 'File is too large. The demo accepts XML files up to 1 MB.';
        if (status === 502 || status === 503 || status === 504) {
            return 'The server is starting up or busy. Please try again in a few seconds.';
        }
        if (status >= 500) return `The server ran into a problem (HTTP ${status}). Please try again.`;
        return `The request failed (HTTP ${status}).`;
    }

    // fetch() that turns network failures and non-2xx responses (JSON or not,
    // e.g. an HTML page from a proxy) into an Error with a readable message.
    async function fetchChecked(url, options) {
        let response;
        try {
            response = await fetch(url, options);
        } catch (e) {
            throw new Error('Could not reach the server. If the demo has been idle it may need a moment to wake up, so please try again shortly.');
        }
        if (!response.ok) {
            let detail = null;
            if ((response.headers.get('content-type') || '').includes('application/json')) {
                try {
                    const body = await response.json();
                    if (typeof body.detail === 'string') detail = body.detail;
                } catch (e) {
                    // fall back to the generic message below
                }
            }
            throw new Error(detail || statusMessage(response.status));
        }
        return response;
    }

    async function fetchJson(url, options) {
        const response = await fetchChecked(url, options);
        if (!(response.headers.get('content-type') || '').includes('application/json')) {
            throw new Error('The server sent an unexpected response. Please try again.');
        }
        try {
            return await response.json();
        } catch (e) {
            throw new Error('The server sent an unexpected response. Please try again.');
        }
    }

    async function fetchText(url) {
        const response = await fetchChecked(url);
        return response.text();
    }

    // ---------- Inspector view state ----------

    function render() {
        const showInput = view === 'input';
        paneUpload.classList.toggle('hidden', !(showInput && activeTab === 'upload'));
        paneSandbox.classList.toggle('hidden', !(showInput && activeTab === 'sandbox'));
        loading.classList.toggle('hidden', view !== 'loading');
        results.classList.toggle('hidden', view !== 'result');

        [[tabUploadBtn, 'upload'], [tabSandboxBtn, 'sandbox']].forEach(([btn, name]) => {
            btn.classList.toggle('active', activeTab === name);
            btn.setAttribute('aria-selected', String(activeTab === name));
        });
    }

    function selectTab(name) {
        if (busy) return;
        activeTab = name;
        view = 'input';
        clearError();
        render();
    }

    function setBusy(value) {
        busy = value;
        const controls = [tabUploadBtn, tabSandboxBtn, browseBtn, analyzeSandboxBtn, loadTemplateBtn, resetBtn, editXmlBtn];
        controls.concat(Array.from(document.querySelectorAll('.sample-chip, .empty-sample-btn')))
            .forEach(el => { el.disabled = value; });
        dropZone.classList.toggle('disabled', value);
    }

    function showError(message) {
        inspectorError.textContent = message;
        inspectorError.classList.remove('hidden');
    }

    function clearError() {
        inspectorError.textContent = '';
        inspectorError.classList.add('hidden');
    }

    // Runs one user action at a time; failures become an inline message.
    async function run(task) {
        if (busy) return;
        clearError();
        setBusy(true);
        try {
            await task();
        } catch (error) {
            view = 'input';
            render();
            showError(error.message);
        } finally {
            setBusy(false);
        }
    }

    // Tab Switching Event Listeners
    tabUploadBtn.addEventListener('click', () => selectTab('upload'));
    tabSandboxBtn.addEventListener('click', () => selectTab('sandbox'));
    resetBtn.addEventListener('click', () => {
        selectTab(activeTab);
        fileInput.value = '';
    });
    editXmlBtn.addEventListener('click', () => {
        if (!lastSubmission) return;
        xmlEditor.value = lastSubmission.text;
        editorFilename.textContent = lastSubmission.name;
        selectTab('sandbox');
        xmlEditor.focus();
    });

    // Load XML Template handler
    loadTemplateBtn.addEventListener('click', () => {
        xmlEditor.value = xmlTemplate;
        editorFilename.textContent = templateFilename;
        // Visual feedback
        const origText = loadTemplateBtn.textContent;
        loadTemplateBtn.textContent = '✓ Loaded!';
        loadTemplateBtn.style.color = 'var(--success)';
        setTimeout(() => {
            loadTemplateBtn.textContent = origText;
            loadTemplateBtn.style.color = '';
        }, 1200);
    });

    // Edited content is the visitor's own payload, not the sample it started from.
    xmlEditor.addEventListener('input', () => {
        editorFilename.textContent = templateFilename;
    });

    // ---------- Samples ----------

    async function loadSamples() {
        try {
            samples = await fetchJson('/api/samples');
            sampleChips.innerHTML = '';
            samples.forEach(sample => {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'sample-chip';
                btn.textContent = sample.label;
                btn.title = `Analyze ${sample.filename}`;
                btn.disabled = busy;
                btn.addEventListener('click', () => runSample(sample));
                sampleChips.appendChild(btn);
            });
        } catch (error) {
            samples = [];
            sampleChips.innerHTML = '';
            const note = document.createElement('span');
            note.className = 'sample-placeholder';
            note.textContent = `Samples are unavailable. ${error.message}`;
            sampleChips.appendChild(note);
        }
        renderHistory();
    }

    function runSample(sample) {
        return run(async () => {
            const xml = await fetchText(`/api/samples/${encodeURIComponent(sample.id)}`);
            xmlEditor.value = xml;
            editorFilename.textContent = sample.filename;
            activeTab = 'sandbox';
            await analyze(new File([xml], sample.filename, { type: 'text/xml' }), xml);
        });
    }

    // ---------- Upload & analysis ----------

    // Drag and Drop Zone events
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, preventDefaults, false);
    });

    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    ['dragenter', 'dragover'].forEach(eventName => {
        dropZone.addEventListener(eventName, () => dropZone.classList.add('dragover'), false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, () => dropZone.classList.remove('dragover'), false);
    });

    dropZone.addEventListener('drop', e => handleFiles(e.dataTransfer.files), false);
    dropZone.addEventListener('click', e => {
        if (!busy && e.target !== browseBtn && e.target !== fileInput) fileInput.click();
    });
    browseBtn.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', e => handleFiles(e.target.files));

    function handleFiles(files) {
        if (!files || files.length === 0) return;
        const file = files[0];
        fileInput.value = ''; // lets the same file be chosen again

        run(async () => {
            if (!file.name.toLowerCase().endsWith('.xml')) {
                throw new Error('Please choose an XML file (.xml).');
            }
            const text = await file.text();
            activeTab = 'upload';
            await analyze(file, text);
        });
    }

    // Sandbox Execution Form Submission
    analyzeSandboxBtn.addEventListener('click', () => run(async () => {
        const content = xmlEditor.value.trim();
        if (!content) {
            throw new Error('The sandbox editor is empty. Paste some XML or load the template.');
        }
        const name = editorFilename.textContent || templateFilename;
        await analyze(new File([content], name, { type: 'text/xml' }), content);
    }));

    // Common Upload and Analysis routine
    async function analyze(file, text) {
        if (file.size > MAX_UPLOAD_BYTES) {
            throw new Error(`File is too large (${formatBytes(file.size)}). The demo accepts XML files up to 1 MB.`);
        }

        view = 'loading';
        render();

        const formData = new FormData();
        formData.append('file', file);
        const [data] = await Promise.all([
            fetchJson('/api/analyze', { method: 'POST', body: formData }),
            new Promise(resolve => setTimeout(resolve, MIN_SPINNER_MS))
        ]);

        lastSubmission = { name: file.name, text };
        displayResults(data, text);
        addSessionItem(data);
        renderDashboard();
    }

    function displayResults(data, text) {
        const features = data.features || {};
        const errors = Array.isArray(data.errors) ? data.errors : [];

        // Submitted XML
        elXml.textContent = text.length > MAX_PREVIEW_CHARS
            ? `${text.slice(0, MAX_PREVIEW_CHARS)}\n… (preview truncated)`
            : text;
        elXml.scrollTop = 0;
        elXmlMeta.textContent = formatBytes(features.xml_size);

        // Populate basic metadata
        elFilename.textContent = data.filename;
        elStatus.textContent = data.status;
        elStatus.className = `status-badge status-${statusClass(data.status)}`;
        elSummary.textContent = summaryFor(data.status, errors.length);

        // Validation failures or review reason
        elErrors.innerHTML = '';
        if (errors.length > 0) {
            errors.forEach(message => {
                const li = document.createElement('li');
                li.textContent = message;
                elErrors.appendChild(li);
            });
            const isReview = data.status === 'REQUIRES_REVIEW';
            elErrorsTitle.textContent = isReview ? 'Review Reason' : 'Validation Failures';
            elErrorsContainer.classList.toggle('review', isReview);
            elErrorsContainer.classList.remove('hidden');
        } else {
            elErrorsContainer.classList.add('hidden');
        }

        // Parse Risk Prediction
        const { risk_score: riskScore, risk_flag: riskFlag } = data.prediction || {};
        if (typeof riskScore !== 'number') {
            elRiskScore.textContent = 'N/A';
            elRiskFlag.textContent = 'No model';
            elRiskFlag.className = 'flag-badge flag-NA';
            elRiskScore.style.color = 'var(--text-secondary)';
            elRiskBar.style.width = '0%';
        } else {
            const flag = flagClass(riskFlag);
            elRiskScore.textContent = formatPercent(riskScore);
            elRiskFlag.textContent = flag;
            elRiskFlag.className = `flag-badge flag-${flag}`;
            elRiskScore.style.color = flag === 'HIGH' ? 'var(--danger)' : 'var(--success)';
            elRiskBar.style.width = `${Math.max(0, Math.min(100, riskScore))}%`;
            elRiskBar.className = `risk-bar-fill ${flag === 'HIGH' ? 'high-bg' : 'low-bg'}`;
        }

        // Populate subgrid details
        elMissing.textContent = features.missing_fields ?? '–';
        elOptional.textContent = features.missing_optional_fields !== undefined
            ? `${features.missing_optional_fields} of ${OPTIONAL_FIELD_COUNT}`
            : '–';
        elDepth.textContent = features.nesting_depth ?? '–';
        elSize.textContent = formatBytes(features.xml_size);
        elTime.textContent = typeof data.processing_ms === 'number' ? `${data.processing_ms.toFixed(1)} ms` : '–';

        view = 'result';
        render();
        results.classList.remove('fade-in');
        void results.offsetWidth; // restart the fade-in animation
        results.classList.add('fade-in');

        const top = results.getBoundingClientRect().top;
        if (top < 0 || top > window.innerHeight - 160) {
            results.scrollIntoView({ block: 'start', behavior: 'smooth' });
        }
    }

    function summaryFor(status, errorCount) {
        if (status === 'VALID') {
            return 'Passed every validation rule: the transaction ID and amount were found, and the amount is within the 1,000,000 review limit.';
        }
        if (status === 'REQUIRES_REVIEW') {
            return 'Passed validation, but the amount is above the 1,000,000 review limit, so a person has to approve it before processing.';
        }
        const rules = errorCount === 1 ? 'rule' : 'rules';
        return `Failed ${errorCount} validation ${rules}. The invoice cannot be processed until the problems below are fixed.`;
    }

    // ---------- Dashboard: batch results merged with this session ----------

    function loadSession() {
        try {
            const items = JSON.parse(sessionStorage.getItem(SESSION_KEY) || '[]');
            return Array.isArray(items) ? items : [];
        } catch (e) {
            return [];
        }
    }

    function saveSession() {
        try {
            sessionStorage.setItem(SESSION_KEY, JSON.stringify(sessionItems));
        } catch (e) {
            // storage unavailable (private mode, blocked): keep the session in memory only
        }
    }

    function addSessionItem(data) {
        const features = data.features || {};
        sessionItems.unshift({
            source_file: data.filename,
            id: data.id || '',
            status: data.status,
            errors: (data.errors || []).join('; '),
            missing_fields: features.missing_fields,
            missing_optional_fields: features.missing_optional_fields,
            nesting_depth: features.nesting_depth,
            xml_size: features.xml_size,
            processing_ms: data.processing_ms,
            risk_score: data.prediction ? data.prediction.risk_score : 'N/A',
            risk_flag: data.prediction ? data.prediction.risk_flag : 'N/A'
        });
        sessionItems = sessionItems.slice(0, MAX_SESSION_ITEMS);
        saveSession();
    }

    async function loadDashboard() {
        const [stats, history] = await Promise.allSettled([fetchJson('/api/stats'), fetchJson('/api/history')]);
        batchStats = stats.status === 'fulfilled' ? stats.value : null;
        batchHistory = history.status === 'fulfilled' && Array.isArray(history.value) ? history.value : [];
        const failed = [stats, history].find(r => r.status === 'rejected');
        batchError = failed ? failed.reason.message : null;
        renderDashboard();
    }

    function computeTotals() {
        const b = batchStats || {};
        const num = v => (Number.isFinite(Number(v)) ? Number(v) : 0);
        const countStatus = status => sessionItems.filter(i => i.status === status).length;
        const scoredSession = sessionItems.filter(i => typeof i.risk_score === 'number');

        const batchTotal = num(b.Total_Processed);
        const batchScored = b.Scored_Transactions !== undefined
            ? num(b.Scored_Transactions)
            : (num(b.Average_Risk_Score) > 0 ? batchTotal : 0);
        const scored = batchScored + scoredSession.length;
        const riskSum = num(b.Average_Risk_Score) * batchScored
            + scoredSession.reduce((sum, i) => sum + i.risk_score, 0);
        const high = num(b.Total_High_Risk_Flags) + sessionItems.filter(i => i.risk_flag === 'HIGH').length;

        return {
            batchTotal,
            total: batchTotal + sessionItems.length,
            valid: num(b.Valid_Transactions) + countStatus('VALID'),
            invalid: num(b.Invalid_Transactions) + countStatus('INVALID'),
            scored,
            avgRisk: scored > 0 ? riskSum / scored : null,
            high,
            low: Math.max(0, scored - high)
        };
    }

    function renderDashboard() {
        const t = computeTotals();

        // Update KPI Cards
        statTotal.textContent = t.total.toLocaleString('en-US');
        statFailure.textContent = t.total > 0 ? formatPercent((t.invalid / t.total) * 100) : '–';
        statRisk.textContent = t.avgRisk === null ? '–' : formatPercent(t.avgRisk);
        statFlags.textContent = t.high.toLocaleString('en-US');

        const n = sessionItems.length;
        const yours = `${n} ${n === 1 ? 'analysis' : 'analyses'} from this browser session`;
        if (batchStats) {
            statsCaption.textContent = n > 0
                ? `Totals combine the ${t.batchTotal.toLocaleString('en-US')}-invoice synthetic batch with your ${yours}.`
                : `Totals cover the ${t.batchTotal.toLocaleString('en-US')}-invoice synthetic batch. Files you analyse are added for this browser session.`;
        } else if (batchError) {
            statsCaption.textContent = `Batch totals could not be loaded: ${batchError} Showing your ${yours}.`;
        } else {
            statsCaption.textContent = 'Loading totals…';
        }

        // Update SVG Radial Health Gauge
        const validShare = t.total > 0 ? Math.round((t.valid / t.total) * 100) : 0;
        gaugeVal.textContent = t.total > 0 ? `${validShare}%` : '–';
        const circumference = 2 * Math.PI * 50;
        gaugeFill.style.strokeDashoffset = circumference - (validShare / 100) * circumference;

        // Update Risk Distribution Bars
        distValLow.textContent = t.low.toLocaleString('en-US');
        distValHigh.textContent = t.high.toLocaleString('en-US');
        distBarLow.style.width = t.scored > 0 ? `${(t.low / t.scored) * 100}%` : '0%';
        distBarHigh.style.width = t.scored > 0 ? `${(t.high / t.scored) * 100}%` : '0%';

        renderHistory();
    }

    // ---------- History feed ----------

    function renderHistory() {
        const items = sessionItems.slice(0, MAX_FEED_SESSION_ITEMS).map(i => ({ ...i, origin: 'session' }))
            .concat(batchHistory.map(i => ({ ...i, origin: 'batch' })));

        historyFeed.innerHTML = '';
        if (items.length === 0) {
            historyFeed.appendChild(createEmptyState());
            return;
        }
        items.forEach(item => historyFeed.appendChild(createAccordionItem(item)));
    }

    function createEmptyState() {
        const empty = document.createElement('div');
        empty.className = 'feed-empty-state';
        const message = document.createElement('p');
        message.textContent = batchError
            ? `No analyses to show. ${batchError}`
            : (batchStats ? 'No analyses yet.' : 'Loading analyses…');
        empty.appendChild(message);
        if (samples.length > 0) {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'btn-primary-outline empty-sample-btn';
            btn.textContent = 'Try a sample';
            btn.disabled = busy;
            btn.addEventListener('click', () => runSample(samples[0]));
            empty.appendChild(btn);
        }
        return empty;
    }

    function escapeHtml(value) {
        return String(value ?? '').replace(/[&<>"']/g, c => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        }[c]));
    }

    function statusClass(status) {
        return ['VALID', 'INVALID', 'REQUIRES_REVIEW'].includes(status) ? status : 'NA';
    }

    function flagClass(flag) {
        return flag === 'LOW' || flag === 'HIGH' ? flag : 'NA';
    }

    function isBlank(value) {
        return value === undefined || value === null || value === '';
    }

    // Helper to generate Accordion Card HTML
    function createAccordionItem(item) {
        const itemDiv = document.createElement('div');
        itemDiv.className = 'accordion-item';

        const hasScore = typeof item.risk_score === 'number';
        const riskScoreStr = hasScore ? formatPercent(item.risk_score) : 'N/A';
        const riskFlag = hasScore ? flagClass(item.risk_flag) : 'NA';
        const origin = item.origin === 'session' ? 'Your session' : 'Synthetic batch';

        const detail = (label, value) => `
            <div class="detail-field">
                <span class="detail-label">${label}</span>
                <span class="detail-value">${escapeHtml(value)}</span>
            </div>`;

        const errorBlock = item.errors
            ? `<div class="detail-errors">
                 <span class="detail-label error-header">${item.status === 'REQUIRES_REVIEW' ? 'Review reason' : 'Errors'}</span>
                 <p class="detail-error-msg">${escapeHtml(item.errors)}</p>
               </div>`
            : '';

        itemDiv.innerHTML = `
            <button type="button" class="accordion-summary" aria-expanded="false">
                <span class="file-info">
                    <span class="file-name" title="${escapeHtml(item.source_file)}">${escapeHtml(item.source_file)}</span>
                    <span class="file-id">ID: ${escapeHtml(item.id || 'N/A')} <span class="origin-tag origin-${item.origin}">${origin}</span></span>
                </span>
                <span class="badge-group">
                    <span class="badge status-${statusClass(item.status)}">${escapeHtml(item.status)}</span>
                    <span class="badge flag-${riskFlag}" title="Experimental risk score">${riskScoreStr}</span>
                </span>
                <span class="chevron-icon" aria-hidden="true">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                        <polyline points="6 9 12 15 18 9"></polyline>
                    </svg>
                </span>
            </button>
            <div class="accordion-details">
                <div class="detail-grid">
                    ${detail('Payload Size', formatBytes(item.xml_size))}
                    ${detail('Missing Required', isBlank(item.missing_fields) ? '–' : item.missing_fields)}
                    ${detail('Missing Optional', isBlank(item.missing_optional_fields) ? '–' : `${item.missing_optional_fields} of ${OPTIONAL_FIELD_COUNT}`)}
                    ${detail('Nesting Depth', isBlank(item.nesting_depth) ? '–' : item.nesting_depth)}
                    ${typeof item.processing_ms === 'number' ? detail('Server Time', `${item.processing_ms.toFixed(1)} ms`) : ''}
                    ${errorBlock}
                </div>
            </div>
        `;
        return itemDiv;
    }

    // Accordion Toggle click handler using event delegation
    historyFeed.addEventListener('click', (e) => {
        const summary = e.target.closest('.accordion-summary');
        if (!summary) return;

        const item = summary.parentElement;
        const isActive = item.classList.contains('active');

        // Close all siblings
        historyFeed.querySelectorAll('.accordion-item').forEach(el => {
            el.classList.remove('active');
            el.querySelector('.accordion-summary').setAttribute('aria-expanded', 'false');
        });

        // Toggle clicked item
        if (!isActive) {
            item.classList.add('active');
            summary.setAttribute('aria-expanded', 'true');
        }
    });

    // ---------- Formatting ----------

    function formatPercent(value) {
        return `${Number(Number(value).toFixed(1))}%`;
    }

    function formatBytes(bytes) {
        const n = Number(bytes);
        if (isBlank(bytes) || !Number.isFinite(n)) return 'N/A';
        if (n < 1000) return `${n} B`;
        if (n < 1000000) return `${(n / 1000).toFixed(1)} KB`;
        return `${(n / 1000000).toFixed(1)} MB`;
    }
});
