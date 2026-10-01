// SPL Auction System — Enforced Light Theme Controller
(function() {
    // 1. Instant anti-flash Light Theme initialization (Light Theme Only)
    document.documentElement.setAttribute('data-theme', 'light');
    if (document.body) {
        document.body.setAttribute('data-theme', 'light');
    }
    try {
        localStorage.removeItem('spl_theme');
        localStorage.removeItem('spl-theme');
    } catch (e) {}
})();

document.addEventListener('DOMContentLoaded', function() {
    // Enforce light theme
    document.documentElement.setAttribute('data-theme', 'light');
    if (document.body) {
        document.body.setAttribute('data-theme', 'light');
    }

    // Form Loading state handler
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
        form.addEventListener('submit', function(e) {
            const submitBtn = form.querySelector('button[type="submit"]');
            if (submitBtn && !submitBtn.disabled) {
                const loadingText = submitBtn.getAttribute('data-loading-text') || 'Processing...';
                submitBtn.disabled = true;
                submitBtn.innerHTML = `<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>${loadingText}`;
            }
        });
    });
});
