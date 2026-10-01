# Sphoorthy Premier League (SPL) — Auction Day Operator Guide

This step-by-step operational playbook is designed for the **Auction Administrator / Operator** and the **Event Anchor** during the physical SPL college auction.

---

## Roles on Event Day
1. **Event Anchor**: Physically draws player chits from the bowl, announces Player Name and Roll Number.
2. **Auction Admin / Operator**: Operates the SPL Admin Web App on laptop connected to projector.
3. **Franchise Owners (6 Teams)**: Logged into their respective franchise dashboards on mobile/tablets to view live purse and place bids.

---

## Pre-Auction Checklist (30 Minutes Before Start)

1. **Start Server & Web App**: Ensure Flask server or PythonAnywhere instance is active.
2. **Admin Login**: Log into `/admin` on operator laptop.
3. **Check System Health**: Go to `/admin/system/health`. Ensure all 9 subsystems show **OK**.
4. **Run Auction Integrity Audit**: Go to `/admin/system/auction-check`. Verify 6 franchises and ₹3,00,000 starting purse.
5. **Open Projector View**: Open `/projector` on dedicated projector screen (or second monitor). Verify display hides admin controls and future player queues.
6. **Franchise Dashboard Verification**: Have franchise owners log into `/franchise/dashboard` with their assigned credentials.

---

## Live Primary Auction Workflow (Step-by-Step)

```
[Anchor picks chit]
       ↓
[Anchor announces Name & Roll No]
       ↓
[Admin types Roll No on /admin/auction]
       ↓
[Player appears on Projector & Franchise Screens]
       ↓
[Admin clicks "START BIDDING"]
       ↓
[Franchises place Bids (+₹2k / +₹5k / +₹10k increments)]
       ↓
[Player SOLD or UNSOLD]
       ↓
[Repeat for next chit]
```

### Operational Steps:

1. **Draw Chit**: Anchor draws a physical player chit from the bowl.
2. **Announce Player**: Anchor reads player name and Roll Number aloud.
3. **Search Player**: Admin enters Roll Number into **Roll Number Search** input on `/admin/auction`.
4. **Activate Player**: Admin clicks **[ACTIVATE PLAYER]**. Player preview displays on projector.
5. **Start Bidding**: Admin clicks **[START BIDDING]**. The 30-second countdown timer begins.
6. **Accept Bids**:
   - Franchise owners click bid buttons on their dashboard, OR raise physical paddles.
   - Admin can also place bids manually on behalf of franchises if required.
7. **Finalize Sale**:
   - When bidding closes, click **[MARK SOLD]**.
   - System automatically deducts final bid amount from winning franchise purse, adds player to squad, records transaction, and logs audit record.
8. **Mark Unsold**: If no franchise bids, click **[MARK UNSOLD]**. Player status updates to `UNSOLD`.

---

## Post-Primary Auction Workflow

### 1. Second-Chance Auction (`/admin/second-chance`)
1. Update Event State to `SECOND_CHANCE`.
2. Admin reviews list of `UNSOLD` players.
3. Teams request players with remaining purse funds.
4. Admin activates player under Second-Chance under the hammer.

### 2. Squad Review & Validation (`/admin/system/auction-check`)
1. Click **[VALIDATE SQUADS]**.
2. Verify all 6 teams have between **14 and 15 players**.
3. Verify no team has exceeded ₹3,00,000 purse limit.

### 3. Squad Locking
1. Click **[LOCK SQUADS]**.
2. Once locked, primary/second-chance bidding is disabled and squad compositions become immutable.

---

## Post-Auction Fixture Generation (`/admin/fixtures`)

1. Admin navigates to `/admin/fixtures`.
2. Select **Single Round Robin (15 matches)** or **Double Round Robin (30 matches)**.
3. Click **[GENERATE FIXTURES]**. Review draft schedule dates, times, and venues.
4. Click **[PUBLISH FIXTURES]**. Fixtures become visible on public `/fixtures` screen.
