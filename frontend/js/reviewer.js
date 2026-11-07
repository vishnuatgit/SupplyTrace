// The name the person gives as the author of their review actions. There is no
// sign-in in the demo, so it is remembered in this browser only.

const KEY = 'supplytrace.reviewer';

export function getReviewerName() {
    try {
        return localStorage.getItem(KEY) || '';
    } catch {
        return '';
    }
}

export function setReviewerName(name) {
    try {
        localStorage.setItem(KEY, name);
    } catch {
        // storage unavailable: the name lasts for this page only
    }
}
