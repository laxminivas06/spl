// SPL — Sphoorthy Premier League Auction System JS

document.addEventListener('DOMContentLoaded', function() {
    // Intercept native fetch to handle 401 Unauthorized responses globally
    var originalFetch = window.fetch;
    window.fetch = function() {
        return originalFetch.apply(this, arguments).then(function(response) {
            if (response.status === 401) {
                // If API returns unauthorized, immediately redirect user to login
                window.location.href = '/login';
            }
            return response;
        });
    };
});

// Handle browser back-forward navigation cache to ensure private pages are never restored after logout
window.addEventListener('pageshow', function(event) {
    if (event.persisted) {
        window.location.reload();
    }
});
