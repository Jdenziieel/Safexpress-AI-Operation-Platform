# Advanced Chunking Implementation Plan

## Executive Summary

This document outlines a comprehensive plan to implement advanced chunking capabilities for the Knowledge Base PDF processing system. The enhancements focus on four key areas:
1. **Layout-Aware Chunking** - Understanding document structure and visual layout
2. **Multi-Column Support** - Detecting and processing multi-column layouts
3. **Header/Footer Detection** - Identifying and handling repeated page elements
4. **Footnote Handling** - Detecting and properly associating footnotes with content

---

## Current System Analysis

### System Architecture Overview

**Current Processing Pipeline:**
```
PDF Upload → Extraction → AI Chunking → Anchoring → Storage
     ↓            ↓            ↓            ↓           ↓
Security    Text/Images   GPT-4      Coordinate   Weaviate
Validation  Tables        Two-Pass   Matching     Vector DB
            Base64        Processing              
```

### Current Strengths

1. **Robust Extraction (`pdf_extractor.py`)**
   - Uses `pdfplumber` for text extraction with line-by-line precision
   - `PyMuPDF` (fitz) for image extraction with accurate coordinates
   - Font size, style (bold/italic), and spacing metadata captured
   - Adaptive word tolerance based on font size
   - Table detection with bounding boxes
   - Unique IDs for lines, tables, and images (e.g., `p1-ln-5`, `p2-tbl-0`, `p1-img-0-0`)

2. **Intelligent Chunking (`chunking_service.py`)**
   - Two-pass approach: text-only pass, then image pass
   - OpenAI GPT-4 for semantic understanding
   - Context-aware chunking (considers document structure)
   - Image processing with surrounding text context

3. **Precise Anchoring (`anchoring_service.py`)**
   - Text matching with normalization
   - Coordinate mapping to PDF space
   - Page break continuation detection
   - Multi-line chunk support

4. **Coordinate Utilities (`coordinate_utils.py`)**
   - Page break continuation logic
   - Vertical proximity detection
   - Cross-page bounding box calculation

### Current Limitations

1. **No Layout Analysis**
   - No detection of columns, regions, or spatial relationships
   - Text processed sequentially (top-to-bottom)
   - Cannot distinguish between main content and sidebars

2. **Single-Column Assumption**
   - Multi-column documents processed incorrectly
   - Reading order follows Y-coordinate only
   - Columns get interleaved in output

3. **No Header/Footer Detection**
   - Headers/footers included in chunks
   - Repeated content pollutes knowledge base
   - Page numbers treated as regular text

4. **No Footnote Recognition**
   - Footnotes not linked to referring text
   - Small font sizes not specially handled
   - Superscript markers not detected

---

## Implementation Plan

### Phase 1: Layout-Aware Chunking

#### 1.1 Document Layout Analysis Module

**New File: `backend/core/layout_analyzer.py`**

```python
"""Document layout analysis and region detection."""
import statistics
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass

@dataclass
class LayoutRegion:
    """Represents a detected layout region"""
    region_id: str
    region_type: str  # 'header', 'footer', 'body', 'sidebar', 'footnote'
    box: Dict[str, float]  # {l, t, r, b}
    page: int
    confidence: float
    elements: List[Dict]  # Lines/images/tables in this region
    
class LayoutAnalyzer:
    """Analyzes document layout and identifies regions"""
    
    def __init__(self):
        self.header_threshold = 0.15  # Top 15% of page
        self.footer_threshold = 0.85  # Bottom 15% of page
        self.footnote_size_ratio = 0.8  # 80% of normal font size
        
    def analyze_page_layout(self, elements: List[Dict], 
                           page_width: float, 
                           page_height: float) -> Dict:
        """
        Analyze layout of a single page
        Returns: {
            'regions': List[LayoutRegion],
            'columns': List[ColumnInfo],
            'reading_order': List[element_ids]
        }
        """
        pass
        
    def detect_columns(self, text_lines: List[Dict], 
                      page_width: float) -> List[Dict]:
        """
        Detect column layout using X-coordinate clustering
        
        Algorithm:
        1. Extract left edges (indent values) of all lines
        2. Cluster X-coordinates using DBSCAN or histogram analysis
        3. Identify column boundaries
        4. Assign lines to columns
        5. Determine reading order (left-to-right, top-to-bottom within columns)
        """
        pass
        
    def detect_headers_footers(self, elements: List[Dict], 
                               page_height: float) -> Tuple[List, List]:
        """
        Detect headers and footers using:
        - Vertical position (top/bottom margins)
        - Repetition across pages
        - Font size (often smaller)
        - Content patterns (page numbers, dates, titles)
        """
        pass
        
    def detect_footnotes(self, text_lines: List[Dict], 
                        page_height: float) -> List[Dict]:
        """
        Detect footnotes using:
        - Small font size (< 80% of body text)
        - Bottom region of page
        - Superscript markers (¹, ², ³, *, †, ‡)
        - Indentation patterns
        - Separator lines or spacing
        """
        pass
        
    def calculate_reading_order(self, regions: List[LayoutRegion], 
                               columns: List[Dict]) -> List[str]:
        """
        Calculate proper reading order considering:
        - Column layout (left-to-right)
        - Vertical position within columns
        - Region types (skip headers/footers)
        - Multi-page flow
        """
        pass
```

**Key Algorithms:**

1. **Column Detection Algorithm**
```
Input: List of text lines with coordinates
Output: Column definitions and line assignments

1. Extract left edges (x0/indent) from all lines
2. Create histogram of X-coordinates (bucket by 10px)
3. Find peaks in histogram → column start positions
4. Calculate column widths using right edges
5. Assign each line to nearest column
6. Sort lines within columns by Y-coordinate
7. Build reading order: Col1-top-to-bottom, then Col2, etc.

Edge Cases:
- Lines spanning multiple columns (merge cells, titles)
- Varying column widths
- Irregular layouts (3-column with 2-column sections)
```

2. **Header/Footer Detection Algorithm**
```
Input: All elements from multiple pages
Output: Detected headers/footers with positions

Phase 1: Position-based detection
1. Identify top 15% region (header zone)
2. Identify bottom 15% region (footer zone)
3. Extract elements in these zones

Phase 2: Repetition analysis
1. Compare text content across pages
2. Find exact or near-exact matches
3. Mark repeated content as header/footer

Phase 3: Pattern recognition
1. Detect page numbers (regex: \d+, Page \d+, etc.)
2. Detect dates (common formats)
3. Detect document titles (repeated on every page)

Confidence Scoring:
- Position match: +30%
- Repetition (3+ pages): +40%
- Pattern match: +20%
- Font size smaller than body: +10%
```

3. **Footnote Detection Algorithm**
```
Input: Text lines with font metadata
Output: Footnote elements and their references

Phase 1: Identify footnote region
1. Calculate median body font size
2. Find lines with size < 80% of median
3. Check if in bottom 30% of page
4. Look for separator lines or large spacing

Phase 2: Detect markers
1. Search for superscript numbers: ¹, ², ³
2. Search for symbols: *, †, ‡, §
3. Search for bracketed numbers: [1], [2]
4. Build marker → footnote mapping

Phase 3: Link references
1. Scan body text for matching markers
2. Create bidirectional links
3. Store footnote_id in chunk metadata
```

#### 1.2 Integration Points

**Modify `pdf_extractor.py`:**
```python
def assemble_elements(file_bytes, page, page_number):
    """Enhanced with layout analysis"""
    # ... existing extraction ...
    
    # NEW: Add page dimensions to each element
    for elem in elements:
        elem['page_width'] = page.width
        elem['page_height'] = page.height
    
    return elements

def build_simplified_view_from_elements(elements, gap_multiplier=1.5):
    """Enhanced with layout-aware ordering"""
    from core.layout_analyzer import LayoutAnalyzer
    
    analyzer = LayoutAnalyzer()
    
    # Group by page
    pages = {}
    for el in elements:
        page_no = el.get("page", 1)
        pages.setdefault(page_no, []).append(el)
    
    lines_out = []
    
    for page_no in sorted(pages.keys()):
        page_elems = pages[page_no]
        
        # NEW: Analyze layout
        page_width = page_elems[0].get('page_width', 612)
        page_height = page_elems[0].get('page_height', 792)
        
        layout = analyzer.analyze_page_layout(page_elems, page_width, page_height)
        
        # Use layout-aware reading order instead of simple Y-sort
        ordered_elements = []
        for elem_id in layout['reading_order']:
            elem = next((e for e in page_elems if e.get('id') == elem_id), None)
            if elem:
                ordered_elements.append(elem)
        
        # Filter out headers/footers
        body_elements = [
            e for e in ordered_elements 
            if e.get('region_type') not in ['header', 'footer']
        ]
        
        # ... rest of simplified view building ...
```

**Modify `chunking_service.py`:**
```python
def process_text_only(simplified_view, layout_info):
    """Enhanced prompt with layout awareness"""
    
    text_prompt = f"""You are a PDF text analyzer that outputs structured JSON.
    
    **Document Layout Information:**
    - Column Layout: {layout_info.get('columns', 'single-column')}
    - Detected Regions: {layout_info.get('region_types', [])}
    - Footnotes Present: {layout_info.get('has_footnotes', False)}
    
    **Enhanced Chunking Guidelines:**
    - Respect column boundaries (don't merge across columns)
    - Group related multi-column content (spanning headers, tables)
    - Link footnotes to their references
    - Ignore headers/footers (already filtered)
    - Maintain logical reading order
    
    ... rest of prompt ...
    """
```

---

### Phase 2: Multi-Column Support

#### 2.1 Column Detection Implementation

**Algorithm Details:**

```python
# In layout_analyzer.py

def detect_columns(self, text_lines: List[Dict], page_width: float) -> List[Dict]:
    """
    Multi-column detection using X-coordinate clustering
    """
    if not text_lines:
        return [{'index': 0, 'left': 0, 'right': page_width, 'lines': []}]
    
    # Step 1: Extract left edges
    left_edges = [line.get('indent', line['box']['l']) for line in text_lines]
    
    # Step 2: Create histogram (10px buckets)
    from collections import Counter
    histogram = Counter(int(x / 10) * 10 for x in left_edges)
    
    # Step 3: Find peaks (local maxima)
    peaks = []
    sorted_buckets = sorted(histogram.keys())
    for i, bucket in enumerate(sorted_buckets):
        count = histogram[bucket]
        
        # Check if local maximum
        prev_count = histogram.get(sorted_buckets[i-1], 0) if i > 0 else 0
        next_count = histogram.get(sorted_buckets[i+1], 0) if i < len(sorted_buckets)-1 else 0
        
        if count >= prev_count and count >= next_count and count > 3:
            peaks.append(bucket)
    
    # Step 4: Define column boundaries
    if len(peaks) == 0:
        # Single column (full width)
        return [{'index': 0, 'left': 0, 'right': page_width, 'lines': text_lines}]
    
    elif len(peaks) == 1:
        # Single column (with margin)
        return [{'index': 0, 'left': peaks[0], 'right': page_width, 'lines': text_lines}]
    
    else:
        # Multiple columns
        columns = []
        for i, peak in enumerate(peaks):
            if i < len(peaks) - 1:
                # Column boundary is midpoint between peaks
                right = (peak + peaks[i+1]) / 2
            else:
                right = page_width
            
            columns.append({
                'index': i,
                'left': peak,
                'right': right,
                'lines': []
            })
        
        # Step 5: Assign lines to columns
        for line in text_lines:
            line_left = line.get('indent', line['box']['l'])
            line_right = line['box']['r']
            line_center = (line_left + line_right) / 2
            
            # Check if spans multiple columns
            spanning_cols = []
            for col in columns:
                if line_left <= col['right'] and line_right >= col['left']:
                    spanning_cols.append(col['index'])
            
            if len(spanning_cols) > 1:
                # Line spans multiple columns (likely a header/title)
                line['spans_columns'] = True
                line['column'] = spanning_cols[0]  # Assign to first column
                columns[spanning_cols[0]]['lines'].append(line)
            else:
                # Assign to nearest column by center point
                assigned = False
                for col in columns:
                    if col['left'] <= line_center <= col['right']:
                        line['column'] = col['index']
                        col['lines'].append(line)
                        assigned = True
                        break
                
                if not assigned:
                    # Fallback: assign to first column
                    line['column'] = 0
                    columns[0]['lines'].append(line)
        
        return columns
```

#### 2.2 Reading Order Calculation

```python
def calculate_reading_order(self, regions: List[LayoutRegion], 
                           columns: List[Dict]) -> List[str]:
    """
    Calculate proper reading order for multi-column layout
    """
    ordered_ids = []
    
    # Group regions by type
    headers = [r for r in regions if r.region_type == 'header']
    bodies = [r for r in regions if r.region_type == 'body']
    footnotes = [r for r in regions if r.region_type == 'footnote']
    
    # Process headers first (full width, appears once)
    for header in sorted(headers, key=lambda x: x.box['t']):
        ordered_ids.extend([e['id'] for e in header.elements])
    
    # Process body content by columns
    if len(columns) > 1:
        # Multi-column: process left to right
        for col in sorted(columns, key=lambda x: x['left']):
            # Within column: top to bottom
            col_lines = sorted(col['lines'], key=lambda x: x['box']['t'])
            ordered_ids.extend([line['id'] for line in col_lines])
    else:
        # Single column: top to bottom
        body_elements = []
        for region in bodies:
            body_elements.extend(region.elements)
        body_elements.sort(key=lambda x: x['box']['t'])
        ordered_ids.extend([e['id'] for e in body_elements])
    
    # Process footnotes last
    for footnote in sorted(footnotes, key=lambda x: x.box['t']):
        ordered_ids.extend([e['id'] for e in footnote.elements])
    
    return ordered_ids
```

#### 2.3 Multi-Column Test Cases

Create test PDFs covering:
1. **Two-column academic paper** (equal width columns)
2. **Three-column newsletter** (narrow columns)
3. **Mixed layout** (single-column intro, then two-column body)
4. **Asymmetric columns** (wide main + narrow sidebar)
5. **Column with spanning headers** (titles across both columns)

---

### Phase 3: Header/Footer Detection

#### 3.1 Repetition-Based Detection

```python
def detect_headers_footers(self, all_pages_elements: Dict[int, List[Dict]]) -> Dict:
    """
    Detect headers/footers by finding repeated content across pages
    """
    # Step 1: Extract candidates from margin regions
    header_candidates = {}  # page -> list of lines in header zone
    footer_candidates = {}  # page -> list of lines in footer zone
    
    for page_no, elements in all_pages_elements.items():
        if not elements:
            continue
            
        page_height = elements[0].get('page_height', 792)
        header_zone = page_height * 0.15
        footer_zone = page_height * 0.85
        
        headers = []
        footers = []
        
        for elem in elements:
            if elem.get('type') != 'text':
                continue
                
            y_top = elem['box']['t']
            
            if y_top < header_zone:
                headers.append(elem)
            elif y_top > footer_zone:
                footers.append(elem)
        
        header_candidates[page_no] = headers
        footer_candidates[page_no] = footers
    
    # Step 2: Find repeated patterns
    from collections import Counter
    from utils.text_utils import normalize_text
    
    # Check headers
    header_texts = []
    for page_no, lines in header_candidates.items():
        page_text = ' '.join(normalize_text(line['text']) for line in lines)
        header_texts.append(page_text)
    
    header_counter = Counter(header_texts)
    repeated_headers = {text: count for text, count in header_counter.items() 
                       if count >= 3}  # Appears on 3+ pages
    
    # Check footers
    footer_texts = []
    for page_no, lines in footer_candidates.items():
        page_text = ' '.join(normalize_text(line['text']) for line in lines)
        footer_texts.append(page_text)
    
    footer_counter = Counter(footer_texts)
    repeated_footers = {text: count for text, count in footer_counter.items() 
                       if count >= 3}
    
    # Step 3: Mark elements as header/footer
    detected = {
        'headers': [],
        'footers': [],
        'patterns': {
            'header_text': list(repeated_headers.keys()),
            'footer_text': list(repeated_footers.keys())
        }
    }
    
    for page_no, lines in header_candidates.items():
        page_text = ' '.join(normalize_text(line['text']) for line in lines)
        if page_text in repeated_headers:
            for line in lines:
                line['is_header'] = True
                detected['headers'].append(line)
    
    for page_no, lines in footer_candidates.items():
        page_text = ' '.join(normalize_text(line['text']) for line in lines)
        if page_text in repeated_footers:
            for line in lines:
                line['is_footer'] = True
                detected['footers'].append(line)
    
    return detected
```

#### 3.2 Pattern-Based Detection

```python
import re

def detect_page_numbers(self, text: str) -> bool:
    """Detect if text contains page numbering patterns"""
    patterns = [
        r'^\d+$',  # Just a number
        r'^Page \d+$',
        r'^\d+ of \d+$',
        r'^- \d+ -$',
        r'^\|\s*\d+\s*\|$',
    ]
    
    for pattern in patterns:
        if re.match(pattern, text.strip(), re.IGNORECASE):
            return True
    return False

def detect_document_info(self, text: str) -> bool:
    """Detect common header/footer information"""
    patterns = [
        r'\d{4}-\d{2}-\d{2}',  # Date
        r'©\s*\d{4}',  # Copyright
        r'confidential',  # Confidentiality notice
        r'proprietary',
        r'draft',
        r'version \d+\.\d+',
    ]
    
    text_lower = text.lower()
    for pattern in patterns:
        if re.search(pattern, text_lower):
            return True
    return False
```

#### 3.3 Integration with Extraction

```python
# In pdf_extractor.py - modify assemble_elements

def extract_all_pages(file_bytes):
    """Extract all pages first to enable cross-page analysis"""
    all_pages = {}
    
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page_num, page in enumerate(pdf.pages):
            elements = assemble_elements(file_bytes, page, page_num)
            all_pages[page_num + 1] = elements
    
    # NEW: Cross-page header/footer detection
    from core.layout_analyzer import LayoutAnalyzer
    analyzer = LayoutAnalyzer()
    header_footer_info = analyzer.detect_headers_footers(all_pages)
    
    # Mark elements
    for page_no, elements in all_pages.items():
        for elem in elements:
            elem_id = elem.get('id')
            if any(h['id'] == elem_id for h in header_footer_info['headers']):
                elem['region_type'] = 'header'
            elif any(f['id'] == elem_id for f in header_footer_info['footers']):
                elem['region_type'] = 'footer'
    
    return all_pages, header_footer_info
```

---

### Phase 4: Footnote Handling

#### 4.1 Footnote Detection

```python
def detect_footnotes(self, text_lines: List[Dict], page_height: float) -> Dict:
    """
    Comprehensive footnote detection
    """
    if not text_lines:
        return {'footnotes': [], 'references': []}
    
    # Step 1: Calculate body font size (median)
    font_sizes = [line.get('words', [{}])[0].get('font_size', 12) 
                  for line in text_lines 
                  if line.get('words')]
    font_sizes = [s for s in font_sizes if s]  # Remove None
    
    if not font_sizes:
        return {'footnotes': [], 'references': []}
    
    median_font = statistics.median(font_sizes)
    footnote_threshold = median_font * 0.85  # 85% of body size
    
    # Step 2: Identify footnote region
    footnote_zone_start = page_height * 0.70  # Bottom 30% of page
    
    footnote_candidates = []
    for line in text_lines:
        y_pos = line['box']['t']
        
        # Get average font size for the line
        line_sizes = [w.get('font_size', 12) for w in line.get('words', [])]
        avg_size = statistics.mean(line_sizes) if line_sizes else 12
        
        # Check if in footnote zone with small font
        if y_pos > footnote_zone_start and avg_size < footnote_threshold:
            footnote_candidates.append(line)
    
    # Step 3: Look for separator lines or large spacing
    separator_detected = False
    for i in range(len(text_lines) - 1):
        current_line = text_lines[i]
        next_line = text_lines[i + 1]
        
        # Check for horizontal line (rule)
        if current_line.get('text', '').strip() in ['_' * 10, '-' * 10]:
            separator_detected = True
            break
        
        # Check for large spacing before footnotes
        spacing = next_line['box']['t'] - current_line['box']['b']
        line_height = current_line['box']['b'] - current_line['box']['t']
        
        if spacing > line_height * 3:  # 3x normal spacing
            # Check if next line starts footnote region
            next_y = next_line['box']['t']
            if next_y > footnote_zone_start:
                separator_detected = True
                break
    
    # Step 4: Extract footnote markers
    marker_patterns = [
        r'^(\d+)\.',  # 1. , 2. , etc.
        r'^\[(\d+)\]',  # [1], [2], etc.
        r'^(\*+)',  # *, **, etc.
        r'^([†‡§¶])',  # Symbols
        r'^([¹²³⁴⁵⁶⁷⁸⁹⁰]+)',  # Superscript numbers
    ]
    
    footnotes = []
    for line in footnote_candidates:
        text = line.get('text', '').strip()
        
        for pattern in marker_patterns:
            match = re.match(pattern, text)
            if match:
                marker = match.group(1)
                footnote_text = text[match.end():].strip()
                
                footnotes.append({
                    'marker': marker,
                    'text': footnote_text,
                    'full_text': text,
                    'line_id': line.get('id'),
                    'box': line.get('box'),
                    'page': line.get('page'),
                    'font_size': statistics.mean([w.get('font_size', 12) 
                                                 for w in line.get('words', [])])
                })
                break
    
    # Step 5: Find references in body text
    references = []
    body_lines = [line for line in text_lines if line not in footnote_candidates]
    
    for line in body_lines:
        text = line.get('text', '')
        
        # Search for superscript markers or bracketed numbers
        ref_patterns = [
            r'(\d+)',  # Could be superscript (need font analysis)
            r'\[(\d+)\]',
            r'(\*+)',
            r'([†‡§¶])',
            r'([¹²³⁴⁵⁶⁷⁸⁹⁰]+)',
        ]
        
        for pattern in ref_patterns:
            for match in re.finditer(pattern, text):
                marker = match.group(1)
                
                # Check if this marker has a corresponding footnote
                matching_footnote = next((f for f in footnotes 
                                         if f['marker'] == marker), None)
                
                if matching_footnote:
                    references.append({
                        'marker': marker,
                        'line_id': line.get('id'),
                        'footnote_id': matching_footnote['line_id'],
                        'position': match.start(),
                        'page': line.get('page')
                    })
    
    return {
        'footnotes': footnotes,
        'references': references,
        'separator_detected': separator_detected,
        'body_font_size': median_font,
        'footnote_threshold': footnote_threshold
    }
```

#### 4.2 Footnote Linking in Chunks

```python
# In anchoring_service.py

def anchor_chunks_to_pdf(result_chunks, structured):
    """Enhanced with footnote linking"""
    
    # ... existing code ...
    
    # NEW: Extract footnote information
    from core.layout_analyzer import LayoutAnalyzer
    analyzer = LayoutAnalyzer()
    
    # Group structured data by page
    pages = {}
    for elem in structured:
        page = elem.get('page', 1)
        pages.setdefault(page, []).append(elem)
    
    # Detect footnotes for each page
    all_footnotes = {}
    for page_no, elements in pages.items():
        text_lines = [e for e in elements if e.get('type') == 'text']
        page_height = elements[0].get('page_height', 792) if elements else 792
        
        footnote_info = analyzer.detect_footnotes(text_lines, page_height)
        all_footnotes[page_no] = footnote_info
    
    # Link footnotes to chunks
    for chunk in result_chunks:
        chunk_text = chunk.get('text', '')
        chunk_page = chunk.get('metadata', {}).get('page', 1)
        
        if chunk_page not in all_footnotes:
            continue
        
        page_footnotes = all_footnotes[chunk_page]
        
        # Check if chunk contains footnote references
        linked_footnotes = []
        for ref in page_footnotes['references']:
            # Check if reference line is part of this chunk
            if ref['line_id'] in chunk.get('metadata', {}).get('line_ids', []):
                # Find corresponding footnote
                footnote = next((f for f in page_footnotes['footnotes']
                               if f['line_id'] == ref['footnote_id']), None)
                
                if footnote:
                    linked_footnotes.append({
                        'marker': ref['marker'],
                        'text': footnote['text'],
                        'page': footnote['page']
                    })
        
        # Add to chunk metadata
        if linked_footnotes:
            chunk['metadata']['footnotes'] = linked_footnotes
            chunk['metadata']['has_footnotes'] = True
```

---

## Testing Strategy

### Unit Tests

1. **Column Detection Tests** (`test_layout_analyzer.py`)
   ```python
   def test_single_column_detection():
       """Test single column layout"""
       pass
   
   def test_two_column_equal_width():
       """Test equal-width two-column layout"""
       pass
   
   def test_three_column_newsletter():
       """Test three-column newsletter layout"""
       pass
   
   def test_asymmetric_columns():
       """Test main + sidebar layout"""
       pass
   
   def test_mixed_column_layout():
       """Test variable column layout"""
       pass
   ```

2. **Header/Footer Tests**
   ```python
   def test_header_detection_by_position():
       """Test position-based header detection"""
       pass
   
   def test_header_detection_by_repetition():
       """Test repetition-based header detection"""
       pass
   
   def test_page_number_patterns():
       """Test various page number formats"""
       pass
   
   def test_footer_with_copyright():
       """Test footer with copyright notice"""
       pass
   ```

3. **Footnote Tests**
   ```python
   def test_footnote_detection_numeric():
       """Test numeric footnote markers (1, 2, 3)"""
       pass
   
   def test_footnote_detection_symbols():
       """Test symbol footnote markers (*, †, ‡)"""
       pass
   
   def test_footnote_reference_linking():
       """Test linking footnotes to references"""
       pass
   
   def test_superscript_detection():
       """Test superscript number detection"""
       pass
   ```

### Integration Tests

1. **End-to-End Processing**
   - Upload multi-column PDF
   - Verify correct reading order
   - Check header/footer exclusion
   - Validate footnote linking

2. **Real-World Documents**
   - Academic papers (2-column with footnotes)
   - Magazines (3-column with sidebars)
   - Technical manuals (headers/footers with page numbers)
   - Legal documents (extensive footnotes)

### Test Data

Create/collect test PDFs:
1. `test_two_column_academic.pdf` - Standard academic paper
2. `test_three_column_newsletter.pdf` - Newsletter layout
3. `test_mixed_layout.pdf` - Variable column layout
4. `test_headers_footers.pdf` - Document with headers/footers
5. `test_footnotes_numeric.pdf` - Numeric footnotes
6. `test_footnotes_symbols.pdf` - Symbol footnotes
7. `test_complex_layout.pdf` - Combined: multi-column + headers + footnotes

---

## Implementation Phases & Timeline

### Phase 1: Layout Analysis Foundation (Week 1-2)
- [ ] Create `layout_analyzer.py` module
- [ ] Implement basic column detection
- [ ] Add unit tests for column detection
- [ ] Integrate with `pdf_extractor.py`
- [ ] Test with 2-column documents

### Phase 2: Reading Order & Multi-Column (Week 2-3)
- [ ] Implement reading order calculation
- [ ] Handle spanning elements (headers across columns)
- [ ] Add support for 3+ columns
- [ ] Test with varied layouts
- [ ] Integrate with simplified view generation

### Phase 3: Header/Footer Detection (Week 3-4)
- [ ] Implement position-based detection
- [ ] Add repetition analysis
- [ ] Implement pattern matching (page numbers, dates)
- [ ] Filter headers/footers from output
- [ ] Test with various document types

### Phase 4: Footnote System (Week 4-5)
- [ ] Implement footnote detection
- [ ] Add marker recognition (numeric, symbols)
- [ ] Build reference linking system
- [ ] Integrate with chunking service
- [ ] Add footnote metadata to chunks

### Phase 5: Testing & Refinement (Week 5-6)
- [ ] Comprehensive unit testing
- [ ] Integration testing
- [ ] Real-world document testing
- [ ] Performance optimization
- [ ] Documentation updates

### Phase 6: Deployment & Monitoring (Week 6)
- [ ] Deploy to production
- [ ] Monitor processing accuracy
- [ ] Collect user feedback
- [ ] Bug fixes and adjustments

---

## Configuration & Tuning

### Configurable Parameters

Add to `config.py`:
```python
class Config:
    # ... existing config ...
    
    # Layout Analysis
    ENABLE_LAYOUT_ANALYSIS = True
    COLUMN_DETECTION_THRESHOLD = 0.15  # Min distance ratio to split columns
    HEADER_ZONE_RATIO = 0.15  # Top 15% for headers
    FOOTER_ZONE_RATIO = 0.85  # Bottom 15% for footers
    
    # Header/Footer Detection
    REPETITION_THRESHOLD = 3  # Min pages to consider repeated
    ENABLE_HEADER_DETECTION = True
    ENABLE_FOOTER_DETECTION = True
    
    # Footnote Detection
    ENABLE_FOOTNOTE_DETECTION = True
    FOOTNOTE_SIZE_RATIO = 0.85  # 85% of body font
    FOOTNOTE_ZONE_RATIO = 0.70  # Bottom 30% for footnotes
    FOOTNOTE_MARKER_PATTERNS = [
        r'^(\d+)\.',
        r'^\[(\d+)\]',
        r'^(\*+)',
        # ... configurable patterns
    ]
```

### Performance Considerations

1. **Caching Layout Analysis**
   - Cache column detection per page
   - Cache header/footer patterns per document
   - Store in session or database

2. **Parallel Processing**
   - Process pages in parallel for layout analysis
   - Parallelize column detection across pages

3. **Optimization Targets**
   - Column detection: < 50ms per page
   - Header/footer detection: < 100ms per document
   - Footnote detection: < 30ms per page

---

## API Enhancements

### New Endpoints

1. **Layout Analysis Endpoint**
```python
@router.post("/pdf/analyze-layout")
async def analyze_layout(file: UploadFile = File(...)):
    """
    Analyze PDF layout without full processing
    Returns layout information for preview
    """
    pass
```

2. **Layout Preview Endpoint**
```python
@router.get("/pdf/layout-preview/{doc_id}")
async def get_layout_preview(doc_id: str):
    """
    Get layout visualization data
    Returns column boundaries, regions, reading order
    """
    pass
```

### Enhanced Response Schema

```python
{
    "chunks": [...],
    "layout_info": {
        "pages": [
            {
                "page_number": 1,
                "columns": [
                    {"index": 0, "left": 72, "right": 300},
                    {"index": 1, "left": 312, "right": 540}
                ],
                "regions": [
                    {"type": "header", "box": {...}, "content": "..."},
                    {"type": "body", "box": {...}},
                    {"type": "footer", "box": {...}, "content": "..."}
                ],
                "footnotes": [
                    {"marker": "1", "text": "...", "references": ["chunk-id-1"]}
                ]
            }
        ],
        "reading_order_preserved": true,
        "multi_column": true,
        "has_headers": true,
        "has_footers": true,
        "has_footnotes": true
    }
}
```

---

## Frontend Enhancements

### Visualization Components

1. **Layout Overlay**
   - Display detected columns as vertical guides
   - Highlight headers/footers in different color
   - Show reading order with numbered arrows
   - Mark footnote references

2. **Layout Inspector**
   - Toggle column boundaries on/off
   - Show/hide headers and footers
   - Expand footnotes inline
   - Navigate by reading order

3. **Configuration Panel**
   - Enable/disable layout analysis
   - Adjust detection thresholds
   - Toggle header/footer filtering
   - Enable/disable footnote linking

---

## Success Metrics

### Accuracy Metrics

1. **Column Detection Accuracy**
   - Target: 95%+ correct column identification
   - Measure: Manual review of 100 test documents

2. **Reading Order Accuracy**
   - Target: 98%+ correct reading sequence
   - Measure: Compare to human-annotated order

3. **Header/Footer Detection**
   - Target: 90%+ precision, 95%+ recall
   - Measure: False positives vs. missed detections

4. **Footnote Linking**
   - Target: 85%+ correct marker → footnote links
   - Measure: Validation against ground truth

### Performance Metrics

1. **Processing Time**
   - Target: < 20% overhead vs. current system
   - Measure: Average processing time per page

2. **Memory Usage**
   - Target: < 50MB additional memory per document
   - Measure: Peak memory during processing

3. **User Satisfaction**
   - Target: 80%+ users report improved accuracy
   - Measure: User feedback surveys

---

## Risk Mitigation

### Potential Issues & Solutions

1. **False Column Detection**
   - **Risk:** Indented lists mistaken for columns
   - **Solution:** Require consistent pattern across page; minimum column width
   - **Fallback:** Allow manual column specification

2. **Header/Footer False Positives**
   - **Risk:** Body content at margins detected as header/footer
   - **Solution:** Require repetition across multiple pages; add confidence scoring
   - **Fallback:** User can mark exceptions

3. **Footnote Marker Ambiguity**
   - **Risk:** Numbers in body text mistaken for footnote markers
   - **Solution:** Require small font + bottom position + matching marker in footnotes
   - **Fallback:** Manual footnote annotation

4. **Performance Degradation**
   - **Risk:** Layout analysis adds significant processing time
   - **Solution:** Optimize algorithms; cache results; parallel processing
   - **Fallback:** Make layout analysis optional (config flag)

---

## Future Enhancements

### Phase 2 (Post-MVP)

1. **Advanced Layout Types**
   - Text boxes and callouts
   - Pull quotes
   - Sidebars with different styling
   - Irregular layouts

2. **Enhanced Footnote Features**
   - Endnotes (footnotes at document end)
   - Multi-page footnotes
   - Nested footnotes
   - Citation linking

3. **Machine Learning Integration**
   - Train layout detection model
   - Learn column patterns from examples
   - Auto-improve with user corrections

4. **Interactive Layout Editor**
   - Visual column boundary adjustment
   - Manual region marking
   - Reading order editor
   - Footnote relationship editor

---

## Conclusion

This implementation plan provides a comprehensive roadmap for adding advanced chunking capabilities to the Knowledge Base system. The phased approach ensures:

1. **Incremental Value** - Each phase delivers standalone improvements
2. **Risk Management** - Early testing identifies issues before full deployment
3. **Performance Balance** - Optimization built into design from start
4. **User Impact** - Measurable improvements in accuracy and usability

**Estimated Total Timeline:** 6 weeks
**Estimated Effort:** 1 full-time developer
**Expected Impact:** 30-50% improvement in chunk accuracy for complex layouts

---

## Appendix

### A. Reference Materials

- PDFPlumber Documentation: https://github.com/jsvine/pdfplumber
- PyMuPDF Documentation: https://pymupdf.readthedocs.io/
- Layout Analysis Papers:
  - "Page Segmentation of Historical Document Images with Convolutional Autoencoders"
  - "Document Structure Analysis Algorithms: A Literature Review"

### B. Code Examples

See implementation details in:
- `backend/core/layout_analyzer.py` (to be created)
- `backend/core/pdf_extractor.py` (modifications)
- `backend/services/chunking_service.py` (enhancements)

### C. Test Cases

Full test suite specifications in:
- `backend/tests/test_layout_analyzer.py`
- `backend/tests/test_integration_advanced_chunking.py`
