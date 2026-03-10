"""
Google Nest integration via Smart Device Management (SDM) API.

Requires:
  - $5 Device Access enrollment at https://console.nest.google.com/products
  - Smart Device Management API enabled in Google Cloud Console
  - NEST_PROJECT_ID in .env (format: enterprises/abc-123)
  - Same GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET as Calendar/Gmail

OAuth token is stored separately from the Gmail/Calendar token in data/nest_token.json.
"""

import json
import os

import requests
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow
from src.env_loader import load_env
from src.egress import ensure_allowed_url
from src.security import safe_error_message

load_env()

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_PATH  = os.path.join(PROJECT_DIR, "data", "nest_token.json")

SDM_SCOPE       = "https://www.googleapis.com/auth/sdm.service"
SDM_BASE_URL    = "https://smartdevicemanagement.googleapis.com/v1"
NEST_PROJECT_ID     = os.getenv("NEST_PROJECT_ID", "")  # full path: enterprises/abc-123
_NEST_PROJECT_UUID  = NEST_PROJECT_ID.replace("enterprises/", "")  # just the UUID part

CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
REDIRECT_URI  = "http://localhost:8000/auth/nest/callback"


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def is_authenticated() -> bool:
    if not os.path.exists(TOKEN_PATH):
        return False
    try:
        creds = _load_creds()
        return creds is not None and (creds.valid or creds.refresh_token)
    except Exception:
        return False


def _load_creds() -> Credentials | None:
    if not os.path.exists(TOKEN_PATH):
        return None
    with open(TOKEN_PATH) as f:
        data = json.load(f)
    from datetime import datetime, timezone
    expiry = None
    if data.get("expiry"):
        expiry = datetime.fromisoformat(data["expiry"]).replace(tzinfo=None)
    creds = Credentials(
        token=data.get("token"),
        refresh_token=data.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        scopes=[SDM_SCOPE],
        expiry=expiry,
    )
    return creds


def _save_creds(creds: Credentials) -> None:
    os.makedirs(os.path.dirname(TOKEN_PATH), exist_ok=True)
    with open(TOKEN_PATH, "w") as f:
        json.dump({
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "expiry": creds.expiry.isoformat() if creds.expiry else None,
        }, f)


def _get_valid_creds() -> Credentials | None:
    creds = _load_creds()
    if creds is None:
        return None
    if not creds.valid and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_creds(creds)
        except Exception:
            return None
    return creds if creds.valid else None


def get_auth_url() -> str:
    """
    Nest SDM requires authorization through nestservices.google.com,
    not the standard accounts.google.com endpoint.
    """
    from urllib.parse import urlencode
    params = urlencode({
        "redirect_uri":  REDIRECT_URI,
        "client_id":     CLIENT_ID,
        "access_type":   "offline",
        "prompt":        "consent",
        "response_type": "code",
        "scope":         SDM_SCOPE,
    })
    return f"https://nestservices.google.com/partnerconnections/{_NEST_PROJECT_UUID}/auth?{params}"


def handle_oauth_callback(code: str) -> bool:
    """Exchange auth code for tokens. Returns True on success."""
    try:
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET,
                    "redirect_uris": [REDIRECT_URI],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            },
            scopes=[SDM_SCOPE],
            redirect_uri=REDIRECT_URI,
        )
        flow.fetch_token(code=code)
        _save_creds(flow.credentials)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# SDM API calls
# ---------------------------------------------------------------------------

def _api_get(path: str) -> dict:
    creds = _get_valid_creds()
    if not creds:
        return {"error": "Nest not authenticated"}
    url = f"{SDM_BASE_URL}/{path}"
    ensure_allowed_url(url)
    resp = requests.get(
        url,
        headers={"Authorization": f"Bearer {creds.token}"},
        timeout=10,
    )
    if not resp.ok:
        return {"error": f"SDM API error {resp.status_code}: {safe_error_message(resp.text)}"}
    return resp.json()


def _api_post(path: str, body: dict) -> dict:
    creds = _get_valid_creds()
    if not creds:
        return {"error": "Nest not authenticated"}
    url = f"{SDM_BASE_URL}/{path}"
    ensure_allowed_url(url)
    resp = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {creds.token}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=10,
    )
    if not resp.ok:
        return {"error": f"SDM API error {resp.status_code}: {safe_error_message(resp.text)}"}
    return resp.json() if resp.text else {"success": True}


def list_devices() -> list[dict]:
    """Return all SDM devices with their type and display name."""
    if not NEST_PROJECT_ID:
        return []
    result = _api_get(f"{NEST_PROJECT_ID}/devices")
    devices = result.get("devices", [])
    out = []
    for d in devices:
        traits = d.get("traits", {})
        info   = traits.get("sdm.devices.traits.Info", {})
        # Prefer customName, then room displayName, then truncated device ID
        room_name = ""
        for rel in d.get("parentRelations", []):
            room_name = rel.get("displayName", "").strip()
            if room_name:
                break
        display_name = info.get("customName") or room_name or d["name"].split("/")[-1][:12]
        out.append({
            "id":           d["name"],
            "type":         d.get("type", "").split(".")[-1],
            "display_name": display_name,
            "traits":       list(traits.keys()),
        })
    return out


def _c_to_f(c: float) -> float:
    return round(c * 9 / 5 + 32, 1)


def _f_to_c(f: float) -> float:
    return round((f - 32) * 5 / 9, 1)


def get_thermostat_status(device_id: str) -> dict:
    """
    Return current thermostat state in Fahrenheit.
    device_id: full device name, e.g. enterprises/xxx/devices/yyy
    """
    result = _api_get(f"{device_id}")
    if "error" in result:
        return result

    traits = result.get("traits", {})

    temp_c   = traits.get("sdm.devices.traits.Temperature", {}).get("ambientTemperatureCelsius")
    humidity = traits.get("sdm.devices.traits.Humidity", {}).get("ambientHumidityPercent")
    mode     = traits.get("sdm.devices.traits.ThermostatMode", {}).get("mode", "UNKNOWN")
    hvac     = traits.get("sdm.devices.traits.ThermostatHvac", {}).get("status", "UNKNOWN")

    setpoint = traits.get("sdm.devices.traits.ThermostatTemperatureSetpoint", {})
    heat_c   = setpoint.get("heatCelsius")
    cool_c   = setpoint.get("coolCelsius")

    info         = traits.get("sdm.devices.traits.Info", {})
    display_name = info.get("customName", device_id.split("/")[-1])

    return {
        "name":              display_name,
        "current_temp_f":    _c_to_f(temp_c) if temp_c is not None else None,
        "humidity_pct":      humidity,
        "mode":              mode,          # HEAT / COOL / HEATCOOL / OFF
        "hvac_status":       hvac,          # HEATING / COOLING / OFF
        "heat_setpoint_f":   _c_to_f(heat_c) if heat_c is not None else None,
        "cool_setpoint_f":   _c_to_f(cool_c) if cool_c is not None else None,
    }


def set_thermostat_mode(device_id: str, mode: str) -> dict:
    """mode: HEAT | COOL | HEATCOOL | OFF"""
    return _api_post(
        f"{device_id}:executeCommand",
        {"command": "sdm.devices.commands.ThermostatMode.SetMode", "params": {"mode": mode}},
    )


def set_thermostat_temperature(device_id: str, temp_f: float, mode: str = None) -> dict:
    """
    Set target temperature in Fahrenheit.
    mode: HEAT sets heat setpoint, COOL sets cool setpoint,
          HEATCOOL sets both (±2°F range), None uses current mode.
    """
    temp_c = _f_to_c(temp_f)

    if mode == "HEATCOOL":
        params = {"heatCelsius": _f_to_c(temp_f - 2), "coolCelsius": _f_to_c(temp_f + 2)}
        command = "sdm.devices.commands.ThermostatTemperatureSetpoint.SetRange"
    elif mode == "COOL":
        params  = {"coolCelsius": temp_c}
        command = "sdm.devices.commands.ThermostatTemperatureSetpoint.SetCool"
    else:  # HEAT or default
        params  = {"heatCelsius": temp_c}
        command = "sdm.devices.commands.ThermostatTemperatureSetpoint.SetHeat"

    return _api_post(f"{device_id}:executeCommand", {"command": command, "params": params})


def get_camera_status(device_id: str) -> dict:
    """Return basic camera info and available features."""
    result = _api_get(f"{device_id}")
    if "error" in result:
        return result

    traits = result.get("traits", {})
    info   = traits.get("sdm.devices.traits.Info", {})
    name   = info.get("customName", device_id.split("/")[-1])

    features = []
    if "sdm.devices.traits.CameraMotion" in traits:
        features.append("motion detection")
    if "sdm.devices.traits.CameraPerson" in traits:
        features.append("person detection")
    if "sdm.devices.traits.CameraLiveStream" in traits:
        features.append("live stream")
    if "sdm.devices.traits.CameraSound" in traits:
        features.append("sound detection")

    return {"name": name, "device_id": device_id, "features": features}
