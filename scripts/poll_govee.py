#!/usr/bin/env python3
"""Poll a Govee Wi-Fi thermometer via the cloud API, store readings, and alert on overheat.

Designed to run both locally (for testing) and inside GitHub Actions on a schedule.

Modes
-----
  --list-devices   Print every device on the account (sku, device id, name) so you can
                   find your thermometer's identifiers once. Configure them afterwards.
  --once           (default) Take a single reading, append it to the history, write the
                   latest snapshot, and run the overheat alert check.

Configuration (environment variables)
-------------------------------------
  GOVEE_API_KEY        required. Your Govee developer API key.
  GOVEE_DEVICE_SKU     required for --once. e.g. "H5179".
  GOVEE_DEVICE_ID      required for --once. e.g. "AB:CD:..." (MAC-style id).
  TEMP_UNIT            "C" (default) or "F" — unit to DISPLAY/store after conversion.
  ALERT_THRESHOLD_C    overheat threshold in Celsius (default 30).
  ALERT_RECOVERED      "1" (default) to also email when temperature drops back below.

  SMTP_USER            Gmail address used to send alert mail (e.g. you@gmail.com).
  SMTP_APP_PASSWORD    Gmail app password (NOT your normal password).
  ALERT_TO             comma-separated recipient list (you + IT partner).
  SMTP_HOST            default "smtp.gmail.com".
  SMTP_PORT            default 587 (STARTTLS).

Local dev: put these in a .env file (gitignored); python-dotenv loads it automatically.
"""

from __future__ import annotations

import argparse
import json
import os
import smtplib
import sys
import uuid
from datetime import datetime, timezone, timedelta
from email.message import EmailMessage
from pathlib import Path

import requests

try:  # optional convenience for local development
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv is optional
    pass

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "docs" / "data"
LATEST_FILE = DATA_DIR / "latest.json"
READINGS_FILE = DATA_DIR / "readings.json"
STATE_FILE = DATA_DIR / "state.json"

# --------------------------------------------------------------------------- #
# Govee API
# --------------------------------------------------------------------------- #
API_BASE = "https://openapi.api.govee.com"
DEVICES_URL = f"{API_BASE}/router/api/v1/user/devices"
STATE_URL = f"{API_BASE}/router/api/v1/device/state"

HISTORY_DAYS = 30
HTTP_TIMEOUT = 20


def _api_key() -> str:
    key = os.environ.get("GOVEE_API_KEY", "").strip()
    if not key:
        sys.exit("ERROR: GOVEE_API_KEY is not set.")
    return key


def _headers() -> dict:
    return {"Content-Type": "application/json", "Govee-API-Key": _api_key()}


def list_devices() -> None:
    """Print all devices on the account so the user can find their thermometer."""
    resp = requests.get(DEVICES_URL, headers=_headers(), timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()
    devices = payload.get("data", []) or []
    if not devices:
        print("No devices returned. (Check the API key / account.)")
        print(json.dumps(payload, indent=2))
        return
    print(f"Found {len(devices)} device(s):\n")
    for d in devices:
        print(f"  name   : {d.get('deviceName')}")
        print(f"  sku    : {d.get('sku')}")
        print(f"  device : {d.get('device')}")
        instances = [c.get("instance") for c in d.get("capabilities", [])]
        print(f"  caps   : {', '.join(filter(None, instances))}")
        print()
    print("Set GOVEE_DEVICE_SKU and GOVEE_DEVICE_ID to your thermometer's values above.")


def fetch_state(sku: str, device: str) -> dict:
    """Return the raw /device/state payload for one device."""
    body = {
        "requestId": str(uuid.uuid4()),
        "payload": {"sku": sku, "device": device},
    }
    resp = requests.post(
        STATE_URL, headers=_headers(), json=body, timeout=HTTP_TIMEOUT
    )
    resp.raise_for_status()
    return resp.json()


def _capability_value(payload: dict, instance: str):
    """Extract a capability's state value by its instance name."""
    for cap in payload.get("payload", {}).get("capabilities", []):
        if cap.get("instance") == instance:
            return cap.get("state", {}).get("value")
    return None


def f_to_c(value: float) -> float:
    return (value - 32.0) * 5.0 / 9.0


def parse_reading(payload: dict) -> dict:
    """Pull temperature + humidity out of a /device/state payload.

    Govee returns sensorTemperature in Fahrenheit. We normalise to the configured
    TEMP_UNIT (Celsius by default) for storage/display, and always keep a Celsius
    value for threshold comparisons.
    """
    raw_temp = _capability_value(payload, "sensorTemperature")
    humidity = _capability_value(payload, "sensorHumidity")
    if raw_temp is None:
        raise ValueError(
            "No sensorTemperature in response. Raw payload:\n"
            + json.dumps(payload, indent=2)
        )

    raw_temp = float(raw_temp)
    # API reports Fahrenheit; convert to Celsius as our canonical value.
    temp_c = f_to_c(raw_temp)

    display_unit = os.environ.get("TEMP_UNIT", "C").upper()
    temp_display = raw_temp if display_unit == "F" else round(temp_c, 2)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "temperature": temp_display,
        "temperature_c": round(temp_c, 2),
        "unit": display_unit,
        "humidity": round(float(humidity), 1) if humidity is not None else None,
    }


# --------------------------------------------------------------------------- #
# Storage
# --------------------------------------------------------------------------- #
def _load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return default
    return default


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def store_reading(reading: dict) -> None:
    _write_json(LATEST_FILE, reading)

    history = _load_json(READINGS_FILE, [])
    if not isinstance(history, list):
        history = []
    history.append(reading)

    cutoff = datetime.now(timezone.utc) - timedelta(days=HISTORY_DAYS)
    trimmed = []
    for r in history:
        try:
            ts = datetime.fromisoformat(r["timestamp"])
        except (KeyError, ValueError):
            continue
        if ts >= cutoff:
            trimmed.append(r)
    _write_json(READINGS_FILE, trimmed)


# --------------------------------------------------------------------------- #
# Alerting
# --------------------------------------------------------------------------- #
def _send_email(subject: str, body: str) -> bool:
    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_APP_PASSWORD", "").strip()
    recipients = [
        a.strip() for a in os.environ.get("ALERT_TO", "").split(",") if a.strip()
    ]
    if not (user and password and recipients):
        print("Alert email skipped: SMTP_USER / SMTP_APP_PASSWORD / ALERT_TO not all set.")
        return False

    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "587"))

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = ", ".join(recipients)
    msg.set_content(body)

    try:
        with smtplib.SMTP(host, port, timeout=HTTP_TIMEOUT) as server:
            server.starttls()
            server.login(user, password)
            server.send_message(msg)
        print(f"Alert email sent to {', '.join(recipients)}")
        return True
    except Exception as exc:  # noqa: BLE001 - alerting must never crash the poll
        print(f"WARNING: failed to send alert email: {exc}")
        return False


def check_alert(reading: dict) -> None:
    """De-bounced overheat alerting using state.json as memory."""
    threshold = float(os.environ.get("ALERT_THRESHOLD_C", "30"))
    alert_recovered = os.environ.get("ALERT_RECOVERED", "1") == "1"
    temp_c = reading["temperature_c"]

    state = _load_json(STATE_FILE, {"alerting": False, "since": None})
    was_alerting = bool(state.get("alerting"))
    is_alerting = temp_c >= threshold

    when = reading["timestamp"]
    t_disp = f"{reading['temperature']} °{reading['unit']}"

    if is_alerting and not was_alerting:
        _send_email(
            subject=f"⚠️ Server room OVERHEAT: {t_disp}",
            body=(
                f"The server room temperature has reached {t_disp} "
                f"({temp_c} °C), at or above the {threshold} °C threshold.\n\n"
                f"Time (UTC): {when}\n"
                f"Humidity: {reading.get('humidity')} %\n"
            ),
        )
        state = {"alerting": True, "since": when}
    elif was_alerting and not is_alerting:
        if alert_recovered:
            _send_email(
                subject=f"✅ Server room temperature recovered: {t_disp}",
                body=(
                    f"The server room temperature is back to {t_disp} "
                    f"({temp_c} °C), below the {threshold} °C threshold.\n\n"
                    f"Time (UTC): {when}\n"
                ),
            )
        state = {"alerting": False, "since": None}
    # else: no state change -> no email (de-bounced)

    _write_json(STATE_FILE, state)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def run_once() -> None:
    sku = os.environ.get("GOVEE_DEVICE_SKU", "").strip()
    device = os.environ.get("GOVEE_DEVICE_ID", "").strip()
    if not (sku and device):
        sys.exit(
            "ERROR: GOVEE_DEVICE_SKU and GOVEE_DEVICE_ID must be set. "
            "Run with --list-devices to find them."
        )

    payload = fetch_state(sku, device)
    reading = parse_reading(payload)
    store_reading(reading)
    check_alert(reading)
    print(
        f"OK {reading['timestamp']}: "
        f"{reading['temperature']} °{reading['unit']} "
        f"({reading['temperature_c']} °C), "
        f"humidity {reading.get('humidity')} %"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Poll a Govee thermometer.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--list-devices", action="store_true", help="List account devices and exit."
    )
    group.add_argument(
        "--once", action="store_true", help="Take one reading (default)."
    )
    args = parser.parse_args()

    if args.list_devices:
        list_devices()
    else:
        run_once()


if __name__ == "__main__":
    main()
