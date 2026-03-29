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


MAX_BODY_LENGTH = 2000

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
]

# A URL whose total length exceeds this threshold is considered a tracking URL
_TRACKING_URL_MIN_LEN = 120


def clean_plain_text_body(body: str) -> Dict[str, Any]:
    """
    Clean a plain-text email body:
      1. Replace tracking URLs (> 120 chars) with a short placeholder.
      2. Strip common footer / boilerplate blocks.
      3. Collapse excessive whitespace.
      4. Cap total length at MAX_BODY_LENGTH.

    Returns a dict with the same shape as clean_email_body() so the
    caller can handle both paths uniformly.
    """
    if not body:
        return {"clean_text": "", "links": [], "images": [], "has_tables": False}

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

        # Once we hit a footer marker, discard the rest
        if not hit_footer:
            for pat in _FOOTER_PATTERNS:
                if pat.search(stripped):
                    hit_footer = True
                    break
        if hit_footer:
            continue

        line = re.sub(r"https?://\S+", _shorten_url, line)

        cleaned_lines.append(line)

    text = "\n".join(cleaned_lines)

    # Collapse runs of blank lines / whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = text.strip()

    # Truncate
    if len(text) > MAX_BODY_LENGTH:
        text = text[:MAX_BODY_LENGTH] + "\n...[truncated]"

    return {
        "clean_text": text,
        "links": extracted_links,
        "images": [],
        "has_tables": False,
    }


def extract_action_items(clean_text: str) -> List[str]:
    """
    Extract potential action items from email text.
    
    Args:
        clean_text: Clean email body text
        
    Returns:
        List of potential action items
    """
    if not clean_text:
        return []
    
    text_lower = clean_text.lower()
    action_items = []
    
    # Common action phrases
    action_patterns = [
        r'please (.*?)[\.\n]',
        r'you (?:need to|should|must) (.*?)[\.\n]',
        r'(?:action required|urgent|important):? (.*?)[\.\n]',
        r'reminder:? (.*?)[\.\n]',
        r'due (?:date|by):? (.*?)[\.\n]',
    ]
    
    for pattern in action_patterns:
        matches = re.finditer(pattern, text_lower, re.IGNORECASE)
        for match in matches:
            action = match.group(1).strip()
            if len(action) > 10 and len(action) < 200:  # Reasonable length
                action_items.append(action)
    
    return action_items[:5]  # Return top 5


def format_email_object(email_obj: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enhance email object with formatted body and extracted metadata.
    This is called by gmail-agent before returning emails.
    
    Both HTML and plain-text emails are cleaned.  The original raw body
    is preserved in ``body_full`` so that forward / reply workflows can
    use the unmodified content when needed.
    
    Fields added for every email:
        - body_full:  Original unmodified body (HTML or plain text)
        - body_clean: Clean text version
        - body_links: Extracted URLs
        - action_items: Potential action items

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

    # Always keep the raw original for forward / reply
    email_obj['body_full'] = original_body
    
    # Check if body is HTML (contains tags)
    is_html = bool(re.search(r'<[^>]+>', original_body))
    
    if is_html:
        formatted = clean_email_body(original_body)
        
        email_obj['body_html'] = original_body
        email_obj['body'] = formatted['clean_text']
        email_obj['body_clean'] = formatted['clean_text']
        email_obj['body_links'] = formatted['links']
        email_obj['body_images'] = formatted['images']
        email_obj['body_has_tables'] = formatted['has_tables']
        email_obj['action_items'] = extract_action_items(formatted['clean_text'])
    else:
        formatted = clean_plain_text_body(original_body)

        email_obj['body'] = formatted['clean_text']
        email_obj['body_clean'] = formatted['clean_text']
        email_obj['body_links'] = formatted['links']
        email_obj['action_items'] = extract_action_items(formatted['clean_text'])
    
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
