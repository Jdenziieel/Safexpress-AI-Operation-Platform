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
    
    For HTML emails, adds:
        - body_clean: Clean text version
        - body_html: Original HTML (preserved)
        - body_links: Extracted links
        - body_images: Extracted images
        - body_has_tables: Boolean
        - action_items: Potential action items
    
    For plain text emails, leaves object unchanged (no extra fields).
    
    Args:
        email_obj: Email dictionary with 'body' field
        
    Returns:
        Enhanced email object (HTML) or unchanged object (plain text)
    """
    if 'body' not in email_obj or not email_obj['body']:
        return email_obj
    
    original_body = email_obj['body']
    
    # Check if body is HTML (contains tags)
    is_html = bool(re.search(r'<[^>]+>', original_body))
    
    if is_html:
        # HTML email: Format and add metadata fields
        formatted = clean_email_body(original_body)
        
        # Keep original HTML in body_html field
        email_obj['body_html'] = original_body
        
        # Replace body with clean text
        email_obj['body'] = formatted['clean_text']
        
        # Add metadata fields
        email_obj['body_clean'] = formatted['clean_text']
        email_obj['body_links'] = formatted['links']
        email_obj['body_images'] = formatted['images']
        email_obj['body_has_tables'] = formatted['has_tables']
        
        # Extract action items
        email_obj['action_items'] = extract_action_items(formatted['clean_text'])
    # else: Plain text email - return unchanged, no extra fields added
    
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
