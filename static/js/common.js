// Sphoorthy Premier League (SPL) - Common Utilities & Real-Time Sync

// Sound System (Web Audio API Synthesizer)
class SPLAudio {
    constructor() {
        this.enabled = localStorage.getItem('spl_sound') !== 'false';
        this.ctx = null;
        this.init();
    }

    init() {
        const toggleBtn = document.getElementById('soundToggleBtn');
        if (toggleBtn) {
            this.updateIcon(toggleBtn);
            toggleBtn.addEventListener('click', () => {
                this.enabled = !this.enabled;
                localStorage.setItem('spl_sound', this.enabled);
                this.updateIcon(toggleBtn);
                showToast(this.enabled ? 'Sound FX Enabled' : 'Sound FX Muted', 'info');
            });
        }
    }

    updateIcon(btn) {
        if (!btn) return;
        btn.innerHTML = this.enabled 
            ? '<i class="fa-solid fa-volume-high"></i>' 
            : '<i class="fa-solid fa-volume-xmark" style="color:#ef4444;"></i>';
    }

    getContext() {
        if (!this.ctx) {
            const AudioCtx = window.AudioContext || window.webkitAudioContext;
            if (AudioCtx) this.ctx = new AudioCtx();
        }
        if (this.ctx && this.ctx.state === 'suspended') {
            this.ctx.resume();
        }
        return this.ctx;
    }

    playTone(freq, type = 'sine', duration = 0.15, gainVal = 0.2) {
        if (!this.enabled) return;
        try {
            const ctx = this.getContext();
            if (!ctx) return;
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.type = type;
            osc.frequency.setValueAtTime(freq, ctx.currentTime);
            gain.gain.setValueAtTime(gainVal, ctx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + duration);
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.start();
            osc.stop(ctx.currentTime + duration);
        } catch (e) {
            console.warn('Audio tone error:', e);
        }
    }

    playBidSound() {
        this.playTone(587.33, 'triangle', 0.12, 0.25); // D5
        setTimeout(() => this.playTone(880, 'sine', 0.18, 0.25), 60); // A5
    }

    playSoldSound() {
        if (!this.enabled) return;
        const notes = [523.25, 659.25, 783.99, 1046.50]; // C-E-G-C Fanfare
        notes.forEach((freq, idx) => {
            setTimeout(() => this.playTone(freq, 'triangle', 0.35, 0.3), idx * 120);
        });
    }

    playUnsoldSound() {
        if (!this.enabled) return;
        const notes = [440, 415.30, 392.00, 349.23]; // Descending sad tone
        notes.forEach((freq, idx) => {
            setTimeout(() => this.playTone(freq, 'sawtooth', 0.25, 0.15), idx * 100);
        });
    }

    playTimerTick() {
        this.playTone(1000, 'sine', 0.05, 0.08);
    }
}

const splAudio = new SPLAudio();

// Format Currency
function formatCurrency(amount) {
    if (amount === undefined || amount === null || isNaN(amount)) return '₹ 0';
    return '₹ ' + Number(amount).toLocaleString('en-IN');
}

// Format Seconds to MM:SS
function formatTimer(seconds) {
    const s = Math.max(0, Math.floor(seconds || 0));
    const mins = Math.floor(s / 60);
    const secs = s % 60;
    return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
}

// Toast Notifications
function showToast(message, type = 'info', duration = 3500) {
    const container = document.getElementById('toastContainer');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast-item toast-${type}`;
    
    let icon = 'fa-circle-info';
    if (type === 'success') icon = 'fa-circle-check';
    if (type === 'error') icon = 'fa-circle-exclamation';
    if (type === 'warning') icon = 'fa-triangle-exclamation';

    toast.innerHTML = `
        <i class="fa-solid ${icon}"></i>
        <div class="toast-content">${message}</div>
    `;

    container.appendChild(toast);
    setTimeout(() => {
        toast.style.animation = 'fadeOutToast 0.3s forwards';
        setTimeout(() => toast.remove(), 300);
    }, duration);
}

// Role Switcher Helper
async function switchRole(targetRole) {
    try {
        const res = await fetch('/api/auth/switch-role', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ role: targetRole })
        });
        const data = await res.json();
        if (data.success) {
            showToast(`Switched to ${data.user.title}`, 'success');
            setTimeout(() => {
                if (data.user.role === 'admin') window.location.href = '/admin';
                else if (data.user.role === 'anchor') window.location.href = '/auction';
                else window.location.href = '/team';
            }, 300);
        } else {
            showToast(data.message || 'Could not switch role', 'error');
        }
    } catch (e) {
        showToast('Role switch failed', 'error');
    }
}

// Real-Time Server-Sent Events (SSE) Client
class SPLEventSync {
    constructor() {
        this.eventSource = null;
        this.reconnectTimer = null;
        this.init();
    }

    init() {
        this.connect();
    }

    connect() {
        if (this.eventSource) {
            this.eventSource.close();
        }

        const pill = document.getElementById('sseConnectionPill');
        const pillText = document.getElementById('sseStatusText');

        this.eventSource = new EventSource('/api/events');

        this.eventSource.onopen = () => {
            if (pill) {
                pill.style.borderColor = 'rgba(74, 222, 128, 0.4)';
                pill.style.background = 'rgba(74, 222, 128, 0.15)';
                pill.style.color = '#4ade80';
            }
            if (pillText) pillText.textContent = 'LIVE SYNC';
        };

        this.eventSource.addEventListener('CONNECTED', (e) => {
            window.dispatchEvent(new CustomEvent('spl:connected', { detail: JSON.parse(e.data) }));
        });

        this.eventSource.addEventListener('STATE_UPDATE', (e) => {
            const data = JSON.parse(e.data);
            window.dispatchEvent(new CustomEvent('spl:state_update', { detail: data }));
        });

        this.eventSource.addEventListener('PLAYER_ACTIVATED', (e) => {
            const data = JSON.parse(e.data);
            splAudio.playBidSound();
            window.dispatchEvent(new CustomEvent('spl:player_activated', { detail: data }));
        });

        this.eventSource.addEventListener('BID_PLACED', (e) => {
            const data = JSON.parse(e.data);
            splAudio.playBidSound();
            window.dispatchEvent(new CustomEvent('spl:bid', { detail: data }));
        });

        this.eventSource.addEventListener('PLAYER_SOLD', (e) => {
            const data = JSON.parse(e.data);
            splAudio.playSoldSound();
            if (typeof confetti === 'function') {
                confetti({ particleCount: 100, spread: 80, origin: { y: 0.6 } });
            }
            window.dispatchEvent(new CustomEvent('spl:sold', { detail: data }));
        });

        this.eventSource.addEventListener('PLAYER_UNSOLD', (e) => {
            const data = JSON.parse(e.data);
            splAudio.playUnsoldSound();
            window.dispatchEvent(new CustomEvent('spl:unsold', { detail: data }));
        });

        this.eventSource.onerror = () => {
            if (pill) {
                pill.style.borderColor = 'rgba(239, 68, 68, 0.4)';
                pill.style.background = 'rgba(239, 68, 68, 0.15)';
                pill.style.color = '#ef4444';
            }
            if (pillText) pillText.textContent = 'RECONNECTING';

            this.eventSource.close();
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = setTimeout(() => this.connect(), 3000);
        };
    }
}

// Global SSE instance
window.splEventSync = new SPLEventSync();
