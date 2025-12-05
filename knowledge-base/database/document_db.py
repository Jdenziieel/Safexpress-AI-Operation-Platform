# database/document_db.py
import sqlite3
import json
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional

class DocumentDatabase:
    def __init__(self, db_path: str = "database/documents.db"):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """Initialize document tracking database tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Documents table - tracks all uploaded files
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                doc_id TEXT PRIMARY KEY,
                file_name TEXT NOT NULL,
                upload_date TEXT NOT NULL,
                file_size_bytes INTEGER NOT NULL,
                chunks INTEGER NOT NULL,
                uploaded_by TEXT,
                content_hash TEXT UNIQUE NOT NULL,
                page_count INTEGER,
                weaviate_doc_id TEXT,
                metadata TEXT,
                current_version INTEGER DEFAULT 1
            )
        """)
        
        # Document versions table - tracks version history
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS document_versions (
                version_id TEXT PRIMARY KEY,
                doc_id TEXT NOT NULL,
                file_name TEXT NOT NULL,
                version_number INTEGER NOT NULL,
                upload_date TEXT NOT NULL,
                archived_date TEXT NOT NULL,
                file_size_bytes INTEGER,
                chunks INTEGER,
                uploaded_by TEXT,
                content_hash TEXT,
                page_count INTEGER,
                replaced_by TEXT,
                FOREIGN KEY (doc_id) REFERENCES documents(doc_id)
            )
        """)
        
        # Indexes for fast lookups
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_file_name ON documents(file_name)")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_content_hash ON documents(content_hash)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_uploaded_by ON documents(uploaded_by)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_upload_date ON documents(upload_date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_version_doc_id ON document_versions(doc_id)")
        
        # Add current_version column if it doesn't exist (migration)
        try:
            cursor.execute("ALTER TABLE documents ADD COLUMN current_version INTEGER DEFAULT 1")
        except sqlite3.OperationalError:
            pass  # Column already exists
        
        conn.commit()
        conn.close()
    
    def check_duplicate_by_filename(self, filename: str) -> Optional[Dict]:
        """
        Check if a document with this filename already exists.
        
        Args:
            filename: Name of the file to check
            
        Returns:
            Document info dict if exists, None otherwise
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT doc_id, file_name, upload_date, file_size_bytes, 
                   chunks, uploaded_by, content_hash, weaviate_doc_id, current_version
            FROM documents 
            WHERE file_name = ?
        """, (filename,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                "doc_id": row["doc_id"],
                "file_name": row["file_name"],
                "upload_date": row["upload_date"],
                "file_size_bytes": row["file_size_bytes"],
                "chunks": row["chunks"],
                "uploaded_by": row["uploaded_by"],
                "content_hash": row["content_hash"],
                "weaviate_doc_id": row["weaviate_doc_id"],
                "current_version": row["current_version"] or 1
            }
        return None
    
    def check_duplicate_by_hash(self, content_hash: str) -> Optional[Dict]:
        """
        Check if a document with this content hash already exists.
        This detects renamed duplicates.
        
        Args:
            content_hash: SHA256 hash of file content
            
        Returns:
            Document info dict if exists, None otherwise
        """
        # Skip check for temporary hashes
        if not content_hash or content_hash.startswith("temp-"):
            return None
            
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT doc_id, file_name, upload_date, file_size_bytes, 
                   chunks, uploaded_by, content_hash
            FROM documents 
            WHERE content_hash = ?
        """, (content_hash,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                "doc_id": row["doc_id"],
                "file_name": row["file_name"],
                "upload_date": row["upload_date"],
                "file_size_bytes": row["file_size_bytes"],
                "chunks": row["chunks"],
                "uploaded_by": row["uploaded_by"],
                "content_hash": row["content_hash"]
            }
        return None
    
    def check_duplicates(self, filename: str, content_hash: Optional[str] = None) -> Dict:
        """
        Check for any duplicate - either by filename or content hash.
        Duplicates are not allowed in the knowledge base.
        
        Args:
            filename: Name of the file to check
            content_hash: SHA256 hash of file content (optional)
            
        Returns:
            Dictionary with detection results:
            - is_duplicate: True if any duplicate found
            - duplicate_type: 'filename', 'content', or 'both'
            - existing_doc: The existing document info (prioritizes filename match)
            - message: Human-readable description of the duplicate
        """
        existing_by_filename = self.check_duplicate_by_filename(filename)
        existing_by_hash = self.check_duplicate_by_hash(content_hash) if content_hash else None
        
        # Determine if duplicate exists and what type
        is_duplicate = bool(existing_by_filename or existing_by_hash)
        duplicate_type = None
        existing_doc = None
        message = None
        
        if existing_by_filename and existing_by_hash:
            duplicate_type = 'both'
            existing_doc = existing_by_filename  # Prioritize filename match for replacement
            if existing_by_filename['doc_id'] == existing_by_hash['doc_id']:
                message = f"This exact file '{filename}' already exists in the knowledge base."
            else:
                message = f"Filename '{filename}' already exists, and content matches another file '{existing_by_hash['file_name']}'."
        elif existing_by_filename:
            duplicate_type = 'filename'
            existing_doc = existing_by_filename
            message = f"A file named '{filename}' already exists in the knowledge base."
        elif existing_by_hash:
            duplicate_type = 'content'
            existing_doc = existing_by_hash
            message = f"This file content already exists as '{existing_by_hash['file_name']}' in the knowledge base."
        
        return {
            'is_duplicate': is_duplicate,
            'duplicate_type': duplicate_type,
            'existing_doc': existing_doc,
            'message': message
        }
    
    def insert_document(self, doc_data: Dict, version: int = 1) -> str:
        """
        Insert a new document record.
        
        Args:
            doc_data: Dictionary containing document information
            Required fields: doc_id, file_name, file_size_bytes, chunks, content_hash
            Optional fields: uploaded_by, page_count, weaviate_doc_id, metadata
            version: Version number for the document (default 1 for new documents)
            
        Returns:
            doc_id of inserted document
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Use Philippine time (UTC+8)
        ph_tz = timezone(timedelta(hours=8))
        upload_date = datetime.now(ph_tz).isoformat()
        
        cursor.execute("""
            INSERT INTO documents 
            (doc_id, file_name, upload_date, file_size_bytes, chunks, 
             uploaded_by, content_hash, page_count, weaviate_doc_id, metadata, current_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            doc_data.get("doc_id"),
            doc_data.get("file_name"),
            upload_date,
            doc_data.get("file_size_bytes"),
            doc_data.get("chunks"),
            doc_data.get("uploaded_by"),
            doc_data.get("content_hash"),
            doc_data.get("page_count"),
            doc_data.get("weaviate_doc_id"),
            json.dumps(doc_data.get("metadata", {})),
            version
        ))
        
        conn.commit()
        conn.close()
        
        return doc_data.get("doc_id")
    
    def update_document(self, doc_id: str, updates: Dict) -> bool:
        """
        Update an existing document record.
        
        Args:
            doc_id: Document ID to update
            updates: Dictionary of fields to update
            
        Returns:
            True if updated successfully
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Build dynamic UPDATE query
        set_clauses = []
        values = []
        
        allowed_fields = [
            "file_name", "file_size_bytes", "chunks", "uploaded_by",
            "content_hash", "page_count", "weaviate_doc_id"
        ]
        
        for field in allowed_fields:
            if field in updates:
                set_clauses.append(f"{field} = ?")
                values.append(updates[field])
        
        if "metadata" in updates:
            set_clauses.append("metadata = ?")
            values.append(json.dumps(updates["metadata"]))
        
        if not set_clauses:
            conn.close()
            return False
        
        values.append(doc_id)
        query = f"UPDATE documents SET {', '.join(set_clauses)} WHERE doc_id = ?"
        
        cursor.execute(query, values)
        conn.commit()
        affected = cursor.rowcount
        conn.close()
        
        return affected > 0
    
    def delete_document(self, doc_id: str) -> bool:
        """
        Delete a document record.
        
        Args:
            doc_id: Document ID to delete
            
        Returns:
            True if deleted successfully
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
        conn.commit()
        affected = cursor.rowcount
        conn.close()
        
        return affected > 0
    
    def get_document(self, doc_id: str) -> Optional[Dict]:
        """
        Get a document by ID.
        
        Args:
            doc_id: Document ID
            
        Returns:
            Document info dict if found, None otherwise
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT doc_id, file_name, upload_date, file_size_bytes, 
                   chunks, uploaded_by, content_hash, page_count,
                   weaviate_doc_id, metadata
            FROM documents 
            WHERE doc_id = ?
        """, (doc_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                "doc_id": row["doc_id"],
                "file_name": row["file_name"],
                "upload_date": row["upload_date"],
                "file_size_bytes": row["file_size_bytes"],
                "chunks": row["chunks"],
                "uploaded_by": row["uploaded_by"],
                "content_hash": row["content_hash"],
                "page_count": row["page_count"],
                "weaviate_doc_id": row["weaviate_doc_id"],
                "metadata": json.loads(row["metadata"]) if row["metadata"] else {}
            }
        return None
    
    def get_document_by_filename(self, file_name: str) -> Optional[Dict]:
        """
        Get a document by filename.
        
        Args:
            file_name: Name of the file
            
        Returns:
            Document info dict if found, None otherwise
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT doc_id, file_name, upload_date, file_size_bytes, 
                   chunks, uploaded_by, content_hash, page_count,
                   weaviate_doc_id, metadata, current_version
            FROM documents 
            WHERE file_name = ?
        """, (file_name,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                "doc_id": row["doc_id"],
                "file_name": row["file_name"],
                "upload_date": row["upload_date"],
                "file_size_bytes": row["file_size_bytes"],
                "chunks": row["chunks"],
                "uploaded_by": row["uploaded_by"],
                "content_hash": row["content_hash"],
                "page_count": row["page_count"],
                "weaviate_doc_id": row["weaviate_doc_id"],
                "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
                "current_version": row["current_version"] or 1
            }
        return None
    
    def list_documents(
        self, 
        limit: int = 100, 
        offset: int = 0,
        uploaded_by: Optional[str] = None,
        order_by: str = "upload_date",
        order_dir: str = "DESC"
    ) -> List[Dict]:
        """
        List all documents with pagination and filtering.
        
        Args:
            limit: Maximum number of results
            offset: Number of results to skip
            uploaded_by: Filter by user (optional)
            order_by: Field to sort by (default: upload_date)
            order_dir: Sort direction (ASC or DESC)
            
        Returns:
            List of document info dicts
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Build query with optional filter
        query = """
            SELECT doc_id, file_name, upload_date, file_size_bytes, 
                   chunks, uploaded_by, content_hash, page_count, current_version,
                   weaviate_doc_id
            FROM documents
        """
        params = []
        
        if uploaded_by:
            query += " WHERE uploaded_by = ?"
            params.append(uploaded_by)
        
        # Add ordering
        allowed_order_fields = ["upload_date", "file_name", "file_size_bytes", "chunks"]
        if order_by not in allowed_order_fields:
            order_by = "upload_date"
        
        if order_dir.upper() not in ["ASC", "DESC"]:
            order_dir = "DESC"
        
        query += f" ORDER BY {order_by} {order_dir} LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        
        return [
            {
                "doc_id": row["doc_id"],
                "file_name": row["file_name"],
                "upload_date": row["upload_date"],
                "file_size_bytes": row["file_size_bytes"],
                "chunks": row["chunks"],
                "uploaded_by": row["uploaded_by"],
                "content_hash": row["content_hash"],
                "page_count": row["page_count"],
                "current_version": row["current_version"],
                "weaviate_doc_id": row["weaviate_doc_id"]
            }
            for row in rows
        ]
    
    def get_document_count(self, uploaded_by: Optional[str] = None) -> int:
        """
        Get total count of documents.
        
        Args:
            uploaded_by: Filter by user (optional)
            
        Returns:
            Total number of documents
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if uploaded_by:
            cursor.execute("SELECT COUNT(*) FROM documents WHERE uploaded_by = ?", (uploaded_by,))
        else:
            cursor.execute("SELECT COUNT(*) FROM documents")
        
        count = cursor.fetchone()[0]
        conn.close()
        
        return count

    # ═══════════════════════════════════════════════════════════════════════════
    # VERSION HISTORY METHODS
    # ═══════════════════════════════════════════════════════════════════════════
    
    def archive_document_version(self, doc_id: str, replaced_by: str = None) -> Optional[str]:
        """
        Archive current document to version history before replacement.
        
        Args:
            doc_id: Document ID to archive
            replaced_by: User who is replacing the document
            
        Returns:
            version_id if successful, None otherwise
        """
        import uuid
        
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get current document
        cursor.execute("""
            SELECT doc_id, file_name, upload_date, file_size_bytes, chunks,
                   uploaded_by, content_hash, page_count, current_version
            FROM documents WHERE doc_id = ?
        """, (doc_id,))
        
        row = cursor.fetchone()
        if not row:
            conn.close()
            return None
        
        # Use Philippine time (UTC+8)
        ph_tz = timezone(timedelta(hours=8))
        archived_date = datetime.now(ph_tz).isoformat()
        
        version_id = str(uuid.uuid4())
        current_version = row["current_version"] or 1
        
        # Insert into version history
        cursor.execute("""
            INSERT INTO document_versions 
            (version_id, doc_id, file_name, version_number, upload_date, 
             archived_date, file_size_bytes, chunks, uploaded_by, 
             content_hash, page_count, replaced_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            version_id,
            row["doc_id"],
            row["file_name"],
            current_version,
            row["upload_date"],
            archived_date,
            row["file_size_bytes"],
            row["chunks"],
            row["uploaded_by"],
            row["content_hash"],
            row["page_count"],
            replaced_by
        ))
        
        conn.commit()
        conn.close()
        
        return version_id
    
    def get_next_version_number(self, file_name: str) -> int:
        """
        Get the next version number for a file.
        
        Args:
            file_name: Name of the file
            
        Returns:
            Next version number
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get max version from both current doc and version history
        cursor.execute("""
            SELECT MAX(version_number) FROM document_versions WHERE file_name = ?
        """, (file_name,))
        
        max_archived = cursor.fetchone()[0] or 0
        
        cursor.execute("""
            SELECT current_version FROM documents WHERE file_name = ?
        """, (file_name,))
        
        current = cursor.fetchone()
        current_version = current[0] if current else 0
        
        conn.close()
        
        return max(max_archived, current_version) + 1
    
    def get_document_versions(self, file_name: str) -> List[Dict]:
        """
        Get version history for a document by filename.
        
        Args:
            file_name: Name of the file
            
        Returns:
            List of version records, newest first
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get archived versions
        cursor.execute("""
            SELECT version_id, doc_id, file_name, version_number, upload_date,
                   archived_date, file_size_bytes, chunks, uploaded_by,
                   content_hash, page_count, replaced_by
            FROM document_versions 
            WHERE file_name = ?
            ORDER BY version_number DESC
        """, (file_name,))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [
            {
                "version_id": row["version_id"],
                "doc_id": row["doc_id"],
                "file_name": row["file_name"],
                "version_number": row["version_number"],
                "upload_date": row["upload_date"],
                "archived_date": row["archived_date"],
                "file_size_bytes": row["file_size_bytes"],
                "chunks": row["chunks"],
                "uploaded_by": row["uploaded_by"],
                "content_hash": row["content_hash"],
                "page_count": row["page_count"],
                "replaced_by": row["replaced_by"],
                "is_current": False
            }
            for row in rows
        ]
    
    def get_full_document_history(self, file_name: str) -> Dict:
        """
        Get complete document history including current version and all archived versions.
        
        Args:
            file_name: Name of the file
            
        Returns:
            Dictionary with current version and version history
        """
        # Get current document
        current = self.check_duplicate_by_filename(file_name)
        
        # Get version number for current
        if current:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT current_version FROM documents WHERE doc_id = ?", (current['doc_id'],))
            version_row = cursor.fetchone()
            current['version_number'] = version_row[0] if version_row else 1
            current['is_current'] = True
            conn.close()
        
        # Get archived versions
        versions = self.get_document_versions(file_name)
        
        # Count total versions
        total_versions = len(versions) + (1 if current else 0)
        
        return {
            "file_name": file_name,
            "current": current,
            "versions": versions,
            "total_versions": total_versions
        }