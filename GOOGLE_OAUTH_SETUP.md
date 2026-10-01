# Google OAuth Setup & Google Cloud Configuration Guide

This document provides step-by-step instructions for configuring Google Identity Services (OAuth 2.0) for the **SPL (Sphoorthy Premier League)** application.

---

## 1. Google Cloud Console Configuration

To enable Google Sign-In for Franchise Owners, follow these steps in the Google Cloud Console:

1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project or select your existing project (e.g., `SPL-Auction-System`).
3. Navigate to **APIs & Services > OAuth consent screen**:
   - User Type: Select **External**.
   - App Name: `Sphoorthy Premier League`
   - User Support Email: Administrator's email.
   - Developer Contact Information: Administrator's email.
   - Save and continue through Scopes (ensure `openid`, `email`, `profile` are selected).
4. Navigate to **APIs & Services > Credentials**:
   - Click **+ CREATE CREDENTIALS** -> **OAuth client ID**.
   - Application Type: Select **Web application**.
   - Name: `SPL Web Client`.

---

## 2. Authorized JavaScript Origins & Redirect URIs

Configure the exact origins and redirect URIs depending on your environment.

### A. Local Development Environment
- **Authorized JavaScript Origins**:
  - `http://127.0.0.1:5000`
  - `http://localhost:5000`
- **Authorized Redirect URIs**:
  - `http://127.0.0.1:5000/auth/google/callback`
  - `http://localhost:5000/auth/google/callback`

### B. PythonAnywhere Production Environment
- **Authorized JavaScript Origins**:
  - `https://YOUR-USERNAME.pythonanywhere.com`
- **Authorized Redirect URIs**:
  - `https://YOUR-USERNAME.pythonanywhere.com/auth/google/callback`

> **CRITICAL**: Google requires exact scheme (`http://` vs `https://`), domain name, port, path, and case matching. Any mismatch will result in a `redirect_uri_mismatch` error.

---

## 3. Environment Variables Configuration

Copy `.env.example` to `.env` (or set Environment Variables in PythonAnywhere Web tab):

```env
GOOGLE_CLIENT_ID=your_actual_client_id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your_actual_client_secret
GOOGLE_REDIRECT_URI=https://YOUR-USERNAME.pythonanywhere.com/auth/google/callback
```

> **SECURITY NOTE**: Never commit `.env` or your `GOOGLE_CLIENT_SECRET` to Git or expose it to frontend templates.

---

## 4. Franchise Owner Authorization Workflow

1. Admin opens **Admin -> Franchises**.
2. Click **Authentication & Logo** or **Configure Team & Auth** for a franchise.
3. Enter the franchise owner's official Gmail account in **AUTHORIZED GOOGLE OWNER EMAIL** (e.g., `owner@gmail.com`).
4. Ensure **Enable Google Authentication** is checked (`ENABLED`).
5. When the Franchise Owner clicks **[ Continue with Google ]** on `/login`:
   - Google authenticates the Google Account.
   - SPL retrieves the verified email and normalizes it (lowercase, trimmed).
   - SPL matches the email against `Franchise.authorized_email`.
   - If authorized & franchise active, SPL creates the franchise session.
   - If not authorized, access is denied with a clear warning page.
