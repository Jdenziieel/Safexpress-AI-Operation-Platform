"""Coordinate and bounding box utility functions."""


def lines_are_on_same_page(line1, line2):
    """Check if two lines are on the same page."""
    return line1.get("page") == line2.get("page")


def lines_are_vertically_close(line1, line2, threshold_multiplier=2.0):
    """
    Check if two lines are vertically close enough to be considered continuous.
    Uses a more generous threshold for multi-line matching.
    """
    try:
        line1_box = line1.get("box", {})
        line2_box = line2.get("box", {})
        
        line1_bottom = line1_box.get("b", 0)
        line2_top = line2_box.get("t", 0)
        
        # Calculate line heights
        line1_height = line1_box.get("b", 0) - line1_box.get("t", 0)
        line2_height = line2_box.get("b", 0) - line2_box.get("t", 0)
        avg_height = (line1_height + line2_height) / 2
        
        # Gap between lines
        gap = line2_top - line1_bottom
        
        # Lines are close if gap is less than 2x average line height (more generous)
        return gap < (avg_height * threshold_multiplier) if avg_height > 0 else False
    except (KeyError, TypeError, ZeroDivisionError):
        return False


def is_page_break_continuation(line1, line2):
    """
    Check if line2 is a continuation of line1 across a page break.
    This handles cases where text flows from the bottom of one page to the top of the next.
    """
    try:
        page1 = line1.get("page", 1)
        page2 = line2.get("page", 1)
        
        # Must be consecutive pages
        if page2 != page1 + 1:
            return False
        
        # Line1 should be near the bottom of its page
        line1_box = line1.get("box", {})
        page1_height = line1.get("page_height", 792)  # Default PDF height
        line1_bottom = line1_box.get("b", 0)
        
        # Line2 should be near the top of its page
        line2_box = line2.get("box", {})
        line2_top = line2_box.get("t", 0)
        
        # More lenient thresholds for document
        bottom_threshold = page1_height * 0.6  # Last 40% of page
        is_line1_near_bottom = line1_bottom > bottom_threshold
        
        top_threshold = page1_height * 0.4     # First 40% of page
        is_line2_near_top = line2_top < top_threshold
        
        # Check horizontal alignment (similar indentation)
        line1_indent = line1.get("indent", line1_box.get("l", 0))
        line2_indent = line2.get("indent", line2_box.get("l", 0))
        indent_diff = abs(line1_indent - line2_indent)
        
        # More lenient indent variation (50 pixels instead of 20)
        similar_indent = indent_diff < 50
        
        return is_line1_near_bottom and is_line2_near_top and similar_indent
        
    except (KeyError, TypeError, AttributeError):
        return False


def lines_are_continuous(line1, line2):
    """
    Enhanced version that checks both same-page proximity and cross-page continuation.
    """
    # Same page check
    if lines_are_on_same_page(line1, line2):
        return lines_are_vertically_close(line1, line2, threshold_multiplier=2.0)
    
    # Cross-page check
    return is_page_break_continuation(line1, line2)


def calculate_chunk_box(matched_lines):
    """
    Enhanced version that handles cross-page bounding boxes correctly.
    Returns multiple boxes (one per page) for cross-page content.
    """
    if not matched_lines:
        return {"l": 0, "t": 0, "r": 0, "b": 0}
    
    # Flatten the matched_lines list in case it contains nested lists
    flattened_lines = []
    for item in matched_lines:
        if isinstance(item, list):
            flattened_lines.extend(item)
        else:
            flattened_lines.append(item)

    # Get all line boxes with page info
    line_data = []
    for line in flattened_lines:
        if isinstance(line, dict) and "box" in line and line["box"]:
            line_data.append({
                "box": line["box"],
                "page": line.get("page", 1)
            })
    
    if not line_data:
        return {"l": 0, "t": 0, "r": 0, "b": 0}
    
    # Group boxes by page
    boxes_by_page = {}
    for data in line_data:
        page = data["page"]
        boxes_by_page.setdefault(page, []).append(data["box"])
    
    # Check if content spans multiple pages
    if len(boxes_by_page) == 1:
        # Single page - return single box
        page = list(boxes_by_page.keys())[0]
        line_boxes = boxes_by_page[page]
        line_boxes.sort(key=lambda box: box.get("t", 0))
        
        top = line_boxes[0].get("t", 0)
        bottom = line_boxes[-1].get("b", 0)
        left = min(box.get("l", 0) for box in line_boxes)
        right = max(box.get("r", 0) for box in line_boxes)
        
        return {
            "l": left,
            "t": top, 
            "r": right,
            "b": bottom
        }
    else:
        # Multi-page content - return array of boxes (one per page)
        # This prevents coordinate confusion between pages
        boxes_array = []
        for page in sorted(boxes_by_page.keys()):
            page_boxes = boxes_by_page[page]
            page_boxes.sort(key=lambda box: box.get("t", 0))
            
            top = page_boxes[0].get("t", 0)
            bottom = page_boxes[-1].get("b", 0)
            left = min(box.get("l", 0) for box in page_boxes)
            right = max(box.get("r", 0) for box in page_boxes)
            
            boxes_array.append({
                "l": left,
                "t": top,
                "r": right,
                "b": bottom,
                "page": page
            })
        
        return boxes_array


def pdf_lines_for_match(structured):
    """
    Extract text lines from structured output, preserving line objects with metadata.
    """
    lines = []
    for element in structured:
        if element.get("type") == "text" and "text" in element:
            lines.append({
                "text": element["text"],
                "box": element.get("box", {}),
                "page": element.get("page", 1),
                "id": element.get("id", ""),
                "type": element.get("type", "text")
            })
    return lines


def calculate_match_score(chunk_text, combined_text):
    """
    Calculate match score between chunk and combined text.
    Returns score from 0-100.
    """
    if not chunk_text or not combined_text:
        return 0
    
    # Exact match = 100%
    if chunk_text == combined_text:
        return 100
    
    # Containment matches
    if chunk_text in combined_text:
        # Score based on how much of combined text is the chunk
        return int((len(chunk_text) / len(combined_text)) * 95)
    
    if combined_text in chunk_text:
        # Score based on how much of chunk is covered
        return int((len(combined_text) / len(chunk_text)) * 90)
    
    # Word-based similarity for partial matches
    chunk_words = set(chunk_text.split())
    combined_words = set(combined_text.split())
    
    if not chunk_words:
        return 0
    
    intersection = chunk_words & combined_words
    union = chunk_words | combined_words
    
    # Jaccard similarity * 85 (max score for word-based match)
    similarity = len(intersection) / len(union) if union else 0
    return int(similarity * 85)
