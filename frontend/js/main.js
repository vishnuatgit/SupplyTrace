// Entry point: a small hash router over the seven views, the theme toggle, and
// the wiring between views. Routes look like #/check, #/batch, #/review,
// #/vendors, #/audit, #/rules, #/about. Hashes without the slash (#main) are in-page links.

import { initCheck, getSamples, runSampleById, editInSandbox } from './check.js';
import { initBatch, runSamples, runFiles } from './batch.js';
import { initAudit, showAudit } from './audit.js';
import { initReview, showReview, refreshReviewCount } from './review.js';
import { initVendors, showVendors } from './vendors.js';
import { showReference } from './reference.js';
import { initOverview, refreshOverview, rememberChecks } from './overview.js';
import { initPipeline } from './pipeline.js';
import { initChartTooltips } from './charts.js';

const ROUTES = {
    check: { title: 'SupplyTrace | Supplier XML invoice validation', onShow: refreshOverview },
    batch: { title: 'Batch check · SupplyTrace' },
    review: { title: 'Review queue · SupplyTrace', onShow: showReview },
    vendors: { title: 'Vendors · SupplyTrace', onShow: showVendors },
    audit: { title: 'Audit log · SupplyTrace', onShow: showAudit },
    rules: { title: 'Rules and model · SupplyTrace', onShow: showReference },
    about: { title: 'About · SupplyTrace' },
};

function parseHash() {
    const [name, query = ''] = location.hash.replace(/^#\/?/, '').split('?');
    return { route: name in ROUTES ? name : 'check', params: new URLSearchParams(query) };
}

function showRoute(route, { userNavigation = false, params = new URLSearchParams() } = {}) {
    // A link inside the batch drawer can change the view: close the drawer with it.
    document.getElementById('drawer')?.close();
    document.querySelectorAll('[data-view]').forEach(view => {
        view.hidden = view.dataset.view !== route;
    });
    document.querySelectorAll('.main-nav a').forEach(link => {
        if (link.dataset.route === route) link.setAttribute('aria-current', 'page');
        else link.removeAttribute('aria-current');
    });
    document.title = ROUTES[route].title;
    if (userNavigation) {
        window.scrollTo(0, 0);
        // Move focus to the new view's heading so screen readers announce it.
        document.querySelector(`#view-${route} .view-title`)?.focus({ preventScroll: true });
    }
    ROUTES[route].onShow?.(params);
}

function handleRoute({ userNavigation }) {
    // An in-page link (#main) only scrolls; it never changes the view.
    const anchor = location.hash && !location.hash.startsWith('#/');
    if (anchor && userNavigation) return;
    const { route, params } = anchor ? { route: 'check', params: new URLSearchParams() } : parseHash();
    showRoute(route, { userNavigation, params });

    // Deep links: #/check?sample=bad-amount runs that sample;
    // #/batch?run=samples runs every sample as a batch (once).
    if (route === 'check' && params.get('sample')) runSampleById(params.get('sample'));
    if (route === 'batch' && params.get('run') === 'samples') {
        history.replaceState(null, '', '#/batch');
        runSamples();
    }
}

// Switches view from code (no hashchange event), keeping a history entry.
function go(route) {
    history.pushState(null, '', `#/${route}`);
    showRoute(route, { userNavigation: true });
}

// ---------- Theme ----------

function setupThemeToggle() {
    const button = document.getElementById('theme-toggle');
    const meta = document.querySelector('meta[name="theme-color"]');
    const apply = theme => {
        document.documentElement.setAttribute('data-theme', theme);
        const next = theme === 'dark' ? 'light' : 'dark';
        button.setAttribute('aria-label', `Switch to ${next} theme`);
        button.title = `Switch to ${next} theme`;
        meta.setAttribute('content', theme === 'dark' ? '#06090e' : '#f5f6fa');
    };
    apply(document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark');
    button.addEventListener('click', () => {
        const theme = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
        document.documentElement.classList.add('theme-switching');
        apply(theme);
        try {
            localStorage.setItem('supplytrace.theme', theme);
        } catch {
            // storage unavailable: the choice lasts for this page only
        }
        setTimeout(() => document.documentElement.classList.remove('theme-switching'), 250);
    });
}

// ---------- Start ----------

setupThemeToggle();
initChartTooltips();
initPipeline();
initOverview();
initCheck({
    onBatchFiles: files => {
        go('batch');
        runFiles(files);
    },
    onChecked: result => {
        rememberChecks([result]);
        refreshOverview();
        refreshReviewCount();
    },
});
initBatch({
    getSamples,
    openInSandbox: (text, name, problem) => {
        go('check');
        editInSandbox(text, name, problem);
    },
    onChecked: results => {
        rememberChecks(results);
        refreshReviewCount();
    },
});
initAudit();
initReview();
initVendors();
refreshReviewCount();

window.addEventListener('hashchange', () => handleRoute({ userNavigation: true }));
handleRoute({ userNavigation: false });
