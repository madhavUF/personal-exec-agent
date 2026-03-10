# Personal AI Assistant - Project Plan

## Vision
A personal AI that knows everything about you. Ask questions in natural language, get answers from your own data.

**Long-term goal:** Productize this for others to use - a simple, private, local-first personal AI anyone can set up.

## Why This Matters
- Big tech has your data, but YOU can't easily search it
- LLMs are powerful but don't know YOUR information
- Privacy-first: your data stays on your machine
- Open source alternative to commercial "second brain" apps

```
You: "What's my driver's license number?"
AI: "Your DL number is X12345678, expires March 2027."

You: "Show me photos from my trip to Japan"
AI: [Shows relevant photos]

You: "What did I decide in last week's meeting?"
AI: "You decided to launch MVP in Q2, with John on frontend..."
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     YOUR MAC (Local)                        │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                    my_data/                          │   │
│  │  documents/    images/    audio/    exports/         │   │
│  │  ├── work/     ├── photos/         ├── emails/       │   │
│  │  ├── personal/ ├── screenshots/    ├── messages/     │   │
│  │  └── notes/    └── scans/          └── calendar/     │   │
│  └──────────────────────────────────────────────────────┘   │
│                           │                                 │
│                      [INDEXER]                              │
│                           │                                 │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              LOCAL VECTOR DATABASE                   │   │
│  │  • Text embeddings (sentence-transformers)           │   │
│  │  • Image embeddings (CLIP)                           │   │
│  │  • Metadata (dates, types, sources)                  │   │
│  └──────────────────────────────────────────────────────┘   │
│                           │                                 │
│                    [RETRIEVAL]                              │
│                           │                                 │
└───────────────────────────┼─────────────────────────────────┘
                            │ Only relevant chunks
                            ▼
                  ┌───────────────────┐
                  │   Claude API      │
                  │   (Generation)    │
                  └───────────────────┘
                            │
                            ▼
                       YOUR ANSWER
```

## Project Phases

### Phase 1: Foundation
**Status: ✅ Complete**

- [x] Basic document loading (txt, md, pdf, docx, images with OCR)
- [x] Text embeddings (sentence-transformers)
- [x] ChromaDB vector store + hybrid search
- [x] Chunking for large documents (config-driven)
- [x] Configuration file (config.yaml) used by RAG, loader, app
- [x] Simple CLI (rag.py) and project structure

### Phase 2: Enhanced Processing
**Status: 🔶 In Progress**

- [x] OCR for images (docTR)
- [x] Smarter chunking (section-aware for Markdown)
- [x] Privacy: exclude folders/patterns from config when indexing
- [ ] Better metadata extraction (dates, authors)
- [ ] File watching (auto-index new files) or Re-index API (done: POST /api/reindex)

### Phase 3: Image Support
**Status: 🔲 Not Started**

Goals:
- [ ] CLIP embeddings for images
- [ ] Visual similarity search
- [ ] Image descriptions (BLIP or Claude Vision)
- [ ] Photo organization by content

### Phase 4: Claude Integration
**Status: ✅ Complete**

- [x] Claude API (and Groq/Ollama/OpenAI via MODEL_PROVIDER)
- [x] Conversational interface (web + Telegram)
- [x] Multi-turn memory (SQLite sessions, 30-day TTL)
- [x] Send images to Claude for analysis (vision)

### Phase 5: Always-On Assistant
**Status: ✅ Complete**

- [x] Background service (install_daemon.sh, launchd)
- [x] FastAPI server + /docs, /redoc
- [x] Menu bar app (macOS)
- [x] Mobile access (Telegram bot)
- [ ] Voice input (Whisper) — optional

### Phase 6: Polish & Deploy
**Status: 🔶 In Progress**

- [x] README and clean repo
- [x] Privacy controls (exclude in config.yaml)
- [x] Upload size limit (config: api.upload_max_mb)
- [ ] Docker container option
- [ ] Backup/restore functionality
- [ ] Usage dashboard

### Phase 7: Productize for Others
**Status: 🔶 In Progress**

- [x] Install script (scripts/install.sh)
- [ ] Configuration wizard (guided setup)
- [ ] Multiple platform support (Windows, Linux)
- [ ] Documentation and tutorials
- [ ] Example use cases and templates
- [ ] Optional cloud sync (encrypted)
- [ ] Pricing model exploration (open core?)

## File Structure (Target)

```
ml-from-scratch/
├── README.md                 # Project documentation
├── PROJECT_PLAN.md           # This file
├── requirements.txt          # Dependencies
├── config.yaml               # Configuration
│
├── my_data/                  # YOUR PERSONAL DATA
│   ├── documents/            # PDFs, Word, text
│   ├── images/               # Photos, screenshots
│   ├── audio/                # Voice memos (future)
│   └── exports/              # Email, calendar exports
│
├── src/                      # Source code
│   ├── __init__.py
│   ├── indexer.py            # Index files → embeddings
│   ├── retriever.py          # Search embeddings
│   ├── generator.py          # Claude API integration
│   ├── ocr.py                # Image text extraction
│   ├── embeddings.py         # Embedding models
│   └── utils.py              # Helpers
│
├── data/                     # Generated data (git-ignored)
│   ├── index.db              # SQLite database
│   ├── embeddings/           # Cached embeddings
│   └── cache/                # Temporary files
│
├── lessons/                  # Your learning files (keep!)
│   ├── lesson_1_*.py
│   ├── lesson_2_*.py
│   └── ...
│
└── scripts/
    ├── index.py              # Run indexer
    ├── search.py             # Search CLI
    ├── chat.py               # Chat with Claude
    └── serve.py              # API server
```

## Getting Started

### Current (Phase 1):
```bash
# Add files to my_data/
cp ~/Documents/*.pdf my_data/

# Index them
python load_documents.py

# Search
python rag.py
```

### Future (Phase 5+):
```bash
# Start the assistant (runs in background)
python -m personal_ai start

# Query from anywhere
personal-ai "What's my DL number?"

# Or via API
curl http://localhost:8000/ask?q="What's my DL number?"
```

## Tech Stack

| Component | Current | Future Option |
|-----------|---------|---------------|
| Embeddings | sentence-transformers (config) | Same |
| Image embeddings | - | CLIP |
| OCR | docTR | Same |
| Vector DB | ChromaDB (config) | Same |
| LLM | Claude / Groq / Ollama / OpenAI | Same |
| API | FastAPI + /docs, /redoc | Same |
| Voice | - | Whisper |

## Privacy Considerations

- All indexing happens locally
- Only relevant chunks sent to Claude (not entire files)
- Exclude sensitive folders/patterns in config.yaml (used by load_documents)
- API key stored securely (environment variable)
- Optional AgentGate: OAuth tokens never in agent process

## Next Steps

1. File watcher or periodic re-index
2. CLIP / image search (Phase 3)
3. Docker and backup/restore
4. Configuration wizard for new users
