// Hand-drawn charts (inline SVG and plain HTML), fed only by real API data.
// Colours come from CSS classes, so both themes style them; every chart has a
// text equivalent (legend, labels or a table) so nothing depends on colour alone.

import { el, svg, clear, formatNumber, formatPercent, statusText } from './ui.js';

export const STATUS_ORDER = ['VALID', 'INVALID', 'REQUIRES_REVIEW', 'REJECTED'];

// ---------- Tooltip: one floating element for every [data-tip] mark ----------

let tooltip;

function showTip(text, x, y) {
    tooltip.textContent = text;
    tooltip.hidden = false;
    const { width, height } = tooltip.getBoundingClientRect();
    const left = Math.min(Math.max(8, x - width / 2), window.innerWidth - width - 8);
    const top = y - height - 12 < 8 ? y + 16 : y - height - 12;
    tooltip.style.transform = `translate(${Math.round(left)}px, ${Math.round(top)}px)`;
}

export function initChartTooltips() {
    tooltip = document.getElementById('chart-tooltip');
    const hide = () => { tooltip.hidden = true; };
    document.addEventListener('pointermove', event => {
        const mark = event.target.closest?.('[data-tip]');
        if (mark) showTip(mark.dataset.tip, event.clientX, event.clientY);
        else hide();
    });
    document.addEventListener('focusin', event => {
        const mark = event.target.closest?.('[data-tip]');
        if (!mark) return hide();
        const box = mark.getBoundingClientRect();
        showTip(mark.dataset.tip, box.left + box.width / 2, box.top);
    });
    document.addEventListener('focusout', hide);
    window.addEventListener('scroll', hide, { passive: true });
}

// ---------- Ring: the share of each status, valid share in the middle ----------

export function statusRing(container, counts, { centerLabel = 'valid', note = null } = {}) {
    const total = STATUS_ORDER.reduce((sum, s) => sum + (counts[s] || 0), 0);
    const r = 50;
    const circumference = 2 * Math.PI * r;
    const gap = total > 0 && STATUS_ORDER.filter(s => counts[s]).length > 1 ? 3 : 0;
    const ring = svg('svg', { viewBox: '0 0 120 120', class: 'ring', role: 'img', 'aria-label': ringLabel(counts, total) },
        svg('circle', { class: 'ring-track', cx: 60, cy: 60, r }));
    let offset = 0;
    for (const status of STATUS_ORDER) {
        const n = counts[status] || 0;
        if (!n) continue;
        const length = (n / total) * circumference;
        const visible = Math.max(0.5, length - gap);
        ring.append(svg('circle', {
            class: `ring-seg seg-${status}`, cx: 60, cy: 60, r,
            'stroke-dasharray': `${visible} ${circumference - visible}`,
            'stroke-dashoffset': String(-offset),
            transform: 'rotate(-90 60 60)',
            'data-tip': `${statusText(status)}: ${formatNumber(n)} (${formatPercent((n / total) * 100)})`,
        }));
        offset += length;
    }
    const share = total ? Math.round(((counts.VALID || 0) / total) * 100) : null;
    const center = el('div', { class: 'ring-center' },
        el('span', { class: 'ring-value', text: share === null ? '–' : `${share}%` }),
        el('span', { class: 'ring-caption', text: centerLabel }));
    const legend = el('ul', { class: 'legend' }, STATUS_ORDER.filter(s => s !== 'REJECTED' || counts[s]).map(status => el('li', {},
        el('span', { class: `legend-dot seg-${status}`, 'aria-hidden': 'true' }),
        el('span', { class: 'legend-label', text: statusText(status) }),
        el('span', { class: 'legend-value', text: formatNumber(counts[status] || 0) }))));
    clear(container).append(el('div', { class: 'ring-wrap' }, ring, center), legend,
        note ? el('p', { class: 'chart-note', text: note }) : null);
}

function ringLabel(counts, total) {
    if (!total) return 'No files yet';
    return STATUS_ORDER.filter(s => counts[s]).map(s => `${statusText(s)} ${counts[s]}`).join(', ');
}

// ---------- Charts drawn at their real width ----------

// SVG charts are drawn with a viewBox as wide as their container, so text is
// always rendered at its CSS size (never scaled down), and redrawn when the
// container's width changes.
const sized = new WeakMap(); // container -> { width, redraw }
const resizer = typeof ResizeObserver === 'function'
    ? new ResizeObserver(entries => {
        for (const entry of entries) {
            const item = sized.get(entry.target);
            const width = Math.round(entry.contentRect.width);
            if (item && width && Math.abs(width - item.width) > 4) item.redraw();
        }
    })
    : null;

function drawAtWidth(container, draw, fallback) {
    const width = Math.round(container.clientWidth);
    sized.set(container, { width, redraw: () => drawAtWidth(container, draw, fallback) });
    resizer?.observe(container);
    draw(width || fallback);
}

// ---------- Histogram: risk scores in 10 bins, split by LOW / HIGH flag ----------

export function riskHistogram(container, bins, options = {}) {
    drawAtWidth(container, width => drawHistogram(container, bins, width, options), 240);
}

function drawHistogram(container, bins, W, { threshold = 50 } = {}) {
    const H = 168;
    const pad = { top: 18, right: 6, bottom: 40, left: 6 };
    const plotW = W - pad.left - pad.right;
    const plotH = H - pad.top - pad.bottom;
    const max = Math.max(1, ...bins.map(b => b.low + b.high));
    const step = plotW / bins.length;
    const barW = Math.max(4, step - 4);
    const y = v => pad.top + plotH - (v / max) * plotH;
    const x = v => pad.left + (v / 100) * plotW;

    const chart = svg('svg', { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: 'histogram', role: 'img', 'aria-label': histogramLabel(bins) });
    chart.append(svg('line', { class: 'grid-line', x1: pad.left, x2: W - pad.right, y1: y(0), y2: y(0) }));
    bins.forEach((bin, i) => {
        const left = pad.left + i * step + (step - barW) / 2;
        const total = bin.low + bin.high;
        const group = svg('g', { class: 'bin', 'data-tip': `${bin.from}–${bin.to}%: ${filesText(total)} (${bin.low} low, ${bin.high} high)` });
        group.append(svg('rect', { class: 'hit', x: pad.left + i * step, y: pad.top, width: step, height: plotH }));
        let top = y(0);
        for (const [band, n] of [['low', bin.low], ['high', bin.high]]) {
            if (!n) continue;
            const h = Math.max(2, (n / max) * plotH);
            top -= h;
            group.append(svg('rect', { class: `bar bar-${band}`, x: left, y: top, width: barW, height: h - (band === 'low' && bin.high ? 1.5 : 0), rx: 2 }));
        }
        if (total) group.append(svg('text', { class: 'bar-label', x: left + barW / 2, y: top - 5, 'text-anchor': 'middle', text: formatNumber(total) }));
        chart.append(group);
    });
    chart.append(svg('line', { class: 'threshold', x1: x(threshold), x2: x(threshold), y1: pad.top - 8, y2: y(0) }));
    [0, 25, 50, 75, 100].forEach(v => {
        chart.append(svg('line', { class: 'tick', x1: x(v), x2: x(v), y1: y(0), y2: y(0) + 4 }));
        chart.append(svg('text', {
            class: 'axis-text', x: x(v), y: y(0) + 17,
            'text-anchor': v === 0 ? 'start' : v === 100 ? 'end' : 'middle', text: `${v}%`,
        }));
    });
    chart.append(svg('text', { class: 'axis-title', x: pad.left + plotW / 2, y: H - 3, 'text-anchor': 'middle', text: 'Risk score' }));

    const low = bins.reduce((s, b) => s + b.low, 0);
    const high = bins.reduce((s, b) => s + b.high, 0);
    const split = el('div', { class: 'flag-split', role: 'img', 'aria-label': `${formatNumber(low)} low risk, ${formatNumber(high)} high risk` },
        low ? el('span', { class: 'flag-seg seg-low', style: { flexGrow: String(low) }, 'data-tip': `Low: ${filesText(low)} (${formatPercent((low / (low + high)) * 100)})` }) : null,
        high ? el('span', { class: 'flag-seg seg-high', style: { flexGrow: String(high) }, 'data-tip': `High: ${filesText(high)} (${formatPercent((high / (low + high)) * 100)})` }) : null);
    const legend = el('ul', { class: 'legend legend-inline' },
        el('li', {}, el('span', { class: 'legend-dot bar-low', 'aria-hidden': 'true' }), el('span', { class: 'legend-label', text: 'Low' }), el('span', { class: 'legend-value', text: formatNumber(low) })),
        el('li', {}, el('span', { class: 'legend-dot bar-high', 'aria-hidden': 'true' }), el('span', { class: 'legend-label', text: 'High (over 50%)' }), el('span', { class: 'legend-value', text: formatNumber(high) })));
    clear(container).append(chart, split, legend,
        el('p', { class: 'chart-note', text: 'Files per 10-point bin. The dashed line is the 50% HIGH threshold.' }));
}

const filesText = n => `${formatNumber(n)} ${n === 1 ? 'file' : 'files'}`;

function histogramLabel(bins) {
    const parts = bins.filter(b => b.low + b.high).map(b => `${b.from} to ${b.to}%: ${b.low + b.high}`);
    return `Risk score histogram, files per 10-point bin. ${parts.join('; ') || 'No scored files'}.`;
}

// ---------- Horizontal bars (reasons, importances, rules broken) ----------

// items: [{ label, value, tone, display }]
export function barList(container, items, { max, empty = 'Nothing to show yet.' } = {}) {
    if (!items.length) {
        clear(container).append(el('p', { class: 'chart-empty', text: empty }));
        return;
    }
    const top = max ?? Math.max(...items.map(i => i.value), 1);
    clear(container).append(el('ul', { class: 'bar-list' }, items.map(item => el('li', {
        'data-tip': `${item.label}: ${item.display ?? formatNumber(item.value)}`,
    },
    el('span', { class: 'bar-name', text: item.label }),
    el('span', { class: 'bar-track', 'aria-hidden': 'true' },
        el('span', { class: `bar-fill tone-${item.tone || 'primary'}`, style: { width: `${Math.max(1.5, (item.value / top) * 100)}%` } })),
    el('span', { class: 'bar-value', text: item.display ?? formatNumber(item.value) })))));
}

// ---------- Split bar: one stacked bar of statuses ----------

export function splitBar(container, counts, { label = 'Status split' } = {}) {
    const total = STATUS_ORDER.reduce((sum, s) => sum + (counts[s] || 0), 0);
    if (!total) {
        clear(container);
        return;
    }
    const bar = el('div', { class: 'split-bar', role: 'img', 'aria-label': `${label}: ${ringLabel(counts, total)}` },
        STATUS_ORDER.filter(s => counts[s]).map(status => el('span', {
            class: `split-seg seg-${status}`,
            style: { flexGrow: String(counts[status]) },
            'data-tip': `${statusText(status)}: ${formatNumber(counts[status])} (${formatPercent((counts[status] / total) * 100)})`,
        })));
    clear(container).append(bar);
}

// ---------- Strip plot: one dot per file on a 0-100% risk axis ----------

// rows: [{ score, status, label }]; onSelect(index) is called for a click or Enter.
export function riskStrip(container, rows, options = {}) {
    drawAtWidth(container, width => drawStrip(container, rows, Math.min(720, Math.max(280, width)), options), 560);
}

function drawStrip(container, rows, W, { threshold = 50, onSelect } = {}) {
    const pad = { left: 14, right: 14, top: 22, bottom: 30 };
    const plotW = W - pad.left - pad.right;
    const R = 7;
    const scored = rows.map((row, index) => ({ ...row, index })).filter(row => typeof row.score === 'number');
    // Stack dots that would overlap into rows (a small beeswarm).
    const lanes = [];
    const placed = scored.sort((a, b) => a.score - b.score).map(row => {
        const x = pad.left + (row.score / 100) * plotW;
        let lane = lanes.findIndex(lastX => x - lastX >= 2 * R + 2);
        if (lane < 0) lane = lanes.length;
        lanes[lane] = x;
        return { ...row, x, lane };
    });
    const laneCount = Math.max(1, lanes.length);
    const H = pad.top + laneCount * (2 * R + 3) + pad.bottom;
    const base = H - pad.bottom;
    const chart = svg('svg', { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: 'strip', role: 'group', 'aria-label': 'Risk score of each file' });
    chart.append(svg('line', { class: 'axis-line', x1: pad.left, x2: W - pad.right, y1: base, y2: base }));
    [0, 25, 50, 75, 100].forEach(v => {
        const x = pad.left + (v / 100) * plotW;
        chart.append(svg('line', { class: 'tick', x1: x, x2: x, y1: base, y2: base + 4 }));
        chart.append(svg('text', { class: 'axis-text', x, y: base + 18, 'text-anchor': v === 0 ? 'start' : v === 100 ? 'end' : 'middle', text: `${v}%` }));
    });
    const tx = pad.left + (threshold / 100) * plotW;
    chart.append(svg('line', { class: 'threshold', x1: tx, x2: tx, y1: 4, y2: base }));
    chart.append(svg('text', { class: 'threshold-text', x: tx + 6, y: 14, text: 'HIGH above 50%' }));
    placed.forEach(row => {
        const cy = base - R - 3 - row.lane * (2 * R + 3);
        const dot = svg('circle', {
            class: `dot seg-${row.status}`, cx: row.x, cy, r: R, tabindex: '0', role: 'button',
            'aria-label': `${row.label}: ${statusText(row.status)}, risk ${formatPercent(row.score)}. Open details.`,
            'data-tip': `${row.label} · ${statusText(row.status)} · ${formatPercent(row.score)}`,
        });
        if (onSelect) {
            dot.addEventListener('click', () => onSelect(row.index));
            dot.addEventListener('keydown', event => {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    onSelect(row.index);
                }
            });
        }
        chart.append(dot);
    });
    const missing = rows.length - scored.length;
    clear(container).append(chart);
    if (missing) container.append(el('p', { class: 'chart-note', text: `${missing} rejected ${missing === 1 ? 'file has' : 'files have'} no score.` }));
}

// ---------- Risk gauge: a half ring from 0 to 100% ----------

export function riskGauge(score, flag, { threshold = 50 } = {}) {
    const r = 52;
    const half = Math.PI * r;
    const value = Math.max(0, Math.min(100, score));
    const angle = Math.PI * (1 - threshold / 100);
    const tick = (radius) => [60 + radius * Math.cos(angle), 64 - radius * Math.sin(angle)];
    const [x1, y1] = tick(r - 9);
    const [x2, y2] = tick(r + 9);
    return svg('svg', { viewBox: '0 0 120 70', class: 'gauge', role: 'img', 'aria-label': `Risk score ${formatPercent(value)}, ${flag}` },
        svg('path', { class: 'gauge-track', d: `M ${60 - r} 64 A ${r} ${r} 0 0 1 ${60 + r} 64` }),
        svg('path', {
            class: `gauge-fill gauge-${flag}`, d: `M ${60 - r} 64 A ${r} ${r} 0 0 1 ${60 + r} 64`,
            'stroke-dasharray': `${(value / 100) * half} ${half}`,
        }),
        svg('line', { class: 'gauge-tick', x1, y1, x2, y2 }));
}

// ---------- Waterfall: base rate, each feature's push, the score ----------

// drivers: { base, contributions: [{ label, points, value }] } in percentage points.
// The running total can pass 100% on the way (a big push up, then smaller ones
// down), so the axis widens to fit every bar instead of clipping them.
export function riskWaterfall(container, drivers, score, flag, { top = 4 } = {}) {
    const significant = drivers.contributions.slice(0, top).filter(d => Math.abs(d.points) >= 0.05);
    const rest = drivers.contributions.slice(significant.length);
    const restPoints = rest.reduce((sum, d) => sum + d.points, 0);
    const steps = significant.map(d => ({ label: d.label, detail: valueText(d), points: d.points }));
    if (rest.length && Math.abs(restPoints) >= 0.05) {
        steps.push({ label: `${rest.length} other features`, detail: 'combined', points: restPoints });
    }

    let running = drivers.base;
    const moves = steps.map(step => {
        const from = running;
        running += step.points;
        return { ...step, from, to: running };
    });
    const ends = [0, 100, drivers.base, score, ...moves.flatMap(m => [m.from, m.to])];
    const lo = Math.min(...ends);
    const hi = Math.max(...ends);
    const x = v => ((v - lo) / (hi - lo)) * 100;
    const bar = (from, to) => ({ left: x(Math.min(from, to)), width: x(Math.max(from, to)) - x(Math.min(from, to)) });
    const mid = x(50);

    const rows = [row('Base rate', 'share of failed files in training', bar(0, drivers.base), mid, 'base', formatPercent(drivers.base))];
    for (const move of moves) {
        const sign = move.points >= 0 ? '+' : '−';
        rows.push(row(move.label, move.detail, bar(move.from, move.to), mid,
            move.points >= 0 ? 'up' : 'down', `${sign}${Math.abs(move.points).toFixed(1)} pts`));
    }
    rows.push(row('Risk score', flag === 'HIGH' ? 'flagged HIGH' : 'flagged LOW', bar(0, score), mid, `total-${flag}`, formatPercent(score), true));

    const ticks = [0, 50, 100].map(v => el('span', { class: 'wf-tick', style: { left: `${x(v)}%` }, text: `${v}%` }));
    const axis = el('div', { class: 'wf-row wf-axis-row', 'aria-hidden': 'true' },
        el('span'), el('span', { class: 'wf-axis' }, ticks), el('span'));
    clear(container).append(el('ol', { class: 'waterfall' }, rows), axis,
        el('p', { class: 'wf-caption', text: 'pts = percentage points of risk. Bars start where the previous one ended.' }));
}

function valueText(driver) {
    if (driver.label.startsWith('Optional')) return `${driver.value} of 4 missing`;
    if (driver.label === 'Nesting depth') return `${driver.value} levels`;
    return driver.value ? 'yes' : 'no';
}

function row(label, detail, { left, width }, mid, kind, display, total = false) {
    return el('li', { class: `wf-row wf-${kind}${total ? ' wf-total' : ''}` },
        el('span', { class: 'wf-label' }, el('span', { text: label }), el('span', { class: 'wf-detail', text: detail })),
        el('span', { class: 'wf-track', 'aria-hidden': 'true' },
            el('span', { class: 'wf-mid', style: { left: `${mid}%` } }),
            el('span', { class: 'wf-bar', style: { left: `${left}%`, width: `${Math.max(0.8, width)}%` } })),
        el('span', { class: 'wf-value', text: display }));
}

// ---------- Confusion matrix (2 x 2) ----------

export function confusionMatrix(title, m) {
    const cells = [
        ['true_positives', 'Failed, flagged', 'good'],
        ['false_negatives', 'Failed, missed', 'bad'],
        ['false_positives', 'Processed, flagged', 'bad'],
        ['true_negatives', 'Processed, passed', 'good'],
    ];
    const total = cells.reduce((sum, [key]) => sum + m[key], 0) || 1;
    return el('figure', { class: 'matrix' },
        el('figcaption', { text: title }),
        el('div', { class: 'matrix-grid' },
            el('span', { class: 'matrix-corner', 'aria-hidden': 'true' }),
            el('span', { class: 'matrix-col', text: 'Flagged' }),
            el('span', { class: 'matrix-col', text: 'Passed' }),
            el('span', { class: 'matrix-row', text: 'Failed' }),
            cell(m.true_positives, total, cells[0]),
            cell(m.false_negatives, total, cells[1]),
            el('span', { class: 'matrix-row', text: 'Processed' }),
            cell(m.false_positives, total, cells[2]),
            cell(m.true_negatives, total, cells[3])));
}

function cell(n, total, [, label, kind]) {
    return el('span', {
        class: `matrix-cell matrix-${kind}${n ? '' : ' is-zero'}`,
        style: { '--share': String(n / total) },
        'data-tip': `${label}: ${n}`,
    }, el('span', { class: 'matrix-n', text: formatNumber(n) }), el('span', { class: 'matrix-label', text: label }));
}
