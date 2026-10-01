// SPL Auction System — Real-Time Polling, Audio & Control Client JS (Phase 5)

let auctionPollInterval = null;
let currentAuctionState = null;
let previousBid = 0;
let previousState = null;
let networkErrorCount = 0;
let soundEnabled = localStorage.getItem('spl_sound_enabled') === 'true';

function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]') || document.querySelector('input[name="csrf_token"]');
    return meta ? meta.value || meta.content : '';
}

function formatCurrencyJs(value) {
    try {
        const val = parseInt(value, 10);
        return 'Rs. ' + val.toLocaleString('en-IN');
    } catch (e) {
        return 'Rs. ' + value;
    }
}

// ==================== 1. WEB AUDIO API SYNTHESIZER ====================

function toggleSound() {
    soundEnabled = !soundEnabled;
    localStorage.setItem('spl_sound_enabled', soundEnabled ? 'true' : 'false');
    const soundBtn = document.getElementById('btn-toggle-sound');
    if (soundBtn) {
        soundBtn.innerHTML = soundEnabled ? '<i class="fa-solid fa-volume-high me-1"></i> SOUND ON' : '<i class="fa-solid fa-volume-xmark me-1"></i> SOUND OFF';
        soundBtn.className = soundEnabled ? 'btn btn-success btn-sm' : 'btn btn-outline-secondary btn-sm';
    }
}

function playAuctionSound(type) {
    if (!soundEnabled) return;
    try {
        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        if (!AudioCtx) return;
        const ctx = new AudioCtx();

        if (type === 'bid') {
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.type = 'sine';
            osc.frequency.setValueAtTime(800, ctx.currentTime);
            gain.gain.setValueAtTime(0.15, ctx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.15);
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.start();
            osc.stop(ctx.currentTime + 0.15);
        } else if (type === 'outbid') {
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.type = 'triangle';
            osc.frequency.setValueAtTime(450, ctx.currentTime);
            osc.frequency.setValueAtTime(300, ctx.currentTime + 0.1);
            gain.gain.setValueAtTime(0.2, ctx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.25);
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.start();
            osc.stop(ctx.currentTime + 0.25);
        } else if (type === 'sold') {
            const freqs = [523.25, 659.25, 783.99, 1046.50]; // C5, E5, G5, C6
            freqs.forEach((freq, idx) => {
                const osc = ctx.createOscillator();
                const gain = ctx.createGain();
                osc.type = 'sine';
                osc.frequency.setValueAtTime(freq, ctx.currentTime + idx * 0.08);
                gain.gain.setValueAtTime(0.2, ctx.currentTime + idx * 0.08);
                gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + idx * 0.08 + 0.25);
                osc.connect(gain);
                gain.connect(ctx.destination);
                osc.start(ctx.currentTime + idx * 0.08);
                osc.stop(ctx.currentTime + idx * 0.08 + 0.25);
            });
        } else if (type === 'unsold') {
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.type = 'sawtooth';
            osc.frequency.setValueAtTime(300, ctx.currentTime);
            osc.frequency.linearRampToValueAtTime(150, ctx.currentTime + 0.4);
            gain.gain.setValueAtTime(0.15, ctx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.4);
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.start();
            osc.stop(ctx.currentTime + 0.4);
        }
    } catch (e) {
        console.warn('Audio playback error:', e);
    }
}

// ==================== 2. FULLSCREEN TOGGLE ====================

function toggleFullscreen() {
    if (!document.fullscreenElement) {
        document.documentElement.requestFullscreen().catch(err => {
            console.warn(`Error attempting to enable fullscreen: ${err.message}`);
        });
    } else {
        if (document.exitFullscreen) {
            document.exitFullscreen();
        }
    }
}

// ==================== 3. CORE POLLING & RECOVERY ====================

function startAuctionPolling(intervalMs = 1000) {
    fetchAuctionState();
    if (!auctionPollInterval) {
        auctionPollInterval = setInterval(fetchAuctionState, intervalMs);
    }
    // Also setup periodic admin events polling if on admin page
    if (document.getElementById('admin-event-stream')) {
        setInterval(fetchAdminAuditEvents, 3000);
    }
}

function fetchAuctionState() {
    fetch('/api/auction/state')
        .then(res => {
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            return res.json();
        })
        .then(data => {
            // Hide connection error banner if active
            setNetworkBanner(false);
            networkErrorCount = 0;

            // Trigger bid audio if bid increased
            if (previousBid > 0 && data.current_bid > previousBid && data.status === 'BIDDING') {
                playAuctionSound('bid');
                triggerBidChangeAnimation(data.current_bid);
            }

            // Sound on SOLD or UNSOLD state transitions
            if (previousState && previousState !== data.status) {
                if (data.status === 'SOLD') playAuctionSound('sold');
                if (data.status === 'UNSOLD') playAuctionSound('unsold');
            }

            previousBid = data.current_bid;
            previousState = data.status;
            currentAuctionState = data;

            updateAuctionUi(data);
        })
        .catch(err => {
            networkErrorCount++;
            console.warn(`Auction polling failure #${networkErrorCount}:`, err);
            if (networkErrorCount >= 2) {
                setNetworkBanner(true);
            }
        });
}

function setNetworkBanner(show) {
    let banner = document.getElementById('network-interrupted-banner');
    if (show) {
        if (!banner) {
            banner = document.createElement('div');
            banner.id = 'network-interrupted-banner';
            banner.className = 'network-interrupted-banner';
            banner.innerHTML = '<i class="fa-solid fa-triangle-exclamation me-2"></i>CONNECTION INTERRUPTED — RECONNECTING TO SERVER...';
            document.body.prepend(banner);
        }
    } else {
        if (banner) banner.remove();
    }
}

// ==================== 4. UI ROUTER ====================

function updateAuctionUi(data) {
    const liveContainer = document.getElementById('live-projector-content');
    if (liveContainer) updateProjectorUi(data);

    const adminPanel = document.getElementById('admin-auction-panel');
    if (adminPanel) updateAdminUi(data);

    const franchiseCard = document.getElementById('franchise-bidding-card');
    if (franchiseCard) updateFranchiseUi(data);
}

// ==================== 5. PROJECTOR UI UPDATER ====================

function updateProjectorUi(data) {
    const statusWaiting = document.getElementById('projector-status-waiting');
    const playerCard = document.getElementById('projector-player-card');
    const soldCard = document.getElementById('projector-sold-card');
    const unsoldCard = document.getElementById('projector-unsold-card');

    if (!statusWaiting || !playerCard) return;

    // Reset all sub-cards hidden
    statusWaiting.classList.add('d-none');
    playerCard.classList.add('d-none');
    if (soldCard) soldCard.classList.add('d-none');
    if (unsoldCard) unsoldCard.classList.add('d-none');

    const status = data.status;

    if (status === 'WAITING' || !data.active_player) {
        statusWaiting.classList.remove('d-none');
        document.getElementById('projector-waiting-text').innerText = 'WAITING FOR NEXT PLAYER';
        return;
    }

    const p = data.active_player;

    if (status === 'SOLD' && soldCard) {
        // Calculate remaining seconds based on server sold_display_until timestamp (Requirements 1 & 8)
        let remainingSec = 10;
        if (data.sold_until_timestamp) {
            remainingSec = Math.max(0, Math.ceil((data.sold_until_timestamp - Date.now()) / 1000));
        } else if (data.sold_remaining_seconds !== undefined && data.sold_remaining_seconds !== null) {
            remainingSec = data.sold_remaining_seconds;
        }

        // Exactly 10 seconds completed: automatically clear sold screen (Requirements 1, 7, 8)
        if (remainingSec <= 0) {
            stopSoldConfetti();
            soldCard.classList.add('d-none');
            statusWaiting.classList.remove('d-none');
            const waitText = document.getElementById('projector-waiting-text');
            if (waitText) waitText.innerText = 'WAITING FOR NEXT PLAYER';
            fetch('/api/auction/clear-sold', { method: 'POST' }).catch(() => {});
            return;
        }

        soldCard.classList.remove('d-none');
        soldCard.className = 'spl-card border-success p-4 p-md-5 d-flex flex-column justify-content-center shadow-2xl animate-sold-celebration my-auto text-center position-relative overflow-hidden';
        
        const soldTimerEl = document.getElementById('sold-timer-seconds');
        if (soldTimerEl) soldTimerEl.innerText = remainingSec;

        const soldName = document.getElementById('sold-player-name');
        if (soldName) soldName.innerText = p.name;
        
        const soldPrice = document.getElementById('sold-final-price');
        if (soldPrice) soldPrice.innerText = formatCurrencyJs(data.sold_price || data.current_bid);
        
        const winningF = data.winning_franchise || data.highest_bidder;
        const soldWinTeam = document.getElementById('sold-winning-franchise');
        if (soldWinTeam) soldWinTeam.innerText = winningF ? winningF.name : 'AIVONTRAA FC';
        
        const soldWinLogo = document.getElementById('sold-winning-logo');
        if (soldWinLogo) {
            const wLogo = (winningF && winningF.logo) ? (winningF.logo.startsWith('http') ? winningF.logo : `/static/uploads/${winningF.logo}`) : '/static/uploads/default_logo.png';
            soldWinLogo.src = wLogo;
        }

        const soldPhoto = document.getElementById('sold-player-photo');
        if (soldPhoto) {
            const pPhoto = (p && p.photo) ? (p.photo.startsWith('http') ? p.photo : `/static/uploads/${p.photo}`) : '/static/uploads/default_player.png';
            soldPhoto.src = pPhoto;
        }

        startSoldConfetti();
        return;
    } else {
        stopSoldConfetti();
    }

    if (status === 'UNSOLD' && unsoldCard) {
        unsoldCard.classList.remove('d-none');
        unsoldCard.className = 'spl-card border-danger p-4 p-md-5 shadow-lg animate-sold my-auto text-center';
        const unsoldName = document.getElementById('unsold-player-name');
        if (unsoldName) unsoldName.innerText = p.name;
        const unsoldPrice = document.getElementById('unsold-base-price');
        if (unsoldPrice) unsoldPrice.innerText = formatCurrencyJs(p.base_price);
        const unsoldPhoto = document.getElementById('unsold-player-photo');
        if (unsoldPhoto) {
            const pPhoto = (p && p.photo) ? (p.photo.startsWith('http') ? p.photo : `/static/uploads/${p.photo}`) : '/static/uploads/default_player.png';
            unsoldPhoto.src = pPhoto;
        }
        return;
    }

    // Active Player View (PLAYER_PREVIEW, BIDDING, PAUSED, TIME_EXPIRED)
    playerCard.classList.remove('d-none');

    const imgEl = document.getElementById('projector-player-photo');
    if (imgEl) {
        const photoSrc = p.photo && p.photo.startsWith('http') ? p.photo : `/static/uploads/${p.photo || 'default_player.png'}`;
        imgEl.src = photoSrc;
    }

    // Player details neatly positioned in corner overlay (Requirement 8)
    const nameEl = document.getElementById('projector-player-name');
    if (nameEl) nameEl.innerText = p.name;
    const roleEl = document.getElementById('projector-player-role');
    if (roleEl) roleEl.innerText = p.role;
    const catEl = document.getElementById('projector-player-category');
    if (catEl) catEl.innerText = p.category;
    const branchEl = document.getElementById('projector-player-branch');
    if (branchEl) branchEl.innerText = p.branch || 'CSE';
    const yearEl = document.getElementById('projector-player-year');
    if (yearEl) yearEl.innerText = p.year ? (p.year.toString().toLowerCase().includes('year') ? p.year : `${p.year} Year`) : '3rd Year';

    const baseEl = document.getElementById('projector-base-price');
    if (baseEl) baseEl.innerText = formatCurrencyJs(p.base_price);
    const curBidEl = document.getElementById('projector-current-bid');
    if (curBidEl) curBidEl.innerText = formatCurrencyJs(data.current_bid);

    // 10-Second Digital Countdown Timer
    const timerEl = document.getElementById('projector-timer');
    if (timerEl) {
        if (status === 'BIDDING') {
            const sec = data.remaining_seconds != null ? data.remaining_seconds : 10;
            timerEl.innerText = `${sec}s`;
            if (sec <= 3) {
                timerEl.className = 'projector-timer-display timer-urgent';
            } else if (sec <= 6) {
                timerEl.className = 'projector-timer-display timer-warning';
            } else {
                timerEl.className = 'projector-timer-display text-cyan';
            }
        } else if (status === 'PAUSED') {
            timerEl.innerText = 'PAUSED';
            timerEl.className = 'projector-timer-display text-warning';
        } else if (status === 'PLAYER_PREVIEW') {
            timerEl.innerText = 'READY';
            timerEl.className = 'projector-timer-display text-info';
        } else if (data.remaining_seconds === 0 && status !== 'WAITING') {
            timerEl.innerText = '0s';
            timerEl.className = 'projector-timer-display text-danger';
        } else {
            timerEl.innerText = status;
            timerEl.className = 'projector-timer-display text-muted';
        }
    }

    // Top Two Bidding Franchisees (🥇 Highest Bidder & 🥈 Second Highest Bidder)
    const leadName = document.getElementById('projector-lead-name');
    const leadAmount = document.getElementById('projector-lead-amount');
    const leadLogo = document.getElementById('projector-lead-logo');
    const leadCard = document.getElementById('projector-lead-card');

    if (data.highest_bidder) {
        if (leadName) leadName.innerText = `${data.highest_bidder.name} (${data.highest_bidder.short_name})`;
        if (leadAmount) leadAmount.innerText = formatCurrencyJs(data.highest_bidder.amount || data.current_bid);
        if (leadLogo) {
            const hLogo = data.highest_bidder.logo ? (data.highest_bidder.logo.startsWith('http') ? data.highest_bidder.logo : `/static/uploads/${data.highest_bidder.logo}`) : '/static/uploads/default_logo.png';
            leadLogo.src = hLogo;
        }
        if (leadCard) leadCard.className = 'p-3 rounded bg-dark border border-warning shadow-sm position-relative text-center h-100 leading-bidder';
    } else {
        if (leadName) leadName.innerText = 'No Bids Placed Yet';
        if (leadAmount) leadAmount.innerText = '₹ 0';
        if (leadLogo) leadLogo.src = '/static/uploads/default_logo.png';
        if (leadCard) leadCard.className = 'p-3 rounded bg-dark border border-secondary shadow-sm position-relative text-center h-100';
    }

    const secName = document.getElementById('projector-second-name');
    const secAmount = document.getElementById('projector-second-amount');
    const secLogo = document.getElementById('projector-second-logo');

    if (data.second_highest_bidder) {
        if (secName) secName.innerText = `${data.second_highest_bidder.name} (${data.second_highest_bidder.short_name})`;
        if (secAmount) secAmount.innerText = formatCurrencyJs(data.second_highest_bidder.amount);
        if (secLogo) {
            const sLogo = data.second_highest_bidder.logo ? (data.second_highest_bidder.logo.startsWith('http') ? data.second_highest_bidder.logo : `/static/uploads/${data.second_highest_bidder.logo}`) : '/static/uploads/default_logo.png';
            secLogo.src = sLogo;
        }
    } else {
        if (secName) secName.innerText = 'No Challenger Yet';
        if (secAmount) secAmount.innerText = '—';
        if (secLogo) secLogo.src = '/static/uploads/default_logo.png';
    }
}

function triggerBidChangeAnimation(newAmount) {
    const bidEl = document.getElementById('projector-current-bid');
    if (bidEl) {
        bidEl.classList.remove('animate-bid-update');
        void bidEl.offsetWidth; // trigger reflow
        bidEl.classList.add('animate-bid-update');
    }
    const newBidTag = document.getElementById('projector-new-bid-tag');
    if (newBidTag) {
        newBidTag.innerText = `NEW BID ${formatCurrencyJs(newAmount)}`;
        newBidTag.classList.remove('d-none');
        setTimeout(() => newBidTag.classList.add('d-none'), 2000);
    }
}

// ==================== 6. ADMIN CONTROL UI UPDATER ====================

function updateAdminUi(data) {
    const statusBadge = document.getElementById('admin-status-badge');
    if (statusBadge) {
        statusBadge.innerText = `STATUS: ${data.status}`;
        if (data.status === 'BIDDING') statusBadge.className = 'badge bg-success fs-6';
        else if (data.status === 'PAUSED') statusBadge.className = 'badge bg-warning text-dark fs-6';
        else if (data.status === 'PLAYER_PREVIEW') statusBadge.className = 'badge bg-info text-dark fs-6';
        else if (data.status === 'SOLD') statusBadge.className = 'badge bg-primary fs-6';
        else if (data.status === 'UNSOLD') statusBadge.className = 'badge bg-danger fs-6';
        else statusBadge.className = 'badge badge-status-waiting fs-6';
    }

    const currentBidEl = document.getElementById('admin-current-bid');
    if (currentBidEl) currentBidEl.innerText = formatCurrencyJs(data.current_bid);

    const highestBidderEl = document.getElementById('admin-highest-bidder');
    if (highestBidderEl) {
        highestBidderEl.innerText = data.highest_bidder ? data.highest_bidder.name : 'No bids yet';
    }

    const timerEl = document.getElementById('admin-timer-display');
    if (timerEl) {
        if (data.status === 'BIDDING') {
            const sec = data.remaining_seconds;
            timerEl.innerText = `00:${sec < 10 ? '0' : ''}${sec}`;
            timerEl.className = sec <= 5 ? 'fs-4 fw-bold text-danger' : 'fs-4 fw-bold text-cyan';
        } else if (data.status === 'PAUSED') {
            timerEl.innerText = 'PAUSED';
            timerEl.className = 'fs-4 fw-bold text-warning';
        } else {
            timerEl.innerText = data.status;
            timerEl.className = 'fs-4 fw-bold text-muted';
        }
    }

    // Toggle Action Buttons
    const btnStart = document.getElementById('btn-admin-start');
    const btnPause = document.getElementById('btn-admin-pause');
    const btnResume = document.getElementById('btn-admin-resume');
    const btnExtend = document.getElementById('btn-admin-extend');
    const btnSold = document.getElementById('btn-admin-sold');
    const btnUnsold = document.getElementById('btn-admin-unsold');

    if (data.status === 'PLAYER_PREVIEW') {
        if (btnStart) btnStart.disabled = false;
        if (btnPause) btnPause.disabled = true;
        if (btnResume) btnResume.disabled = true;
        if (btnExtend) btnExtend.disabled = true;
        if (btnSold) btnSold.disabled = true;
        if (btnUnsold) btnUnsold.disabled = false;
    } else if (data.status === 'BIDDING') {
        if (btnStart) btnStart.disabled = true;
        if (btnPause) btnPause.disabled = false;
        if (btnResume) btnResume.disabled = true;
        if (btnExtend) btnExtend.disabled = false;
        if (btnSold) btnSold.disabled = !data.highest_bidder;
        if (btnUnsold) btnUnsold.disabled = false;
    } else if (data.status === 'PAUSED') {
        if (btnStart) btnStart.disabled = true;
        if (btnPause) btnPause.disabled = true;
        if (btnResume) btnResume.disabled = false;
        if (btnExtend) btnExtend.disabled = false;
        if (btnSold) btnSold.disabled = !data.highest_bidder;
        if (btnUnsold) btnUnsold.disabled = false;
    } else {
        if (btnStart) btnStart.disabled = true;
        if (btnPause) btnPause.disabled = true;
        if (btnResume) btnResume.disabled = true;
        if (btnExtend) btnExtend.disabled = true;
        if (btnSold) btnSold.disabled = true;
        if (btnUnsold) btnUnsold.disabled = true;
    }

    // Render Recent Bids for Admin
    if (data.recent_bids) {
        renderAdminRecentBids(data.recent_bids);
    }
}

function renderAdminRecentBids(bids) {
    const listEl = document.getElementById('admin-recent-bids-list');
    if (!listEl) return;

    if (!bids || bids.length === 0) {
        listEl.innerHTML = '<div class="text-muted small text-center py-2">No bids recorded for current player</div>';
        return;
    }

    listEl.innerHTML = bids.map(b => `
        <div class="d-flex justify-content-between align-items-center py-1.5 border-bottom border-secondary">
            <div>
                <span class="badge bg-secondary me-2">${b.timestamp}</span>
                <strong class="text-white">${b.franchise_name}</strong>
            </div>
            <div class="text-gold fw-bold">${formatCurrencyJs(b.amount)}</div>
        </div>
    `).join('');
}

function fetchAdminAuditEvents() {
    fetch('/api/auction/events')
        .then(res => res.json())
        .then(data => {
            const streamEl = document.getElementById('admin-event-stream');
            if (!streamEl || !data.events) return;
            streamEl.innerHTML = data.events.map(ev => `
                <div class="py-1 border-bottom border-secondary text-truncate">
                    <span class="text-muted small me-2">${ev.time}</span>
                    <span class="text-cyan fw-semibold me-1">[${ev.action}]</span>
                    <span class="text-white small">${ev.details}</span>
                </div>
            `).join('');
        })
        .catch(() => {});
}

// ==================== 7. FRANCHISE DASHBOARD UPDATER ====================

function updateFranchiseUi(data) {
    if (!data.franchise_info) return;

    const fi = data.franchise_info;
    const purseEl = document.getElementById('franchise-purse-display');
    if (purseEl) purseEl.innerText = formatCurrencyJs(fi.remaining_purse);

    const squadEl = document.getElementById('franchise-squad-display');
    if (squadEl) squadEl.innerText = `${fi.squad_count} / ${fi.squad_limit}`;

    const activePlayerCard = document.getElementById('franchise-active-player-section');
    if (!data.active_player) {
        if (activePlayerCard) {
            activePlayerCard.innerHTML = `
                <div class="text-center py-4 text-muted">
                    <i class="fa-solid fa-hourglass-start fa-2x mb-2"></i>
                    <div>Waiting for Admin to activate next player...</div>
                </div>
            `;
        }
        return;
    }

    const p = data.active_player;
    const bidBtn = document.getElementById('btn-franchise-bid');
    const bidAmount = data.next_valid_bid;

    // Status Banner on Franchise Card
    const statusBanner = document.getElementById('franchise-status-banner');
    if (statusBanner) {
        if (fi.is_highest_bidder) {
            statusBanner.className = 'alert alert-success fw-bold py-2 mb-3 text-center';
            statusBanner.innerHTML = '<i class="fa-solid fa-trophy me-2"></i>YOU ARE CURRENTLY HIGHEST BIDDER!';
            statusBanner.classList.remove('d-none');
        } else if (data.highest_bidder && data.status === 'BIDDING') {
            statusBanner.className = 'alert alert-warning fw-bold py-2 mb-3 text-center';
            statusBanner.innerHTML = '<i class="fa-solid fa-bell me-2"></i>YOU HAVE BEEN OUTBID!';
            statusBanner.classList.remove('d-none');
        } else {
            statusBanner.classList.add('d-none');
        }
    }

    const nameEl = document.getElementById('franchise-player-name');
    if (nameEl) nameEl.innerText = p.name;
    const rollEl = document.getElementById('franchise-player-roll');
    if (rollEl) rollEl.innerText = `#${p.roll_number}`;
    const roleEl = document.getElementById('franchise-player-role');
    if (roleEl) roleEl.innerText = p.role;
    const catEl = document.getElementById('franchise-player-category');
    if (catEl) catEl.innerText = p.category;
    const cbEl = document.getElementById('franchise-current-bid');
    if (cbEl) cbEl.innerText = formatCurrencyJs(data.current_bid);
    const hbEl = document.getElementById('franchise-highest-bidder');
    if (hbEl) hbEl.innerText = data.highest_bidder ? data.highest_bidder.name : 'No Bids Yet';

    if (bidBtn) {
        if (fi.can_bid) {
            bidBtn.disabled = false;
            bidBtn.className = 'btn btn-spl-primary btn-lg w-100 py-3 shadow-lg';
            bidBtn.innerHTML = `<i class="fa-solid fa-gavel me-2"></i>BID ${formatCurrencyJs(bidAmount)}`;
            bidBtn.onclick = function() { submitFranchiseBid(bidAmount); };
        } else {
            bidBtn.disabled = true;
            bidBtn.className = 'btn btn-secondary btn-lg w-100 py-3';
            bidBtn.innerHTML = `<i class="fa-solid fa-lock me-2"></i>${fi.cannot_bid_reason || 'Bidding Disabled'}`;
        }
    }
}

// ==================== 8. ACTION HANDLERS ====================

function submitFranchiseBid(amount) {
    const btn = document.getElementById('btn-franchise-bid');
    if (btn) btn.disabled = true;

    fetch('/api/auction/bid', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken()
        },
        body: JSON.stringify({ amount: amount })
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            fetchAuctionState();
        } else {
            alert(data.message || 'Bid rejected.');
            fetchAuctionState();
        }
    })
    .catch(err => {
        alert('Network error submitting bid.');
        fetchAuctionState();
    });
}

function adminFindPlayer() {
    const rollInput = document.getElementById('admin-roll-input');
    const rollNo = rollInput ? rollInput.value.trim() : '';
    const errBox = document.getElementById('admin-find-error');

    if (errBox) errBox.classList.add('d-none');

    if (!rollNo) {
        if (errBox) {
            errBox.innerText = 'Please enter a player roll number.';
            errBox.classList.remove('d-none');
        } else alert('Please enter a player roll number.');
        return;
    }

    fetch('/api/auction/find-player', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken()
        },
        body: JSON.stringify({ roll_number: rollNo })
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            renderFoundPlayerCard(data.player);
        } else {
            if (errBox) {
                errBox.innerText = data.message || 'Player not found.';
                errBox.classList.remove('d-none');
            } else alert(data.message || 'Player not found.');
        }
    });
}

function renderFoundPlayerCard(p) {
    const cardEl = document.getElementById('admin-found-player-card');
    if (!cardEl) return;

    cardEl.classList.remove('d-none');
    document.getElementById('found-player-name').innerText = p.name;
    document.getElementById('found-player-roll').innerText = `#${p.roll_number}`;
    document.getElementById('found-player-role').innerText = p.role;
    document.getElementById('found-player-category').innerText = p.category;
    document.getElementById('found-base-price').innerText = formatCurrencyJs(p.base_price);

    const actBtn = document.getElementById('btn-activate-player');
    if (actBtn) {
        actBtn.onclick = function() { adminActivatePlayer(p.id); };
    }
}

function adminActivatePlayer(playerId) {
    fetch('/api/auction/activate', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken()
        },
        body: JSON.stringify({ player_id: playerId })
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            const cardEl = document.getElementById('admin-found-player-card');
            if (cardEl) cardEl.classList.add('d-none');
            fetchAuctionState();
        } else {
            alert(data.message || 'Failed to activate player.');
        }
    });
}

function adminControlAction(action, extraData = {}) {
    // Disable submit buttons inside confirm modals if applicable
    if (action === 'sold') {
        const btn = document.getElementById('btn-confirm-sold-submit');
        if (btn) btn.disabled = true;
    } else if (action === 'unsold') {
        const btn = document.getElementById('btn-confirm-unsold-submit');
        if (btn) btn.disabled = true;
    }

    fetch(`/api/auction/${action}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken()
        },
        body: JSON.stringify(extraData)
    })
    .then(res => res.json())
    .then(data => {
        // Re-enable confirm buttons
        const btnS = document.getElementById('btn-confirm-sold-submit');
        if (btnS) btnS.disabled = false;
        const btnU = document.getElementById('btn-confirm-unsold-submit');
        if (btnU) btnU.disabled = false;

        if (data.success) {
            fetchAuctionState();
        } else {
            alert(data.message || 'Action failed.');
            fetchAuctionState();
        }
    })
    .catch(err => {
        const btnS = document.getElementById('btn-confirm-sold-submit');
        if (btnS) btnS.disabled = false;
        const btnU = document.getElementById('btn-confirm-unsold-submit');
        if (btnU) btnU.disabled = false;
        alert('Network error communicating with server.');
    });
}

// ==================== 9. KEYBOARD SHORTCUTS ====================

document.addEventListener('keydown', function(e) {
    // Disable shortcuts if user is typing in an input or textarea
    const tag = e.target.tagName.toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return;

    if (!currentAuctionState) return;

    // Check if on Admin panel
    if (!document.getElementById('admin-auction-panel')) return;

    if (e.code === 'Space') {
        e.preventDefault();
        if (currentAuctionState.status === 'BIDDING') adminControlAction('pause');
        else if (currentAuctionState.status === 'PAUSED') adminControlAction('resume');
    } else if (e.key === 'e' || e.key === 'E') {
        e.preventDefault();
        if (['BIDDING', 'PAUSED'].includes(currentAuctionState.status)) {
            adminControlAction('extend', { seconds: 10 });
        }
    } else if (e.key === 's' || e.key === 'S') {
        e.preventDefault();
        const btnSold = document.getElementById('btn-admin-sold');
        if (btnSold && !btnSold.disabled) {
            const soldModal = new bootstrap.Modal(document.getElementById('confirmSoldModal'));
            soldModal.show();
        }
    } else if (e.key === 'u' || e.key === 'U') {
        e.preventDefault();
        const btnUnsold = document.getElementById('btn-admin-unsold');
        if (btnUnsold && !btnUnsold.disabled) {
            const unsoldModal = new bootstrap.Modal(document.getElementById('confirmUnsoldModal'));
            unsoldModal.show();
        }
    }
});

// ==================== 8. SMOOTH CELEBRATION CONFETTI (Requirement 9) ====================
let confettiAnimationId = null;

function startSoldConfetti() {
    const canvas = document.getElementById('sold-confetti-canvas');
    if (!canvas) return;
    if (confettiAnimationId) return; // already running

    const ctx = canvas.getContext('2d');
    canvas.width = canvas.parentElement ? canvas.parentElement.offsetWidth : window.innerWidth;
    canvas.height = canvas.parentElement ? canvas.parentElement.offsetHeight : window.innerHeight;

    const colors = ['#ffd700', '#00f2fe', '#10b981', '#f59e0b', '#ec4899', '#3b82f6', '#ffffff'];
    const particles = [];
    const count = 65;

    for (let i = 0; i < count; i++) {
        particles.push({
            x: Math.random() * canvas.width,
            y: Math.random() * canvas.height - canvas.height * 0.8,
            size: Math.random() * 8 + 4,
            speedY: Math.random() * 2.5 + 2,
            speedX: (Math.random() - 0.5) * 2,
            rotation: Math.random() * 360,
            rotationSpeed: (Math.random() - 0.5) * 5,
            color: colors[Math.floor(Math.random() * colors.length)],
            opacity: Math.random() * 0.4 + 0.6
        });
    }

    function renderConfetti() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        particles.forEach(p => {
            p.y += p.speedY;
            p.x += p.speedX;
            p.rotation += p.rotationSpeed;
            if (p.y > canvas.height) {
                p.y = -10;
                p.x = Math.random() * canvas.width;
            }

            ctx.save();
            ctx.translate(p.x, p.y);
            ctx.rotate((p.rotation * Math.PI) / 180);
            ctx.globalAlpha = p.opacity;
            ctx.fillStyle = p.color;
            ctx.fillRect(-p.size / 2, -p.size / 2, p.size, p.size * 0.6);
            ctx.restore();
        });

        confettiAnimationId = requestAnimationFrame(renderConfetti);
    }

    renderConfetti();
}

function stopSoldConfetti() {
    if (confettiAnimationId) {
        cancelAnimationFrame(confettiAnimationId);
        confettiAnimationId = null;
    }
    const canvas = document.getElementById('sold-confetti-canvas');
    if (canvas) {
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
    }
}


