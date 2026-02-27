"""
Apple Notes Loader
===================

Extracts notes from Apple Notes via AppleScript and indexes them
into documents.json for RAG search.

Usage:
    python load_notes.py

Notes are chunked if longer than 500 characters.
Existing notes in documents.json are replaced on re-run.
"""

import json
import os
import subprocess
from datetime import datetime

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DOCS_PATH = os.path.join(PROJECT_DIR, 'data/documents.json')
CHUNK_SIZE = 500  # characters per chunk
BATCH_SIZE = 50   # notes per AppleScript call


def get_note_count():
    """Get total number of notes."""
    result = subprocess.run(
        ['osascript', '-e', 'tell application "Notes" to get count of every note'],
        capture_output=True, text=True
    )
    return int(result.stdout.strip())


def get_notes_batch(start, count):
    """Fetch a batch of notes (1-indexed) via AppleScript."""
    # AppleScript to get notes in range, separated by a delimiter
    script = f'''
    set output to ""
    set delim to "<<<NOTE_DELIM>>>"
    set fieldDelim to "<<<FIELD_DELIM>>>"
    tell application "Notes"
        set noteList to every note
        set batchEnd to {start + count - 1}
        if batchEnd > (count of noteList) then
            set batchEnd to (count of noteList)
        end if
        repeat with i from {start} to batchEnd
            set n to item i of noteList
            set noteName to name of n
            set noteBody to plaintext of n
            set output to output & noteName & fieldDelim & noteBody & delim
        end repeat
    end tell
    return output
    '''
    result = subprocess.run(
        ['osascript', '-e', script],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        print(f"  Warning: batch starting at {start} had errors: {result.stderr[:100]}")
        return []

    raw = result.stdout
    notes = []
    for entry in raw.split('<<<NOTE_DELIM>>>'):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split('<<<FIELD_DELIM>>>', 1)
        if len(parts) == 2:
            title = parts[0].strip()
            body = parts[1].strip()
            if body:  # Skip empty notes
                notes.append({'title': title, 'body': body})
    return notes


def chunk_text(text, chunk_size=CHUNK_SIZE):
    """Split text into chunks at sentence boundaries."""
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    current = ""
    sentences = text.replace('\n', '\n ').split('. ')

    for sentence in sentences:
        if len(current) + len(sentence) + 2 > chunk_size and current:
            chunks.append(current.strip())
            current = sentence
        else:
            current = current + ". " + sentence if current else sentence

    if current.strip():
        chunks.append(current.strip())

    return chunks if chunks else [text]


def load_notes():
    """Main: extract Apple Notes and add to documents.json."""
    print("Apple Notes Loader")
    print("=" * 40)

    # Get note count
    total = get_note_count()
    print(f"Found {total} notes in Apple Notes")

    # Load existing documents
    if os.path.exists(DOCS_PATH):
        with open(DOCS_PATH, 'r') as f:
            documents = json.load(f)
    else:
        documents = []

    # Remove previously loaded notes (to allow re-runs)
    documents = [d for d in documents if d.get('metadata', {}).get('type') != 'apple_note']
    existing_count = len(documents)
    print(f"Existing documents (non-notes): {existing_count}")

    # Determine next ID
    max_id = max((int(d['id']) for d in documents if d['id'].isdigit()), default=0)
    next_id = max_id + 1

    # Fetch notes in batches
    all_notes = []
    for start in range(1, total + 1, BATCH_SIZE):
        batch_end = min(start + BATCH_SIZE - 1, total)
        print(f"  Fetching notes {start}-{batch_end}...")
        batch = get_notes_batch(start, BATCH_SIZE)
        all_notes.extend(batch)

    print(f"Extracted {len(all_notes)} notes with content")

    # Chunk and create document entries
    notes_added = 0
    for note in all_notes:
        title = note['title']
        body = note['body']

        # Skip very short notes (< 20 chars)
        if len(body) < 20:
            continue

        chunks = chunk_text(body)
        for i, chunk in enumerate(chunks):
            chunk_title = title if len(chunks) == 1 else f"{title} (part {i+1})"
            documents.append({
                'id': str(next_id),
                'title': chunk_title,
                'content': chunk,
                'metadata': {
                    'source': f"apple_notes/{title}",
                    'type': 'apple_note',
                    'loaded': datetime.now().isoformat()
                }
            })
            next_id += 1
            notes_added += 1

    # Save
    os.makedirs(os.path.dirname(DOCS_PATH), exist_ok=True)
    with open(DOCS_PATH, 'w') as f:
        json.dump(documents, f, indent=2)

    print(f"\nDone! Added {notes_added} chunks from Apple Notes")
    print(f"Total documents in index: {len(documents)}")
    print(f"\nNext: restart the dashboard (python app.py) to search your notes")


if __name__ == "__main__":
    load_notes()
