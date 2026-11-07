// The Review view: the queue of invoices that need a person (a table with
// filters), and one review opened from it (the analysis, the actions and the
// full history). Routes: #/review for the queue, #/review?id=3 for one review.

import { getJson, postJson } from './api.js';
import {
    el, clear, icon, badge, flagBadge, duplicateTag, formatDateTime, formatRelative, formatNumber, formatPercent,
    announce, toast,
} from './ui.js';
import { checklist, riskBlock, duplicateNote } from './result.js';
import { getReviewerName, setReviewerName } from './reviewer.js';

const SEARCH_DELAY_MS = 250;
const STATE_TEXT = { open: 'Open', approved: 'Approved', rejected: 'Rejected' };
const STATE_ICON = { open: 'clock', approved: 'check-circle', rejected: 'x-circle' };
const ACTION_TEXT = {
    created: 'Added to the queue', assigned: 'Assigned', commented: 'Comment',
    approved: 'Approved', rejected: 'Rejected',
};
const ACTION_ICON = { created: 'flag', assigned: 'user', commented: 'message', approved: 'check-circle', rejected: 'x-circle' };

let dom;
let filters = { state: 'open', status: '', assignee: '', q: '' };
let requestId = 0;
let searchTimer = null;

export function initReview() {
    const $ = id => document.getElementById(id);
    dom = {
        list: $('review-list'), detail: $('review-detail'), output: $('review-output'),
        filter: $('review-filter'), status: $('review-status'), assignee: $('review-assignee'),
        search: $('review-search'), refresh: $('review-refresh'), name: $('review-name'),
        navCount: $('review-nav-count'),
    };
    dom.name.value = getReviewerName();
    dom.name.addEventListener('change', () => setReviewerName(dom.name.value.trim()));

    dom.filter.addEventListener('change', event => {
        filters.state = event.target.value;
        markCheckedFilter();
        loadQueue({ announceCount: true });
    });
    dom.status.addEventListener('change', () => {
        filters.status = dom.status.value;
        loadQueue({ announceCount: true });
    });
    dom.assignee.addEventListener('change', () => {
        filters.assignee = dom.assignee.value;
        loadQueue({ announceCount: true });
    });
    dom.search.addEventListener('input', () => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => {
            filters.q = dom.search.value.trim();
            loadQueue({ announceCount: true });
        }, SEARCH_DELAY_MS);
    });
    dom.refresh.addEventListener('click', () => loadQueue({ announceDone: true }));
    document.addEventListener('reviews-changed', refreshReviewCount);
    markCheckedFilter();
}

function markCheckedFilter() {
    dom.filter.querySelectorAll('label').forEach(label => {
        label.classList.toggle('is-checked', label.querySelector('input').checked);
    });
}

// The number of open reviews, shown next to "Review" in the menu.
export async function refreshReviewCount() {
    try {
        const data = await getJson('/api/reviews?state=open&limit=1');
        dom.navCount.textContent = formatNumber(data.counts.open);
        dom.navCount.classList.toggle('is-empty', data.counts.open === 0);
        dom.navCount.setAttribute('aria-label', `${data.counts.open} open`);
    } catch {
        // the menu simply shows no number
    }
}

export function showReview(params) {
    const id = Number(params.get('id'));
    const one = Number.isInteger(id) && id > 0;
    dom.list.hidden = one;
    dom.detail.hidden = !one;
    if (one) loadDetail(id);
    else loadQueue();
}

function errorCard(title, message, retry) {
    return el('div', { class: 'error-card', role: 'alert' },
        el('span', { class: 'error-icon', 'aria-hidden': 'true' }, icon('x-circle')),
        el('div', {},
            el('p', { class: 'error-title', text: title }),
            el('p', { text: message }),
            el('div', { class: 'error-actions' },
                retry ? el('button', { type: 'button', class: 'btn btn-secondary', on: { click: retry } }, icon('refresh'), 'Try again') : null,
                el('a', { class: 'btn btn-outline', href: '#/review' }, 'Back to the queue'))));
}

function stateBadge(state) {
    return el('span', { class: `badge review-state review-${state}` }, icon(STATE_ICON[state]), STATE_TEXT[state] || state);
}

function riskCell(review) {
    const score = review.risk_score;
    return flagBadge(typeof score === 'number' ? { risk_score: score, risk_flag: score > 50 ? 'HIGH' : 'LOW' } : null);
}

// ---------- The queue ----------

async function loadQueue({ announceDone = false, announceCount = false } = {}) {
    const id = ++requestId; // only the latest request may render
    dom.output.setAttribute('aria-busy', 'true');
    dom.refresh.classList.add('is-loading');
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
    try {
        const data = await getJson(`/api/reviews?${params}`);
        if (id !== requestId) return;
        renderCounts(data);
        renderAssigneeOptions(data.assignees);
        renderQueue(data);
        dom.navCount.textContent = formatNumber(data.counts.open);
        if (announceDone) {
            announce('Review queue refreshed.');
            toast('Review queue refreshed.', { kind: 'info', duration: 2200 });
        } else if (announceCount) {
            announce(`${formatNumber(data.matching)} matching reviews.`);
        }
    } catch (error) {
        if (id !== requestId) return;
        clear(dom.output).append(errorCard('The review queue could not be loaded', error.message, () => loadQueue()));
    } finally {
        if (id === requestId) {
            dom.output.removeAttribute('aria-busy');
            dom.refresh.classList.remove('is-loading');
        }
    }
}

function renderCounts(data) {
    const counts = { all: Object.values(data.counts).reduce((sum, n) => sum + n, 0), ...data.counts };
    dom.filter.querySelectorAll('[data-count]').forEach(slot => {
        slot.textContent = formatNumber(counts[slot.dataset.count] ?? 0);
    });
}

function renderAssigneeOptions(names) {
    const options = [['', 'Anyone'], ['unassigned', 'Unassigned'], ...names.map(name => [name, name])];
    if (filters.assignee && !options.some(([value]) => value === filters.assignee)) options.push([filters.assignee, filters.assignee]);
    clear(dom.assignee).append(...options.map(([value, label]) => el('option', { value, text: label, selected: value === filters.assignee })));
}

function resetFilters() {
    filters = { state: '', status: '', assignee: '', q: '' };
    dom.filter.querySelector('input[value=""]').checked = true;
    dom.status.value = '';
    dom.search.value = '';
    markCheckedFilter();
    loadQueue();
}

function renderQueue(data) {
    const everything = Object.values(data.counts).reduce((sum, n) => sum + n, 0);
    if (data.matching === 0) {
        const nothingYet = everything === 0 && !filters.status && !filters.assignee && !filters.q;
        const openCleared = filters.state === 'open' && !filters.status && !filters.assignee && !filters.q && everything > 0;
        const title = nothingYet ? 'The review queue is empty'
            : openCleared ? 'Nothing is waiting for review'
                : 'No reviews match these filters';
        const text = nothingYet ? 'Files that need a person land here: invoices above the review limit are added automatically, and you can send an invalid invoice from its result.'
            : openCleared ? 'Every review has been decided. Switch to Approved or Rejected to see them.'
                : 'Try another state, status or assignee, or clear the search.';
        clear(dom.output).append(el('div', { class: 'empty-state' },
            el('div', { class: 'empty-icon' }, icon('flag')),
            el('p', { class: 'empty-title', text: title }),
            el('p', { text }),
            nothingYet
                ? el('a', { class: 'btn btn-outline', href: '#/check?sample=high-value' }, 'Check the high-value sample')
                : el('button', { type: 'button', class: 'btn btn-secondary', on: { click: resetFilters } }, icon('x'), 'Show all reviews')));
        return;
    }

    const now = Date.now();
    const header = el('tr', {},
        el('th', { scope: 'col', class: 'num', text: '#' }),
        el('th', { scope: 'col', text: 'Invoice' }),
        el('th', { scope: 'col', text: 'Status' }),
        el('th', { scope: 'col', class: 'num', text: 'Amount' }),
        el('th', { scope: 'col', class: 'num', text: 'Risk' }),
        el('th', { scope: 'col', text: 'Review' }),
        el('th', { scope: 'col', text: 'Assigned to' }),
        el('th', { scope: 'col', text: 'Updated' }));
    const body = el('tbody');
    data.reviews.forEach(review => {
        body.append(el('tr', {},
            el('td', { class: 'num cell-muted', 'data-label': '#', text: review.id }),
            el('td', { 'data-label': 'Invoice' },
                el('a', { class: 'mono file-cell review-link', href: `#/review?id=${review.id}`, text: review.filename }),
                el('span', { class: 'cell-sub' }, review.invoice_id ? el('span', { class: 'mono', text: review.invoice_id }) : el('span', { text: 'No transaction ID' }))),
            el('td', { 'data-label': 'Status' }, badge(review.validation_status), duplicateTag(review.duplicate)),
            el('td', { class: 'num mono', 'data-label': 'Amount', text: review.amount || '–' }),
            el('td', { class: 'num', 'data-label': 'Risk' }, riskCell(review)),
            el('td', { 'data-label': 'Review' }, stateBadge(review.state)),
            el('td', { 'data-label': 'Assigned to' }, review.assignee ? el('span', { text: review.assignee }) : el('span', { class: 'cell-muted', text: 'Unassigned' })),
            el('td', { 'data-label': 'Updated' },
                el('time', { class: 'time-main', datetime: review.updated_at, text: formatRelative(review.updated_at, now) || 'just now' }))));
    });
    const table = el('table', { class: 'data-table review-table stack-on-mobile' },
        el('caption', { class: 'visually-hidden', text: 'Review queue, newest first' }),
        el('thead', {}, header), body);
    const note = data.matching > data.reviews.length
        ? `Showing the newest ${formatNumber(data.reviews.length)} of ${formatNumber(data.matching)} reviews.`
        : `${formatNumber(data.matching)} ${data.matching === 1 ? 'review' : 'reviews'}, newest first.`;
    clear(dom.output).append(el('div', { class: 'table-scroll' }, table), el('div', { class: 'table-more' }, el('p', { text: note })));
}

// ---------- One review ----------

async function loadDetail(id) {
    const token = ++requestId;
    clear(dom.detail).append(el('div', { class: 'glass-panel' }, el('div', { class: 'skeleton skeleton-line' }), el('div', { class: 'skeleton skeleton-block' })));
    try {
        const review = await getJson(`/api/reviews/${id}`);
        if (token !== requestId) return;
        renderDetail(review);
        document.title = `Review #${review.id} · SupplyTrace`;
    } catch (error) {
        if (token !== requestId) return;
        const missing = error.status === 404;
        clear(dom.detail).append(errorCard(missing ? 'This review does not exist' : 'The review could not be loaded',
            missing ? `There is no review #${id}. It may have been on a demo server that restarted.` : error.message,
            missing ? null : () => loadDetail(id)));
    }
}

function metaItem(label, ...value) {
    return el('div', { class: 'sub-metric' }, el('span', { class: 'sub-label', text: label }), el('span', { class: 'sub-value' }, ...value));
}

function renderDetail(review) {
    const result = review.result;
    const closed = review.state !== 'open';
    const decision = closed ? review.history.filter(e => e.action === review.state).at(-1) : null;

    const head = el('section', { class: 'glass-panel review-head' },
        el('a', { class: 'back-link', href: '#/review' }, icon('arrow-right', 'flip'), 'Back to the queue'),
        el('div', { class: 'review-title-row' },
            el('h2', { class: 'review-title' }, el('span', { class: 'cell-muted', text: `#${review.id}` }), el('span', { class: 'mono', text: review.filename })),
            el('div', { class: 'badge-group' }, badge(review.validation_status), stateBadge(review.state))),
        el('p', { class: 'review-reason', text: review.reason }),
        duplicateNote(result.duplicate),
        el('div', { class: 'metrics-subgrid' },
            metaItem('Transaction ID', review.invoice_id ? el('span', { class: 'mono', text: review.invoice_id }) : el('span', { class: 'muted', text: 'not found' })),
            metaItem('Amount', review.amount ? el('span', { class: 'mono', text: review.amount }) : el('span', { class: 'muted', text: 'not found' })),
            metaItem('Risk score', typeof review.risk_score === 'number' ? formatPercent(review.risk_score) : 'N/A'),
            metaItem('Assigned to', review.assignee || el('span', { class: 'muted', text: 'nobody yet' })),
            metaItem('Added', formatDateTime(review.created_at))),
        decision ? el('div', { class: `review-decision review-${review.state}` }, icon(STATE_ICON[review.state]),
            el('span', {}, el('strong', { text: `${STATE_TEXT[review.state]} by ${decision.actor}` }), `: ${decision.comment}`)) : null);

    const main = el('div', { class: 'review-main' },
        checklistSection(result), riskBlock(result),
        el('p', { class: 'muted review-xml-note', text: 'The XML itself is not stored. This is the analysis as it was when the file was checked.' }));

    const side = el('div', { class: 'review-side' }, actionsPanel(review), historyPanel(review));

    clear(dom.detail).append(head, el('div', { class: 'review-grid' }, side, main));
}

function checklistSection(result) {
    const section = checklist(result, { interactive: false });
    section.classList.add('glass-panel');
    return section;
}

function showFormError(box, message, focusNode) {
    box.textContent = message;
    box.hidden = false;
    focusNode?.focus();
}

function actionsPanel(review) {
    const closed = review.state !== 'open';
    const error = el('p', { class: 'inline-error', role: 'alert', hidden: true });
    const comment = el('textarea', {
        id: 'review-comment', rows: '3', maxlength: '2000', class: 'text-input',
        placeholder: closed ? 'Add a note to the history' : 'What did you check? Required to approve or reject.',
    });
    const reviewer = el('input', { id: 'review-assign-name', type: 'text', maxlength: '60', class: 'text-input', value: review.assignee || '', placeholder: 'Reviewer name', autocomplete: 'off' });

    // Runs one action, then redraws the review from the server's answer.
    async function send(button, path, body, message) {
        error.hidden = true;
        button.disabled = true;
        try {
            const updated = await postJson(`/api/reviews/${review.id}/${path}`, body);
            renderDetail(updated);
            document.dispatchEvent(new CustomEvent('reviews-changed'));
            toast(message);
            announce(message);
        } catch (e) {
            button.disabled = false;
            showFormError(error, e.message);
            if (e.status === 409) loadDetail(review.id); // someone else got there first
        }
    }

    function actor() {
        const name = dom.name.value.trim();
        if (name) return name;
        showFormError(error, 'Enter your name at the top of the page first, so the history shows who did this.', dom.name);
        return null;
    }

    function needComment() {
        const text = comment.value.trim();
        if (text) return text;
        showFormError(error, 'A comment is required.', comment);
        return null;
    }

    const assign = el('button', { type: 'button', class: 'btn btn-secondary' }, icon('user'), 'Assign');
    assign.addEventListener('click', () => {
        const name = actor();
        const who = reviewer.value.trim();
        if (!name) return;
        if (!who) return showFormError(error, 'Enter the reviewer to assign.', reviewer);
        send(assign, 'assign', { reviewer: who, actor: name }, `Assigned to ${who}.`);
    });
    const assignMe = el('button', { type: 'button', class: 'btn-text' }, 'Assign to me');
    assignMe.addEventListener('click', () => {
        reviewer.value = dom.name.value.trim();
        assign.click();
    });

    const decide = (verb, path, label, cls) => {
        const button = el('button', { type: 'button', class: `btn ${cls}` }, icon(verb === 'approve' ? 'check-circle' : 'x-circle'), label);
        button.addEventListener('click', () => {
            const name = actor();
            const text = name && needComment();
            if (text) send(button, path, { actor: name, comment: text }, `Review #${review.id} ${STATE_TEXT[path === 'approve' ? 'approved' : 'rejected'].toLowerCase()}.`);
        });
        return button;
    };
    const addComment = el('button', { type: 'button', class: 'btn btn-outline' }, icon('message'), 'Add comment');
    addComment.addEventListener('click', () => {
        const name = actor();
        const text = name && needComment();
        if (text) send(addComment, 'comments', { actor: name, comment: text }, 'Comment added.');
    });

    const children = [el('h3', { class: 'sub-label', text: closed ? 'Decided' : 'Your action' })];
    if (!closed) {
        children.push(
            el('div', { class: 'form-row' },
                el('label', { for: 'review-assign-name', class: 'field-label', text: 'Assign to' }),
                el('div', { class: 'inline-form' }, reviewer, assign),
                assignMe));
    }
    children.push(
        el('div', { class: 'form-row' },
            el('label', { for: 'review-comment', class: 'field-label', text: closed ? 'Comment' : 'Comment (required to approve or reject)' }),
            comment),
        error,
        el('div', { class: 'result-actions review-buttons' },
            closed ? null : decide('reject', 'reject', 'Reject', 'btn-secondary'),
            closed ? null : decide('approve', 'approve', 'Approve', 'btn-primary'),
            addComment));
    return el('section', { class: 'glass-panel review-actions' }, children);
}

function historyPanel(review) {
    const items = review.history.map(event => el('li', { class: `history-item history-${event.action}` },
        el('span', { class: 'history-icon', 'aria-hidden': 'true' }, icon(ACTION_ICON[event.action] || 'info')),
        el('div', { class: 'history-body' },
            el('p', { class: 'history-line' },
                el('strong', { text: event.actor }), ` · ${ACTION_TEXT[event.action] || event.action} · `,
                el('time', { datetime: event.at, title: formatDateTime(event.at), text: formatRelative(event.at) || 'just now' })),
            event.comment ? el('p', { class: 'history-comment', text: event.comment }) : null)));
    return el('section', { class: 'glass-panel review-history' },
        el('h3', { class: 'sub-label', text: `History (${review.history.length})` }),
        el('p', { class: 'muted history-note', text: 'Append-only: entries are never edited or removed.' }),
        el('ol', { class: 'history-list' }, items));
}
