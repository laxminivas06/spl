# Sphoorthy Premier League (SPL) — PythonAnywhere Deployment Guide

This document provides a step-by-step production deployment guide for hosting the **SPL Application** on **PythonAnywhere** (Web App / WSGI).

---

## 1. Prerequisites on PythonAnywhere

1. Log into your PythonAnywhere account (`https://www.pythonanywhere.com/`).
2. Open a **Bash Console**.
3. Clone or upload your repository to `/home/yourusername/SPL`.

```bash
cd /home/yourusername/
git clone <your-repository-url> SPL
cd SPL
```

---

## 2. Python Virtual Environment Setup

Create and configure a virtual environment with required dependencies:

```bash
mkvirtualenv --python=/usr/bin/python3.10 spl-env
pip install -r requirements.txt
```

---

## 3. Web App Setup on PythonAnywhere Dashboard

1. Go to the **Web** tab in PythonAnywhere dashboard.
2. Click **Add a new web app**.
3. Choose **Manual Configuration** (Do NOT choose Flask wizard).
4. Select **Python 3.10**.

### Environment & Code Paths
- **Source Code**: `/home/yourusername/SPL`
- **Working Directory**: `/home/yourusername/SPL`
- **Virtualenv**: `/home/yourusername/.virtualenvs/spl-env`

---

## 4. Configure WSGI File (`/var/www/yourusername_pythonanywhere_com_wsgi.py`)

Edit your WSGI configuration file on PythonAnywhere to load environment variables and import `create_app()`:

```python
import os
import sys

# Path to project directory
path = '/home/yourusername/SPL'
if path not in sys.path:
    sys.path.append(path)

# Production Environment Variables
os.environ['FLASK_ENV'] = 'prod'
os.environ['SECRET_KEY'] = 'production-super-secret-key-sphoorthy-2026'
os.environ['ADMIN_PASSWORD'] = 'SPLAdmin@2026!'

from app import create_app
from app.services.seed_service import seed_database

application = create_app('prod')

# Initialize JSON storage & seed admin/franchises automatically
with application.app_context():
    from app.extensions import db
    db.create_all()
    seed_database()
```

---

## 5. Static Files Mapping

On the **Web** tab, configure static file mappings so CSS/JS assets serve directly via PythonAnywhere web server:

| URL | Path |
|---|---|
| `/static/` | `/home/yourusername/SPL/app/static/` |

---

## 6. Initial Storage & Admin Setup

Execute the initial database seed command in Bash console:

```bash
cd /home/yourusername/SPL
workon spl-env
python run.py seed
```

Verify output shows:
- Initial settings configured
- 6 Franchises created with unique passwords
- Development Admin account created (`admin` / `SPLAdmin@2026!`)

---

## 7. Security Hardening Checklist Before Event Day

- [ ] Ensure `FLASK_ENV=prod` (`DEBUG = False`).
- [ ] Ensure `SECRET_KEY` is a long random string.
- [ ] Log in as `admin` at `https://yourusername.pythonanywhere.com/login`.
- [ ] Navigate to `/admin/settings/security` and change default Admin password.
- [ ] Navigate to `/admin/system/health` to verify all 9 subsystems report `OK`.
- [ ] Navigate to `/admin/backup` and create an initial baseline snapshot.
- [ ] Reload the web application on PythonAnywhere Web tab.
