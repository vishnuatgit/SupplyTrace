document.addEventListener('DOMContentLoaded', () => {
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
    const loadTemplateBtn = document.getElementById('load-template-btn');
    const analyzeSandboxBtn = document.getElementById('analyze-sandbox-btn');

    // Results UI Elements
    const elFilename = document.getElementById('res-filename');
    const elStatus = document.getElementById('res-status');
    const elRiskScore = document.getElementById('res-risk-score');
    const elRiskFlag = document.getElementById('res-risk-flag');
    const elMissing = document.getElementById('res-missing');
    const elSize = document.getElementById('res-size');
    const elTime = document.getElementById('res-time');
    const elErrorsContainer = document.getElementById('res-errors-container');
    const elErrors = document.getElementById('res-errors');

    // Dashboard Stats Cards
    const statTotal = document.getElementById('stat-total');
    const statFailure = document.getElementById('stat-failure');
    const statRisk = document.getElementById('stat-risk');
    const statFlags = document.getElementById('stat-flags');

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

    // Initial Load
    fetchDashboardStats();
    fetchHistory();
    xmlEditor.value = xmlTemplate;

    // Tab Switching Event Listeners
    tabUploadBtn.addEventListener('click', () => {
        tabUploadBtn.classList.add('active');
        tabSandboxBtn.classList.remove('active');
        paneUpload.classList.add('active');
        paneSandbox.classList.remove('active');
    });

    tabSandboxBtn.addEventListener('click', () => {
        tabSandboxBtn.classList.add('active');
        tabUploadBtn.classList.remove('active');
        paneSandbox.classList.add('active');
        paneUpload.classList.remove('active');
    });

    // Load XML Template handler
    loadTemplateBtn.addEventListener('click', () => {
        xmlEditor.value = xmlTemplate;
        // Visual feedback
        const origText = loadTemplateBtn.textContent;
        loadTemplateBtn.textContent = '✓ Loaded!';
        loadTemplateBtn.style.color = 'var(--success)';
        setTimeout(() => {
            loadTemplateBtn.textContent = origText;
            loadTemplateBtn.style.color = '';
        }, 1200);
    });

    // Fetch History & Stats from API
    async function fetchHistory() {
        try {
            const res = await fetch('/api/history');
            if (res.ok) {
                const data = await res.json();
                historyFeed.innerHTML = '';
                if (data.length === 0) {
                    historyFeed.innerHTML = '<div class="feed-empty-state">No transaction logs loaded.</div>';
                    return;
                }
                data.forEach(item => {
                    appendHistoryRow(item);
                });
            }
        } catch (e) {
            console.error("Failed to fetch transaction history", e);
        }
    }

    async function fetchDashboardStats() {
        try {
            const res = await fetch('/api/stats');
            if (res.ok) {
                const data = await res.json();
                
                // Update KPI Cards
                statTotal.textContent = data.Total_Processed;
                statFailure.textContent = `${data.Failure_Rate_Percent}%`;
                statRisk.textContent = `${data.Average_Risk_Score}%`;
                statFlags.textContent = data.Total_High_Risk_Flags;

                // Update SVG Radial Health Gauge
                const total = data.Total_Processed;
                const complianceRate = total > 0 
                    ? Math.round((data.Valid_Transactions / total) * 100) 
                    : 100;
                
                gaugeVal.textContent = `${complianceRate}%`;
                
                const r = 50;
                const circumference = 2 * Math.PI * r;
                const offset = circumference - (complianceRate / 100) * circumference;
                gaugeFill.style.strokeDashoffset = offset;

                // Update Risk Distribution Bars
                const highRiskCount = data.Total_High_Risk_Flags;
                const lowRiskCount = total - highRiskCount;
                
                distValLow.textContent = lowRiskCount;
                distValHigh.textContent = highRiskCount;

                if (total === 0) {
                    distBarLow.style.width = '0%';
                    distBarHigh.style.width = '0%';
                } else {
                    distBarLow.style.width = `${(lowRiskCount / total) * 100}%`;
                    distBarHigh.style.width = `${(highRiskCount / total) * 100}%`;
                }
            }
        } catch (e) {
            console.error("Failed to fetch dashboard stats", e);
        }
    }

    // Helper to generate Accordion Card HTML
    function createAccordionItem(item) {
        const itemDiv = document.createElement('div');
        itemDiv.className = 'accordion-item fade-in';

        const riskScoreStr = item.risk_score === 'N/A' || item.risk_score === '' ? 'N/A' : `${item.risk_score}%`;
        const riskFlagStr = item.risk_flag || 'N/A';

        // Size format
        let sizeStr = 'N/A';
        if (item.xml_size !== undefined && item.xml_size !== '') {
            sizeStr = `${(parseFloat(item.xml_size) / 1024).toFixed(2)} KB`;
        }

        // Latency format
        let latencyStr = 'N/A';
        if (item.processing_time !== undefined && item.processing_time !== '') {
            latencyStr = `${parseFloat(item.processing_time).toFixed(2)} ms`;
        }

        const errorBlock = item.errors 
            ? `<div class="detail-errors">
                 <span class="detail-label error-header">Errors</span>
                 <p class="detail-error-msg">${item.errors}</p>
               </div>`
            : '';

        itemDiv.innerHTML = `
            <div class="accordion-summary">
                <div class="file-info">
                    <span class="file-name" title="${item.source_file}">${item.source_file}</span>
                    <span class="file-id">ID: ${item.id || item.transaction_id || 'N/A'}</span>
                </div>
                <div class="badge-group">
                    <span class="badge status-${item.status}">${item.status}</span>
                    <span class="badge flag-${riskFlagStr}">${riskScoreStr}</span>
                </div>
                <div class="chevron-icon">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                        <polyline points="6 9 12 15 18 9"></polyline>
                    </svg>
                </div>
            </div>
            <div class="accordion-details">
                <div class="detail-grid">
                    <div class="detail-field">
                        <span class="detail-label">Payload Size</span>
                        <span class="detail-value">${sizeStr}</span>
                    </div>
                    <div class="detail-field">
                        <span class="detail-label">Latency</span>
                        <span class="detail-value">${latencyStr}</span>
                    </div>
                    <div class="detail-field">
                        <span class="detail-label">Missing Fields</span>
                        <span class="detail-value">${item.missing_fields !== undefined && item.missing_fields !== '' ? item.missing_fields : 0}</span>
                    </div>
                    ${errorBlock}
                </div>
            </div>
        `;
        return itemDiv;
    }

    function appendHistoryRow(item) {
        const itemDiv = createAccordionItem(item);
        historyFeed.appendChild(itemDiv);
    }

    function prependHistoryRow(item) {
        // Remove empty state if present
        const emptyState = historyFeed.querySelector('.feed-empty-state');
        if (emptyState) {
            emptyState.remove();
        }

        const itemDiv = createAccordionItem(item);
        if (historyFeed.firstChild) {
            historyFeed.insertBefore(itemDiv, historyFeed.firstChild);
        } else {
            historyFeed.appendChild(itemDiv);
        }

        // Limit feed list to 15 items
        while (historyFeed.children.length > 15) {
            historyFeed.removeChild(historyFeed.lastChild);
        }
    }

    // Accordion Toggle click handler using event delegation
    historyFeed.addEventListener('click', (e) => {
        const summary = e.target.closest('.accordion-summary');
        if (!summary) return;

        const item = summary.parentElement;
        const isActive = item.classList.contains('active');

        // Close all siblings
        const allItems = historyFeed.querySelectorAll('.accordion-item');
        allItems.forEach(el => el.classList.remove('active'));

        // Toggle clicked item
        if (!isActive) {
            item.classList.add('active');
        }
    });

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

    dropZone.addEventListener('drop', handleDrop, false);
    browseBtn.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', (e) => handleFiles(e.target.files));
    resetBtn.addEventListener('click', resetUI);

    function handleDrop(e) {
        const dt = e.dataTransfer;
        const files = dt.files;
        handleFiles(files);
    }

    function handleFiles(files) {
        if (files.length === 0) return;
        const file = files[0];
        
        if (!file.name.toLowerCase().endsWith('.xml')) {
            alert('Please upload a valid XML file.');
            return;
        }

        uploadAndAnalyze(file);
    }

    // Sandbox Execution Form Submission
    analyzeSandboxBtn.addEventListener('click', () => {
        const content = xmlEditor.value.trim();
        if (!content) {
            alert('Sandbox editor is empty.');
            return;
        }

        // Convert the string content to an in-memory XML File object
        const blob = new Blob([content], { type: 'text/xml' });
        const file = new File([blob], 'sandbox_invoice.xml', { type: 'text/xml' });
        
        uploadAndAnalyze(file);
    });

    // Common Upload and Analysis routine
    async function uploadAndAnalyze(file) {
        // Switch UI to loading state
        paneUpload.classList.add('hidden');
        paneSandbox.classList.add('hidden');
        // Hide tabs header to avoid context switching during processing
        document.querySelector('.tab-selectors').style.pointerEvents = 'none';
        results.classList.add('hidden');
        loading.classList.remove('hidden');

        const formData = new FormData();
        formData.append('file', file);

        try {
            // Artificial tiny delay to enjoy the sleek spinner animation
            const [response] = await Promise.all([
                fetch('/api/analyze', {
                    method: 'POST',
                    body: formData
                }),
                new Promise(resolve => setTimeout(resolve, 600))
            ]);

            if (!response.ok) {
                const errData = await response.json();
                throw new Error(errData.detail || 'Analysis failed');
            }

            const data = await response.json();
            displayResults(data);

        } catch (error) {
            alert('Error analyzing payload: ' + error.message);
            resetUI();
        } finally {
            document.querySelector('.tab-selectors').style.pointerEvents = 'auto';
        }
    }

    function displayResults(data) {
        loading.classList.add('hidden');
        results.classList.remove('hidden');
        results.classList.add('fade-in');

        // Populate basic metadata
        elFilename.textContent = data.filename;
        elStatus.textContent = data.status;
        elStatus.className = `status-badge status-${data.status}`;

        // Populate subgrid details
        elMissing.textContent = data.features.missing_fields;
        elSize.textContent = `${(data.features.xml_size / 1024).toFixed(2)} KB`;
        elTime.textContent = `${data.features.processing_time.toFixed(2)} ms`;

        // Parse Risk Prediction
        const riskScore = data.prediction.risk_score;
        const riskFlag = data.prediction.risk_flag;
        if (riskScore === 'N/A') {
            elRiskScore.textContent = 'N/A';
            elRiskFlag.textContent = 'N/A';
            elRiskFlag.className = 'flag-badge flag-NA';
            elRiskScore.style.color = 'var(--text-secondary)';
        } else {
            elRiskScore.textContent = `${riskScore}%`;
            elRiskFlag.textContent = riskFlag;
            elRiskFlag.className = `flag-badge flag-${riskFlag}`;
            elRiskScore.style.color = riskFlag === 'HIGH' ? 'var(--danger)' : 'var(--success)';
        }

        // Process validation errors
        if (data.errors && data.errors.length > 0) {
            elErrorsContainer.classList.remove('hidden');
            elErrors.textContent = data.errors.join('; ');
        } else {
            elErrorsContainer.classList.add('hidden');
        }

        // Standardize item and prepend to transaction history
        const historyItem = {
            source_file: data.filename,
            id: data.features.id || data.features.transaction_id || 'N/A',
            status: data.status,
            errors: data.errors.join('; '),
            missing_fields: data.features.missing_fields,
            xml_size: data.features.xml_size,
            processing_time: data.features.processing_time,
            risk_score: riskScore,
            risk_flag: riskFlag
        };

        prependHistoryRow(historyItem);
        
        // Refresh Stats Cards and SVG charts
        fetchDashboardStats();
    }

    function resetUI() {
        results.classList.add('hidden');
        results.classList.remove('fade-in');
        loading.classList.add('hidden');
        
        // Restore active tab
        if (tabUploadBtn.classList.contains('active')) {
            paneUpload.classList.remove('hidden');
        } else {
            paneSandbox.classList.remove('hidden');
        }
        
        fileInput.value = '';
    }
});
