"""SQLite database manager for Legifrance indexing."""
import sqlite3
from pathlib import Path
from typing import List, Dict, Any, Optional


class DBManager:
    """Lightweight SQLite manager."""
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None
    
    def connect(self):
        """Open connection."""
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        return self
    
    def close(self):
        """Close connection."""
        if self.conn:
            self.conn.close()
            self.conn = None
    
    def __enter__(self):
        return self.connect()
    
    def __exit__(self, *args):
        self.close()
    
    def execute(self, query: str, params: tuple = ()) -> sqlite3.Cursor:
        """Execute single query."""
        return self.conn.execute(query, params)
    
    def executemany(self, query: str, params_list: List[tuple]):
        """Execute many (batch insert)."""
        self.conn.executemany(query, params_list)
        self.conn.commit()
    
    def query(self, query: str, params: tuple = ()) -> List[Dict]:
        """Query and return rows as dicts."""
        cur = self.conn.execute(query, params)
        return [dict(row) for row in cur.fetchall()]
    
    def query_one(self, query: str, params: tuple = ()) -> Optional[Dict]:
        """Query and return first row."""
        rows = self.query(query, params)
        return rows[0] if rows else None
    
    def commit(self):
        """Commit transaction."""
        self.conn.commit()
    
    def create_index(self, schema_sql: str):
        """Create index from schema file."""
        self.conn.executescript(schema_sql)
        self.conn.commit()


def create_legifrance_index(db_path: Path):
    """Create Legifrance index with schema."""
    schema = """
    PRAGMA journal_mode=WAL;
    PRAGMA synchronous=NORMAL;
    PRAGMA foreign_keys=ON;
    
    -- Metadata
    CREATE TABLE IF NOT EXISTS index_metadata (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    
    -- Documents
    CREATE TABLE IF NOT EXISTS documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        path TEXT UNIQUE NOT NULL,
        file_type TEXT NOT NULL,
        language TEXT,
        page_count INTEGER,
        size INTEGER NOT NULL,
        modified_at INTEGER NOT NULL,
        indexed_at INTEGER NOT NULL,
        content_hash TEXT NOT NULL,
        metadata_json TEXT,
        archive_name TEXT,
        xml_path TEXT,
        xml_id TEXT,
        nature TEXT,
        juridiction TEXT,
        date_decision INTEGER
    );
    CREATE INDEX IF NOT EXISTS idx_doc_path ON documents(path);
    CREATE INDEX IF NOT EXISTS idx_doc_archive ON documents(archive_name);
    CREATE INDEX IF NOT EXISTS idx_doc_xml_id ON documents(xml_id);
    CREATE INDEX IF NOT EXISTS idx_doc_nature ON documents(nature);
    
    -- Pages
    CREATE TABLE IF NOT EXISTS pages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        doc_id INTEGER NOT NULL,
        page_number INTEGER,
        content TEXT NOT NULL,
        content_length INTEGER NOT NULL,
        content_stem TEXT,
        was_ocr INTEGER DEFAULT 0,
        ocr_confidence REAL,
        FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE,
        UNIQUE (doc_id, page_number)
    );
    CREATE INDEX IF NOT EXISTS idx_page_doc ON pages(doc_id);
    
    -- FTS5
    CREATE VIRTUAL TABLE IF NOT EXISTS content_fts USING fts5(
        content,
        doc_id UNINDEXED,
        page_number UNINDEXED,
        tokenize='unicode61 remove_diacritics 1',
        content='pages',
        content_rowid='id'
    );
    
    -- Triggers
    CREATE TRIGGER IF NOT EXISTS pages_ai AFTER INSERT ON pages BEGIN
        INSERT INTO content_fts(rowid, content, doc_id, page_number)
        VALUES (new.id, new.content, new.doc_id, new.page_number);
    END;
    
    CREATE TRIGGER IF NOT EXISTS pages_ad AFTER DELETE ON pages BEGIN
        DELETE FROM content_fts WHERE rowid = old.id;
    END;
    
    CREATE TRIGGER IF NOT EXISTS pages_au AFTER UPDATE ON pages BEGIN
        UPDATE content_fts SET content = new.content WHERE rowid = new.id;
    END;
    """
    
    with DBManager(db_path) as db:
        db.create_index(schema)
