let currentAuctionState = null;
let allPlayersData = [];
let allTeamsData = [];
let allStudentsData = [];
let currentStudentStatusFilter = 'PENDING';

document.addEventListener('DOMContentLoaded', () => {
    initAdminTabs();
    fetchAdminData();
    fetchStudentApprovals();
    loadAuditLogs();

    // Listen to real-time SSE broadcasts
    window.addEventListener('spl:state_update', (e) => handleStateUpdate(e.detail));
    window.addEventListener('spl:player_activated', (e) => handleStateUpdate(e.detail));
    window.addEventListener('spl:bid', (e) => handleStateUpdate(e.detail));
    window.addEventListener('spl:sold', (e) => {
        handleStateUpdate(e.detail);
        fetchAdminData();
    });
    window.addEventListener('spl:unsold', (e) => {
        handleStateUpdate(e.detail);
        fetchAdminData();
    });
    window.addEventListener('spl:student_verification_updated', (e) => {
        fetchStudentApprovals();
        fetchAdminData();
    });

    // Client-side timer ticker to smooth out display between SSE events
    setInterval(() => {
        if (currentAuctionState && !currentAuctionState.is_timer_paused && currentAuctionState.timer_remaining > 0) {
            currentAuctionState.timer_remaining = Math.max(0, currentAuctionState.timer_remaining - 1);
            const timerEl = document.getElementById('adminTimerDisplay');
            if (timerEl) timerEl.textContent = formatTimer(currentAuctionState.timer_remaining);
        }
    }, 1000);
});

function initAdminTabs() {
    const tabs = document.querySelectorAll('.tab-btn');
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            tabs.forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            tab.classList.add('active');
            const target = document.getElementById(tab.dataset.tab);
            if (target) target.classList.add('active');
        });
    });
}

async function fetchAdminData() {
    try {
        const [statsRes, teamsRes, playersRes, stateRes] = await Promise.all([
            fetch('/api/admin/stats').then(r => r.json()),
            fetch('/api/teams').then(r => r.json()),
            fetch('/api/players').then(r => r.json()),
            fetch('/api/auction/state').then(r => r.json())
        ]);

        if (statsRes.success) renderKPIs(statsRes.stats);
        if (teamsRes.success) {
            allTeamsData = teamsRes.teams;
            renderTeamsOverview(teamsRes.teams);
            renderTeamsGrid(teamsRes.teams);
        }
        if (playersRes.success) {
            allPlayersData = playersRes.players;
            renderPlayersList(playersRes.players);
            renderUnsoldList(playersRes.players);
        }
        if (stateRes.state) {
            handleStateUpdate(stateRes);
        }
    } catch (e) {
        console.error('Error loading admin data:', e);
    }
}

function handleStateUpdate(data) {
    if (!data) return;
    const state = data.state || data;
    currentAuctionState = state;

    const titleEl = document.getElementById('adminActivePlayerTitle');
    const badgeEl = document.getElementById('adminAuctionStatusBadge');
    const bidEl = document.getElementById('adminCurrentBid');
    const leadEl = document.getElementById('adminLeadingTeam');
    const nextEl = document.getElementById('adminNextBid');
    const timerEl = document.getElementById('adminTimerDisplay');
    const pauseBtn = document.getElementById('btnPauseResume');

    if (badgeEl) {
        badgeEl.textContent = state.status || 'READY';
        badgeEl.className = 'live-badge-glow ' + (state.status === 'BIDDING' ? 'status-bidding' : (state.status === 'PAUSED' ? 'status-paused' : ''));
    }

    if (data.player && (state.status === 'BIDDING' || state.status === 'PLAYER_ACTIVATED' || state.status === 'PLAYER_SELECTED' || state.status === 'PLAYER_ANNOUNCED')) {
        if (titleEl) titleEl.textContent = `${data.player.name} (${data.player.roll_no || ''}) - ${data.player.role || ''}`;
    } else if (state.status === 'SOLD' && data.player) {
        if (titleEl) titleEl.textContent = `SOLD: ${data.player.name} (${data.player.roll_no || ''})`;
    } else if (state.status === 'UNSOLD' && data.player) {
        if (titleEl) titleEl.textContent = `UNSOLD: ${data.player.name}`;
    } else {
        if (titleEl) titleEl.textContent = 'No Active Player on Stage';
    }

    if (bidEl) bidEl.textContent = formatCurrency(state.current_bid || 0);
    if (leadEl) leadEl.textContent = (data.leading_team ? data.leading_team.name : (state.leading_team_name || 'None'));
    if (nextEl) nextEl.textContent = formatCurrency(state.next_bid || 10000);
    if (timerEl) timerEl.textContent = formatTimer(state.timer_remaining || 30);

    if (pauseBtn) {
        if (state.is_timer_paused) {
            pauseBtn.innerHTML = '<i class="fa-solid fa-play"></i> Resume';
            pauseBtn.className = 'btn btn-gold btn-sm';
        } else {
            pauseBtn.innerHTML = '<i class="fa-solid fa-pause"></i> Pause';
            pauseBtn.className = 'btn btn-secondary btn-sm';
        }
    }
}

function renderKPIs(stats) {
    if (!stats) return;
    document.getElementById('kpiTotalPlayers').textContent = stats.total_players || 0;
    document.getElementById('kpiAvailableCount').textContent = `${stats.available_players || 0} in pool`;
    document.getElementById('kpiSoldPlayers').textContent = stats.sold_players || 0;
    document.getElementById('kpiUnsoldCount').textContent = `${stats.unsold_players || 0} unsold`;
    document.getElementById('kpiTotalSpent').textContent = formatCurrency(stats.total_spent || 0);
    document.getElementById('kpiRemainingPurse').textContent = `${formatCurrency(stats.total_balance || 0)} available purse`;
    document.getElementById('kpiHighestBid').textContent = formatCurrency(stats.highest_bid || 0);
    document.getElementById('kpiHighestPlayer').textContent = stats.highest_player ? `${stats.highest_player.name} (${stats.highest_player.sold_team_name})` : 'None';
}

function renderTeamsOverview(teams) {
    const tbody = document.getElementById('adminTeamsOverviewTable');
    if (!tbody) return;

    if (!teams || teams.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-center py-4">No franchises found.</td></tr>';
        return;
    }

    tbody.innerHTML = teams.map(t => {
        const squadCount = (t.squad || []).length;
        const remainingSlots = Math.max(0, 15 - squadCount);
        return `
            <tr>
                <td>
                    <div style="display:flex; align-items:center; gap:10px;">
                        <div style="width:12px; height:12px; border-radius:50%; background:${t.color || '#3b82f6'};"></div>
                        <strong>${t.name}</strong> <span class="credentials-tag">${t.short_name || ''}</span>
                    </div>
                </td>
                <td><span class="credentials-tag">${t.email || `${t.username}@spl.edu`}</span></td>
                <td><strong>${squadCount}</strong> / 15</td>
                <td><span style="color:#38bdf8;">${remainingSlots} slots</span></td>
                <td>${formatCurrency(t.spent || 0)}</td>
                <td><strong style="color:#4ade80;">${formatCurrency(t.balance || 0)}</strong></td>
                <td>
                    <button class="btn btn-secondary btn-xs" onclick="openEditTeamModal('${t.id}')"><i class="fa-solid fa-pen"></i> Edit</button>
                    <a href="/team?team_id=${t.id}" class="btn btn-gold btn-xs"><i class="fa-solid fa-eye"></i> View Portal</a>
                </td>
            </tr>
        `;
    }).join('');
}

function renderTeamsGrid(teams) {
    const grid = document.getElementById('adminTeamsGrid');
    if (!grid) return;

    grid.innerHTML = teams.map(t => {
        const squadCount = (t.squad || []).length;
        return `
            <div class="team-admin-card" style="border-top: 4px solid ${t.color || '#3b82f6'};">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
                    <h4 style="margin:0; font-size:1.15rem; color:#fff;">${t.name}</h4>
                    <span class="credentials-tag">${t.short_name}</span>
                </div>
                <div style="font-size:0.85rem; color:#94a3b8; margin-bottom:8px;">
                    <div>Authorized Gmail: <strong style="color:#38bdf8;">${t.email || `${t.username}@spl.edu`}</strong></div>
                    <div>Owner: <strong>${t.owner || 'Not Set'}</strong> | Captain: <strong>${t.captain || 'Not Set'}</strong></div>
                </div>
                <div style="display:flex; justify-content:space-between; background:rgba(0,0,0,0.2); padding:8px 12px; border-radius:8px; margin:10px 0;">
                    <div><small>Remaining Purse</small><div style="color:#4ade80; font-weight:800; font-size:1.1rem;">${formatCurrency(t.balance || 0)}</div></div>
                    <div><small>Squad Count</small><div style="color:#fbbf24; font-weight:800; font-size:1.1rem;">${squadCount} / 15</div></div>
                </div>
                <div style="display:flex; gap:6px; margin-top:10px;">
                    <button class="btn btn-secondary btn-sm flex-1" onclick="openEditTeamModal('${t.id}')"><i class="fa-solid fa-pen"></i> Edit</button>
                    <a href="/team?team_id=${t.id}" class="btn btn-gold btn-sm flex-1" target="_blank"><i class="fa-solid fa-eye"></i> Team Portal</a>
                </div>
            </div>
        `;
    }).join('');
}

function renderPlayersList(players) {
    const tbody = document.getElementById('adminPlayersTable');
    if (!tbody) return;

    if (!players || players.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" class="text-center py-4">No players found matching filter.</td></tr>';
        return;
    }

    tbody.innerHTML = players.map(p => {
        let statusBadge = '<span class="badge badge-blue">AVAILABLE</span>';
        if (p.status === 'SOLD') statusBadge = '<span class="badge badge-green">SOLD</span>';
        if (p.status === 'UNSOLD') statusBadge = '<span class="badge badge-red">UNSOLD</span>';

        return `
            <tr>
                <td>
                    <div style="display:flex; align-items:center; gap:10px;">
                        <div style="width:32px; height:32px; border-radius:50%; background:#1e293b; display:flex; align-items:center; justify-content:center; overflow:hidden;">
                            ${p.photo ? `<img src="${p.photo}" style="width:100%; height:100%; object-fit:cover;">` : '<i class="fa-solid fa-user" style="font-size:0.8rem; color:#94a3b8;"></i>'}
                        </div>
                        <strong>${p.name}</strong>
                    </div>
                </td>
                <td><span class="credentials-tag">${p.roll_no || ''}</span></td>
                <td>${p.year || '-'}</td>
                <td><span class="player-role-pill">${p.role || 'All-Rounder'}</span></td>
                <td>${formatCurrency(p.base_price || 10000)}</td>
                <td>${statusBadge}</td>
                <td>${p.sold_price ? `${formatCurrency(p.sold_price)} (${p.sold_team_name})` : '-'}</td>
                <td>
                    <div style="display:flex; gap:4px;">
                        ${p.status !== 'SOLD' ? `<button class="btn btn-gold btn-xs" onclick="quickActivatePlayer('${p.id}')" title="Put directly on auction stage"><i class="fa-solid fa-play"></i> Activate</button>` : ''}
                        <button class="btn btn-secondary btn-xs" onclick="openEditPlayerModal('${p.id}')"><i class="fa-solid fa-pen"></i></button>
                        <button class="btn btn-danger btn-xs" onclick="deletePlayer('${p.id}', '${p.name}')"><i class="fa-solid fa-trash"></i></button>
                    </div>
                </td>
            </tr>
        `;
    }).join('');
}

function renderUnsoldList(players) {
    const tbody = document.getElementById('adminUnsoldTable');
    if (!tbody) return;

    const unsold = players.filter(p => p.status === 'UNSOLD' || p.status === 'UNSOLD_POOL');
    if (unsold.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-center py-4" style="color:#94a3b8;">No unsold players currently.</td></tr>';
        return;
    }

    tbody.innerHTML = unsold.map(p => `
        <tr>
            <td><input type="checkbox" class="unsold-select-cb" value="${p.id}"></td>
            <td><strong>${p.name}</strong></td>
            <td><span class="credentials-tag">${p.roll_no}</span></td>
            <td>${p.role}</td>
            <td>${formatCurrency(p.base_price || 10000)}</td>
            <td>${p.unsold_at ? new Date(p.unsold_at).toLocaleTimeString() : '-'}</td>
            <td>
                <button class="btn btn-gold btn-xs" onclick="quickActivatePlayer('${p.id}')"><i class="fa-solid fa-play"></i> Auction Now</button>
            </td>
        </tr>
    `).join('');
}

function filterPlayersList() {
    const q = (document.getElementById('playerSearchInput').value || '').toLowerCase();
    const st = document.getElementById('playerFilterStatus').value;
    const rl = document.getElementById('playerFilterRole').value;

    const filtered = allPlayersData.filter(p => {
        const matchesQ = !q || p.name.toLowerCase().includes(q) || (p.roll_no && p.roll_no.toLowerCase().includes(q));
        const matchesSt = !st || p.status === st;
        const matchesRl = !rl || p.role === rl;
        return matchesQ && matchesSt && matchesRl;
    });

    renderPlayersList(filtered);
}

// Master Controls Actions
async function togglePauseResume() {
    if (!currentAuctionState) return;
    const action = currentAuctionState.is_timer_paused ? 'resume' : 'pause';
    try {
        const res = await fetch(`/api/auction/${action}`, { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            showToast(data.message, 'info');
        }
    } catch (e) {
        showToast('Auction control failed', 'error');
    }
}

async function activateCurrentPlayer() {
    try {
        const res = await fetch('/api/auction/activate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) });
        const data = await res.json();
        if (data.success) {
            showToast(data.message, 'success');
        } else {
            showToast(data.message || 'No player to activate', 'error');
        }
    } catch (e) {
        showToast('Activation failed', 'error');
    }
}

async function quickActivatePlayer(playerId) {
    try {
        const res = await fetch(`/api/auction/select/${playerId}`, { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            showToast(`Player ${data.player.name} activated on stage!`, 'success');
        }
    } catch (e) {
        showToast('Could not activate player', 'error');
    }
}

async function extendTimer(seconds) {
    try {
        const res = await fetch('/api/auction/extend-timer', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ seconds: seconds })
        });
        const data = await res.json();
        if (data.success) showToast(data.message, 'info');
    } catch (e) {
        showToast('Timer extension failed', 'error');
    }
}

async function undoLastBid() {
    if (!confirm('Undo the last bid?')) return;
    try {
        const res = await fetch('/api/auction/undo-bid', { method: 'POST' });
        const data = await res.json();
        if (data.success) showToast(data.message, 'success');
        else showToast(data.message, 'error');
    } catch (e) {
        showToast('Undo failed', 'error');
    }
}

function openSoldModal() {
    if (!currentAuctionState || !currentAuctionState.leading_team_id) {
        showToast('Cannot mark SOLD: No team has placed a leading bid!', 'error');
        return;
    }
    document.getElementById('modalSoldPlayerName').textContent = document.getElementById('adminActivePlayerTitle').textContent;
    document.getElementById('modalSoldTeamName').textContent = currentAuctionState.leading_team_name || 'Winning Franchise';
    document.getElementById('modalSoldPrice').textContent = formatCurrency(currentAuctionState.current_bid);
    document.getElementById('soldConfirmModal').classList.remove('hidden');
}

function closeSoldModal() {
    document.getElementById('soldConfirmModal').classList.add('hidden');
}

async function executeSold() {
    closeSoldModal();
    try {
        const res = await fetch('/api/auction/sold', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            showToast(data.message, 'success');
            fetchAdminData();
        } else {
            showToast(data.message || 'Sold confirmation failed', 'error');
        }
    } catch (e) {
        showToast('Sold execution error', 'error');
    }
}

async function confirmUnsold() {
    if (!confirm('Mark current player as UNSOLD?')) return;
    try {
        const res = await fetch('/api/auction/unsold', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            showToast(data.message, 'info');
            fetchAdminData();
        } else {
            showToast(data.message, 'error');
        }
    } catch (e) {
        showToast('Unsold execution error', 'error');
    }
}

// Second Chance Pool
function toggleSelectAllUnsold(master) {
    document.querySelectorAll('.unsold-select-cb').forEach(cb => cb.checked = master.checked);
}

async function reactivateSelectedUnsold() {
    const selected = Array.from(document.querySelectorAll('.unsold-select-cb:checked')).map(cb => cb.value);
    if (selected.length === 0) {
        showToast('Select at least one unsold player to reactivate.', 'warning');
        return;
    }
    try {
        const res = await fetch('/api/auction/second-chance', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ player_ids: selected })
        });
        const data = await res.json();
        if (data.success) {
            showToast(data.message, 'success');
            fetchAdminData();
        }
    } catch (e) {
        showToast('Reactivation failed', 'error');
    }
}

// Audit Logs
async function loadAuditLogs() {
    const tbody = document.getElementById('adminAuditTable');
    if (!tbody) return;
    try {
        const res = await fetch('/api/audit-logs');
        const data = await res.json();
        if (data.success && data.logs) {
            if (data.logs.length === 0) {
                tbody.innerHTML = '<tr><td colspan="7" class="text-center py-4">No audit events recorded yet.</td></tr>';
                return;
            }
            tbody.innerHTML = data.logs.slice(0, 100).map(log => `
                <tr>
                    <td style="font-size:0.8rem; color:#94a3b8;">${log.formatted_time || log.timestamp}</td>
                    <td><span class="audit-badge audit-${log.action}">${log.action}</span></td>
                    <td><strong>${log.user}</strong></td>
                    <td><span class="credentials-tag">${log.role}</span></td>
                    <td>${log.player || '-'}</td>
                    <td>${log.team || '-'}</td>
                    <td style="font-size:0.85rem;">${log.details || ''}</td>
                </tr>
            `).join('');
        }
    } catch (e) {
        console.error('Audit logs error:', e);
    }
}

// Player Modal Form
function openAddPlayerModal() {
    document.getElementById('playerForm').reset();
    document.getElementById('editPlayerId').value = '';
    document.getElementById('playerModalTitle').innerHTML = '<i class="fa-solid fa-user-plus"></i> Add Player';
    document.getElementById('playerModal').classList.remove('hidden');
}

function openEditPlayerModal(id) {
    const p = allPlayersData.find(x => x.id === id);
    if (!p) return;
    document.getElementById('playerForm').reset();
    document.getElementById('editPlayerId').value = p.id;
    document.getElementById('formPlayerName').value = p.name;
    document.getElementById('formPlayerRoll').value = p.roll_no || '';
    document.getElementById('formPlayerYear').value = p.year || '';
    document.getElementById('formPlayerRole').value = p.role || 'All-Rounder';
    document.getElementById('formPlayerBasePrice').value = p.base_price || 10000;
    document.getElementById('formPlayerRuns').value = p.batting?.runs || 0;
    document.getElementById('formPlayerWickets').value = p.bowling?.wickets || 0;
    document.getElementById('formPlayerSR').value = p.batting?.strike_rate || 0.0;
    document.getElementById('formPlayerFifties').value = p.batting?.fifties || 0;
    document.getElementById('playerModalTitle').innerHTML = `<i class="fa-solid fa-pen"></i> Edit ${p.name}`;
    document.getElementById('playerModal').classList.remove('hidden');
}

function closePlayerModal() {
    document.getElementById('playerModal').classList.add('hidden');
}

async function savePlayerForm(e) {
    e.preventDefault();
    const form = document.getElementById('playerForm');
    const formData = new FormData(form);
    const playerId = document.getElementById('editPlayerId').value;
    const url = playerId ? `/api/players/${playerId}` : '/api/players';
    
    try {
        const res = await fetch(url, { method: 'POST', body: formData });
        const data = await res.json();
        if (data.success) {
            showToast(data.message, 'success');
            closePlayerModal();
            fetchAdminData();
        } else {
            showToast(data.message || 'Error saving player', 'error');
        }
    } catch (e) {
        showToast('Network error saving player', 'error');
    }
}

async function deletePlayer(id, name) {
    if (!confirm(`Are you sure you want to delete ${name}?`)) return;
    try {
        const res = await fetch(`/api/players/${id}`, { method: 'DELETE' });
        const data = await res.json();
        if (data.success) {
            showToast(data.message, 'info');
            fetchAdminData();
        } else {
            showToast(data.message, 'error');
        }
    } catch (e) {
        showToast('Failed to delete player', 'error');
    }
}

// Team Modal Form
function openAddTeamModal() {
    document.getElementById('teamForm').reset();
    document.getElementById('editTeamId').value = '';
    document.getElementById('teamModalTitle').innerHTML = '<i class="fa-solid fa-shield-halved"></i> Add Franchise';
    document.getElementById('teamModal').classList.remove('hidden');
}

function openEditTeamModal(id) {
    const t = allTeamsData.find(x => x.id === id);
    if (!t) return;
    document.getElementById('teamForm').reset();
    document.getElementById('editTeamId').value = t.id;
    document.getElementById('formTeamName').value = t.name;
    document.getElementById('formTeamShort').value = t.short_name || '';
    document.getElementById('formTeamEmail').value = t.email || `${t.username}@spl.edu`;
    document.getElementById('formTeamBudget').value = t.initial_budget || 500000;
    document.getElementById('formTeamOwner').value = t.owner || '';
    document.getElementById('formTeamCaptain').value = t.captain || '';
    document.getElementById('formTeamColor').value = t.color || '#3b82f6';
    document.getElementById('teamModalTitle').innerHTML = `<i class="fa-solid fa-pen"></i> Edit ${t.name}`;
    document.getElementById('teamModal').classList.remove('hidden');
}

function closeTeamModal() {
    document.getElementById('teamModal').classList.add('hidden');
}

async function saveTeamForm(e) {
    e.preventDefault();
    const form = document.getElementById('teamForm');
    const formData = new FormData(form);
    const teamId = document.getElementById('editTeamId').value;
    const url = teamId ? `/api/teams/${teamId}` : '/api/teams';

    try {
        const res = await fetch(url, { method: 'POST', body: formData });
        const data = await res.json();
        if (data.success) {
            showToast(data.message, 'success');
            closeTeamModal();
            fetchAdminData();
        } else {
            showToast(data.message || 'Error saving team', 'error');
        }
    } catch (e) {
        showToast('Network error saving team', 'error');
    }
}

// Excel Import
async function handleExcelFile(file) {
    if (!file) return;
    const formData = new FormData();
    formData.append('file', file);

    const resultDiv = document.getElementById('excelImportResult');
    if (resultDiv) resultDiv.innerHTML = '<div class="alert alert-info"><i class="fa-solid fa-spinner fa-spin"></i> Parsing and importing roster...</div>';

    try {
        const res = await fetch('/api/players/import', { method: 'POST', body: formData });
        const data = await res.json();
        if (data.success) {
            resultDiv.innerHTML = `
                <div class="alert alert-success">
                    <i class="fa-solid fa-circle-check"></i> ${data.message}
                    <div style="font-size:0.85rem; margin-top:4px;">Added: <strong>${data.added_count || 0}</strong> | Updated: <strong>${data.updated_count || 0}</strong></div>
                </div>
            `;
            fetchAdminData();
        } else {
            resultDiv.innerHTML = `<div class="alert alert-error"><i class="fa-solid fa-circle-exclamation"></i> ${data.message}</div>`;
        }
    } catch (e) {
        if (resultDiv) resultDiv.innerHTML = `<div class="alert alert-error">Import network error.</div>`;
    }
}

// Settings
async function saveAdminSettings() {
    const payload = {
        league_name: document.getElementById('settingLeagueName').value,
        default_budget: parseInt(document.getElementById('settingDefaultBudget').value) || 500000,
        max_squad_size: parseInt(document.getElementById('settingMaxSquad').value) || 15,
        base_price: parseInt(document.getElementById('settingBasePrice').value) || 10000,
        timer_seconds: parseInt(document.getElementById('settingTimerSeconds').value) || 30
    };

    try {
        const res = await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.success) showToast('Settings saved successfully.', 'success');
    } catch (e) {
        showToast('Failed to save settings.', 'error');
    }
}

async function fullAuctionReset() {
    const confirmation = prompt('DANGER: This will reset all 6 teams to ₹5,00,000 purse and clear all squads! Type RESET to confirm:');
    if (confirmation !== 'RESET') return;

    try {
        const res = await fetch('/api/admin/reset-auction', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ type: 'full_reset' })
        });
        const data = await res.json();
        if (data.success) {
            showToast(data.message, 'success');
            fetchAdminData();
        }
    } catch (e) {
        showToast('Reset failed', 'error');
    }
}

// ----------------- STUDENT REGISTRATION & VERIFICATION -----------------

async function fetchStudentApprovals() {
    try {
        const res = await fetch('/api/admin/students');
        const data = await res.json();
        if (data.success) {
            allStudentsData = data.students || [];
            renderStudentApprovals(data);
        }
    } catch (e) {
        console.error('Error fetching student approvals:', e);
    }
}

function renderStudentApprovals(data) {
    const summary = data.summary || { total: 0, pending: 0, approved: 0, rejected: 0 };
    
    // Update summary counts
    const totalEl = document.getElementById('statStudentTotal');
    const pendingEl = document.getElementById('statStudentPending');
    const approvedEl = document.getElementById('statStudentApproved');
    const rejectedEl = document.getElementById('statStudentRejected');
    const pendingBadge = document.getElementById('pendingApprovalBadge');

    if (totalEl) totalEl.textContent = summary.total;
    if (pendingEl) pendingEl.textContent = summary.pending;
    if (approvedEl) approvedEl.textContent = summary.approved;
    if (rejectedEl) rejectedEl.textContent = summary.rejected;

    if (pendingBadge) {
        if (summary.pending > 0) {
            pendingBadge.textContent = summary.pending;
            pendingBadge.style.display = 'inline-block';
        } else {
            pendingBadge.style.display = 'none';
        }
    }

    filterStudentsList();
}

function setStudentStatusFilter(status) {
    const statusSelect = document.getElementById('studentFilterStatus');
    if (statusSelect) {
        statusSelect.value = status;
        filterStudentsList();
    }
}

function filterStudentsList() {
    const searchQuery = (document.getElementById('studentSearchInput')?.value || '').trim().toLowerCase();
    const statusFilter = document.getElementById('studentFilterStatus')?.value || '';
    const roleFilter = document.getElementById('studentFilterRole')?.value || '';

    let filtered = allStudentsData.filter(s => {
        const status = s.approval_status || 'PENDING';
        if (statusFilter && status !== statusFilter) return false;
        if (roleFilter && s.role !== roleFilter) return false;
        if (searchQuery) {
            const matchName = (s.name || '').toLowerCase().includes(searchQuery);
            const matchRoll = (s.roll_no || '').toLowerCase().includes(searchQuery);
            const matchDept = (s.department || '').toLowerCase().includes(searchQuery);
            const matchRole = (s.role || '').toLowerCase().includes(searchQuery);
            if (!matchName && !matchRoll && !matchDept && !matchRole) return false;
        }
        return true;
    });

    const countText = document.getElementById('studentResultCountText');
    if (countText) {
        countText.textContent = `Showing ${filtered.length} of ${allStudentsData.length} students`;
    }

    renderStudentsCards(filtered);
}

function renderStudentsCards(students) {
    const container = document.getElementById('studentsCardsContainer');
    if (!container) return;

    if (!students || students.length === 0) {
        container.innerHTML = `
            <div style="grid-column: 1 / -1; text-align: center; padding: 40px 20px; background: rgba(15,23,42,0.4); border-radius: 16px; border: 1px dashed rgba(255,255,255,0.1);">
                <i class="fa-solid fa-user-slash" style="font-size: 2.5rem; color: #64748b; margin-bottom: 12px; display:block;"></i>
                <h4 style="color: #94a3b8; margin:0 0 6px 0;">No student registrations found</h4>
                <p style="color: #64748b; font-size: 0.85rem; margin:0;">Try changing your search keywords or status filters.</p>
            </div>
        `;
        return;
    }

    container.innerHTML = students.map(s => {
        const status = s.approval_status || 'PENDING';
        const roleIcon = s.role === 'Batsman' ? '🏏' : (s.role === 'Bowler' ? '⚡' : '🏏⚡');
        const photoUrl = s.photo || '';
        
        let statusBadge = '';
        if (status === 'APPROVED') {
            statusBadge = `<span class="student-status-badge student-status-badge-approved"><i class="fa-solid fa-circle-check"></i> Approved</span>`;
        } else if (status === 'REJECTED') {
            statusBadge = `<span class="student-status-badge student-status-badge-rejected"><i class="fa-solid fa-circle-xmark"></i> Rejected</span>`;
        } else {
            statusBadge = `<span class="student-status-badge student-status-badge-pending"><i class="fa-solid fa-clock"></i> Pending Review</span>`;
        }

        const formattedDate = s.registered_at ? new Date(s.registered_at).toLocaleDateString(undefined, {
            month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
        }) : 'Recent';

        return `
            <div class="student-admin-card" id="studentCard_${s.roll_no}">
                <div>
                    <div class="student-card-header">
                        ${photoUrl ? `
                            <img src="${photoUrl}" alt="${s.name}" class="student-thumb" onclick="previewStudentPhoto('${photoUrl}', '${escapeHtml(s.name)}', '${s.roll_no}', '${escapeHtml(s.year || '')} • ${escapeHtml(s.department || '')}')">
                        ` : `
                            <div class="student-thumb" style="display:flex; align-items:center; justify-content:center; font-size:1.6rem; color:#64748b;">
                                👤
                            </div>
                        `}
                        <div class="student-card-meta">
                            <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:6px;">
                                <div class="student-card-name" title="${escapeHtml(s.name)}">${escapeHtml(s.name || 'Unnamed')}</div>
                            </div>
                            <div class="student-card-roll">${s.roll_no}</div>
                            <div class="student-card-dept">${escapeHtml(s.year || 'Year N/A')} • ${escapeHtml(s.department || 'Dept N/A')}</div>
                            <div style="display:flex; justify-content:space-between; align-items:center; margin-top:6px;">
                                <span class="student-card-role-pill">${roleIcon} ${escapeHtml(s.role || 'Player')}</span>
                                ${statusBadge}
                            </div>
                        </div>
                    </div>

                    ${s.rejection_reason && status === 'REJECTED' ? `
                        <div style="background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.25); border-radius: 8px; padding: 6px 10px; margin-top: 10px; font-size: 0.78rem; color: #fca5a5;">
                            <strong>Reason:</strong> ${escapeHtml(s.rejection_reason)}
                        </div>
                    ` : ''}

                    <div style="font-size: 0.72rem; color: #64748b; margin-top: 8px;">
                        Registered: ${formattedDate}
                    </div>
                </div>

                <div class="student-card-actions">
                    ${status !== 'APPROVED' ? `
                        <button class="btn btn-success btn-xs" style="flex:1;" onclick="approveStudent('${s.roll_no}')">
                            <i class="fa-solid fa-check"></i> Accept
                        </button>
                    ` : ''}

                    ${status !== 'REJECTED' ? `
                        <button class="btn btn-danger btn-xs" style="flex:1;" onclick="openRejectStudentModal('${s.roll_no}', '${escapeHtml(s.name)}')">
                            <i class="fa-solid fa-xmark"></i> Reject
                        </button>
                    ` : ''}

                    ${status !== 'PENDING' ? `
                        <button class="btn btn-secondary btn-xs" onclick="resetStudentStatus('${s.roll_no}')" title="Reset to Pending">
                            <i class="fa-solid fa-rotate-left"></i> Reset
                        </button>
                    ` : ''}
                </div>
            </div>
        `;
    }).join('');
}

function previewStudentPhoto(url, name, rollNo, meta) {
    const modal = document.getElementById('studentPhotoModal');
    const img = document.getElementById('modalStudentPhotoImg');
    const nameEl = document.getElementById('modalStudentPhotoName');
    const rollEl = document.getElementById('modalStudentPhotoRoll');
    const metaEl = document.getElementById('modalStudentPhotoMeta');

    if (img) img.src = url;
    if (nameEl) nameEl.textContent = name;
    if (rollEl) rollEl.textContent = rollNo;
    if (metaEl) metaEl.textContent = meta;

    if (modal) modal.classList.remove('hidden');
}

function closeStudentPhotoModal() {
    const modal = document.getElementById('studentPhotoModal');
    if (modal) modal.classList.add('hidden');
}

async function approveStudent(rollNo) {
    try {
        const res = await fetch('/api/admin/students/approve', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ roll_no: rollNo })
        });
        const data = await res.json();
        if (data.success) {
            showToast(data.message || `Student ${rollNo} accepted into auction pool.`, 'success');
            fetchStudentApprovals();
            fetchAdminData();
        } else {
            showToast(data.message || 'Failed to approve student.', 'error');
        }
    } catch (e) {
        showToast('Approval request failed.', 'error');
    }
}

function openRejectStudentModal(rollNo, name) {
    const modal = document.getElementById('rejectStudentModal');
    const nameEl = document.getElementById('rejectStudentNameDisplay');
    const rollEl = document.getElementById('rejectStudentRollDisplay');
    const inputRoll = document.getElementById('rejectStudentRollInput');
    const reasonInput = document.getElementById('rejectStudentReasonInput');

    if (nameEl) nameEl.textContent = name;
    if (rollEl) rollEl.textContent = rollNo;
    if (inputRoll) inputRoll.value = rollNo;
    if (reasonInput) reasonInput.value = '';

    if (modal) modal.classList.remove('hidden');
}

function closeRejectStudentModal() {
    const modal = document.getElementById('rejectStudentModal');
    if (modal) modal.classList.add('hidden');
}

async function submitRejectStudent() {
    const rollNo = document.getElementById('rejectStudentRollInput')?.value;
    const reason = document.getElementById('rejectStudentReasonInput')?.value || '';
    if (!rollNo) return;

    try {
        const res = await fetch('/api/admin/students/reject', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ roll_no: rollNo, reason: reason })
        });
        const data = await res.json();
        if (data.success) {
            showToast(data.message || `Student ${rollNo} marked as rejected.`, 'info');
            closeRejectStudentModal();
            fetchStudentApprovals();
            fetchAdminData();
        } else {
            showToast(data.message || 'Rejection failed.', 'error');
        }
    } catch (e) {
        showToast('Network error while rejecting student.', 'error');
    }
}

async function resetStudentStatus(rollNo) {
    try {
        const res = await fetch('/api/admin/students/reset', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ roll_no: rollNo })
        });
        const data = await res.json();
        if (data.success) {
            showToast(`Reset ${rollNo} status to Pending Review.`, 'info');
            fetchStudentApprovals();
            fetchAdminData();
        } else {
            showToast(data.message || 'Failed to reset status.', 'error');
        }
    } catch (e) {
        showToast('Network error while resetting status.', 'error');
    }
}

async function approveAllStudents() {
    const pendingCount = allStudentsData.filter(s => (s.approval_status || 'PENDING') === 'PENDING').length;
    if (pendingCount === 0) {
        showToast('No pending student registrations to accept.', 'info');
        return;
    }

    if (!confirm(`Are you sure you want to accept and approve all ${pendingCount} pending student registrations into the official SPL auction pool?`)) {
        return;
    }

    try {
        const res = await fetch('/api/admin/students/approve-all', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        const data = await res.json();
        if (data.success) {
            showToast(data.message, 'success');
            fetchStudentApprovals();
            fetchAdminData();
        } else {
            showToast(data.message || 'Batch approval failed.', 'error');
        }
    } catch (e) {
        showToast('Network error during batch approval.', 'error');
    }
}

function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

