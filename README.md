# Govee Server-Room Thermometer → Dashboard + Overheat Alerts

Monitor a Govee Wi-Fi thermometer remotely with **zero infrastructure running in your
office**. A GitHub Actions cron job polls the Govee cloud API every 15 minutes, commits the
reading into this repo, and a static GitHub Pages page shows the live value plus a history
graph. If the room overheats, it emails you and your IT partner.

```
GitHub Actions (cron, every 15 min)
  └─ scripts/poll_govee.py
       ├─ read temperature/humidity from the Govee cloud API
       ├─ append to docs/data/readings.json (rolling 30 days)
       ├─ write docs/data/latest.json
       ├─ email alert on overheat threshold crossing (de-bounced)
       └─ commit & push the data files

GitHub Pages (serves /docs)
  └─ docs/index.html + app.js  →  live readout + Chart.js graph
```

---

## 1. Local setup & testing

Requires Python 3.9+.

```powershell
cd C:\ProgettiLavori\GooveThermometer
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

copy .env.example .env      # then edit .env and put your real GOVEE_API_KEY in it
```

Find your thermometer's identifiers:

```powershell
python scripts\poll_govee.py --list-devices
```

Copy its `sku` and `device` into `.env` as `GOVEE_DEVICE_SKU` and `GOVEE_DEVICE_ID`, then
take a single reading:

```powershell
python scripts\poll_govee.py --once
```

This writes `docs/data/latest.json` and appends to `docs/data/readings.json`. Compare the
value with the Govee Home app to confirm the unit/conversion is correct.

Preview the page locally (a plain `file://` open also works, but a tiny server avoids
fetch/CORS quirks):

```powershell
python -m http.server -d docs 8000
# then open http://localhost:8000
```

---

## 2. Deploy to GitHub Pages

1. Create a **public** GitHub repo and push this project.
2. **Settings → Pages →** Source: *Deploy from a branch*, Branch: `main`, Folder: `/docs`.
   Your page will be at `https://<org-or-user>.github.io/<repo>/`.
3. **Settings → Secrets and variables → Actions → Secrets**, add:
   - `GOVEE_API_KEY`
   - `GOVEE_DEVICE_SKU`
   - `GOVEE_DEVICE_ID`
   - `SMTP_USER` (your Gmail address)
   - `SMTP_APP_PASSWORD` (a Gmail *app password* — see below)
   - `ALERT_TO` (comma-separated: you + IT partner)
4. *(Optional)* **Variables** tab — override defaults without code changes:
   - `TEMP_UNIT` (`C` or `F`, default `C`)
   - `ALERT_THRESHOLD_C` (default `30`)
   - `ALERT_RECOVERED` (`1`/`0`, default `1`)
5. **Actions tab →** *Poll Govee thermometer* → **Run workflow** to trigger the first run
   manually, then let the 15-minute cron take over.

Share the Pages URL with your IT partner.

### Gmail app password
Alerts use Gmail SMTP. With 2-step verification enabled, create an app password at
<https://myaccount.google.com/apppasswords> and use that 16-character value as
`SMTP_APP_PASSWORD` (not your normal Google password).

### Prefer phone push instead of email?
You can swap the email transport for a free [ntfy.sh](https://ntfy.sh) topic (no
credentials, push to the ntfy mobile app). See `_send_email()` in `scripts/poll_govee.py`
for where to plug it in.

---

## 3. Security notes

- The API key lives **only** in `.env` (local, gitignored) and GitHub **Actions secrets** —
  never in `docs/` and never committed.
- ⚠️ If the API key was ever shared in plaintext (chat, email), **regenerate it** on the
  Govee developer portal and use only the new key.
- The public page exposes temperature/humidity numbers only. The page is marked `noindex`;
  share the URL privately for an extra layer of obscurity.

---

## Files

| Path | Purpose |
|------|---------|
| `scripts/poll_govee.py` | Poll the API, store readings, send alerts |
| `.github/workflows/poll.yml` | 15-minute cron that runs the poller and commits data |
| `docs/index.html`, `app.js`, `style.css` | The dashboard |
| `docs/data/*.json` | Latest reading, history, alert state (written by the job) |
| `requirements.txt` | `requests`, `python-dotenv` |
