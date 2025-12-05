"""Text utility functions for normalization and processing."""
import re
import unicodedata


def normalize_text(s: str) -> str:
    """
    Normalize text by collapsing whitespace and trimming.
    
    Args:
        s: Input string
        
    Returns:
        Normalized string with single spaces
    """
    return re.sub(r"\s+", " ", (s or "").strip())


def normalize_ligatures(s: str) -> str:
    """
    Normalize common ligatures to their ASCII equivalents.
    
    Args:
        s: Input string
        
    Returns:
        String with ligatures replaced
    """
    ligature_map = {
        '\ufb00': 'ff',  # ﬀ
        '\ufb01': 'fi',  # ﬁ
        '\ufb02': 'fl',  # ﬂ
        '\ufb03': 'ffi', # ﬃ
        '\ufb04': 'ffl', # ﬄ
        '\u0152': 'OE',  # Œ
        '\u0153': 'oe',  # œ
        '\u00c6': 'AE',  # Æ
        '\u00e6': 'ae',  # æ
    }
    
    for ligature, replacement in ligature_map.items():
        s = s.replace(ligature, replacement)
    
    return s


def normalize_text_for_matching(s: str) -> str:
    """
    Normalize text for fuzzy matching by:
    - Replacing ligatures with ASCII equivalents
    - Removing punctuation (except alphanumeric)
    - Collapsing whitespace
    - Converting to lowercase
    
    Args:
        s: Input string
        
    Returns:
        Normalized string suitable for fuzzy matching
    """
    # Replace ligatures first
    s = normalize_ligatures(s or "")
    
    # Remove special characters but keep alphanumeric and spaces
    s = re.sub(r'[^\w\s]', ' ', s)
    
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s.strip())
    
    # Lowercase
    return s.lower()
