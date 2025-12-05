"""Core PDF extraction functionality."""
import io
import statistics
import base64
import pdfplumber
import fitz


def lines_from_chars(page, line_tol=5, word_tol=None):
    """
    Group page.chars into lines; return list of line dicts with
    text, bbox, font_size, style, spacing metadata, and per-word font info.
    """
    chars = sorted(
        page.chars,
        key=lambda c: (round(c.get("top", 0), 1), round(c.get("x0", 0), 1))
    )
    if not chars:
        return []
    
    # Calculate adaptive word tolerance if not provided
    if word_tol is None:
        font_sizes = [c.get("size", 12) for c in chars if c.get("size")]
        avg_font_size = statistics.median(font_sizes) if font_sizes else 12.0
        word_tol = avg_font_size * 0.4  # 40% of font size for word separation

    # --- group chars into lines
    lines = []
    current = [chars[0]]
    for ch in chars[1:]:
        if abs(ch.get("top", 0) - current[0].get("top", 0)) < line_tol:
            current.append(ch)
        else:
            lines.append(current)
            current = [ch]
    if current:
        lines.append(current)

    # --- build line objects
    line_objs = []
    prev_bottom = None

    # Get page number from page object for unique ID generation
    page_number = getattr(page, 'page_number', 1)

    for idx, ln in enumerate(lines):
        # Calculate line-specific word tolerance
        line_font_sizes = [c.get("size", 12) for c in ln if c.get("size")]
        line_avg_font = statistics.median(line_font_sizes) if line_font_sizes else 12.0
        line_word_tol = line_avg_font * 0.4  # Per-line adaptive tolerance

        # group chars into words within the line
        words = []
        current_word = [ln[0]]
        for ch in ln[1:]:
            prev = current_word[-1]
            gap = abs(ch.get("x0", 0) - prev.get("x1", 0))
            
            if gap > line_word_tol:
                words.append(current_word)
                current_word = [ch]
            else:
                current_word.append(ch)
        if current_word:
            words.append(current_word)

        word_objs = []
        for w in words:
            text = "".join(c.get("text", "") for c in w).strip()
            if not text:
                continue
            l = min(c.get("x0", 0) for c in w)
            t = min(c.get("top", 0) for c in w)
            r = max(c.get("x1", 0) for c in w)
            b = max(c.get("bottom", 0) for c in w)

            sizes = [float(c.get("size", 0)) for c in w if c.get("size") is not None]
            font_size = round(statistics.median(sizes), 2) if sizes else None

            fonts = [c.get("fontname", "") for c in w]
            bold = any("Bold" in f for f in fonts)
            italic = any("Italic" in f or "Oblique" in f for f in fonts)

            word_objs.append({
                "text": text,
                "box": {"l": l, "t": t, "r": r, "b": b},
                "font_size": font_size,
                "bold": bold,
                "italic": italic,
            })

        if not word_objs:
            continue

        l = min(w["box"]["l"] for w in word_objs)
        t = min(w["box"]["t"] for w in word_objs)
        r = max(w["box"]["r"] for w in word_objs)
        b = max(w["box"]["b"] for w in word_objs)

        # spacing metadata
        line_breaks_before = 0
        if prev_bottom is not None and (t - prev_bottom) > line_tol:
            line_breaks_before = 1
        prev_bottom = b

        # Generate unique line ID with page prefix
        unique_line_id = f"p{page_number}-ln-{idx}"

        line_objs.append({
            "id": unique_line_id,
            "type": "text",
            "text": " ".join(w["text"] for w in word_objs),
            "box": {"l": l, "t": t, "r": r, "b": b},
            "indent": l,
            "line_breaks_before": line_breaks_before,
            "line_breaks_after": 0,  # to be filled later
            "words": word_objs,
        })

    # --- fill line_breaks_after
    for i in range(len(line_objs) - 1):
        gap = line_objs[i+1]["box"]["t"] - line_objs[i]["box"]["b"]
        if gap > line_tol:
            line_objs[i]["line_breaks_after"] = 1

    return line_objs


def extract_tables_with_bbox(page):
    """
    Use page.find_tables() to get table objects and their bbox.
    Returns list of dicts: { type: 'table', 'table': rows, 'box': {l,t,r,b} }
    """
    tables = []
    found = page.find_tables()

    # Get page number for unique ID generation
    page_number = getattr(page, 'page_number', 1)

    for table_idx, t in enumerate(found):
        bbox = getattr(t, "bbox", None) or getattr(t, "_bbox", None)
        if bbox and len(bbox) == 4:
            l, ttop, r, btm = bbox
        else:
            # fallback: compute bbox from extracted table rows if possible, else skip
            rows = t.extract()
            if rows:
                try:
                    # collect text tokens, find their bounding boxes via page.extract_words
                    words = page.extract_words()
                    # naive fallback -> whole page dims
                    l, ttop, r, btm = 0, 0, page.width, page.height
                except Exception:
                    l, ttop, r, btm = 0, 0, page.width, page.height
            else:
                l, ttop, r, btm = 0, 0, page.width, page.height

        table_rows = t.extract()
        unique_table_id = f"p{page_number}-tbl-{table_idx}"

        tables.append({
            "id": unique_table_id,
            "type": "table",
            "table": table_rows,
            "box": {"l": l, "t": ttop, "r": r, "b": btm},
        })
    return tables


def line_intersects_bbox(line, bbox, margin=1.0):
    """
    Return True if line's vertical midpoint is inside bbox vertically and horizontally overlaps.
    margin: small tolerance
    """
    line_mid = (line["box"]["t"] + line["box"]["b"]) / 2.0
    tb_top, tb_bottom = bbox["t"] - margin, bbox["b"] + margin
    horiz_overlap = not (line["box"]["r"] < bbox["l"] or line["box"]["l"] > bbox["r"])
    return (tb_top <= line_mid <= tb_bottom) and horiz_overlap


def extract_images_with_bbox_pymupdf(file_bytes, page_number):
    """
    Uses xref placement rects to get true positions of images on the page.
    Returns list of dicts with unique IDs.
    """
    images = []
    with fitz.open(stream=file_bytes, filetype="pdf") as doc:
        page = doc[page_number]
        xref_rows = page.get_images(full=True)
        if not xref_rows:
            return images

        for img_index, row in enumerate(xref_rows):
            xref = row[0]
            rects = page.get_image_rects(xref)  # may return multiple placements
            try:
                pix = fitz.Pixmap(doc, xref)
                if pix.n > 4:  # convert CMYK/others to RGB
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                img_b64 = base64.b64encode(pix.tobytes("png")).decode("utf-8")
            except Exception as e:
                print(f"[WARN] xref={xref} pixmap failed: {e}")
                continue

            for placement_idx, rect in enumerate(rects):
                l, t, r, b = rect.x0, rect.y0, rect.x1, rect.y1
                unique_image_id = f"p{page_number+1}-img-{img_index}-{placement_idx}"
                images.append({
                    "id": unique_image_id,
                    "type": "image",
                    "subtype": "embedded",
                    "box": {"l": l, "t": t, "r": r, "b": b},
                    "page": page_number + 1,
                    "image_b64": img_b64,
                })
    return images


def assemble_elements(file_bytes, page, page_number):
    """
    Build ordered elements for the page:
    - get text lines (with font/style/spacing metadata)
    - get tables (with bbox)
    - get images (with bbox/base64)
    - remove lines that overlap table bboxes
    - combine into one list sorted by vertical position
    """
    text_lines = lines_from_chars(page)  # enriched with style + spacing + word-level info
    tables = extract_tables_with_bbox(page)
    images = extract_images_with_bbox_pymupdf(file_bytes, page_number)
    
    # --- Filter out text lines that overlap with any table bbox
    filtered_lines = []
    for ln in text_lines:
        in_any_table = any(line_intersects_bbox(ln, tb["box"]) for tb in tables)
        if not in_any_table:
            filtered_lines.append(ln)

    # --- Merge all elements into a unified list
    elements = []
    for ln in filtered_lines:
        elements.append({
            **ln,  # contains line-level text, box, spacing, and word-level list
            "page": page_number + 1,
            "top": ln["box"]["t"],
        })
    for tb in tables:
        elements.append({
            **tb,
            "page": page_number + 1,
            "top": tb["box"]["t"],
        })
    for im in images:
        elements.append({
            **im,
            "page": page_number + 1,
            "top": im["box"]["t"],
        })

    # --- Sort by top coordinate, fallback to left (chronological order)
    elements.sort(key=lambda e: (e["top"], e["box"].get("l", 0)))

    return elements


def build_simplified_view_from_elements(elements, gap_multiplier=1.5):
    """
    Build a simplified string preserving structure:
    - Preserve explicit line breaks (line_breaks_before/after) from extraction
    - Fallback to gap-based blank lines when explicit counts aren't present
    - Include a page header once per page
    - Place images inline at their positions with bbox info
    - Use inline markers for font size, bold, italic
    """
    lines_out = []

    # Group elements by page
    pages = {}
    for el in elements:
        page_no = el.get("page", 1)
        pages.setdefault(page_no, []).append(el)

    for page_no in sorted(pages.keys()):
        page_elems = pages[page_no]
        # Sort by visual order
        page_elems.sort(key=lambda e: (e.get("top", e["box"]["t"]), e["box"].get("l", 0)))

        # Median line height per page (gap fallback)
        heights = [
            (el["box"]["b"] - el["box"]["t"])
            for el in page_elems
            if el.get("type") == "text" and "box" in el
        ]
        median_height = statistics.median(heights) if heights else 12.0
        threshold = median_height * gap_multiplier

        # Page header (once)
        lines_out.append(f"[PAGE={page_no}]")

        prev_bottom = None
        active_size = None  # track active font size block

        for el in page_elems:
            top = el["box"]["t"]
            bottom = el["box"]["b"]

            # Explicit breaks BEFORE, else gap fallback
            lb_before = int(el.get("line_breaks_before", 0) or 0)
            if lb_before > 0:
                lines_out.extend([""] * lb_before)
            else:
                if prev_bottom is not None:
                    gap = top - prev_bottom
                    if gap > threshold:
                        lines_out.append("")

            if el["type"] == "text":
                words_out = []

                # Compute line font size (median of words)
                word_sizes = [w.get("font_size") for w in el.get("words", []) if w.get("font_size")]
                line_size = statistics.median(word_sizes) if word_sizes else None

                # Emit size tag when size changes
                if line_size and line_size != active_size:
                    if active_size:
                        words_out.append("</s>")
                    words_out.append(f"<s={int(line_size)}>")
                    active_size = line_size

                # Render words with style markers
                for w in el.get("words", []):
                    text = w.get("text", "")
                    bold = w.get("bold", False)
                    italic = w.get("italic", False)

                    if bold and italic:
                        words_out.append(f"*_ {text} _*")
                    elif bold:
                        words_out.append(f"*{text}*")
                    elif italic:
                        words_out.append(f"_{text}_")
                    else:
                        words_out.append(text)

                # Do not strip to preserve trailing spaces if present
                line_str = " ".join(words_out)
                lines_out.append(line_str)
                prev_bottom = bottom

            elif el["type"] == "table":
                lines_out.append("[TABLE]")
                for row in el.get("table", []):
                    lines_out.append(" | ".join(str(cell) for cell in row))
                lines_out.append("[/TABLE]")
                prev_bottom = bottom

            elif el["type"] == "image":
                bx = el.get("box", {})
                lines_out.append(
                    f"[IMAGE page={page_no} l={bx.get('l', 0):.1f} t={bx.get('t', 0):.1f} "
                    f"r={bx.get('r', 0):.1f} b={bx.get('b', 0):.1f}]"
                )
                prev_bottom = bottom

            # Explicit breaks AFTER
            lb_after = int(el.get("line_breaks_after", 0) or 0)
            if lb_after > 0:
                lines_out.extend([""] * lb_after)

        # Close active size at end of page
        if active_size:
            lines_out.append("</s>")
            active_size = None

        # Page separator
        lines_out.append("")

    # Trim trailing blanks
    while lines_out and lines_out[-1] == "":
        lines_out.pop()

    return "\n".join(lines_out)
