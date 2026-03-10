"""
Personal RAG System
====================

This is your actual RAG system that searches YOUR documents
and answers questions using Claude API.

All data stays local. Only top-K retrieved chunks (~2500 chars)
are sent to Claude per query.

Usage:
1. Add files to my_data/ folder
2. Run: python load_documents.py
3. Run: python rag.py
4. Ask questions about your documents!

Commands:
  Type a question to search and get AI answer
  'list'   - show all documents
  'debug'  - toggle showing raw chunks
  'quit'   - exit
"""

import json
import os
import re

from src.env_loader import load_env
load_env()

from src.config import (
    get_docs_path_str,
    get_chroma_path,
    get_search_settings,
    get_embeddings_model,
    get_vector_db_collection,
    get_llm_settings,
    PROJECT_DIR,
)


# =============================================================================
# RAGEngine class with lazy initialization
# =============================================================================

class RAGEngine:
    def __init__(self):
        self._initialized = False
        self._model = None
        self._chroma_client = None
        self._collection = None
        self._claude_client = None
        self._documents = None

    def _initialize(self):
        """Load models and data on first use."""
        if self._initialized:
            return

        import chromadb
        from sentence_transformers import SentenceTransformer
        import anthropic

        print("Loading RAG system...")

        docs_path = get_docs_path_str()
        chroma_path = str(get_chroma_path())
        search_cfg = get_search_settings()
        llm_cfg = get_llm_settings()

        if not os.path.exists(docs_path):
            raise FileNotFoundError(
                f"{docs_path} not found. Run 'python load_documents.py' first."
            )

        with open(docs_path, 'r') as f:
            self._documents = json.load(f)

        print(f"  Loaded {len(self._documents)} document chunks")

        # Load embedding model from config
        self._model = SentenceTransformer(get_embeddings_model())

        # Initialize ChromaDB
        os.makedirs(chroma_path, exist_ok=True)
        self._chroma_client = chromadb.PersistentClient(path=chroma_path)
        self._collection = self._chroma_client.get_or_create_collection(
            name=get_vector_db_collection(),
            metadata={"hnsw:space": "cosine"}
        )

        # Initialize Claude API client
        self._claude_client = anthropic.Anthropic()

        # Sync ChromaDB
        self._sync_collection()

        # Remove old embeddings.npy if it exists
        old_embeddings = str(PROJECT_DIR / "data" / "embeddings.npy")
        if os.path.exists(old_embeddings):
            os.remove(old_embeddings)
            print("  Removed old embeddings.npy (now using ChromaDB)")

        self._initialized = True
        print(f"  Ready!")
        print()

    def _sync_collection(self):
        """Keep ChromaDB in sync with documents.json."""
        existing_ids = set()
        if self._collection.count() > 0:
            existing_ids = set(self._collection.get()['ids'])

        doc_ids = [doc['id'] for doc in self._documents]

        # Find new documents to add
        new_docs = [doc for doc in self._documents if doc['id'] not in existing_ids]

        # Find stale IDs to remove
        stale_ids = [id for id in existing_ids if id not in doc_ids]

        if stale_ids:
            self._collection.delete(ids=stale_ids)
            print(f"  Removed {len(stale_ids)} stale entries from ChromaDB")

        if new_docs:
            batch_size = 100
            for i in range(0, len(new_docs), batch_size):
                batch = new_docs[i:i + batch_size]
                ids = [doc['id'] for doc in batch]
                contents = [doc['content'] for doc in batch]
                embeddings = self._model.encode(contents).tolist()
                metadatas = [
                    {
                        'title': doc['title'],
                        'source': doc.get('metadata', {}).get('source', 'unknown'),
                        'type': doc.get('metadata', {}).get('type', 'unknown')
                    }
                    for doc in batch
                ]

                self._collection.add(
                    ids=ids,
                    embeddings=embeddings,
                    documents=contents,
                    metadatas=metadatas
                )

            print(f"  Added {len(new_docs)} new documents to ChromaDB")
        else:
            print(f"  ChromaDB in sync ({self._collection.count()} documents)")

    def _keyword_score(self, query, content):
        """Improved keyword matching score."""
        stop_words = {'what', 'whats', 'is', 'my', 'the', 'a', 'an', 'to', 'for', 'of', 'in', 'on', 'me', 'i'}

        query_clean = re.sub(r"[^\w\s]", "", query.lower())
        query_words = [w for w in query_clean.split() if w and w not in stop_words]

        if not query_words:
            return 0

        content_clean = re.sub(r"[^\w\s]", "", content.lower())

        def word_matches(word, text):
            if word in text:
                return True
            if word.endswith('s') and word[:-1] in text:
                return True
            if word + 's' in text:
                return True
            return False

        matches = sum(1 for word in query_words if word_matches(word, content_clean))
        return matches / len(query_words)

    def search(self, query, top_k=None):
        """Hybrid search: ChromaDB semantic similarity + keyword re-ranking."""
        if top_k is None:
            top_k = get_search_settings().get("top_k", 5)
        self._initialize()

        query_embedding = self._model.encode(query).tolist()

        chroma_results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k * 2, self._collection.count()),
            include=['documents', 'metadatas', 'distances']
        )

        if not chroma_results['ids'][0]:
            return []

        search_cfg = get_search_settings()
        sem_w = search_cfg.get("semantic_weight", 0.7)
        kw_w = search_cfg.get("keyword_weight", 0.3)
        candidates = []
        for i, doc_id in enumerate(chroma_results['ids'][0]):
            semantic_sim = 1.0 - chroma_results['distances'][0][i]
            content = chroma_results['documents'][0][i]
            metadata = chroma_results['metadatas'][0][i]
            kw_score = self._keyword_score(query, metadata.get('title', '') + ' ' + content)
            combined = sem_w * semantic_sim + kw_w * kw_score

            candidates.append({
                'id': doc_id,
                'title': metadata.get('title', 'Unknown'),
                'content': content,
                'similarity': combined,
                'semantic': semantic_sim,
                'keyword': kw_score,
                'source': metadata.get('source', 'unknown')
            })

        candidates.sort(key=lambda x: x['similarity'], reverse=True)
        return candidates[:top_k]

    def _build_prompt(self, query, results):
        """Build RAG prompt with retrieved context."""
        context_parts = []
        for i, r in enumerate(results):
            context_parts.append(f"[{i+1}. {r['title']}]\n{r['content']}")

        context = "\n\n".join(context_parts)

        prompt = f"""Based on the following personal documents, answer the user's question accurately and concisely.
If the answer is directly stated in the documents, quote the relevant information.
If the documents don't contain enough information to answer, say so.

DOCUMENTS:
{context}

QUESTION: {query}"""
        return prompt

    def generate_answer(self, query, results=None):
        """Send top-K retrieved chunks to Claude and get an answer."""
        self._initialize()
        import anthropic

        if results is None:
            results = self.search(query, top_k=3)

        if not results:
            return "No relevant documents found for your query."

        prompt = self._build_prompt(query, results)

        llm_cfg = get_llm_settings()
        try:
            message = self._claude_client.messages.create(
                model=llm_cfg.get("model", "claude-sonnet-4-20250514"),
                max_tokens=llm_cfg.get("max_tokens", 1024),
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            return message.content[0].text
        except anthropic.AuthenticationError:
            return "[Error] ANTHROPIC_API_KEY not set or invalid. Set it with: export ANTHROPIC_API_KEY=your-key"
        except anthropic.APIError as e:
            return f"[API Error] {e}"

    def list_documents(self):
        """Return list of unique document sources."""
        self._initialize()
        seen_sources = set()
        sources = []
        for doc in self._documents:
            source = doc.get('metadata', {}).get('source', 'unknown')
            if source not in seen_sources:
                seen_sources.add(source)
                sources.append(source)
        return sources


# =============================================================================
# Singleton access
# =============================================================================

_engine = None

def get_engine():
    """Get the singleton RAGEngine instance (lazy - no model load on import)."""
    global _engine
    if _engine is None:
        _engine = RAGEngine()
    return _engine


# =============================================================================
# Interactive mode (CLI)
# =============================================================================

if __name__ == "__main__":
    engine = get_engine()
    engine._initialize()

    print("=" * 60)
    print("PERSONAL RAG SYSTEM (Claude-powered)")
    print("=" * 60)
    print(f"Documents: {len(engine._documents)} chunks in ChromaDB")
    print()
    print("Commands:")
    print("  Type a question to search and get AI answer")
    print("  'list'   - show all documents")
    print("  'debug'  - toggle showing raw chunks")
    print("  'quit'   - exit")
    print()

    debug_mode = False

    while True:
        try:
            query = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not query:
            continue

        if query.lower() in ['quit', 'exit', 'q']:
            print("Goodbye!")
            break

        if query.lower() == 'debug':
            debug_mode = not debug_mode
            print(f"Debug mode: {'ON' if debug_mode else 'OFF'}")
            print()
            continue

        if query.lower() == 'list':
            print("\nAll documents:")
            for source in engine.list_documents():
                print(f"  - {source}")
            print()
            continue

        # Search
        results = engine.search(query, top_k=3)

        if debug_mode:
            print()
            print("-" * 40)
            print("DEBUG: Retrieved chunks")
            print("-" * 40)
            for i, r in enumerate(results):
                print(f"  [{i+1}] {r['title']} (score: {r['similarity']:.3f}, sem: {r['semantic']:.3f}, kw: {r['keyword']:.3f})")
                print(f"      Source: {r['source']}")
                print(f"      {r['content'][:150]}...")
                print()
            print("-" * 40)

        # Generate AI answer
        print()
        answer = engine.generate_answer(query, results)
        print(f"AI: {answer}")
        print()

        # Show sources
        sources = set(r['source'] for r in results)
        print(f"  Sources: {', '.join(sources)}")
        print()
