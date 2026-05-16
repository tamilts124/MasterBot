import os
import re
import json
import time
import sqlite3
from pathlib import Path
from typing import Optional, List
from langchain_core.tools import tool
from .common import _truncate_output


# ---------------------------------------------------------------------------
# Vector store backend — ChromaDB preferred, SQLite FTS5 fallback
# ---------------------------------------------------------------------------

def _get_vector_dir() -> Path:
    work_dir = Path(os.environ.get("AGENT_WORKDIR", "."))
    d = work_dir / ".sas" / "vector_memory"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _chroma_available() -> bool:
    try:
        import chromadb  # noqa
        return True
    except ImportError:
        return False


def _sentence_transformer_available() -> bool:
    try:
        from sentence_transformers import SentenceTransformer  # noqa
        return True
    except ImportError:
        return False


def _sanitise_fts_query(query: str) -> str:
    """Strip FTS5-special characters (dots, hyphens, parens, etc.) to plain words.

    FTS5 treats punctuation as query operators.  A query like 'config.py' or
    'self-healing' raises 'fts5: syntax error' at runtime.  Reducing the query
    to plain whitespace-separated tokens is safe, still matches on meaningful
    words, and degrades gracefully for all inputs.
    """
    words = re.sub(r"[^\w\s]", " ", query).split()
    return " ".join(words)


# ---------------------------------------------------------------------------
# ChromaDB backend (best — persistent, semantic, no API needed)
# ---------------------------------------------------------------------------

class ChromaBackend:
    def __init__(self):
        import chromadb
        from chromadb.config import Settings
        self._client = chromadb.PersistentClient(
            path=str(_get_vector_dir()),
            settings=Settings(anonymized_telemetry=False)
        )
        self._col = self._client.get_or_create_collection(
            name="agent_memory",
            metadata={"hnsw:space": "cosine"}
        )

    def _embed(self, texts: List[str]) -> Optional[List[List[float]]]:
        """Return embeddings via sentence-transformers, or None to let ChromaDB embed."""
        if _sentence_transformer_available():
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer("all-MiniLM-L6-v2")
            return model.encode(texts, show_progress_bar=False).tolist()
        # None → ChromaDB uses its built-in onnx embedder
        return None

    def add(self, topic: str, content: str, metadata: dict) -> str:
        doc_id = f"mem_{abs(hash(topic)) % 10**12}"
        embeddings = self._embed([content])
        kwargs = dict(
            ids=[doc_id],
            documents=[content],
            metadatas=[{**metadata, "topic": topic, "updated_on": time.time()}],
        )
        if embeddings is not None:
            kwargs["embeddings"] = embeddings

        # Upsert: delete first so re-adding the same topic works cleanly
        try:
            self._col.delete(ids=[doc_id])
        except Exception:
            pass
        self._col.add(**kwargs)
        return doc_id

    def search(self, query: str, n_results: int = 5) -> List[dict]:
        count = self._col.count()
        if count == 0:
            return []
        safe_n = min(n_results, count)
        embeddings = self._embed([query])
        if embeddings is not None:
            kwargs = dict(query_embeddings=embeddings, n_results=safe_n)
        else:
            kwargs = dict(query_texts=[query], n_results=safe_n)

        results = self._col.query(**kwargs)
        out = []
        for i, doc in enumerate(results["documents"][0]):
            meta = results["metadatas"][0][i]
            dist = results["distances"][0][i]
            out.append({
                "topic": meta.get("topic", ""),
                "content": doc,
                "score": round(1 - dist, 4),
                "metadata": meta,
            })
        return out

    def list_topics(self) -> List[str]:
        items = self._col.get(include=["metadatas"])
        return [m.get("topic", "") for m in items["metadatas"]]

    def delete(self, topic: str) -> bool:
        doc_id = f"mem_{abs(hash(topic)) % 10**12}"
        try:
            self._col.delete(ids=[doc_id])
            return True
        except Exception:
            return False

    def count(self) -> int:
        return self._col.count()


# ---------------------------------------------------------------------------
# SQLite FTS5 fallback (keyword-based, no deps beyond stdlib)
# ---------------------------------------------------------------------------

class SQLiteFTSBackend:
    """Fallback when ChromaDB is not installed. Uses SQLite FTS5 for keyword search."""

    def __init__(self):
        self._db = _get_vector_dir() / "fts_memory.db"
        with self._conn() as c:
            c.executescript("""
                CREATE VIRTUAL TABLE IF NOT EXISTS memories USING fts5(
                    topic, content, metadata, updated_on UNINDEXED
                );
            """)

    def _conn(self):
        conn = sqlite3.connect(self._db, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def add(self, topic: str, content: str, metadata: dict) -> str:
        with self._conn() as c:
            c.execute("DELETE FROM memories WHERE topic = ?", (topic,))
            c.execute(
                "INSERT INTO memories (topic, content, metadata, updated_on) VALUES (?,?,?,?)",
                (topic, content, json.dumps(metadata), time.time()),
            )
        return topic

    def search(self, query: str, n_results: int = 5) -> List[dict]:
        # FIX: sanitise query so dots, hyphens, parens etc. don't crash FTS5
        safe_query = _sanitise_fts_query(query)

        with self._conn() as c:
            rows = []
            if safe_query:
                try:
                    rows = c.execute(
                        "SELECT topic, content, metadata, rank "
                        "FROM memories WHERE memories MATCH ? ORDER BY rank LIMIT ?",
                        (safe_query, n_results),
                    ).fetchall()
                except Exception:
                    pass  # fall through to LIKE below

            if not rows:
                # LIKE fallback: works for any input, no FTS5 syntax rules
                rows = c.execute(
                    "SELECT topic, content, metadata, 0 AS rank FROM memories "
                    "WHERE content LIKE ? OR topic LIKE ? LIMIT ?",
                    (f"%{query}%", f"%{query}%", n_results),
                ).fetchall()

        return [
            {
                "topic": row["topic"],
                "content": row["content"],
                "score": None,  # FTS5 rank is not a 0-1 probability; omit
                "metadata": json.loads(row["metadata"] or "{}"),
            }
            for row in rows
        ]

    def list_topics(self) -> List[str]:
        with self._conn() as c:
            return [r[0] for r in c.execute(
                "SELECT topic FROM memories ORDER BY updated_on DESC"
            )]

    def delete(self, topic: str) -> bool:
        with self._conn() as c:
            c.execute("DELETE FROM memories WHERE topic = ?", (topic,))
        return True

    def count(self) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM memories").fetchone()[0]


# ---------------------------------------------------------------------------
# Backend singleton — re-resolved when AGENT_WORKDIR changes
# ---------------------------------------------------------------------------

_BACKEND = None
_BACKEND_WORKDIR: Optional[str] = None


def _get_backend():
    """Return (and cache) the best available backend.

    The singleton is invalidated if AGENT_WORKDIR changes between calls so that
    agents running in different working directories always write to the correct
    storage location.
    """
    global _BACKEND, _BACKEND_WORKDIR
    current_workdir = os.environ.get("AGENT_WORKDIR", ".")
    if _BACKEND is None or current_workdir != _BACKEND_WORKDIR:
        _BACKEND = None  # reset so we rebuild below
        _BACKEND_WORKDIR = current_workdir
        if _chroma_available():
            try:
                _BACKEND = ChromaBackend()
                return _BACKEND
            except Exception:
                pass
        _BACKEND = SQLiteFTSBackend()
    return _BACKEND


# ---------------------------------------------------------------------------
# LangChain tools
# ---------------------------------------------------------------------------

@tool
def memory_save(topic: str, content: str, tags: str = "") -> str:
    """Save a piece of knowledge to your long-term vector memory.
    Unlike sas_add_knowledge (keyword lookup), this memory supports SEMANTIC search —
    you can retrieve it later by meaning, not just exact topic name.
    Use this for: code analysis findings, design decisions, bug root-causes, research summaries.
    Args:
        topic: Short title for this memory (used as the key for updates/deletion).
        content: The detailed knowledge to store (can be paragraphs of text).
        tags: Optional comma-separated labels for filtering (e.g. 'auth,bug,backend').
    """
    try:
        backend = _get_backend()
        meta = {"tags": tags, "source": "agent"}
        doc_id = backend.add(topic, content, meta)
        backend_name = "ChromaDB (semantic)" if isinstance(backend, ChromaBackend) else "SQLite FTS (keyword)"
        return f"[Success] Memory saved: '{topic}' ({backend_name}, id={doc_id})"
    except Exception as exc:
        return f"[Error] memory_save failed: {exc}"


@tool
def memory_search(query: str, n_results: int = 5) -> str:
    """Search your long-term vector memory by meaning/concept (semantic search).
    This is far more powerful than list — you can find relevant memories even if you
    don't remember the exact topic name. Ask in natural language.
    Args:
        query: A natural language description of what you're looking for.
               E.g. 'authentication flow', 'database schema for users', 'how we fixed the rate limit bug'.
        n_results: Number of top results to return (default 5).
    """
    try:
        backend = _get_backend()
        results = backend.search(query, n_results=n_results)
        if not results:
            return "[Info] No relevant memories found. Try a broader query or check memory_list."

        lines = [f"[Memory Search: '{query}' — {len(results)} results]\n"]
        for i, r in enumerate(results, 1):
            # FIX: score can be None (SQLite backend) — guard before formatting
            score_str = f"  Relevance: {r['score']:.2%}" if r["score"] is not None else ""
            lines.append(f"{'─' * 60}")
            lines.append(f"#{i} Topic: {r['topic']}{score_str}")
            lines.append(r["content"])
        return _truncate_output("\n".join(lines))
    except Exception as exc:
        return f"[Error] memory_search failed: {exc}"


@tool
def memory_list() -> str:
    """List all topics currently saved in your vector memory.
    Use this for a quick overview of what knowledge you've accumulated this session.
    """
    try:
        backend = _get_backend()
        topics = backend.list_topics()
        count = backend.count()
        backend_name = "ChromaDB (semantic)" if isinstance(backend, ChromaBackend) else "SQLite FTS (keyword)"

        if not topics:
            return f"[Info] Vector memory is empty. Use memory_save to start building it. Backend: {backend_name}"

        lines = [f"[Vector Memory: {count} entries | Backend: {backend_name}]"]
        for t in topics:
            lines.append(f"  • {t}")
        return "\n".join(lines)
    except Exception as exc:
        return f"[Error] memory_list failed: {exc}"


@tool
def memory_delete(topic: str) -> str:
    """Delete a specific memory entry by its topic name.
    Use this to remove outdated or incorrect information from your memory store.
    Args:
        topic: The exact topic name of the memory to delete.
    """
    try:
        backend = _get_backend()
        success = backend.delete(topic)
        if success:
            return f"[Success] Memory deleted: '{topic}'"
        return f"[Info] No memory found with topic: '{topic}'"
    except Exception as exc:
        return f"[Error] memory_delete failed: {exc}"


@tool
def memory_backend_info() -> str:
    """Check which vector memory backend is active and whether semantic search is available.
    Use this to understand your memory capabilities and get install instructions if needed.
    """
    lines = ["[Vector Memory Backend Info]"]
    if _chroma_available():
        lines.append("✅ ChromaDB: INSTALLED (persistent semantic vector search)")
        if _sentence_transformer_available():
            lines.append("✅ sentence-transformers: INSTALLED (local embeddings via all-MiniLM-L6-v2)")
        else:
            lines.append("⚠️  sentence-transformers: NOT installed (ChromaDB will use its built-in onnx embedder)")
            lines.append("   Install for better embeddings: pip install sentence-transformers")
    else:
        lines.append("⚠️  ChromaDB: NOT installed — using SQLite FTS5 fallback (keyword search only)")
        lines.append("   Install for semantic search: pip install chromadb")
        lines.append("   Optional: pip install sentence-transformers  (for local embeddings)")

    try:
        backend = _get_backend()
        lines.append(f"\nActive backend: {'ChromaDB' if isinstance(backend, ChromaBackend) else 'SQLite FTS5'}")
        lines.append(f"Stored memories: {backend.count()}")
        lines.append(f"Storage location: {_get_vector_dir()}")
    except Exception as exc:
        lines.append(f"[Error checking backend] {exc}")

    return "\n".join(lines)
