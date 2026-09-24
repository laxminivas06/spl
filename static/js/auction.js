// Sphoorthy Premier League (SPL) - Anchor Console Script

let currentSelectedPlayer = null;
let currentAuctionState = null;

document.addEventListener('DOMContentLoaded', () => {
    fetchAuctionState();

    // SSE listeners
    window.addEventListener('spl:state_update', (e) => handleStateUpdate(e.detail));
    window.addEventListener('spl:player_activated', (e) => handleStateUpdate(e.detail));
    window.addEventListener('spl:bid', (e) => handleStateUpdate(e.detail));
    window.addEventListener('spl:sold', (e) => handleStateUpdate(e.detail));
    window.addEventListener('spl:unsold', (e) => handleStateUpdate(e.detail));

    // Keyboard shortcut [Space] for random chit
    document.addEventListener('keydown', (e) => {
        if (e.code === 'Space' && document.activeElement.tagName !== 'INPUT') {
            e.preventDefault();
            triggerRandomChit();
        }
    });

    // Enter key in roll no input
    const rollInput = document.getElementById('chitRollInput');
    if (rollInput) {
        rollInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                lookupAndSelectChit();
            }
        });
    }

    // Timer countdown
    setInterval(() => {
        if (currentAuctionState && !currentAuctionState.is_timer_paused && currentAuctionState.timer_remaining > 0) {
            currentAuctionState.timer_remaining = Math.max(0, currentAuctionState.timer_remaining - 1);
            const timerEl = document.getElementById('sidebarTimer');
            if (timerEl) timerEl.textContent = formatTimer(currentAuctionState.timer_remaining);
        }
    }, 1000);
});

async function fetchAuctionState() {
    try {
        const res = await fetch('/api/auction/state');
        const data = await res.json();
        handleStateUpdate(data);
    } catch (e) {
        console.error('Error fetching auction state:', e);
    }
}

function handleStateUpdate(data) {
    if (!data) return;
    const state = data.state || data;
    currentAuctionState = state;

    // Update Sidebar monitor
    const stateBadge = document.getElementById('sidebarAuctionState');
    const bidEl = document.getElementById('sidebarCurrentBid');
    const leadEl = document.getElementById('sidebarLeadingTeam');
    const timerEl = document.getElementById('sidebarTimer');

    if (stateBadge) stateBadge.textContent = state.status || 'READY';
    if (bidEl) bidEl.textContent = formatCurrency(state.current_bid || 0);
    if (leadEl) leadEl.textContent = data.leading_team ? data.leading_team.name : (state.leading_team_name || 'None');
    if (timerEl) timerEl.textContent = formatTimer(state.timer_remaining || 30);

    // Render recent bids
    if (data.recent_bids) {
        const bidsContainer = document.getElementById('anchorRecentBids');
        if (bidsContainer) {
            if (data.recent_bids.length === 0) {
                bidsContainer.innerHTML = '<div style="color:#64748b; font-size:0.85rem; text-align:center; padding:15px;">No bids placed yet.</div>';
            } else {
                bidsContainer.innerHTML = data.recent_bids.slice(-8).reverse().map(b => `
                    <div style="display:flex; justify-content:space-between; align-items:center; padding:6px 10px; border-bottom:1px solid rgba(255,255,255,0.05); font-size:0.85rem;">
                        <div>
                            <strong style="color:#38bdf8;">${b.team_name}</strong>
                            <small style="color:#94a3b8; display:block; font-size:0.75rem;">${b.formatted_time || ''}</small>
                        </div>
                        <strong style="color:#4ade80;">${formatCurrency(b.amount)}</strong>
                    </div>
                `).join('');
            }
        }
    }

    // If a player is currently announced or active on stage, display their card
    const targetPlayer = data.announced_player || data.player;
    if (targetPlayer && (state.status === 'PLAYER_ANNOUNCED' || state.status === 'PLAYER_SELECTED' || state.status === 'PLAYER_ACTIVATED' || state.status === 'BIDDING')) {
        renderPlayerCard(targetPlayer, state.status);
    }
}

function renderPlayerCard(player, status) {
    currentSelectedPlayer = player;
    document.getElementById('playerEmptyState').classList.add('hidden');
    document.getElementById('playerActiveContent').classList.remove('hidden');

    document.getElementById('playerRollTag').textContent = player.roll_no || 'SPL-CHIT';
    document.getElementById('playerYearTag').textContent = player.year || '4th Year';
    document.getElementById('playerRoleBadge').textContent = player.role || 'All-Rounder';
    document.getElementById('playerName').textContent = player.name;
    document.getElementById('playerBasePrice').textContent = formatCurrency(player.base_price || 10000);

    const statusBadge = document.getElementById('anchorPlayerStatusBadge');
    if (statusBadge) {
        if (status === 'BIDDING' || status === 'PLAYER_ACTIVATED') {
            statusBadge.textContent = 'LIVE ON STAGE';
            statusBadge.className = 'badge badge-green';
        } else {
            statusBadge.textContent = 'CHIT DRAWN';
            statusBadge.className = 'badge badge-gold';
        }
    }

    // Photo
    const photoEl = document.getElementById('playerPhoto');
    const fallbackEl = document.getElementById('playerAvatarFallback');
    if (player.photo) {
        photoEl.src = player.photo;
        photoEl.classList.remove('hidden');
        fallbackEl.classList.add('hidden');
    } else {
        photoEl.classList.add('hidden');
        fallbackEl.classList.remove('hidden');
    }

    // Stats
    const bat = player.batting || {};
    const bowl = player.bowling || {};
    const fld = player.fielding || {};

    document.getElementById('statMatches').textContent = bat.matches || 0;
    document.getElementById('statRuns').textContent = bat.runs || 0;
    document.getElementById('statSR').textContent = bat.strike_rate ? Number(bat.strike_rate).toFixed(1) : '0.0';
    document.getElementById('statCenturies').textContent = `${bat.fifties || 0} / ${bat.hundreds || 0}`;

    document.getElementById('statWickets').textContent = bowl.wickets || 0;
    document.getElementById('statEconomy').textContent = bowl.economy ? Number(bowl.economy).toFixed(1) : '0.0';
    document.getElementById('statCatches').textContent = fld.catches || 0;
    document.getElementById('statRunouts').textContent = fld.runouts || 0;

    // Status Message Box
    const statusMsg = document.getElementById('anchorStatusMsg');
    const announceBtn = document.getElementById('btnAnnouncePlayer');
    if (status === 'PLAYER_ANNOUNCED') {
        if (statusMsg) statusMsg.classList.remove('hidden');
        if (announceBtn) announceBtn.innerHTML = '<i class="fa-solid fa-circle-check"></i> ANNOUNCED (WAITING FOR ADMIN)';
    } else if (status === 'BIDDING') {
        if (statusMsg) statusMsg.classList.add('hidden');
        if (announceBtn) announceBtn.innerHTML = '<i class="fa-solid fa-play"></i> LIVE ON AUCTION STAGE';
    } else {
        if (statusMsg) statusMsg.classList.add('hidden');
        if (announceBtn) announceBtn.innerHTML = '<i class="fa-solid fa-bullhorn"></i> ANNOUNCE PLAYER & SEND TO ADMIN';
    }
}

async function lookupAndSelectChit() {
    const rollNo = (document.getElementById('chitRollInput').value || '').trim();
    if (!rollNo) {
        showToast('Please enter a Roll Number.', 'warning');
        return;
    }

    try {
        const res = await fetch('/api/auction/announce', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ roll_no: rollNo })
        });
        const data = await res.json();
        if (data.success) {
            showToast(`Chit Found: ${data.player.name}`, 'success');
            renderPlayerCard(data.player, 'PLAYER_ANNOUNCED');
            document.getElementById('chitRollInput').value = '';
        } else {
            showToast(data.message || 'Chit roll number not found.', 'error');
        }
    } catch (e) {
        showToast('Error looking up chit.', 'error');
    }
}

async function triggerRandomChit() {
    try {
        const res = await fetch('/api/auction/random', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            showToast(`Random Chit Drawn: ${data.player.name}`, 'success');
            renderPlayerCard(data.player, 'PLAYER_ANNOUNCED');
        } else {
            showToast(data.message || 'No available players left in pool.', 'error');
        }
    } catch (e) {
        showToast('Error picking random chit.', 'error');
    }
}

async function markPlayerAnnounced() {
    if (!currentSelectedPlayer) {
        showToast('No player currently selected.', 'warning');
        return;
    }

    try {
        const res = await fetch('/api/auction/announce', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ player_id: currentSelectedPlayer.id })
        });
        const data = await res.json();
        if (data.success) {
            showToast(data.message, 'success');
            document.getElementById('anchorStatusMsg').classList.remove('hidden');
            document.getElementById('btnAnnouncePlayer').innerHTML = '<i class="fa-solid fa-circle-check"></i> ANNOUNCED (WAITING FOR ADMIN)';
        } else {
            showToast(data.message || 'Announcement failed', 'error');
        }
    } catch (e) {
        showToast('Network error announcing player.', 'error');
    }
}
