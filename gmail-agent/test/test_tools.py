"""
Unit tests for Gmail agent tools
"""

import pytest
import base64
from unittest.mock import Mock, patch, MagicMock
from tools import (
    _send_email_impl,
    _search_emails_impl,
    _send_email_with_attachments_impl,
    _reply_to_email_impl,
    _forward_email_impl,
    _get_thread_conversation_impl,
    _create_draft_email_impl,
    _send_draft_email_impl,
    _search_drafts_impl,
    _add_label_impl,
    _remove_label_impl,
    _download_attachment_impl,
)


@pytest.fixture
def mock_credentials():
    """Mock OAuth credentials"""
    return {
        "access_token": "mock_access_token",
        "refresh_token": "mock_refresh_token"
    }


@pytest.fixture
def mock_gmail_service():
    """Mock Gmail service"""
    with patch('tools.build') as mock_build:
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        yield mock_service


class TestSendEmail:
    """Tests for _send_email_impl"""
    
    def test_send_email_success(self, mock_credentials, mock_gmail_service):
        """Test successful email sending"""
        # Setup mock
        mock_gmail_service.users().messages().send().execute.return_value = {
            'id': 'msg123',
            'threadId': 'thread123'
        }
        
        result = _send_email_impl(
            to="test@example.com",
            subject="Test Subject",
            body="Test Body",
            credentials_dict=mock_credentials
        )
        
        assert result['success'] is True
        assert result['message_id'] == 'msg123'
        assert result['thread_id'] == 'thread123'
        assert result['to'] == "test@example.com"
        assert result['subject'] == "Test Subject"
        assert result['error'] is None
    
    def test_send_email_api_error(self, mock_credentials, mock_gmail_service):
        """Test email sending with API error"""
        from googleapiclient.errors import HttpError
        
        # Setup mock to raise error
        mock_gmail_service.users().messages().send().execute.side_effect = HttpError(
            resp=Mock(status=400),
            content=b'Bad Request'
        )
        
        result = _send_email_impl(
            to="test@example.com",
            subject="Test",
            body="Body",
            credentials_dict=mock_credentials
        )
        
        assert result['success'] is False
        assert result['message_id'] is None
        assert "Gmail API error" in result['error']


class TestSearchEmails:
    """Tests for _search_emails_impl"""
    
    def test_search_emails_success(self, mock_credentials, mock_gmail_service):
        """Test successful email search"""
        # Mock message list
        mock_gmail_service.users().messages().list().execute.return_value = {
            'messages': [{'id': 'msg1'}, {'id': 'msg2'}]
        }
        
        # Mock message details
        mock_message = {
            'id': 'msg1',
            'threadId': 'thread1',
            'internalDate': '1234567890',
            'labelIds': ['INBOX'],
            'payload': {
                'headers': [
                    {'name': 'From', 'value': 'sender@example.com'},
                    {'name': 'Subject', 'value': 'Test Subject'},
                    {'name': 'Date', 'value': 'Mon, 1 Jan 2024 12:00:00'}
                ],
                'body': {
                    'data': base64.urlsafe_b64encode(b'Test body').decode()
                }
            }
        }
        
        mock_gmail_service.users().messages().get().execute.return_value = mock_message
        
        result = _search_emails_impl(
            query="from:sender@example.com",
            max_results=5,
            credentials_dict=mock_credentials
        )
        
        assert result['success'] is True
        assert result['count'] == 2
        assert len(result['emails']) == 2
        assert result['query'] == "from:sender@example.com"
        assert result['error'] is None
    
    def test_search_emails_no_results(self, mock_credentials, mock_gmail_service):
        """Test email search with no results"""
        mock_gmail_service.users().messages().list().execute.return_value = {
            'messages': []
        }
        
        result = _search_emails_impl(
            query="nonexistent@example.com",
            max_results=5,
            credentials_dict=mock_credentials
        )
        
        assert result['success'] is False
        assert result['count'] == 0
        assert result['emails'] == []
        assert result['no_results'] is True
        assert "No emails found" in result['error']


class TestSendEmailWithAttachments:
    """Tests for _send_email_with_attachments_impl"""
    
    def test_send_with_attachment_success(self, mock_credentials, mock_gmail_service, tmp_path):
        """Test successful email with attachment"""
        # Create temporary file
        test_file = tmp_path / "test.txt"
        test_file.write_text("Test content")
        
        mock_gmail_service.users().messages().send().execute.return_value = {
            'id': 'msg123',
            'threadId': 'thread123'
        }
        
        result = _send_email_with_attachments_impl(
            to="test@example.com",
            subject="Test",
            body="Body",
            file_path=str(test_file),
            credentials_dict=mock_credentials
        )
        
        assert result['success'] is True
        assert result['message_id'] == 'msg123'
        assert result['attachment_name'] == "test.txt"
        assert result['error'] is None
    
    def test_send_with_attachment_file_not_found(self, mock_credentials, mock_gmail_service):
        """Test email with non-existent attachment"""
        result = _send_email_with_attachments_impl(
            to="test@example.com",
            subject="Test",
            body="Body",
            file_path="/nonexistent/file.txt",
            credentials_dict=mock_credentials
        )
        
        assert result['success'] is False
        assert "File not found" in result['error']


class TestReplyToEmail:
    """Tests for _reply_to_email_impl"""
    
    def test_reply_success(self, mock_credentials, mock_gmail_service):
        """Test successful email reply"""
        # Mock original message
        mock_gmail_service.users().messages().get().execute.return_value = {
            'threadId': 'thread123',
            'payload': {
                'headers': [
                    {'name': 'Message-ID', 'value': '<original@example.com>'},
                    {'name': 'Subject', 'value': 'Original Subject'},
                    {'name': 'From', 'value': 'sender@example.com'}
                ]
            }
        }
        
        # Mock send result
        mock_gmail_service.users().messages().send().execute.return_value = {
            'id': 'reply123',
            'threadId': 'thread123'
        }
        
        result = _reply_to_email_impl(
            message_id="msg123",
            reply_body="This is my reply",
            credentials_dict=mock_credentials
        )
        
        assert result['success'] is True
        assert result['original_message_id'] == "msg123"
        assert result['reply_message_id'] == 'reply123'
        assert result['thread_id'] == 'thread123'
        assert result['error'] is None


class TestForwardEmail:
    """Tests for _forward_email_impl"""
    
    def test_forward_success(self, mock_credentials, mock_gmail_service):
        """Test successful email forwarding"""
        # Mock original message
        mock_gmail_service.users().messages().get().execute.return_value = {
            'payload': {
                'headers': [
                    {'name': 'Subject', 'value': 'Original Subject'},
                    {'name': 'From', 'value': 'original@example.com'},
                    {'name': 'Date', 'value': 'Mon, 1 Jan 2024'}
                ],
                'body': {
                    'data': base64.urlsafe_b64encode(b'Original body').decode()
                }
            }
        }
        
        # Mock send result
        mock_gmail_service.users().messages().send().execute.return_value = {
            'id': 'fwd123',
            'threadId': 'thread123'
        }
        
        result = _forward_email_impl(
            message_id="msg123",
            to="recipient@example.com",
            forward_message="Forwarding this to you",
            credentials_dict=mock_credentials
        )
        
        assert result['success'] is True
        assert result['original_message_id'] == "msg123"
        assert result['forwarded_message_id'] == 'fwd123'
        assert result['to'] == "recipient@example.com"
        assert "Fwd:" in result['subject']
        assert result['error'] is None


class TestGetThreadConversation:
    """Tests for _get_thread_conversation_impl"""
    
    def test_get_thread_success(self, mock_credentials, mock_gmail_service):
        """Test successful thread retrieval"""
        mock_gmail_service.users().threads().get().execute.return_value = {
            'messages': [
                {
                    'id': 'msg1',
                    'payload': {
                        'headers': [
                            {'name': 'From', 'value': 'sender1@example.com'},
                            {'name': 'To', 'value': 'recipient@example.com'},
                            {'name': 'Subject', 'value': 'Thread Subject'},
                            {'name': 'Date', 'value': 'Mon, 1 Jan 2024'}
                        ],
                        'body': {
                            'data': base64.urlsafe_b64encode(b'Message 1').decode()
                        }
                    }
                },
                {
                    'id': 'msg2',
                    'payload': {
                        'headers': [
                            {'name': 'From', 'value': 'sender2@example.com'},
                            {'name': 'To', 'value': 'recipient@example.com'},
                            {'name': 'Subject', 'value': 'Re: Thread Subject'},
                            {'name': 'Date', 'value': 'Tue, 2 Jan 2024'}
                        ],
                        'body': {
                            'data': base64.urlsafe_b64encode(b'Message 2').decode()
                        }
                    }
                }
            ]
        }
        
        result = _get_thread_conversation_impl(
            thread_id="thread123",
            credentials_dict=mock_credentials
        )
        
        assert result['success'] is True
        assert result['thread_id'] == "thread123"
        assert result['message_count'] == 2
        assert len(result['messages']) == 2
        assert result['error'] is None
    
    def test_get_thread_empty(self, mock_credentials, mock_gmail_service):
        """Test thread with no messages"""
        mock_gmail_service.users().threads().get().execute.return_value = {
            'messages': []
        }
        
        result = _get_thread_conversation_impl(
            thread_id="thread123",
            credentials_dict=mock_credentials
        )
        
        assert result['success'] is False
        assert result['message_count'] == 0
        assert result['no_results'] is True


class TestDraftOperations:
    """Tests for draft-related functions"""
    
    def test_create_draft_success(self, mock_credentials, mock_gmail_service):
        """Test successful draft creation"""
        mock_gmail_service.users().drafts().create().execute.return_value = {
            'id': 'draft123',
            'message': {'id': 'msg123'}
        }
        
        result = _create_draft_email_impl(
            to="test@example.com",
            subject="Draft Subject",
            body="Draft Body",
            credentials_dict=mock_credentials
        )
        
        assert result['success'] is True
        assert result['draft_id'] == 'draft123'
        assert result['message_id'] == 'msg123'
        assert result['error'] is None
    
    def test_send_draft_success(self, mock_credentials, mock_gmail_service):
        """Test successful draft sending"""
        mock_gmail_service.users().drafts().send().execute.return_value = {
            'id': 'msg123',
            'threadId': 'thread123'
        }
        
        mock_gmail_service.users().messages().get().execute.return_value = {
            'payload': {
                'headers': [
                    {'name': 'To', 'value': 'test@example.com'},
                    {'name': 'Subject', 'value': 'Test Subject'}
                ]
            }
        }
        
        result = _send_draft_email_impl(
            draft_id="draft123",
            credentials_dict=mock_credentials
        )
        
        assert result['success'] is True
        assert result['draft_id'] == "draft123"
        assert result['message_id'] == 'msg123'
        assert result['error'] is None
    
    def test_search_drafts_success(self, mock_credentials, mock_gmail_service):
        """Test successful draft search"""
        mock_gmail_service.users().drafts().list().execute.return_value = {
            'drafts': [
                {'id': 'draft1'},
                {'id': 'draft2'}
            ]
        }
        
        mock_draft = {
            'id': 'draft1',
            'message': {
                'id': 'msg1',
                'threadId': 'thread1',
                'labelIds': ['DRAFT'],
                'payload': {
                    'headers': [
                        {'name': 'To', 'value': 'test@example.com'},
                        {'name': 'Subject', 'value': 'Draft Subject'},
                        {'name': 'Date', 'value': 'Mon, 1 Jan 2024'}
                    ],
                    'body': {
                        'data': base64.urlsafe_b64encode(b'Draft body').decode()
                    }
                }
            }
        }
        
        mock_gmail_service.users().drafts().get().execute.return_value = mock_draft
        
        result = _search_drafts_impl(
            query="subject:meeting",
            max_results=10,
            credentials_dict=mock_credentials
        )
        
        assert result['success'] is True
        assert result['count'] == 2
        assert len(result['drafts']) == 2
        assert result['error'] is None


class TestLabelOperations:
    """Tests for label add/remove functions"""
    
    def test_add_label_success(self, mock_credentials, mock_gmail_service):
        """Test successful label addition"""
        mock_gmail_service.users().messages().modify().execute.return_value = {
            'threadId': 'thread123',
            'labelIds': ['INBOX', 'STARRED']
        }
        
        mock_gmail_service.users().messages().get().execute.return_value = {
            'payload': {
                'headers': [
                    {'name': 'Subject', 'value': 'Test Subject'},
                    {'name': 'From', 'value': 'test@example.com'}
                ]
            }
        }
        
        result = _add_label_impl(
            message_id="msg123",
            label="STARRED",
            credentials_dict=mock_credentials
        )
        
        assert result['success'] is True
        assert result['message_id'] == "msg123"
        assert result['label_added'] == "STARRED"
        assert result['error'] is None
    
    def test_add_label_invalid(self, mock_credentials, mock_gmail_service):
        """Test adding invalid label"""
        result = _add_label_impl(
            message_id="msg123",
            label="INVALID_LABEL",
            credentials_dict=mock_credentials
        )
        
        assert result['success'] is False
        assert "Invalid label" in result['error']
    
    def test_remove_label_success(self, mock_credentials, mock_gmail_service):
        """Test successful label removal"""
        mock_gmail_service.users().messages().modify().execute.return_value = {
            'threadId': 'thread123',
            'labelIds': ['INBOX']
        }
        
        mock_gmail_service.users().messages().get().execute.return_value = {
            'payload': {
                'headers': [
                    {'name': 'Subject', 'value': 'Test Subject'},
                    {'name': 'From', 'value': 'test@example.com'}
                ]
            }
        }
        
        result = _remove_label_impl(
            message_id="msg123",
            label="STARRED",
            credentials_dict=mock_credentials
        )
        
        assert result['success'] is True
        assert result['message_id'] == "msg123"
        assert result['label_removed'] == "STARRED"
        assert result['error'] is None


class TestDownloadAttachment:
    """Tests for _download_attachment_impl"""
    
    def test_download_attachment_success(self, mock_credentials, mock_gmail_service, tmp_path):
        """Test successful attachment download"""
        # Create save path
        save_path = tmp_path / "attachment.txt"
        
        # Mock attachment data
        test_data = b"Test attachment content"
        encoded_data = base64.urlsafe_b64encode(test_data).decode()
        
        mock_gmail_service.users().messages().attachments().get().execute.return_value = {
            'data': encoded_data
        }
        
        mock_gmail_service.users().messages().get().execute.return_value = {
            'threadId': 'thread123'
        }
        
        result = _download_attachment_impl(
            message_id="msg123",
            attachment_id="attach123",
            save_path=str(save_path),
            credentials_dict=mock_credentials
        )
        
        assert result['success'] is True
        assert result['message_id'] == "msg123"
        assert result['attachment_id'] == "attach123"
        assert result['filename'] == "attachment.txt"
        assert result['file_size'] == len(test_data)
        assert result['error'] is None
        
        # Verify file was written
        assert save_path.exists()
        assert save_path.read_bytes() == test_data
    
    def test_download_attachment_invalid_path(self, mock_credentials, mock_gmail_service):
        """Test download with invalid save path"""
        result = _download_attachment_impl(
            message_id="msg123",
            attachment_id="attach123",
            save_path="/invalid/path/file.txt",
            credentials_dict=mock_credentials
        )
        
        assert result['success'] is False
        assert "Invalid save path" in result['error']