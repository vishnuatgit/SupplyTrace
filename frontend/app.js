document.addEventListener('DOMContentLoaded', () => {
    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('file-input');
    const browseBtn = document.getElementById('browse-btn');
    const loading = document.getElementById('loading');
    const results = document.getElementById('results');
    const resetBtn = document.getElementById('reset-btn');

    // UI Elements for Data
    const elFilename = document.getElementById('res-filename');
    const elStatus = document.getElementById('res-status');
    const elRiskScore = document.getElementById('res-risk-score');
    const elRiskFlag = document.getElementById('res-risk-flag');
    const elMissing = document.getElementById('res-missing');
    const elSize = document.getElementById('res-size');
    const elTime = document.getElementById('res-time');
    const elErrorsContainer = document.getElementById('res-errors-container');
    const elErrors = document.getElementById('res-errors');

    // Dashboard Elements
    const statTotal = document.getElementById('stat-total');
    const statFailure = document.getElementById('stat-failure');
    const statRisk = document.getElementById('stat-risk');
    const statFlags = document.getElementById('stat-flags');
    const historyTableBody = document.getElementById('history-table-body');

    // Fetch Dashboard Stats and History on Load
    fetchDashboardStats();
    fetchHistory();

    async function fetchHistory() {
        try {
            const res = await fetch('/api/history');
            if (res.ok) {
                const data = await res.json();
                historyTableBody.innerHTML = '';
                data.forEach(item => {
                    appendHistoryRow(item);
                });
            }
        } catch (e) {
            console.error("Failed to fetch transaction history", e);
        }
    }

    function appendHistoryRow(item) {
        const tr = document.createElement('tr');
        tr.className = 'fade-in';
        
        // Handle potential N/A for risk score
        const riskScoreStr = item.risk_score === 'N/A' || item.risk_score === '' ? 'N/A' : `${item.risk_score}%`;
        const riskFlagStr = item.risk_flag || 'N/A';
        
        tr.innerHTML = `
            <td>${item.source_file}</td>
            <td><span class="badge status-${item.status}">${item.status}</span></td>
            <td>${riskScoreStr}</td>
            <td><span class="badge flag-${riskFlagStr}">${riskFlagStr}</span></td>
            <td class="error-text">${item.errors || '-'}</td>
        `;
        historyTableBody.appendChild(tr);
    }

    function prependHistoryRow(item) {
        const tr = document.createElement('tr');
        tr.className = 'fade-in';
        
        const riskScoreStr = item.risk_score === 'N/A' || item.risk_score === '' ? 'N/A' : `${item.risk_score}%`;
        const riskFlagStr = item.risk_flag || 'N/A';
        
        tr.innerHTML = `
            <td>${item.source_file}</td>
            <td><span class="badge status-${item.status}">${item.status}</span></td>
            <td>${riskScoreStr}</td>
            <td><span class="badge flag-${riskFlagStr}">${riskFlagStr}</span></td>
            <td class="error-text">${item.errors || '-'}</td>
        `;
        
        if (historyTableBody.firstChild) {
            historyTableBody.insertBefore(tr, historyTableBody.firstChild);
        } else {
            historyTableBody.appendChild(tr);
        }
        
        // Limit to 15 rows
        while (historyTableBody.children.length > 15) {
            historyTableBody.removeChild(historyTableBody.lastChild);
        }
    }

    async function fetchDashboardStats() {
        try {
            const res = await fetch('/api/stats');
            if (res.ok) {
                const data = await res.json();
                statTotal.textContent = data.Total_Processed;
                statFailure.textContent = `${data.Failure_Rate_Percent}%`;
                statRisk.textContent = `${data.Average_Risk_Score}%`;
                statFlags.textContent = data.Total_High_Risk_Flags;
            }
        } catch (e) {
            console.error("Failed to fetch dashboard stats", e);
        }
    }

    // Drag and Drop Logic
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

    async function uploadAndAnalyze(file) {
        // Switch UI to loading state
        dropZone.classList.add('hidden');
        results.classList.add('hidden');
        loading.classList.remove('hidden');

        const formData = new FormData();
        formData.append('file', file);

        try {
            // Give it a tiny artificial delay so the user can enjoy the loading animation
            const [response] = await Promise.all([
                fetch('/api/analyze', {
                    method: 'POST',
                    body: formData
                }),
                new Promise(resolve => setTimeout(resolve, 800))
            ]);

            if (!response.ok) {
                const errData = await response.json();
                throw new Error(errData.detail || 'Analysis failed');
            }

            const data = await response.json();
            displayResults(data);

        } catch (error) {
            alert('Error analyzing file: ' + error.message);
            resetUI();
        }
    }

    function displayResults(data) {
        loading.classList.add('hidden');
        results.classList.remove('hidden');
        results.classList.add('fade-in');

        // Populate basic info
        elFilename.textContent = data.filename;
        
        // Status badge
        elStatus.textContent = data.status;
        elStatus.className = `status-badge status-${data.status}`;

        // Metrics
        elMissing.textContent = data.features.missing_fields;
        elSize.textContent = `${(data.features.xml_size / 1024).toFixed(2)} KB`;
        elTime.textContent = `${data.features.processing_time.toFixed(2)} ms`;

        // Risk prediction
        const riskScore = data.prediction.risk_score;
        if (riskScore === 'N/A') {
            elRiskScore.textContent = 'N/A';
            elRiskFlag.textContent = 'N/A';
            elRiskFlag.className = 'flag-badge flag-NA';
            elRiskScore.style.color = 'var(--text-secondary)';
        } else {
            elRiskScore.textContent = `${riskScore}%`;
            elRiskFlag.textContent = data.prediction.risk_flag;
            elRiskFlag.className = `flag-badge flag-${data.prediction.risk_flag}`;
            
            // Color code the percentage text
            elRiskScore.style.color = data.prediction.risk_flag === 'HIGH' ? 'var(--danger)' : 'var(--success)';
        }

        // Errors
        if (data.errors && data.errors.length > 0) {
            elErrorsContainer.classList.remove('hidden');
            elErrors.textContent = data.errors.join('; ');
        } else {
            elErrorsContainer.classList.add('hidden');
        }

        // Add to history log table
        prependHistoryRow({
            source_file: data.filename,
            status: data.status,
            risk_score: data.prediction.risk_score,
            risk_flag: data.prediction.risk_flag,
            errors: data.errors.join('; ')
        });

        // Refresh stats cards
        fetchDashboardStats();
    }

    function resetUI() {
        results.classList.add('hidden');
        results.classList.remove('fade-in');
        loading.classList.add('hidden');
        dropZone.classList.remove('hidden');
        fileInput.value = '';
    }
});
