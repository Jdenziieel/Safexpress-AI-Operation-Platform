"""Document validation utilities for knowledge base uploads."""
import hashlib


def calculate_file_hash(file_bytes: bytes) -> str:
    """
    Calculate SHA256 hash of file content.
    
    Args:
        file_bytes: Raw file bytes
        
    Returns:
        Hex string of SHA256 hash
    """
    return hashlib.sha256(file_bytes).hexdigest()
