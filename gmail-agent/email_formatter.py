"""
Email Body Formatter for Gmail Agent
Automatically cleans HTML email bodies into human-readable text.
This runs on the gmail-agent side, so supervisor receives clean data.
"""

import re
from html.parser import HTMLParser
from typing import Dict, List, Any


class EmailHTMLParser(HTMLParser):
    """Custom HTML parser that extracts clean text from email HTML"""
    
    def __init__(self):
        super().__init__()
        self.text_parts = []
        self.current_tag = None
        self.skip_tags = {'style', 'script', 'head', 'meta'}
        self.in_skip_tag = False
        self.links = []
        self.images = []
        
    def handle_starttag(self, tag, attrs):
        """Handle opening HTML tags"""
        self.current_tag = tag
        
        if tag in self.skip_tags:
            self.in_skip_tag = True
            return
            
        # Extract links
        if tag == 'a':
            for attr, value in attrs:
                if attr == 'href':
                    self.links.append(value)
        
        # Extract images
        if tag == 'img':
            img_data = {}
            for attr, value in attrs:
                if attr == 'src':
                    img_data['src'] = value
                elif attr == 'alt':
                    img_data['alt'] = value
            if img_data:
                self.images.append(img_data)
        
        # Add formatting hints
        if tag == 'br':
            self.text_parts.append('\n')
        elif tag == 'p':
            self.text_parts.append('\n\n')
        elif tag == 'div':
            self.text_parts.append('\n')
        elif tag in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            self.text_parts.append('\n\n')
        elif tag == 'tr':
            self.text_parts.append('\n')
        elif tag == 'td':
            self.text_parts.append(' ')
            
    def handle_endtag(self, tag):
        """Handle closing HTML tags"""
        if tag in self.skip_tags:
            self.in_skip_tag = False
            
        if tag in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            self.text_parts.append('\n')
        elif tag == 'p':
            self.text_parts.append('\n')
            
    def handle_data(self, data):
        """Handle text content"""
        if not self.in_skip_tag:
            # Clean up whitespace but preserve intentional spacing
            cleaned = data.strip()
            if cleaned:
                self.text_parts.append(cleaned)
                
    def get_text(self) -> str:
        """Get cleaned text output"""
        text = ' '.join(self.text_parts)
        # Clean up multiple newlines and spaces
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' {2,}', ' ', text)
        # Clean up lines that are only whitespace
        text = re.sub(r'\n\s*\n', '\n\n', text)
        return text.strip()


def clean_email_body(html_body: str) -> Dict[str, Any]:
    """
    Convert HTML email body to clean, readable text.
    
    Args:
        html_body: Raw HTML email body
        
    Returns:
        Dictionary containing:
            - clean_text: Human-readable text
            - links: List of URLs found
            - images: List of images found
            - has_tables: Whether email contains tables
    """
    if not html_body:
        return {
            "clean_text": "",
            "links": [],
            "images": [],
            "has_tables": False
        }
    
    # Parse HTML
    parser = EmailHTMLParser()
    try:
        parser.feed(html_body)
    except Exception as e:
        # Fallback: strip all HTML tags
        clean_text = re.sub(r'<[^>]+>', ' ', html_body)
        clean_text = re.sub(r'\s+', ' ', clean_text).strip()
        return {
            "clean_text": clean_text,
            "links": [],
            "images": [],
            "has_tables": False,
            "parse_error": str(e)
        }
    
    clean_text = parser.get_text()
    has_tables = '<table' in html_body.lower()
    
    return {
        "clean_text": clean_text,
        "links": parser.links,
        "images": parser.images,
        "has_tables": has_tables
    }


MAX_BODY_LENGTH = 4000

_INVISIBLE_CHARS = re.compile(r'[\u200a\u200b\u200c\u200d\u200e\u200f\u2028\u2029\ufeff\u00ad]')

_ALT_TEXT_ARTIFACT = re.compile(r'^"[^"]*"\s*"?[^"]*"?\s*\[link\]\s*$')

# Footer patterns that unambiguously mark the start of the boilerplate block.
# Separators (--- / ===) are intentionally excluded because they also appear
# *between* content items (e.g. between job listings).
_FOOTER_PATTERNS = [
    re.compile(r"^\s*unsubscribe", re.IGNORECASE),
    re.compile(r"^\s*manage your .*(alert|notification|subscription|preference)", re.IGNORECASE),
    re.compile(r"^\s*this email was intended for", re.IGNORECASE),
    re.compile(r"^\s*you are receiving .* email", re.IGNORECASE),
    re.compile(r"^\s*learn why we included this", re.IGNORECASE),
    re.compile(r"^\s*©\s*\d{4}", re.IGNORECASE),
    re.compile(r"^\s*\(c\)\s*\d{4}", re.IGNORECASE),
    re.compile(r"^\s*linkedin corporation", re.IGNORECASE),
    re.compile(r"^\s*google llc", re.IGNORECASE),
    re.compile(r"^\s*if you no longer wish", re.IGNORECASE),
    re.compile(r"^\s*to stop receiving", re.IGNORECASE),
    re.compile(r"^\s*powered by", re.IGNORECASE),
    re.compile(r"^\s*sent (by|from|via) .*(mailchimp|sendgrid|hubspot|constant contact)", re.IGNORECASE),
    re.compile(r"^\s*privacy policy", re.IGNORECASE),
    re.compile(r"^\s*\w[\w\s]*,\s*Inc\.", re.IGNORECASE),
]

# A URL whose total length exceeds this threshold is considered a tracking URL
_TRACKING_URL_MIN_LEN = 120


def clean_plain_text_body(body: str) -> Dict[str, Any]:
    """
    Clean a plain-text email body:
      1. Strip invisible Unicode characters (ZWNJ, hair-space, etc.).
      2. Replace tracking URLs (> 120 chars) with ``[link]``.
      3. Clean angle-bracket artifacts left after URL replacement.
      4. Strip image alt-text artifact lines.
      5. Collapse long separator lines (----…) to ``---``.
      6. Strip footer / boilerplate blocks (including social-media rows).
      7. Collapse excessive whitespace.
      8. Cap total length at MAX_BODY_LENGTH.

    Returns a dict with the same shape as clean_email_body() so the
    caller can handle both paths uniformly.
    """
    if not body:
        return {"clean_text": "", "links": [], "images": [], "has_tables": False}

    body = _INVISIBLE_CHARS.sub('', body)

    lines = body.splitlines()
    cleaned_lines: List[str] = []
    extracted_links: List[str] = []
    hit_footer = False

    def _shorten_url(m: re.Match) -> str:
        url = m.group(0)
        extracted_links.append(url)
        if len(url) > _TRACKING_URL_MIN_LEN:
            return "[link]"
        return url

    for line in lines:
        stripped = line.strip()

        if not hit_footer:
            for pat in _FOOTER_PATTERNS:
                if pat.search(stripped):
                    hit_footer = True
                    break
        if hit_footer:
            continue

        line = re.sub(r"https?://\S+", _shorten_url, line)

        # Fix angle-bracket artifacts: <[link]> or <[link] or [link]>
        line = line.replace('<[link]>', '[link]')
        line = line.replace('<[link]', '[link]')
        line = line.replace('[link]>', '[link]')

        # Collapse long separator lines (5+ dashes or equals) to ---
        line = re.sub(r'[-=]{5,}', '---', line)

        stripped_after = line.strip()

        # Drop image alt-text artifact lines: "GitHub" "GitHub" [link]
        if _ALT_TEXT_ARTIFACT.match(stripped_after):
            continue

        # Drop social-media footer rows (3+ [link] on one line)
        if stripped_after.count('[link]') >= 3:
            continue

        # Drop lines that became empty after cleaning
        if not stripped_after and cleaned_lines and not cleaned_lines[-1].strip():
            continue

        cleaned_lines.append(line)

    text = "\n".join(cleaned_lines)

    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = text.strip()

    if len(text) > MAX_BODY_LENGTH:
        text = text[:MAX_BODY_LENGTH] + "\n...[truncated]"

    return {
        "clean_text": text,
        "links": extracted_links,
        "images": [],
        "has_tables": False,
    }


def _is_real_html(body: str) -> bool:
    """
    Determine whether the body is genuine HTML vs plain text that happens
    to contain angle-bracket URLs like ``<https://example.com/...>``.

    Strategy: look for actual HTML structural tags (with or without attrs).
    Angle-bracket-wrapped URLs (common in plain-text emails from Gmail API)
    are NOT HTML.
    """
    _STRUCTURAL_TAGS = re.compile(
        r'<\s*/?\s*(?:html|head|body|div|span|p|br|table|tr|td|th|a|img|ul|ol|li|h[1-6]|style|script|meta|link|form|input|button|label|section|article|header|footer|nav|main)\b',
        re.IGNORECASE,
    )
    return bool(_STRUCTURAL_TAGS.search(body))


def format_email_object(email_obj: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enhance email object with formatted body and extracted metadata.
    This is called by gmail-agent before returning emails.

    Both HTML and plain-text emails are cleaned.  The original raw body
    is preserved in ``body_full`` so that forward / reply workflows can
    use the unmodified content when needed.

    Fields set for every email:
        - body:       Cleaned human-readable text (overwritten in place)
        - body_full:  Original unmodified body (HTML or plain text)
        - body_links: Extracted URLs

    HTML-only extras:
        - body_html:       Original HTML
        - body_images:     Extracted images
        - body_has_tables: Boolean

    Args:
        email_obj: Email dictionary with 'body' field

    Returns:
        Enhanced email object
    """
    if 'body' not in email_obj or not email_obj['body']:
        return email_obj

    original_body = email_obj['body']

    email_obj['body_full'] = original_body

    is_html = _is_real_html(original_body)

    if is_html:
        formatted = clean_email_body(original_body)

        email_obj['body_html'] = original_body
        email_obj['body'] = formatted['clean_text']
        email_obj['body_links'] = formatted['links']
        email_obj['body_images'] = formatted['images']
        email_obj['body_has_tables'] = formatted['has_tables']
    else:
        formatted = clean_plain_text_body(original_body)

        email_obj['body'] = formatted['clean_text']
        email_obj['body_links'] = formatted['links']

    return email_obj


def format_email_list(emails: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Format a list of email objects.
    
    Args:
        emails: List of email dictionaries
        
    Returns:
        List of formatted email dictionaries
    """
    return [format_email_object(email) for email in emails]
