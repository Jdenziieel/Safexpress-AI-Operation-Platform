"""
PII Redactor - Privacy Protection for Admin Dashboard

This module provides centralized PII (Personally Identifiable Information) redaction
for admin-facing logs and activity feeds. It ensures that administrators can monitor
system health and performance without accessing user's private data.

Features:
- Pattern-based PII detection (emails, phones, SSN, credit cards, API keys)
- Field-level redaction for known sensitive fields
- User identifier hashing
- Privacy-safe activity summaries
"""

import re
import hashlib
from typing import Dict, Any, List, Optional, Union
from datetime import datetime


class PIIRedactor:
    """
    Centralized PII redaction for admin-facing logs.
    Applies BEFORE any data is shown to admins.
    """
    
    # PII Detection Patterns
    PATTERNS = {
        'email': r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        'phone': r'\b(\+\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b',
        'ssn': r'\b\d{3}-\d{2}-\d{4}\b',
        'credit_card': r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b',
        'ip_address': r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b',
        'api_key': r'\b(sk_live_|sk_test_|api_key_|apikey_|key_|token_)[A-Za-z0-9]{8,}\b',
        'oauth_token': r'\b(ya29\.|Bearer\s+)[A-Za-z0-9_-]{20,}\b',
    }
    
    # Fields that should ALWAYS be redacted for admins
    SENSITIVE_FIELDS = {
        # Email-related
        'to', 'from', 'cc', 'bcc', 'recipient', 'recipients', 'sender', 
        'email', 'email_address', 'reply_to',
        
        # Message content
        'body', 'content', 'message_body', 'text', 'html_body', 'plain_text',
        'subject', 'title', 'description', 'summary',
        
        # Personal info
        'phone', 'mobile', 'telephone', 'address', 'location',
        'name', 'first_name', 'last_name', 'full_name', 'username',
        
        # Credentials
        'password', 'secret', 'token', 'api_key', 'access_token', 
        'refresh_token', 'auth_token', 'credentials',
        
        # File information
        'file_path', 'file_name', 'filename', 'path', 'document_name',
        'document_id', 'doc_id', 'spreadsheet_id', 'sheet_name',
        
        # Search and queries
        'query', 'search_query', 'search_term', 'q',
        
        # Calendar/Meeting
        'attendees', 'participants', 'invitees', 'organizer',
        'event_title', 'event_description', 'meeting_title',
        
        # User data
        'user_input', 'user_message', 'prompt', 'user_query',
    }
    
    # Fields that are safe to show (whitelist)
    SAFE_FIELDS = {
        'timestamp', 'level', 'logger', 'component', 'operation',
        'success', 'duration_ms', 'status', 'step_number', 'total_steps',
        'agent_name', 'tool_name', 'model', 'tier',
        'input_tokens', 'output_tokens', 'total_tokens', 
        'estimated_cost_usd', 'cost_usd',
        'request_id', 'id', 'created_at',
        '_pii_redacted', '_redaction_level',
    }
    
    # Agent-friendly names
    AGENT_FRIENDLY_NAMES = {
        'gmail': {'name': 'Email Service', 'icon': ''},
        'gmail_agent': {'name': 'Email Service', 'icon': ''},
        'calendar': {'name': 'Calendar Service', 'icon': ''},
        'calendar_agent': {'name': 'Calendar Service', 'icon': ''},
        'gdocs': {'name': 'Documents Service', 'icon': ''},
        'gdocs_agent': {'name': 'Documents Service', 'icon': ''},
        'sheets': {'name': 'Spreadsheets Service', 'icon': ''},
        'sheets_agent': {'name': 'Spreadsheets Service', 'icon': ''},
        'gdrive': {'name': 'File Storage Service', 'icon': ''},
        'gdrive_agent': {'name': 'File Storage Service', 'icon': ''},
    }
    
    # Tool action descriptions (privacy-safe)
    TOOL_ACTIONS = {
        # Gmail
        'send_email': 'Sent an email',
        'read_email': 'Read an email',
        'read_emails': 'Read emails',
        'search_emails': 'Searched emails',
        'create_draft': 'Created a draft',
        'list_emails': 'Listed emails',
        'get_email': 'Retrieved an email',
        'delete_email': 'Deleted an email',
        'forward_email': 'Forwarded an email',
        'reply_to_email': 'Replied to an email',
        
        # Calendar
        'create_event': 'Created a calendar event',
        'update_event': 'Updated a calendar event',
        'delete_event': 'Deleted a calendar event',
        'list_events': 'Listed calendar events',
        'get_event': 'Retrieved a calendar event',
        'search_events': 'Searched calendar events',
        
        # Docs
        'read_document': 'Read a document',
        'create_document': 'Created a document',
        'update_document': 'Updated a document',
        'add_text': 'Added text to a document',
        'delete_document': 'Deleted a document',
        'search_documents': 'Searched documents',
        
        # Sheets
        'read_sheet': 'Read spreadsheet data',
        'update_sheet': 'Updated a spreadsheet',
        'create_sheet': 'Created a spreadsheet',
        'append_rows': 'Added rows to a spreadsheet',
        'delete_rows': 'Deleted rows from a spreadsheet',
        
        # Drive
        'search_files': 'Searched files',
        'upload_file': 'Uploaded a file',
        'download_file': 'Downloaded a file',
        'list_files': 'Listed files',
        'delete_file': 'Deleted a file',
        'move_file': 'Moved a file',
        'copy_file': 'Copied a file',
    }
    
    @classmethod
    def redact_text(cls, text: str, level: str = 'admin') -> str:
        """
        Redact PII from text.
        
        Args:
            text: The text to redact
            level: Redaction level
                - 'admin': Aggressive redaction (default for admin dashboard)
                - 'debug': Minimal redaction (for developers only)
                
        Returns:
            Redacted text
        """
        if not text or not isinstance(text, str):
            return text
            
        result = text
        
        if level == 'admin':
            # Replace all PII patterns
            for pii_type, pattern in cls.PATTERNS.items():
                result = re.sub(
                    pattern, 
                    f'[{pii_type.upper()}_REDACTED]', 
                    result, 
                    flags=re.IGNORECASE
                )
        
        return result
    
    @classmethod
    def redact_value(cls, key: str, value: Any, level: str = 'admin') -> Any:
        """
        Redact a single value based on its key name.
        
        Args:
            key: The field name
            value: The value to potentially redact
            level: Redaction level
            
        Returns:
            Redacted or original value
        """
        if value is None:
            return None
            
        key_lower = key.lower()
        
        # Check if field should be completely redacted
        if level == 'admin' and key_lower in cls.SENSITIVE_FIELDS:
            return '[REDACTED]'
        
        # Check if field is safe (no redaction needed)
        if key_lower in cls.SAFE_FIELDS:
            return value
            
        # For strings, apply pattern-based redaction
        if isinstance(value, str):
            return cls.redact_text(value, level)
            
        # For dicts, recurse
        if isinstance(value, dict):
            return cls.redact_dict(value, level)
            
        # For lists, process each item
        if isinstance(value, list):
            return [cls.redact_value(key, item, level) for item in value]
            
        # Numbers, booleans, etc. - return as-is
        return value
    
    @classmethod
    def redact_dict(cls, data: Dict[str, Any], level: str = 'admin') -> Dict[str, Any]:
        """
        Recursively redact PII from dictionary.
        
        Args:
            data: Dictionary to redact
            level: Redaction level
            
        Returns:
            Redacted dictionary
        """
        if not data or not isinstance(data, dict):
            return data
            
        result = {}
        for key, value in data.items():
            result[key] = cls.redact_value(key, value, level)
                
        return result
    
    @classmethod
    def redact_log_entry(cls, log: Dict[str, Any], level: str = 'admin') -> Dict[str, Any]:
        """
        Redact an entire log entry for admin viewing.
        
        Args:
            log: Log entry dictionary
            level: Redaction level
            
        Returns:
            Redacted log entry
        """
        if not log:
            return log
            
        redacted = {}
        
        for key, value in log.items():
            redacted[key] = cls.redact_value(key, value, level)
        
        # Add redaction metadata
        redacted['_pii_redacted'] = True
        redacted['_redaction_level'] = level
        
        return redacted
    
    @classmethod
    def hash_identifier(cls, identifier: str) -> str:
        """
        Hash an identifier for privacy (one-way).
        Creates a consistent but anonymized identifier.
        
        Args:
            identifier: The identifier to hash
            
        Returns:
            Hashed identifier (user_XXXXXXXX format)
        """
        if not identifier:
            return identifier
        return 'user_' + hashlib.sha256(identifier.encode()).hexdigest()[:8]
    
    @classmethod
    def get_agent_friendly_name(cls, agent_name: str) -> Dict[str, str]:
        """
        Get friendly name and icon for an agent.
        
        Args:
            agent_name: Technical agent name
            
        Returns:
            Dict with 'name' and 'icon' keys
        """
        agent_lower = agent_name.lower() if agent_name else ''
        return cls.AGENT_FRIENDLY_NAMES.get(
            agent_lower, 
            {'name': agent_name or 'Unknown Service', 'icon': ''}
        )
    
    @classmethod
    def get_action_description(cls, tool_name: str) -> str:
        """
        Get privacy-safe description for a tool action.
        
        Args:
            tool_name: Technical tool name
            
        Returns:
            Human-readable action description
        """
        tool_lower = tool_name.lower() if tool_name else ''
        return cls.TOOL_ACTIONS.get(tool_lower, f'Performed action')
    
    @classmethod
    def create_admin_activity_summary(cls, agent_call: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a privacy-safe summary of an action for admins.
        
        Instead of: "Sent email to john@example.com with subject 'Salary Discussion'"
        Returns: {"summary": "Sent an email", "agent_friendly": "Email Service", "icon": ""}
        
        Args:
            agent_call: Agent call record from database
            
        Returns:
            Privacy-safe activity summary
        """
        agent = agent_call.get('agent_name', 'unknown')
        tool = agent_call.get('tool_name', 'action')
        success = agent_call.get('success', True)
        duration_ms = agent_call.get('duration_ms', 0)
        timestamp = agent_call.get('timestamp', '')
        
        agent_info = cls.get_agent_friendly_name(agent)
        action_desc = cls.get_action_description(tool)
        
        status_icon = '' if success else ''
        
        return {
            'timestamp': timestamp,
            'agent': agent,
            'agent_friendly': agent_info['name'],
            'icon': agent_info['icon'],
            'action': tool,
            'action_friendly': action_desc,
            'summary': f"{status_icon} {action_desc}",
            'success': bool(success),
            'duration_ms': duration_ms,
            'duration_friendly': cls.format_duration(duration_ms),
        }
    
    @classmethod
    def format_duration(cls, duration_ms: float) -> str:
        """
        Format duration in human-readable form.
        
        Args:
            duration_ms: Duration in milliseconds
            
        Returns:
            Formatted string like "1.2s" or "250ms"
        """
        if not duration_ms:
            return "0ms"
        if duration_ms < 1000:
            return f"{int(duration_ms)}ms"
        return f"{duration_ms/1000:.1f}s"
    
    @classmethod
    def create_activity_aggregation(
        cls, 
        agent_calls: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Create aggregated activity summary by agent.
        
        Args:
            agent_calls: List of agent call records
            
        Returns:
            Aggregated summary safe for admin viewing
        """
        by_agent = {}
        
        for call in agent_calls:
            agent = call.get('agent_name', 'unknown')
            tool = call.get('tool_name', 'unknown')
            success = call.get('success', True)
            
            if agent not in by_agent:
                agent_info = cls.get_agent_friendly_name(agent)
                by_agent[agent] = {
                    'agent': agent,
                    'friendly_name': agent_info['name'],
                    'icon': agent_info['icon'],
                    'total_actions': 0,
                    'successful': 0,
                    'failed': 0,
                    'actions': {},
                }
            
            by_agent[agent]['total_actions'] += 1
            if success:
                by_agent[agent]['successful'] += 1
            else:
                by_agent[agent]['failed'] += 1
            
            # Count by action type
            action_desc = cls.get_action_description(tool)
            by_agent[agent]['actions'][action_desc] = \
                by_agent[agent]['actions'].get(action_desc, 0) + 1
        
        # Calculate totals
        total_actions = sum(a['total_actions'] for a in by_agent.values())
        total_successful = sum(a['successful'] for a in by_agent.values())
        total_failed = sum(a['failed'] for a in by_agent.values())
        
        return {
            'by_agent': by_agent,
            'totals': {
                'total_actions': total_actions,
                'successful': total_successful,
                'failed': total_failed,
                'success_rate': round(
                    (total_successful / total_actions * 100) if total_actions > 0 else 0, 
                    1
                ),
            }
        }


# Convenience functions for direct import
def redact_for_admin(data: Union[Dict, List, str]) -> Union[Dict, List, str]:
    """
    Convenience function to redact any data for admin viewing.
    
    Args:
        data: Data to redact (dict, list, or string)
        
    Returns:
        Redacted data
    """
    if isinstance(data, dict):
        return PIIRedactor.redact_log_entry(data, level='admin')
    elif isinstance(data, list):
        return [PIIRedactor.redact_log_entry(item, level='admin') 
                if isinstance(item, dict) else item for item in data]
    elif isinstance(data, str):
        return PIIRedactor.redact_text(data, level='admin')
    return data


def create_activity_summary(agent_call: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convenience function to create privacy-safe activity summary.
    
    Args:
        agent_call: Agent call record
        
    Returns:
        Privacy-safe summary
    """
    return PIIRedactor.create_admin_activity_summary(agent_call)
