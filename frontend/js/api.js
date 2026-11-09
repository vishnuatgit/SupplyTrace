// Talking to the SupplyTrace API. Every helper throws an Error whose message
// is safe and useful to show to the person using the page.

// Keep in step with the server (SUPPLYTRACE_MAX_UPLOAD_BYTES, MAX_BATCH_FILES).
const MAX_UPLOAD_BYTES = 1_000_000;
export const MAX_BATCH_FILES = 20;

const TOO_LARGE_MESSAGE = 'File is too large. The demo accepts XML files up to 1 MB.';
const NOT_XML_MESSAGE = 'Only .xml files are supported';
const EMPTY_MESSAGE = 'The file is empty';

const OFFLINE_MESSAGE = 'Could not reach the server. If the demo has been idle it may be waking up (the free server sleeps when idle). Wait a minute and try again, and check your connection.';
const UNEXPECTED_MESSAGE = 'The server sent an unexpected response. Try again in a minute; if it keeps happening, reload the page.';

function messageForStatus(status) {
    if (status === 413) return TOO_LARGE_MESSAGE;
    if (status === 429) return 'Too many requests. Wait a few seconds, then try again.';
    if (status === 502 || status === 503 || status === 504) {
        return 'The server is starting up or busy (the free server may be waking up). Try again in a minute.';
    }
    if (status >= 500) return `The server ran into a problem (HTTP ${status}). Try again in a minute; if it keeps failing, try a different file.`;
    return `The request failed (HTTP ${status}). Check the file and try again.`;
}

// fetch() that turns network failures and error responses (JSON or not, e.g.
// an HTML page from a proxy while the host wakes up) into a readable Error.
// error.status tells a bad file (4xx) from a server problem; error.body keeps
// the JSON error body (for malformed XML it has line, column and reason).
async function request(url, options) {
    let response;
    try {
        response = await fetch(url, options);
    } catch {
        const error = new Error(OFFLINE_MESSAGE);
        error.status = 0;
        throw error;
    }
    if (!response.ok) {
        let body = null;
        if ((response.headers.get('content-type') || '').includes('application/json')) {
            try {
                body = await response.json();
            } catch {
                // fall back to the generic message
            }
        }
        const detail = typeof body?.detail === 'string' ? body.detail : null;
        const error = new Error(detail || messageForStatus(response.status));
        error.status = response.status;
        error.body = body;
        throw error;
    }
    return response;
}

async function readJson(response) {
    if (!(response.headers.get('content-type') || '').includes('application/json')) {
        throw new Error(UNEXPECTED_MESSAGE);
    }
    try {
        return await response.json();
    } catch {
        throw new Error(UNEXPECTED_MESSAGE);
    }
}

export async function getJson(url) {
    return readJson(await request(url));
}

export async function getText(url) {
    return (await request(url)).text();
}

function formOf(field, files) {
    const form = new FormData();
    files.forEach(file => form.append(field, file));
    return form;
}

// Uploads files as multipart form data under one field name and returns the JSON reply.
export async function postFiles(url, field, files, extra = {}) {
    const form = formOf(field, files);
    Object.entries(extra).forEach(([name, value]) => form.append(name, value));
    return readJson(await request(url, { method: 'POST', body: form }));
}

// Uploads files to an endpoint that answers in newline-delimited JSON, and
// calls onLine(object) for each line as soon as it arrives.
export async function postFilesStream(url, field, files, onLine) {
    const response = await request(url, { method: 'POST', body: formOf(field, files) });
    if (!response.body) throw new Error(UNEXPECTED_MESSAGE);
    const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
    let buffer = '';
    const flush = text => {
        if (!text.trim()) return;
        let line;
        try {
            line = JSON.parse(text);
        } catch {
            throw new Error(UNEXPECTED_MESSAGE);
        }
        onLine(line);
    };
    for (;;) {
        let chunk;
        try {
            chunk = await reader.read();
        } catch {
            throw new Error('The connection dropped before the batch finished. Please try again.');
        }
        if (chunk.done) break;
        buffer += chunk.value;
        const lines = buffer.split('\n');
        buffer = lines.pop();
        lines.forEach(flush);
    }
    flush(buffer);
}

// The checks the server makes before parsing, so obvious problems are caught
// without an upload. Returns an error message, or null when the file is fine.
export function precheckFile(file) {
    if (!file.name.toLowerCase().endsWith('.xml')) return NOT_XML_MESSAGE;
    if (file.size > MAX_UPLOAD_BYTES) return TOO_LARGE_MESSAGE;
    if (file.size === 0) return EMPTY_MESSAGE;
    return null;
}

// Sends a JSON body (POST or PUT) and returns the JSON reply.
async function sendJson(method, url, body) {
    return readJson(await request(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    }));
}

export const postJson = (url, body) => sendJson('POST', url, body);
export const putJson = (url, body) => sendJson('PUT', url, body);
