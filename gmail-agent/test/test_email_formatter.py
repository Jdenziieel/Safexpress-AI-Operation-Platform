"""
Unit tests for email formatter
"""

import pytest
from email_formatter import (
    EmailHTMLParser,
    clean_email_body,
    extract_action_items,
    format_email_object,
    format_email_list
)


class TestEmailHTMLParser:
    """Tests for EmailHTMLParser class"""
    
    def test_parse_simple_html(self):
        """Test parsing simple HTML"""
        html = "<p>Hello <strong>world</strong>!</p>"
        parser = EmailHTMLParser()
        parser.feed(html)
        text = parser.get_text()
        
        assert "Hello" in text
        assert "world" in text
    
    def test_parse_with_links(self):
        """Test parsing HTML with links"""
        html = '<p>Visit <a href="https://example.com">our site</a></p>'
        parser = EmailHTMLParser()
        parser.feed(html)
        text = parser.get_text()
        
        assert "Visit" in text
        assert "our site" in text
        assert len(parser.links) == 1
        assert parser.links[0] == "https://example.com"
    
    def test_parse_with_images(self):
        """Test parsing HTML with images"""
        html = '<img src="https://example.com/image.jpg" alt="Test Image">'
        parser = EmailHTMLParser()
        parser.feed(html)
        
        assert len(parser.images) == 1
        assert parser.images[0]['src'] == "https://example.com/image.jpg"
        assert parser.images[0]['alt'] == "Test Image"
    
    def test_skip_script_tags(self):
        """Test that script tags are skipped"""
        html = '<p>Hello</p><script>alert("bad")</script><p>World</p>'
        parser = EmailHTMLParser()
        parser.feed(html)
        text = parser.get_text()
        
        assert "Hello" in text
        assert "World" in text
        assert "alert" not in text
    
    def test_skip_style_tags(self):
        """Test that style tags are skipped"""
        html = '<p>Hello</p><style>.test{color:red}</style><p>World</p>'
        parser = EmailHTMLParser()
        parser.feed(html)
        text = parser.get_text()
        
        assert "Hello" in text
        assert "World" in text
        assert "color" not in text
    
    def test_preserve_line_breaks(self):
        """Test that line breaks are preserved"""
        html = '<p>Line 1</p><br><p>Line 2</p>'
        parser = EmailHTMLParser()
        parser.feed(html)
        text = parser.get_text()
        
        assert "Line 1" in text
        assert "Line 2" in text
        assert "\n" in text
    
    def test_handle_tables(self):
        """Test parsing tables"""
        html = '''
        <table>
            <tr>
                <td>Cell 1</td>
                <td>Cell 2</td>
            </tr>
            <tr>
                <td>Cell 3</td>
                <td>Cell 4</td>
            </tr>
        </table>
        '''
        parser = EmailHTMLParser()
        parser.feed(html)
        text = parser.get_text()
        
        assert "Cell 1" in text
        assert "Cell 2" in text
        assert "Cell 3" in text
        assert "Cell 4" in text
    
    def test_clean_multiple_whitespace(self):
        """Test cleaning of multiple whitespace"""
        html = '<p>Hello     world</p>'
        parser = EmailHTMLParser()
        parser.feed(html)
        text = parser.get_text()
        
        assert "Hello world" in text
        assert "     " not in text


class TestCleanEmailBody:
    """Tests for clean_email_body function"""
    
    def test_clean_simple_html(self):
        """Test cleaning simple HTML email"""
        html = "<p>Hello world!</p>"
        result = clean_email_body(html)
        
        assert result['clean_text'] == "Hello world!"
        assert result['links'] == []
        assert result['images'] == []
        assert result['has_tables'] is False
    
    def test_clean_with_links(self):
        """Test cleaning HTML with links"""
        html = '<p>Visit <a href="https://example.com">our site</a></p>'
        result = clean_email_body(html)
        
        assert "Visit" in result['clean_text']
        assert "our site" in result['clean_text']
        assert len(result['links']) == 1
        assert result['links'][0] == "https://example.com"
    
    def test_clean_with_images(self):
        """Test cleaning HTML with images"""
        html = '<p>Check this out:</p><img src="https://example.com/image.jpg" alt="Test">'
        result = clean_email_body(html)
        
        assert len(result['images']) == 1
        assert result['images'][0]['src'] == "https://example.com/image.jpg"
    
    def test_detect_tables(self):
        """Test table detection"""
        html = '<table><tr><td>Cell</td></tr></table>'
        result = clean_email_body(html)
        
        assert result['has_tables'] is True
    
    def test_empty_html(self):
        """Test with empty HTML"""
        result = clean_email_body("")
        
        assert result['clean_text'] == ""
        assert result['links'] == []
        assert result['images'] == []
    
    def test_malformed_html(self):
        """Test with malformed HTML"""
        html = '<p>Hello <b>world</p>'  # Missing closing </b>
        result = clean_email_body(html)
        
        # Should still extract text
        assert "Hello" in result['clean_text']
        assert "world" in result['clean_text']
    
    def test_nested_elements(self):
        """Test with nested HTML elements"""
        html = '<div><p>Outer <span>Inner <strong>Bold</strong></span></p></div>'
        result = clean_email_body(html)
        
        assert "Outer" in result['clean_text']
        assert "Inner" in result['clean_text']
        assert "Bold" in result['clean_text']
    
    def test_multiple_links(self):
        """Test with multiple links"""
        html = '''
        <p>Visit <a href="https://site1.com">site 1</a> and 
        <a href="https://site2.com">site 2</a></p>
        '''
        result = clean_email_body(html)
        
        assert len(result['links']) == 2
        assert "https://site1.com" in result['links']
        assert "https://site2.com" in result['links']


class TestExtractActionItems:
    """Tests for extract_action_items function"""
    
    def test_extract_please_action(self):
        """Test extracting 'please' actions"""
        text = "Please review the document by Friday."
        actions = extract_action_items(text)
        
        assert len(actions) > 0
        assert any("review" in action.lower() for action in actions)
    
    def test_extract_need_to_action(self):
        """Test extracting 'need to' actions"""
        text = "You need to submit the report before noon."
        actions = extract_action_items(text)
        
        assert len(actions) > 0
        assert any("submit" in action.lower() for action in actions)
    
    def test_extract_urgent_action(self):
        """Test extracting urgent actions"""
        text = "URGENT: Complete the task immediately."
        actions = extract_action_items(text)
        
        assert len(actions) > 0
    
    def test_extract_reminder(self):
        """Test extracting reminders"""
        text = "Reminder: Meeting tomorrow at 10 AM."
        actions = extract_action_items(text)
        
        assert len(actions) > 0
    
    def test_extract_due_date(self):
        """Test extracting due dates"""
        text = "Due by: End of week."
        actions = extract_action_items(text)
        
        assert len(actions) > 0
    
    def test_no_actions(self):
        """Test with text containing no actions"""
        text = "This is just a casual email with no actions."
        actions = extract_action_items(text)
        
        assert len(actions) == 0
    
    def test_empty_text(self):
        """Test with empty text"""
        actions = extract_action_items("")
        
        assert actions == []
    
    def test_limit_action_count(self):
        """Test that action items are limited to 5"""
        text = """
        Please do task 1.
        Please do task 2.
        Please do task 3.
        Please do task 4.
        Please do task 5.
        Please do task 6.
        Please do task 7.
        """
        actions = extract_action_items(text)
        
        assert len(actions) <= 5


class TestFormatEmailObject:
    """Tests for format_email_object function"""
    
    def test_format_html_email(self):
        """Test formatting HTML email"""
        email = {
            "message_id": "msg123",
            "subject": "Test",
            "body": "<p>Hello <strong>world</strong>!</p>"
        }
        
        result = format_email_object(email)
        
        assert "body_html" in result
        assert "body_links" in result
        assert "body_images" in result
        assert "body_has_tables" in result
        
        # Original HTML preserved in body_html
        assert result['body_html'] == "<p>Hello <strong>world</strong>!</p>"
        
        # Clean text in body
        assert result['body'] == "Hello world!"
    
    def test_format_plain_text_email(self):
        """Test formatting plain text email"""
        email = {
            "message_id": "msg123",
            "subject": "Test",
            "body": "Hello world!"
        }
        
        result = format_email_object(email)
        
        assert "body_html" not in result
        assert "body_links" in result
        assert result['body'] == "Hello world!"
    
    def test_format_email_with_links(self):
        """Test formatting email with links"""
        email = {
            "message_id": "msg123",
            "body": '<p>Visit <a href="https://example.com">our site</a></p>'
        }
        
        result = format_email_object(email)
        
        assert len(result['body_links']) == 1
        assert "https://example.com" in result['body_links']
    
    def test_format_email_with_action_items(self):
        """Test formatting email with action items"""
        email = {
            "message_id": "msg123",
            "body": "<p>Please review the document by Friday.</p>"
        }
        
        result = format_email_object(email)
        
        assert 'action_items' in result
        assert len(result['action_items']) > 0
    
    def test_format_email_with_empty_body(self):
        """Test formatting email with empty body"""
        email = {
            "message_id": "msg123",
            "body": ""
        }
        
        result = format_email_object(email)
        
        assert result['message_id'] == "msg123"
        assert result['body'] == ""
    
    def test_format_email_without_body(self):
        """Test formatting email without body field"""
        email = {
            "message_id": "msg123",
            "subject": "Test"
        }
        
        result = format_email_object(email)
        
        assert result == email  # Should return unchanged
    
    def test_format_email_preserves_other_fields(self):
        """Test that other fields are preserved"""
        email = {
            "message_id": "msg123",
            "thread_id": "thread123",
            "from": "sender@example.com",
            "subject": "Test",
            "body": "<p>Hello</p>",
            "date": "2024-01-01"
        }
        
        result = format_email_object(email)
        
        assert result['message_id'] == "msg123"
        assert result['thread_id'] == "thread123"
        assert result['from'] == "sender@example.com"
        assert result['subject'] == "Test"
        assert result['date'] == "2024-01-01"


class TestFormatEmailList:
    """Tests for format_email_list function"""
    
    def test_format_list_of_emails(self):
        """Test formatting a list of emails"""
        emails = [
            {
                "message_id": "msg1",
                "body": "<p>Email 1</p>"
            },
            {
                "message_id": "msg2",
                "body": "<p>Email 2</p>"
            }
        ]
        
        result = format_email_list(emails)
        
        assert len(result) == 2
        assert result[0]['body'] == "Email 1"
        assert result[1]['body'] == "Email 2"
    
    def test_format_empty_list(self):
        """Test formatting empty list"""
        result = format_email_list([])
        
        assert result == []
    
    def test_format_mixed_emails(self):
        """Test formatting mixed HTML and plain text emails"""
        emails = [
            {
                "message_id": "msg1",
                "body": "<p>HTML email</p>"
            },
            {
                "message_id": "msg2",
                "body": "Plain text email"
            }
        ]
        
        result = format_email_list(emails)
        
        assert len(result) == 2
        assert "body_html" in result[0]
        assert "body_html" not in result[1]


class TestComplexHTMLScenarios:
    """Tests for complex real-world HTML scenarios"""
    
    def test_newsletter_format(self):
        """Test parsing newsletter-style HTML"""
        html = '''
        <div>
            <h1>Weekly Newsletter</h1>
            <p>Here are this week's updates:</p>
            <ul>
                <li>Item 1</li>
                <li>Item 2</li>
            </ul>
            <a href="https://example.com">Read more</a>
        </div>
        '''
        result = clean_email_body(html)
        
        assert "Weekly Newsletter" in result['clean_text']
        assert "Item 1" in result['clean_text']
        assert len(result['links']) == 1
    
    def test_signature_format(self):
        """Test parsing email with signature"""
        html = '''
        <p>Thanks for the meeting.</p>
        <div>
            <p>Best regards,</p>
            <p>John Doe<br>
            CEO, Example Corp<br>
            <a href="mailto:john@example.com">john@example.com</a></p>
        </div>
        '''
        result = clean_email_body(html)
        
        assert "Thanks for the meeting" in result['clean_text']
        assert "John Doe" in result['clean_text']
        assert len(result['links']) == 1
    
    def test_forwarded_email_format(self):
        """Test parsing forwarded email"""
        html = '''
        <p>FYI</p>
        <div>
            <p>---------- Forwarded message ---------</p>
            <p>From: Someone<br>
            Subject: Important</p>
            <p>Original message content.</p>
        </div>
        '''
        result = clean_email_body(html)
        
        assert "FYI" in result['clean_text']
        assert "Forwarded message" in result['clean_text']
        assert "Original message content" in result['clean_text']