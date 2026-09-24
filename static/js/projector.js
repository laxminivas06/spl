// Sphoorthy Premier League (SPL) - Projector Broadcast Script

let currentAuctionState = null;
let splashTimer = null;

document.addEventListener('DOMContentLoaded', () => {
    fetchProjectorState();

    // SSE Real-Time Listeners
    window.addEventListener('spl:state_update', (e) => handleProjectorUpdate(e.detail));
    window.addEventListener('spl:player_activated', (e) => handlePlayerActivated(e.detail));
    window.addEventListener('spl:bid', (e) => handleBidEvent(e.detail));
    window.addEventListener('spl:sold', (e) => handleSoldEvent(e.detail));
    window.addEventListener('spl:unsold', (e) => handleUnsoldEvent(e.detail));

    // Smooth client countdown
    setInterval(() => {
        if (currentAuctionState && !currentAuctionState.is_timer_paused && currentAuctionState.timer_remaining > 0) {
            currentAuctionState.timer_remaining = Math.max(0, currentAuctionState.timer_remaining - 1);
            const timerEl = document.getElementById('projTimerVal');
            if (timerEl) timerEl.textContent = formatTimer(currentAuctionState.timer_remaining);
        }
    }, 1000);
});

function toggleFullScreen() {
    if (!document.fullscreenElement) {
        document.documentElement.requestFullscreen().catch(err => console.log(err));
    } else {
        if (document.exitFullscreen) {
            document.exitFullscreen();
        }
    }
}

async function fetchProjectorState() {
    try {
        const res = await fetch('/api/auction/state');
        const data = await res.json();
        handleProjectorUpdate(data);
    } catch (e) {
        console.error('Projector state fetch error:', e);
    }
}

function handleProjectorUpdate(data) {
    if (!data) return;
    const state = data.state || data;
    currentAuctionState = state;

    // Render footer franchise chips (strictly public info - no private purses)
    if (data.teams) {
        renderTeamsFooter(data.teams, state.leading_team_id);
    }

    const emptyBox = document.getElementById('projectorEmptyState');
    const activeBox = document.getElementById('projectorActiveContent');
    const soldSplash = document.getElementById('projSoldSplash');
    const unsoldSplash = document.getElementById('projUnsoldSplash');

    // Display bidding numbers
    document.getElementById('projCurrentBid').textContent = formatCurrency(state.current_bid || 0);
    document.getElementById('projLeadingTeam').textContent = data.leading_team ? data.leading_team.name : (state.leading_team_name || 'None');
    document.getElementById('projNextBid').textContent = formatCurrency(state.next_bid || 10000);
    document.getElementById('projTimerVal').textContent = formatTimer(state.timer_remaining || 30);

    const timerStatus = document.getElementById('projTimerStatusText');
    if (timerStatus) {
        if (state.is_timer_paused) timerStatus.textContent = 'Auction Paused';
        else if (state.timer_remaining <= 0) timerStatus.textContent = 'Timer Expired';
        else timerStatus.textContent = 'Live Bidding Open';
    }

    // Only display player card when official bidding/activation is live
    if (data.player && (state.status === 'BIDDING' || state.status === 'PLAYER_ACTIVATED')) {
        soldSplash.classList.add('hidden');
        unsoldSplash.classList.add('hidden');
        emptyBox.classList.add('hidden');
        activeBox.classList.remove('hidden');

        renderPlayerDetails(data.player);
    } else if (state.status === 'SOLD') {
        // Handled via handleSoldEvent or display sold state
    } else if (state.status === 'UNSOLD') {
        // Handled via handleUnsoldEvent
    } else {
        // Waiting / Idle State
        soldSplash.classList.add('hidden');
        unsoldSplash.classList.add('hidden');
        activeBox.classList.add('hidden');
        emptyBox.classList.remove('hidden');
    }
}

function renderPlayerDetails(player) {
    document.getElementById('projPlayerRoll').textContent = player.roll_no || 'SPL';
    document.getElementById('projPlayerYear').textContent = player.year || '4th Year';
    document.getElementById('projPlayerRole').textContent = player.role || 'All-Rounder';
    document.getElementById('projPlayerName').textContent = player.name;
    document.getElementById('projPlayerBase').textContent = formatCurrency(player.base_price || 10000);

    const photoEl = document.getElementById('projPlayerPhoto');
    const fallbackEl = document.getElementById('projPlayerFallback');
    if (player.photo) {
        photoEl.src = player.photo;
        photoEl.classList.remove('hidden');
        fallbackEl.classList.add('hidden');
    } else {
        photoEl.classList.add('hidden');
        fallbackEl.classList.remove('hidden');
    }

    const bat = player.batting || {};
    const bowl = player.bowling || {};
    const fld = player.fielding || {};

    document.getElementById('projStatMatches').textContent = bat.matches || 0;
    document.getElementById('projStatRuns').textContent = bat.runs || 0;
    document.getElementById('projStatSR').textContent = bat.strike_rate ? Number(bat.strike_rate).toFixed(1) : '0.0';
    document.getElementById('projStat50s').textContent = `${bat.fifties || 0} / ${bat.hundreds || 0}`;

    document.getElementById('projStatWickets').textContent = bowl.wickets || 0;
    document.getElementById('projStatEcon').textContent = bowl.economy ? Number(bowl.economy).toFixed(1) : '0.0';
    document.getElementById('projStatCatches').textContent = fld.catches || 0;
    document.getElementById('projStatRunouts').textContent = fld.runouts || 0;
}

function handlePlayerActivated(data) {
    clearTimeout(splashTimer);
    document.getElementById('projSoldSplash').classList.add('hidden');
    document.getElementById('projUnsoldSplash').classList.add('hidden');
    handleProjectorUpdate(data);
}

function handleBidEvent(data) {
    if (data.state) currentAuctionState = data.state;
    if (data.bid) {
        document.getElementById('projCurrentBid').textContent = formatCurrency(data.bid.amount);
        document.getElementById('projLeadingTeam').textContent = data.bid.team_name;
    }
    if (data.state) {
        document.getElementById('projNextBid').textContent = formatCurrency(data.state.next_bid);
        document.getElementById('projTimerVal').textContent = formatTimer(data.state.timer_remaining || 25);
    }
}

function handleSoldEvent(data) {
    clearTimeout(splashTimer);
    const soldSplash = document.getElementById('projSoldSplash');
    const unsoldSplash = document.getElementById('projUnsoldSplash');
    unsoldSplash.classList.add('hidden');

    document.getElementById('splashSoldPlayer').textContent = data.player?.name || 'Player';
    document.getElementById('splashSoldTeam').textContent = data.team?.name || 'Winning Team';
    document.getElementById('splashSoldPrice').textContent = formatCurrency(data.price || 0);

    soldSplash.classList.remove('hidden');

    // Display for 6 seconds, then transition to Waiting for Next Player state
    splashTimer = setTimeout(() => {
        soldSplash.classList.add('hidden');
        document.getElementById('projectorActiveContent').classList.add('hidden');
        document.getElementById('projectorEmptyState').classList.remove('hidden');
        document.getElementById('projCurrentBid').textContent = '₹ 0';
        document.getElementById('projLeadingTeam').textContent = 'None';
        document.getElementById('projNextBid').textContent = '₹ 10,000';
    }, 6000);
}

function handleUnsoldEvent(data) {
    clearTimeout(splashTimer);
    const soldSplash = document.getElementById('projSoldSplash');
    const unsoldSplash = document.getElementById('projUnsoldSplash');
    soldSplash.classList.add('hidden');

    document.getElementById('splashUnsoldPlayer').textContent = data.player?.name || 'Player';
    unsoldSplash.classList.remove('hidden');

    // Display for 5 seconds, then transition to Waiting for Next Player state
    splashTimer = setTimeout(() => {
        unsoldSplash.classList.add('hidden');
        document.getElementById('projectorActiveContent').classList.add('hidden');
        document.getElementById('projectorEmptyState').classList.remove('hidden');
        document.getElementById('projCurrentBid').textContent = '₹ 0';
        document.getElementById('projLeadingTeam').textContent = 'None';
        document.getElementById('projNextBid').textContent = '₹ 10,000';
    }, 5000);
}

function renderTeamsFooter(teams, leadingTeamId) {
    const footer = document.getElementById('projTeamsFooter');
    if (!footer) return;

    footer.innerHTML = teams.map(t => {
        const isLeading = (t.id === leadingTeamId);
        return `
            <div class="projector-team-chip" style="${isLeading ? 'border-color:#fbbf24; background:rgba(251,191,36,0.2); box-shadow:0 0 15px rgba(251,191,36,0.4);' : ''}">
                <div style="width:14px; height:14px; border-radius:50%; background:${t.color || '#3b82f6'};"></div>
                <span>${t.name}</span>
                <span style="font-size:0.8rem; color:#94a3b8; margin-left:4px;">(${t.squad_count || 0}/15)</span>
            </div>
        `;
    }).join('');
}
