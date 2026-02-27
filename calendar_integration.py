"""
Google Calendar Integration
============================

OAuth2 flow + event fetching for Google Calendar.
Token stored in token.json (git-ignored).

Setup:
1. Go to Google Cloud Console → create project
2. Enable Google Calendar API
3. Create OAuth2 credentials (Web application type)
4. Set redirect URI: http://localhost:8000/auth/google/callback
5. Copy Client ID + Secret to .env
"""

import os
import json
from datetime import datetime, timedelta

from dotenv import load_dotenv
load_dotenv()

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_PATH = os.path.join(PROJECT_DIR, 'token.json')

SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']


def get_oauth_flow(redirect_uri):
    """Build OAuth2 flow from .env credentials."""
    from google_auth_oauthlib.flow import Flow

    client_id = os.getenv('GOOGLE_CLIENT_ID')
    client_secret = os.getenv('GOOGLE_CLIENT_SECRET')

    if not client_id or not client_secret:
        raise ValueError("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set in .env")

    client_config = {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri]
        }
    }

    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=redirect_uri
    )
    return flow


def get_credentials():
    """Load and refresh credentials from token.json."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    if not os.path.exists(TOKEN_PATH):
        return None

    creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            save_credentials(creds)
        except Exception:
            # Token is invalid, need re-auth
            os.remove(TOKEN_PATH)
            return None

    return creds


def save_credentials(creds):
    """Store OAuth token to token.json."""
    with open(TOKEN_PATH, 'w') as f:
        f.write(creds.to_json())


def is_authenticated():
    """Check if we have valid calendar credentials."""
    creds = get_credentials()
    return creds is not None and creds.valid


def get_todays_events():
    """Fetch today's calendar events."""
    return get_upcoming_events(days=1)


def get_upcoming_events(days=7):
    """Fetch events for the next N days."""
    from googleapiclient.discovery import build

    creds = get_credentials()
    if not creds or not creds.valid:
        return None

    service = build('calendar', 'v3', credentials=creds)

    now = datetime.utcnow()
    time_min = now.isoformat() + 'Z'
    time_max = (now + timedelta(days=days)).isoformat() + 'Z'

    events_result = service.events().list(
        calendarId='primary',
        timeMin=time_min,
        timeMax=time_max,
        maxResults=50,
        singleEvents=True,
        orderBy='startTime'
    ).execute()

    events = events_result.get('items', [])

    formatted = []
    for event in events:
        start = event['start'].get('dateTime', event['start'].get('date'))
        end = event['end'].get('dateTime', event['end'].get('date'))
        formatted.append({
            'summary': event.get('summary', 'No title'),
            'start': start,
            'end': end,
            'location': event.get('location', ''),
            'description': event.get('description', ''),
        })

    return formatted
