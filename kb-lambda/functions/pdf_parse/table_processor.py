"""Table processing utilities."""
from text_utils import normalize_text


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


def find_best_matching_table(chunk_text, page_tables, excluded_ids=None):
    """
    Find the best matching table on a page by comparing chunk text with table content.
    Tables whose id is in *excluded_ids* are skipped.
    """
    if not page_tables or not chunk_text.strip():
        return None

    if excluded_ids is None:
        excluded_ids = set()

    best_table = None
    best_score = 0
    
    print(f"[DEBUG] Matching table chunk against {len(page_tables)} tables on page")
    
    for table_idx, table in enumerate(page_tables):
        table_id = table.get("id", "")
        if table_id and table_id in excluded_ids:
            continue

        table_content = extract_table_text_content(table)
        
        if not table_content:
            print(f"[DEBUG] Table {table_idx} has no extractable content")
            continue
            
        similarity_score = calculate_table_similarity(chunk_text, table_content)
        
        print(f"[DEBUG] Table {table_idx} ({table_id}) similarity: {similarity_score:.2f}")
        print(f"[DEBUG] Table content preview: {table_content[:100]}...")
        
        if similarity_score > best_score:
            best_score = similarity_score
            best_table = table
            
    if best_score >= 0.3:
        print(f"[DEBUG] Selected table with {best_score:.2f} similarity")
        return best_table
    else:
        print(f"[DEBUG] No table met similarity threshold (best: {best_score:.2f})")
        return None


def find_matching_tables_cross_page(chunk_text, all_tables, preferred_page=1,
                                     excluded_ids=None, page_proximity_bonus=0.10):
    """
    Search *all_tables* (flat list across every page) for tables matching
    *chunk_text*.  Returns a list of matching table dicts sorted by page,
    or an empty list if nothing exceeds the threshold.

    Scoring:
      - base score   = calculate_table_similarity(chunk_text, table_content)
      - bonus        = +page_proximity_bonus when table.page == preferred_page
      - Tables in *excluded_ids* are skipped.
      - The best-scoring table is always returned.  If other tables share
        content from the same logical table (same id prefix) they are
        included as well, giving multi-page coverage.
    """
    if not all_tables or not chunk_text.strip():
        return []

    if excluded_ids is None:
        excluded_ids = set()

    scored = []
    for table in all_tables:
        table_id = table.get("id", "")
        if table_id and table_id in excluded_ids:
            continue

        table_content = extract_table_text_content(table)
        if not table_content:
            continue

        score = calculate_table_similarity(chunk_text, table_content)
        if table.get("page", 1) == preferred_page:
            score += page_proximity_bonus

        scored.append((score, table))

    if not scored:
        return []

    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best_table = scored[0]

    if best_score < 0.3:
        print(f"[DEBUG] Cross-page: no table met threshold (best: {best_score:.2f})")
        return []

    result = [best_table]

    # Pull in related tables on other pages that also score well
    # (handles tables spanning across pages extracted as separate elements)
    for score, tbl in scored[1:]:
        if score < 0.25:
            break
        if tbl.get("page") != best_table.get("page"):
            result.append(tbl)

    result.sort(key=lambda t: t.get("page", 1))
    pages = [t.get("page", "?") for t in result]
    print(f"[DEBUG] Cross-page: matched {len(result)} table(s) on pages {pages} "
          f"(best score {best_score:.2f})")
    return result
