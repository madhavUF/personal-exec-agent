"""
Gmail Integration
==================

OAuth2 flow + email operations for Gmail.
Shares OAuth flow with calendar_integration but adds Gmail scopes.

Capabilities:
- Send emails
- Read recent emails
- Search emails
- Create drafts
"""

import os
import json
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_PATH = os.path.join(PROJECT_DIR, 'token.json')

# Combined scopes for calendar + gmail
SCOPES = [
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.compose',
]


def get_oauth_flow(redirect_uri):
    """Build OAuth2 flow with Gmail + Calendar scopes."""
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
            os.remove(TOKEN_PATH)
            return None

    return creds


def save_credentials(creds):
    """Store OAuth token to token.json."""
    with open(TOKEN_PATH, 'w') as f:
        f.write(creds.to_json())


def is_authenticated():
    """Check if we have valid Gmail credentials."""
    creds = get_credentials()
    return creds is not None and creds.valid


def get_gmail_service():
    """Get authenticated Gmail API service."""
    from googleapiclient.discovery import build

    creds = get_credentials()
    if not creds or not creds.valid:
        return None

    return build('gmail', 'v1', credentials=creds)


def send_email(to: str, subject: str, body: str, html: bool = False, as_assistant: bool = True) -> dict:
    """
    Send an email.

    Args:
        to: Recipient email address
        subject: Email subject
        body: Email body (plain text or HTML)
        html: If True, body is treated as HTML
        as_assistant: If True, adds assistant signature (default: True)

    Returns:
        dict with success status and message ID or error
    """
    service = get_gmail_service()
    if not service:
        return {"success": False, "error": "Gmail not authenticated"}

    # Get user's display name from env, fallback to email
    user_name = os.getenv('USER_DISPLAY_NAME')
    if not user_name:
        user_email = get_user_email()
        user_name = user_email.split('@')[0].title() if user_email else "User"

    # Add assistant signature if sending as assistant
    if as_assistant:
        assistant_signature = f"\n\n---\nSent on behalf of {user_name} via AI Assistant"
        body = body + assistant_signature

    try:
        if html:
            message = MIMEMultipart('alternative')
            message.attach(MIMEText(body, 'html'))
        else:
            message = MIMEText(body)

        message['to'] = to
        message['subject'] = subject

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        result = service.users().messages().send(
            userId='me',
            body={'raw': raw}
        ).execute()

        return {
            "success": True,
            "message_id": result['id'],
            "thread_id": result['threadId']
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def create_draft(to: str, subject: str, body: str, as_assistant: bool = True) -> dict:
    """
    Create an email draft.

    Args:
        to: Recipient email address
        subject: Email subject
        body: Email body
        as_assistant: If True, adds assistant signature (default: True)

    Returns:
        dict with success status and draft ID or error
    """
    service = get_gmail_service()
    if not service:
        return {"success": False, "error": "Gmail not authenticated"}

    # Get user's display name from env, fallback to email
    user_name = os.getenv('USER_DISPLAY_NAME')
    if not user_name:
        user_email = get_user_email()
        user_name = user_email.split('@')[0].title() if user_email else "User"

    # Add assistant signature if sending as assistant
    if as_assistant:
        assistant_signature = f"\n\n---\nSent on behalf of {user_name} via AI Assistant"
        body = body + assistant_signature

    try:
        message = MIMEText(body)
        message['to'] = to
        message['subject'] = subject

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        draft = service.users().drafts().create(
            userId='me',
            body={'message': {'raw': raw}}
        ).execute()

        return {
            "success": True,
            "draft_id": draft['id'],
            "message": f"Draft created for {to}"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_recent_emails(max_results: int = 10) -> list:
    """
    Get recent emails from inbox.

    Returns:
        List of email summaries
    """
    service = get_gmail_service()
    if not service:
        return None

    try:
        results = service.users().messages().list(
            userId='me',
            maxResults=max_results,
            labelIds=['INBOX']
        ).execute()

        messages = results.get('messages', [])
        emails = []

        for msg in messages:
            msg_data = service.users().messages().get(
                userId='me',
                id=msg['id'],
                format='metadata',
                metadataHeaders=['From', 'Subject', 'Date']
            ).execute()

            headers = {h['name']: h['value'] for h in msg_data['payload']['headers']}
            emails.append({
                'id': msg['id'],
                'from': headers.get('From', 'Unknown'),
                'subject': headers.get('Subject', 'No subject'),
                'date': headers.get('Date', ''),
                'snippet': msg_data.get('snippet', '')
            })

        return emails
    except Exception as e:
        print(f"Error fetching emails: {e}")
        return None


def search_emails(query: str, max_results: int = 10) -> list:
    """
    Search emails using Gmail query syntax.

    Args:
        query: Gmail search query (e.g., "from:john subject:meeting")
        max_results: Maximum number of results

    Returns:
        List of matching email summaries
    """
    service = get_gmail_service()
    if not service:
        return None

    try:
        results = service.users().messages().list(
            userId='me',
            maxResults=max_results,
            q=query
        ).execute()

        messages = results.get('messages', [])
        emails = []

        for msg in messages:
            msg_data = service.users().messages().get(
                userId='me',
                id=msg['id'],
                format='metadata',
                metadataHeaders=['From', 'Subject', 'Date']
            ).execute()

            headers = {h['name']: h['value'] for h in msg_data['payload']['headers']}
            emails.append({
                'id': msg['id'],
                'from': headers.get('From', 'Unknown'),
                'subject': headers.get('Subject', 'No subject'),
                'date': headers.get('Date', ''),
                'snippet': msg_data.get('snippet', '')
            })

        return emails
    except Exception as e:
        print(f"Error searching emails: {e}")
        return None


def get_email_content(message_id: str) -> dict:
    """
    Get full email content by message ID.

    Returns:
        dict with email details and body
    """
    service = get_gmail_service()
    if not service:
        return None

    try:
        msg = service.users().messages().get(
            userId='me',
            id=message_id,
            format='full'
        ).execute()

        headers = {h['name']: h['value'] for h in msg['payload']['headers']}

        # Extract body
        body = ""
        if 'parts' in msg['payload']:
            for part in msg['payload']['parts']:
                if part['mimeType'] == 'text/plain':
                    data = part['body'].get('data', '')
                    body = base64.urlsafe_b64decode(data).decode('utf-8')
                    break
        elif 'body' in msg['payload'] and 'data' in msg['payload']['body']:
            body = base64.urlsafe_b64decode(msg['payload']['body']['data']).decode('utf-8')

        return {
            'id': message_id,
            'from': headers.get('From', 'Unknown'),
            'to': headers.get('To', ''),
            'subject': headers.get('Subject', 'No subject'),
            'date': headers.get('Date', ''),
            'body': body
        }
    except Exception as e:
        print(f"Error getting email: {e}")
        return None


def get_user_email() -> str:
    """Get the authenticated user's email address."""
    service = get_gmail_service()
    if not service:
        return None

    try:
        profile = service.users().getProfile(userId='me').execute()
        return profile.get('emailAddress')
    except Exception:
        return None
