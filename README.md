# Sphoorthy Premier League (SPL) — Auction & Tournament System

## Overview
**SPL (Sphoorthy Premier League)** is a production-grade, IPL-inspired mock auction and tournament management web application built for the physical college cricket tournament at Sphoorthy Engineering College.

The application supports real-time live bidding, physical chit-selection anchor integration, strict purse and squad validation, post-auction second-chance bidding, single/double round-robin fixture generation, and complete role-based application security.

---

## Technical Stack & Architecture
- **Backend Framework**: Python / Flask (App Factory Pattern)
- **Data Storage**: Pure JSON File-Based Storage (Zero SQL / DB Dependency)
- **Session & Auth**: Flask-Login, Werkzeug password hashing (HttpOnly, CSRF-protected sessions)
- **Realtime Updates**: Vanilla JavaScript HTTP Polling (Lightweight, 100% PythonAnywhere WSGI Compatible)
- **Frontend**: HTML5, Vanilla CSS, Bootstrap 5, Modern SVG & Visual Badges
- **Deployment Platform**: Optimized for PythonAnywhere & standard Linux/Windows WSGI hosts

---

## Official SPL Tournament Rules & Specifications
- **Franchises**: 6 Teams (`Cyber Vipers`, `Tech Titans`, `Neural Hawks`, `Data Phoenix`, `Circuit Chargers`, `Iron Giants`)
- **Starting Purse**: ₹3,00,000 per franchise
- **Squad Capacity**: Minimum 14 players, Maximum 15 players
- **Base Price**: ₹10,000 per player
- **Bid Increments**:
  - ₹10,000 to ₹20,000: **+₹2,000**
  - Above ₹20,000 to ₹50,000: **+₹5,000**
  - Above ₹50,000 to ₹1,00,000: **+₹10,000**
  - Above ₹1,00,000: **+₹10,000**
- **Manual Player Activation**: Anchor picks physical chit -> Admin types Roll Number -> Player appears under hammer. **No automatic next-player reveal.**
- **Google OAuth**: Disabled/Removed from active flow; application authentication (Username/Email + Password) active.

---

## Initial Credentials (Development / Testing Only)

> [!WARNING]
> Default Admin credentials are for development/testing only. Change the default password upon initial production login.

### Admin Account
- **Username**: `admin`
- **Password**: `SPLAdmin@2026!`

### Test Franchise Accounts
- `cybervipers` / `Vipers@2026!` (Cyber Vipers)
- `techtitans` / `Titans@2026!` (Tech Titans)
- `neuralhawks` / `Hawks@2026!` (Neural Hawks)
- `dataphoenix` / `Phoenix@2026!` (Data Phoenix)
- `circuitchargers` / `Chargers@2026!` (Circuit Chargers)
- `irongiants` / `Giants@2026!` (Iron Giants)

---

## Local Setup & Development

```bash
# 1. Clone repository
cd c:/PROJECTS/SPL

# 2. Create virtual environment
python -m venv venv
venv\Scripts\activate  # On Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set Environment Variables
set FLASK_ENV=dev
set SECRET_KEY=your-production-secret-key-here
set ADMIN_PASSWORD=SPLAdmin@2026!

# 5. Initialize & Seed Database
python run.py seed

# 6. Run Application
python run.py
```
App will be accessible at: `http://127.0.0.1:5000/`

---

## Core System Architecture & Features

### 1. Unified Application Authentication & Security
- Username/Email + Password authentication with Werkzeug password hashing.
- Role-based authorization (`ADMIN`, `FRANCHISE`, `PUBLIC`).
- Password strength validation on `/admin/settings/security`.
- Strict CSRF token protection on state-changing forms and endpoints.
- IDOR protection preventing franchise A from inspecting franchise B's private data.

### 2. Live Auction Engine & Event Control Panel
- `/admin/event-control`: Central control room for overall event state transitions.
- Anchor chit selection workflow: Roll number search & single-player manual activation.
- Real-time bid increments and countdown timer control (Pause, Resume, Extend).
- SOLD & UNSOLD atomic transactions with instant purse deduction and audit logging.

### 3. Second-Chance Auction & Post-Auction Workflow
- Unsold player pool filtering and selective re-auctioning.
- Squad validation enforcing 14-15 player bounds and ₹3,00,000 purse cap.
- Immutable Squad Locking before fixture generation.

### 4. Tournament Fixture Management
- Single Round-Robin (15 matches) and Double Round-Robin (30 matches) engine.
- Automatic round and venue allocation with draft review before publishing.

### 5. System Health, Audit, & Backup / Recovery
- `/admin/system/health`: 9-subsystem real-time diagnostic health engine.
- `/admin/system/auction-check`: Mathematical purse integrity & squad audit tool.
- `/admin/backup`: Safe JSON storage snapshot backups and confirmed restore operations.

---

## Key Documentation Files
- [DEPLOYMENT.md](file:///c:/PROJECTS/SPL/DEPLOYMENT.md) — Step-by-step PythonAnywhere deployment guide.
- [ADMIN_GUIDE.md](file:///c:/PROJECTS/SPL/ADMIN_GUIDE.md) — Administrator user manual and security guide.
- [AUCTION_DAY_GUIDE.md](file:///c:/PROJECTS/SPL/AUCTION_DAY_GUIDE.md) — Physical auction day operator & anchor operational checklist.
