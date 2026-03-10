"""
Personal AI Agent Dashboard - FastAPI Backend
===============================================

Agent uses Claude to route queries between:
- Document search (ChromaDB RAG)
- Google Calendar
- General knowledge

Run: python app.py → http://localhost:8000
"""

import os
import json
import logging
import time
from datetime import datetime

from src.env_loader import load_env
load_env()

from fastapi import FastAPI, Request, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.concurrency import run_in_threadpool

from rag import get_engine
from load_documents import (
    load_txt, load_md, load_pdf, load_docx, load_image,
    chunk_text_smart, PDF_SUPPORT, DOCX_SUPPORT,
    load_all_documents,
)
import calendar_integration
import gmail_integration
import nest_integration
from src.agent import run_agent
from src.config import (
    PROJECT_DIR,
    get_docs_path_str,
    get_chunking,
    get_upload_max_bytes,
)
from src.telemetry import usage_report
from src.approvals import list_pending_actions, approve_action, reject_action, TOOL_PERMISSION_CLASSES
from src.security import safe_error_message, safe_log
from src.totp_auth import verify_totp_code, has_totp_secret, build_totp_uri
from src.money_agent.state import get_pipeline, update_pipeline_status

app = FastAPI(title="Personal AI Agent", docs_url="/docs", redoc_url="/redoc")


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Return JSON with error details instead of generic 500."""
    logger.exception("Unhandled exception")
    return JSONResponse(
        {"error": safe_error_message(exc), "detail": str(exc)},
        status_code=500
    )

DOCS_PATH = get_docs_path_str()
APPROVAL_API_KEY = os.getenv("APPROVAL_API_KEY", "")
APPROVAL_AUTH_MODE = os.getenv("APPROVAL_AUTH_MODE", "key_or_totp").strip().lower()
SECURITY_HARDENING = os.getenv("SECURITY_HARDENING", "false").strip().lower() in {"1", "true", "yes", "on"}

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", level=logging.INFO)
logger = logging.getLogger("personal_agent.app")

# Mount static files
app.mount("/static", StaticFiles(directory=str(PROJECT_DIR / "static")), name="static")


def _check_approval_auth(request: Request) -> None:
    """
    Approval endpoint auth.
    Modes:
      key          -> x-approval-key
      totp         -> x-approval-totp
      key_or_totp  -> either key or totp
      both         -> both key and totp
    """
    if not SECURITY_HARDENING:
        return

    key = request.headers.get("x-approval-key", "").strip()
    totp = request.headers.get("x-approval-totp", "").strip()

    key_ok = bool(APPROVAL_API_KEY) and key == APPROVAL_API_KEY
    totp_ok = verify_totp_code(totp) if has_totp_secret() else False

    mode = APPROVAL_AUTH_MODE or "key_or_totp"
    if mode == "key":
        if not APPROVAL_API_KEY:
            raise HTTPException(status_code=500, detail="APPROVAL_API_KEY is not configured.")
        if not key_ok:
            raise HTTPException(status_code=401, detail="Invalid approval key.")
        return
    if mode == "totp":
        if not has_totp_secret():
            raise HTTPException(status_code=500, detail="APPROVAL_TOTP_SECRET is not configured.")
        if not totp_ok:
            raise HTTPException(status_code=401, detail="Invalid approval TOTP code.")
        return
    if mode == "both":
        if not APPROVAL_API_KEY:
            raise HTTPException(status_code=500, detail="APPROVAL_API_KEY is not configured.")
        if not has_totp_secret():
            raise HTTPException(status_code=500, detail="APPROVAL_TOTP_SECRET is not configured.")
        if not (key_ok and totp_ok):
            raise HTTPException(status_code=401, detail="Approval auth failed (need key and TOTP).")
        return

    # Default: key_or_totp
    if not (key_ok or totp_ok):
        if not APPROVAL_API_KEY and not has_totp_secret():
            raise HTTPException(status_code=500, detail="No approval auth configured (key or TOTP).")
        raise HTTPException(status_code=401, detail="Approval auth failed (need valid key or TOTP).")


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """Minimal request logging with no body/header secret leakage."""
    t0 = time.time()
    try:
        response = await call_next(request)
        duration_ms = int((time.time() - t0) * 1000)
        safe_log(
            logging.INFO,
            "http_request",
            {
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": duration_ms,
                "client": request.client.host if request.client else None,
            },
        )
        return response
    except Exception as e:
        duration_ms = int((time.time() - t0) * 1000)
        safe_log(
            logging.ERROR,
            "http_request_error",
            {
                "method": request.method,
                "path": request.url.path,
                "duration_ms": duration_ms,
                "error": safe_error_message(e),
            },
        )
        raise


# =============================================================================
# API Endpoints
# =============================================================================

@app.post("/api/chat")
async def chat(request: Request):
    """Main agent endpoint: run Claude tool_use agent loop."""
    body = await request.json()
    query = body.get("query", "").strip()
    session_id = body.get("session_id", None)

    if not query:
        return JSONResponse({"error": "Empty query"}, status_code=400)

    try:
        result = await run_in_threadpool(run_agent, query, session_id)
        return JSONResponse(result)
    except Exception as e:
        logger.exception("Chat error")
        return JSONResponse(
            {"error": safe_error_message(e), "answer": None},
            status_code=500
        )


@app.post("/api/shortcut")
async def shortcut(request: Request):
    """Shortcut-friendly endpoint: returns plain text for macOS Shortcuts."""
    body = await request.json()
    query = body.get("query", "").strip()

    if not query:
        return PlainTextResponse("Error: empty query", status_code=400)

    result = await run_in_threadpool(run_agent, query, None)
    return PlainTextResponse(result["answer"])


@app.get("/api/status")
async def status():
    """Return which integrations are connected."""
    # Check if notes are indexed
    notes_connected = False
    if os.path.exists(DOCS_PATH):
        with open(DOCS_PATH, 'r') as f:
            docs = json.load(f)
        notes_connected = any(d.get('metadata', {}).get('type') == 'apple_note' for d in docs)

    return JSONResponse({
        "calendar":  calendar_integration.is_authenticated(),
        "gmail":     gmail_integration.is_authenticated(),
        "nest":      nest_integration.is_authenticated(),
        "documents": True,
        "notes":     notes_connected
    })


@app.get("/api/auth-debug")
async def auth_debug():
    """Debug auth status — token paths, existence. For troubleshooting Gmail/Calendar."""
    token_path = gmail_integration.TOKEN_PATH
    gmail_ok = gmail_integration.is_authenticated()
    fetch_error = None
    if gmail_ok:
        try:
            from googleapiclient.discovery import build
            creds = gmail_integration.get_credentials()
            service = build("gmail", "v1", credentials=creds)
            results = service.users().messages().list(userId="me", maxResults=2, labelIds=["INBOX"]).execute()
            fetch_error = None if results.get("messages") is not None else "API returned no messages"
        except Exception as e:
            fetch_error = f"{type(e).__name__}: {e}"
    return JSONResponse({
        "token_path": token_path,
        "token_exists": os.path.exists(token_path),
        "gmail_authenticated": gmail_ok,
        "calendar_authenticated": calendar_integration.is_authenticated(),
        "gmail_fetch_error": fetch_error,
    })


@app.get("/api/usage")
async def api_usage(start: str | None = None, end: str | None = None):
    """
    Usage telemetry report (OpenClaw-like).
    Query params:
      start=YYYY-MM-DD (UTC, inclusive)
      end=YYYY-MM-DD (UTC, inclusive)
    """
    return JSONResponse(usage_report(start_date=start, end_date=end))


@app.get("/api/tool-policies")
async def tool_policies():
    """Return tool permission classes."""
    return JSONResponse({"tool_permission_classes": {k: sorted(v) for k, v in TOOL_PERMISSION_CLASSES.items()}})


@app.get("/api/pipeline")
async def pipeline_list(status: str | None = None, limit: int = 50):
    """List jobs in the recruiter pipeline."""
    items = get_pipeline(status=status, limit=limit)
    return JSONResponse({"pipeline": items})


@app.post("/api/pipeline/{item_id}/status")
async def pipeline_update_status(item_id: int, request: Request):
    """Update pipeline item status (e.g. applied, rejected)."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    status = body.get("status", "applied")
    update_pipeline_status(item_id, status)
    return JSONResponse({"id": item_id, "status": status})


@app.post("/api/recruiter")
async def recruiter_run(request: Request):
    """Run the recruiter agent to find jobs."""
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    query = body.get("query", "").strip()
    from src.recruiter_agent import run_recruiter
    result = await run_in_threadpool(run_recruiter, query or None)
    return JSONResponse(result)


@app.get("/api/approvals")
async def approvals_list(request: Request, limit: int = 100):
    """List pending approval actions."""
    _check_approval_auth(request)
    return JSONResponse({"pending": list_pending_actions(limit=limit)})


@app.post("/api/approvals/{approval_id}/approve")
async def approvals_approve(approval_id: int, request: Request):
    """Approve and execute a pending action."""
    _check_approval_auth(request)
    result = approve_action(approval_id)
    status = 200 if "error" not in result else 400
    return JSONResponse(result, status_code=status)


@app.post("/api/approvals/{approval_id}/reject")
async def approvals_reject(approval_id: int, request: Request):
    """Reject a pending action."""
    _check_approval_auth(request)
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    reason = body.get("reason", "")
    result = reject_action(approval_id, reason=reason)
    status = 200 if "error" not in result else 400
    return JSONResponse(result, status_code=status)


@app.get("/api/approvals/totp-setup")
async def approvals_totp_setup(request: Request):
    """
    Return TOTP setup URI for authenticator apps.
    Protected by current approval auth.
    """
    _check_approval_auth(request)
    uri = build_totp_uri(account_name=os.getenv("USER_DISPLAY_NAME", "personal-agent"), issuer_name="Personal AI Agent")
    if not uri:
        return JSONResponse({"error": "APPROVAL_TOTP_SECRET is not configured."}, status_code=400)
    return JSONResponse({"otpauth_uri": uri})


@app.get("/api/calendar/today")
async def calendar_today():
    """Get today's events for the sidebar widget."""
    if not calendar_integration.is_authenticated():
        return JSONResponse({"authenticated": False, "events": []})

    events = calendar_integration.get_todays_events()
    if events is None:
        return JSONResponse({"authenticated": True, "events": [], "error": "Failed to fetch"})

    return JSONResponse({"authenticated": True, "events": events})


@app.get("/api/nest/status")
async def nest_status():
    """Return Nest device statuses for the sidebar widget."""
    if not nest_integration.is_authenticated():
        return JSONResponse({"authenticated": False})
    try:
        devices   = nest_integration.list_devices()
        thermostats = [d for d in devices if d["type"] == "THERMOSTAT"]
        cameras     = [d for d in devices if d["type"] in ("CAMERA", "DOORBELL", "DISPLAY")]
        thermo_data = [nest_integration.get_thermostat_status(d["id"]) for d in thermostats]
        camera_data = [{"name": d["display_name"], "type": d["type"]} for d in cameras]
        return JSONResponse({"authenticated": True, "thermostats": thermo_data, "cameras": camera_data})
    except Exception as e:
        return JSONResponse({"authenticated": True, "error": safe_error_message(e)})


@app.get("/api/documents")
async def documents_list():
    """List indexed documents."""
    engine = get_engine()
    sources = engine.list_documents()
    return JSONResponse({"documents": sources, "count": len(sources)})


@app.post("/api/reindex")
async def reindex():
    """Re-run document indexing from my_data/ and refresh the knowledge base."""
    try:
        documents = load_all_documents()
        out_path = get_docs_path_str()
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(documents, f, indent=2, ensure_ascii=False)
        import rag
        if rag._engine is not None:
            rag._engine._initialized = False
        return JSONResponse({
            "success": True,
            "chunks": len(documents),
            "message": f"Re-indexed {len(documents)} document chunks.",
        })
    except Exception as e:
        return JSONResponse({"error": safe_error_message(e)}, status_code=500)


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    """Upload a file and add it to the knowledge base. Max size from config (default 20 MB)."""
    # Supported extensions
    ext = os.path.splitext(file.filename)[1].lower()
    supported = {'.txt', '.md', '.pdf', '.docx', '.jpg', '.jpeg', '.png'}

    if ext not in supported:
        return JSONResponse(
            {"error": f"Unsupported file type: {ext}. Supported: {', '.join(supported)}"},
            status_code=400
        )

    # Enforce upload size limit
    max_bytes = get_upload_max_bytes()
    content = await file.read()
    if len(content) > max_bytes:
        return JSONResponse(
            {"error": f"File too large (max {max_bytes // (1024*1024)} MB)."},
            status_code=400
        )

    if ext == '.pdf' and not PDF_SUPPORT:
        return JSONResponse({"error": "PDF support not installed (pip install pypdf)"}, status_code=400)
    if ext == '.docx' and not DOCX_SUPPORT:
        return JSONResponse({"error": "DOCX support not installed (pip install python-docx)"}, status_code=400)

    # Save file to uploads folder
    uploads_dir = str(PROJECT_DIR / "my_data" / "uploads")
    os.makedirs(uploads_dir, exist_ok=True)

    filepath = os.path.join(uploads_dir, file.filename)

    # Handle duplicate filenames
    base, extension = os.path.splitext(file.filename)
    counter = 1
    while os.path.exists(filepath):
        filepath = os.path.join(uploads_dir, f"{base}_{counter}{extension}")
        counter += 1

    # Save the file (content already read for size check)
    with open(filepath, 'wb') as f:
        f.write(content)

    # Process the file based on type
    try:
        loaders = {
            '.txt': load_txt,
            '.md': load_md,
            '.pdf': load_pdf,
            '.docx': load_docx,
            '.jpg': load_image,
            '.jpeg': load_image,
            '.png': load_image,
        }

        doc_data = loaders[ext](filepath)
        rel_path = os.path.relpath(filepath, str(PROJECT_DIR / "my_data"))

        # Load existing documents
        if os.path.exists(DOCS_PATH):
            with open(DOCS_PATH, 'r') as f:
                documents = json.load(f)
        else:
            documents = []

        # Get next ID
        existing_ids = [int(d['id'].split('_')[0]) for d in documents if d['id'].split('_')[0].isdigit()]
        next_id = max(existing_ids, default=0) + 1

        # Chunk from config; section-aware for Markdown
        chunk_cfg = get_chunking()
        chunks = chunk_text_smart(
            doc_data['content'],
            chunk_size=chunk_cfg.get('chunk_size', 500),
            overlap=chunk_cfg.get('overlap', 50),
            is_markdown=(ext == '.md'),
        )
        added_count = 0

        for i, chunk in enumerate(chunks):
            doc_id = f"{next_id}_{i+1}" if len(chunks) > 1 else str(next_id)
            title = f"{doc_data['title']} (Part {i+1}/{len(chunks)})" if len(chunks) > 1 else doc_data['title']

            document = {
                'id': doc_id,
                'title': title,
                'content': chunk,
                'metadata': {
                    'source': rel_path,
                    'type': ext[1:],
                    'loaded': datetime.now().isoformat()
                }
            }
            documents.append(document)
            added_count += 1

        # Save updated documents
        with open(DOCS_PATH, 'w', encoding='utf-8') as f:
            json.dump(documents, f, indent=2, ensure_ascii=False)

        # Force RAG engine to re-sync on next query
        import rag
        if rag._engine is not None:
            rag._engine._initialized = False

        return JSONResponse({
            "success": True,
            "filename": os.path.basename(filepath),
            "title": doc_data['title'],
            "chunks": added_count,
            "message": f"Added '{doc_data['title']}' ({added_count} chunk{'s' if added_count > 1 else ''})"
        })

    except Exception as e:
        # Clean up file on error
        if os.path.exists(filepath):
            os.remove(filepath)
        return JSONResponse({"error": f"Failed to process file: {safe_error_message(e)}"}, status_code=500)


# =============================================================================
# AgentGate — credential broker for AI agent tool calls
# The agent only holds AGENT_GATE_KEY; OAuth tokens never leave this server.
# Routes: POST /agent/tool/{provider}/{action}
# Auth:   x-agent-key header must match AGENT_GATE_KEY env var
# =============================================================================

_AGENT_GATE_KEY = os.getenv("AGENT_GATE_KEY", "").strip()


def _check_agent_key(request: Request) -> None:
    if not _AGENT_GATE_KEY:
        raise HTTPException(status_code=500, detail="AGENT_GATE_KEY is not configured.")
    key = request.headers.get("x-agent-key", "")
    if key != _AGENT_GATE_KEY:
        raise HTTPException(status_code=401, detail="Invalid agent key")


@app.post("/agent/tool/calendar/get_events")
async def gate_calendar_get_events(request: Request):
    _check_agent_key(request)
    body = await request.json()
    days = int(body.get("days", 7))
    if not calendar_integration.is_authenticated():
        return JSONResponse({"error": "Google Calendar is not connected."})
    try:
        events = calendar_integration.get_upcoming_events(days=days)
        if events is None:
            return JSONResponse({"error": "Failed to fetch calendar events."})
        return JSONResponse({"events": events, "days_ahead": days})
    except Exception as e:
        return JSONResponse({"error": f"Calendar fetch failed: {safe_error_message(e)}"})


@app.post("/agent/tool/gmail/get_recent_emails")
async def gate_gmail_get_recent(request: Request):
    _check_agent_key(request)
    body = await request.json()
    max_results = int(body.get("max_results", 5))
    if not gmail_integration.is_authenticated():
        return JSONResponse({"error": "Gmail is not connected."})
    try:
        emails = gmail_integration.get_recent_emails(max_results=max_results)
        if emails is None:
            return JSONResponse({"error": "Failed to fetch emails."})
        return JSONResponse({"emails": emails})
    except Exception as e:
        return JSONResponse({"error": f"Email fetch failed: {safe_error_message(e)}"})


@app.post("/agent/tool/gmail/search_emails")
async def gate_gmail_search(request: Request):
    _check_agent_key(request)
    body = await request.json()
    query = body.get("query", "")
    max_results = int(body.get("max_results", 5))
    if not gmail_integration.is_authenticated():
        return JSONResponse({"error": "Gmail is not connected."})
    try:
        emails = gmail_integration.search_emails(query, max_results=max_results)
        if emails is None:
            return JSONResponse({"error": "Failed to search emails."})
        return JSONResponse({"emails": emails, "query": query})
    except Exception as e:
        return JSONResponse({"error": f"Email search failed: {safe_error_message(e)}"})


@app.post("/agent/tool/gmail/send_email")
async def gate_gmail_send(request: Request):
    _check_agent_key(request)
    body = await request.json()
    if not gmail_integration.is_authenticated():
        return JSONResponse({"error": "Gmail is not connected."})
    try:
        result = gmail_integration.send_email(body["to"], body["subject"], body["body"])
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": f"Send email failed: {safe_error_message(e)}"})


@app.post("/agent/tool/gmail/create_draft")
async def gate_gmail_draft(request: Request):
    _check_agent_key(request)
    body = await request.json()
    if not gmail_integration.is_authenticated():
        return JSONResponse({"error": "Gmail is not connected."})
    try:
        result = gmail_integration.create_draft(body["to"], body["subject"], body["body"])
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": f"Create draft failed: {safe_error_message(e)}"})


# =============================================================================
# OAuth Endpoints
# =============================================================================

@app.get("/auth/google")
async def auth_google(request: Request):
    """Start Google OAuth flow (includes Calendar + Gmail scopes)."""
    redirect_uri = "http://localhost:8000/auth/google/callback"
    try:
        # Use gmail_integration which has combined scopes
        flow = gmail_integration.get_oauth_flow(redirect_uri)
        auth_url, _ = flow.authorization_url(
            access_type='offline',
            prompt='consent'
        )
        return RedirectResponse(auth_url)
    except ValueError as e:
        return JSONResponse({"error": safe_error_message(e)}, status_code=500)


@app.get("/auth/google/callback")
async def auth_google_callback(request: Request):
    """Handle OAuth callback."""
    redirect_uri = "http://localhost:8000/auth/google/callback"
    code = request.query_params.get("code")

    if not code:
        return JSONResponse({"error": "No authorization code received"}, status_code=400)

    try:
        flow = gmail_integration.get_oauth_flow(redirect_uri)
        flow.fetch_token(code=code)
        creds = flow.credentials
        gmail_integration.save_credentials(creds)
        return RedirectResponse("/")
    except Exception as e:
        return JSONResponse({"error": f"OAuth error: {safe_error_message(e)}"}, status_code=500)


@app.get("/auth/nest")
async def auth_nest():
    """Start Nest SDM OAuth flow."""
    if not nest_integration.CLIENT_ID:
        return JSONResponse({"error": "GOOGLE_CLIENT_ID not set in .env"}, status_code=500)
    if not nest_integration.NEST_PROJECT_ID:
        return JSONResponse({"error": "NEST_PROJECT_ID not set in .env — add it first."}, status_code=500)
    return RedirectResponse(nest_integration.get_auth_url())


@app.get("/auth/nest/callback")
async def auth_nest_callback(request: Request):
    """Handle Nest SDM OAuth callback."""
    code = request.query_params.get("code")
    if not code:
        return JSONResponse({"error": "No authorization code received"}, status_code=400)
    success = nest_integration.handle_oauth_callback(code)
    if success:
        return RedirectResponse("/")
    return JSONResponse({"error": "Nest OAuth failed"}, status_code=500)


# =============================================================================
# Dashboard
# =============================================================================

@app.get("/")
async def dashboard():
    """Serve the dashboard HTML."""
    html_path = str(PROJECT_DIR / "static" / "index.html")
    with open(html_path, 'r') as f:
        content = f.read()
    return HTMLResponse(content)


# =============================================================================
# Run
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    print("Starting Personal AI Agent Dashboard...")
    print("Open http://localhost:8000 in your browser")
    uvicorn.run(app, host="0.0.0.0", port=8000)
