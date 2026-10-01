# Sphoorthy Premier League (SPL) — Administrator Guide

This guide details administrator tools, user credential management, purse & squad verification, system health monitoring, and security settings in SPL.

---

## 1. Accessing Admin Control Panel

- **Login URL**: `/login` or `/auth/login`
- **Initial Username**: `admin`
- **Initial Password**: `SPLAdmin@2026!`
- **Admin Dashboard**: `/admin`

---

## 2. Password & Security Management (`/admin/settings/security`)

Administrators can change their password at any time.

### Password Policy Rules
- Minimum **10 characters**
- Must contain at least **1 uppercase letter**
- Must contain at least **1 lowercase letter**
- Must contain at least **1 number**
- Must contain at least **1 special character** (`!@#$%^&*()_+-=`)

> [!NOTE]
> If the default development password (`SPLAdmin@2026!`) is active, a security alert warning banner will appear on top of all Admin screens.

---

## 3. Franchise User Management (`/admin/users`)

Administrators can manage franchise user accounts:
- View all franchise accounts and email bindings.
- Enable or disable access for any franchise.
- Reset franchise passwords to a custom unique password.
- Assign or reassign franchise account bindings.

> [!IMPORTANT]
> Passwords are stored using irreversible Werkzeug bcrypt/scrypt hashes. Plaintext passwords are NEVER displayed or exposed in API endpoints.

---

## 4. Auction Integrity Audit (`/admin/system/auction-check`)

Run deep mathematical audit of the auction database:
- Verifies 6 active franchises exist.
- Verifies starting purse defaults to ₹3,00,000.
- Verifies `remaining_purse = 3,00,000 - sum(sold_player_prices)`.
- Validates squad capacity (14 to 15 players per team).
- Ensures no duplicate player purchases or orphan assignments.

If a mismatch is detected, the system displays **`PURSE INTEGRITY ERROR`** or **`SQUAD INTEGRITY ERROR`** without automatically altering database records.

---

## 5. System Health Engine (`/admin/system/health`)

Monitors operational health across 9 core subsystems:
1. **Storage**: JSON data storage verification.
2. **Authentication**: Admin & franchise user account status.
3. **Auction Engine**: Active state validity.
4. **Purse Engine**: Mathematical balance verification.
5. **Squad Engine**: Team capacity checks.
6. **Fixture Engine**: Generated & published match schedules.
7. **Audit Log**: System action tracking count.
8. **Static Files**: Storage availability.
9. **Configuration**: System settings.

---

## 6. Storage Snapshot Backup & Recovery (`/admin/backup`)

- **Create Backup**: Instantly creates a timestamped snapshot in `instance/backups/`.
- **Restore Backup**: Restores previous database snapshot after explicit admin confirmation modal dialog. Safety backup is automatically created prior to restoring.
