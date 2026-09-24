/**
 * Khelo SPL - Franchise Squads View Controller
 */

let squadsTeams = [];
let currentSquadFilter = 'all';

document.addEventListener('DOMContentLoaded', () => {
    loadSquadsData();
});

async function loadSquadsData() {
    try {
        const res = await fetch('/api/teams');
        const data = await res.json();
        if (data.success) {
            squadsTeams = data.teams || [];
            renderSquadFilterPills();
            renderSquadCards();
        }
    } catch (e) {
        console.error("Error loading squad data:", e);
    }
}

function renderSquadFilterPills() {
    const container = document.getElementById('squadFilterPills');
    if (!container) return;

    let html = `<button class="squad-filter-pill ${currentSquadFilter === 'all' ? 'active' : ''}" onclick="filterSquadView('all')">All Franchises (${squadsTeams.length})</button>`;
    
    squadsTeams.forEach(t => {
        const isActive = currentSquadFilter === t.id ? 'active' : '';
        html += `<button class="squad-filter-pill ${isActive}" onclick="filterSquadView('${t.id}')">${t.name}</button>`;
    });

    container.innerHTML = html;
}

function filterSquadView(teamId) {
    currentSquadFilter = teamId;
    renderSquadFilterPills();
    renderSquadCards();
}

function renderSquadCards() {
    const grid = document.getElementById('squadsGrid');
    if (!grid) return;

    const filtered = currentSquadFilter === 'all' 
        ? squadsTeams 
        : squadsTeams.filter(t => t.id === currentSquadFilter);

    if (filtered.length === 0) {
        grid.innerHTML = '<div class="text-center p-5 text-muted">No franchise squads found.</div>';
        return;
    }

    grid.innerHTML = filtered.map(t => {
        const squad = t.squad || [];
        const squadListHtml = squad.length === 0
            ? '<div class="squad-empty"><i class="fa-solid fa-users-slash" style="font-size:2rem; margin-bottom:10px; display:block;"></i>No players purchased yet</div>'
            : squad.map(p => `
                <div class="squad-player-row">
                    <div>
                        <div class="sq-player-name">${p.name}</div>
                        <div class="sq-player-meta">
                            <span class="role-badge role-${(p.role || 'All-Rounder').toLowerCase().replace(' ', '-')}">${p.role}</span>
                            ${p.roll_no ? ` • ${p.roll_no}` : ''}
                        </div>
                    </div>
                    <div class="sq-player-price">${formatCurrency(p.bought_for)}</div>
                </div>
            `).join('');

        return `
            <div class="team-squad-card" style="border-top: 4px solid ${t.color || '#3b82f6'};">
                <div class="team-squad-header">
                    <div class="team-brand-col">
                        <div class="team-card-icon" style="background:${t.color || '#3b82f6'};">
                            ${t.logo ? `<img src="${t.logo}" style="width:100%;height:100%;object-fit:cover;border-radius:12px;">` : (t.short_name || t.name.slice(0,3).toUpperCase())}
                        </div>
                        <div>
                            <h3 class="team-squad-title">${t.name}</h3>
                            <div class="team-squad-sub">Owner: ${t.owner || '-'} | Capt: ${t.captain || '-'}</div>
                        </div>
                    </div>
                    <div class="squad-count-chip">${squad.length} Players</div>
                </div>

                <div class="team-finance-strip">
                    <div class="fin-item">
                        <span class="fin-label">Purse Budget</span>
                        <span class="fin-val">${formatCurrency(t.initial_budget)}</span>
                    </div>
                    <div class="fin-item">
                        <span class="fin-label">Total Spent</span>
                        <span class="fin-val amber">${formatCurrency(t.spent || 0)}</span>
                    </div>
                    <div class="fin-item">
                        <span class="fin-label">Remaining</span>
                        <span class="fin-val green">${formatCurrency(t.balance)}</span>
                    </div>
                </div>

                <div class="squad-player-list">
                    ${squadListHtml}
                </div>
            </div>
        `;
    }).join('');
}
