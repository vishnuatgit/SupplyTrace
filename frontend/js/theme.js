// Applies the saved colour theme before the page paints, so it never flashes.
// Dark is the default; the toggle in the header saves the visitor's choice.
(function () {
    var theme = 'dark';
    try {
        if (localStorage.getItem('supplytrace.theme') === 'light') theme = 'light';
    } catch (e) {
        // storage unavailable (private mode, blocked): keep the default
    }
    document.documentElement.setAttribute('data-theme', theme);
})();
