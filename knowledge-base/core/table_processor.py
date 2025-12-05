"""Table processing utilities."""
from utils.text_utils import normalize_text


def extract_table_text_content(table):
    """
    Extract all text content from a table structure for comparison
    """
    table_data = table.get("table", [])
    if not table_data:
        return ""
    
    # Flatten all table cells into a single text string
    all_text_parts = []
    for row in table_data:
        if isinstance(row, (list, tuple)):
            for cell in row:
                if cell and str(cell).strip():
                    all_text_parts.append(str(cell).strip())
        elif row and str(row).strip():
            all_text_parts.append(str(row).strip())
    
    return " | ".join(all_text_parts)


def calculate_table_similarity(chunk_text, table_content):
    """
    Calculate similarity between AI chunk text and extracted table content
    """
    if not chunk_text or not table_content:
        return 0.0
    
    # Normalize both texts
    chunk_normalized = normalize_text(chunk_text.lower())
    table_normalized = normalize_text(table_content.lower())
    
    # Method 1: Check if table content is contained in chunk (AI descriptions often include table data)
    if table_normalized in chunk_normalized:
        containment_score = len(table_normalized) / len(chunk_normalized)
        return min(0.95, containment_score * 1.2)  # Boost containment matches
    
    # Method 2: Check if chunk is contained in table content  
    if chunk_normalized in table_normalized:
        containment_score = len(chunk_normalized) / len(table_normalized)
        return min(0.90, containment_score * 1.1)
    
    # Method 3: Word overlap similarity
    chunk_words = set(chunk_normalized.split())
    table_words = set(table_normalized.split())
    
    if not chunk_words or not table_words:
        return 0.0
    
    intersection = chunk_words & table_words
    union = chunk_words | table_words
    
    jaccard_similarity = len(intersection) / len(union) if union else 0.0
    
    # Method 4: Key table terms bonus (look for table-specific keywords in chunk)
    table_indicators = {'table', 'program', 'defense', 'date', 'title', 'members', 'adviser'}
    chunk_words_lower = set(word.lower() for word in chunk_text.split())
    
    if table_indicators & chunk_words_lower:
        jaccard_similarity *= 1.3  # 30% bonus for table-related terms
    
    return min(1.0, jaccard_similarity)


def find_best_matching_table(chunk_text, page_tables):
    """
    Find the best matching table on a page by comparing chunk text with table content
    """
    if not page_tables or not chunk_text.strip():
        return None
    
    best_table = None
    best_score = 0
    
    print(f"[DEBUG] Matching table chunk against {len(page_tables)} tables on page")
    
    for table_idx, table in enumerate(page_tables):
        table_content = extract_table_text_content(table)
        
        if not table_content:
            print(f"[DEBUG] Table {table_idx} has no extractable content")
            continue
            
        # Calculate similarity between chunk text and table content
        similarity_score = calculate_table_similarity(chunk_text, table_content)
        
        print(f"[DEBUG] Table {table_idx} similarity: {similarity_score:.2f}")
        print(f"[DEBUG] Table content preview: {table_content[:100]}...")
        
        if similarity_score > best_score:
            best_score = similarity_score
            best_table = table
            
    # Require minimum similarity threshold
    if best_score >= 0.3:  # 30% similarity threshold
        print(f"[DEBUG] ✅ Selected table with {best_score:.2f} similarity")
        return best_table
    else:
        print(f"[DEBUG] ❌ No table met similarity threshold (best: {best_score:.2f})")
        return None
