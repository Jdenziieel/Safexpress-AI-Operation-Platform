"""
Pytest configuration and shared fixtures
"""

import pytest
import os
import sys
from pathlib import Path

# Add parent directory to path so tests can import modules
parent_dir = Path(__file__).parent.parent
sys.path.insert(0, str(parent_dir))

# Set environment variables for testing
os.environ['GOOGLE_CLIENT_ID'] = 'test_client_id'
os.environ['GOOGLE_CLIENT_SECRET'] = 'test_client_secret'
os.environ['OPENAI_API_KEY'] = 'test_openai_key'


@pytest.fixture(autouse=True)
def reset_environment():
    """Reset environment before each test"""
    # This runs before each test
    yield
    # Cleanup after test if needed
    pass


@pytest.fixture
def mock_env_vars(monkeypatch):
    """Mock environment variables"""
    monkeypatch.setenv('GOOGLE_CLIENT_ID', 'test_client_id')
    monkeypatch.setenv('GOOGLE_CLIENT_SECRET', 'test_client_secret')
    monkeypatch.setenv('OPENAI_API_KEY', 'test_openai_key')


@pytest.fixture
def sample_email_data():
    """Sample email data for testing"""
    return {
        "message_id": "msg123",
        "thread_id": "thread123",
        "from": "sender@example.com",
        "to": "recipient@example.com",
        "subject": "Test Subject",
        "date": "Mon, 1 Jan 2024 12:00:00 GMT",
        "body": "Test email body",
        "has_attachments": False,
        "attachments": []
    }


@pytest.fixture
def sample_html_email():
    """Sample HTML email for testing"""
    return {
        "message_id": "msg456",
        "thread_id": "thread456",
        "from": "sender@example.com",
        "subject": "HTML Email",
        "body": "<p>Hello <strong>world</strong>!</p><a href='https://example.com'>Link</a>"
    }


@pytest.fixture
def sample_credentials():
    """Sample OAuth credentials"""
    return {
        "access_token": "ya29.test_access_token",
        "refresh_token": "1//test_refresh_token",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "test_client_id",
        "client_secret": "test_client_secret"
    }


# Configure pytest markers
def pytest_configure(config):
    """Configure custom pytest markers"""
    config.addinivalue_line(
        "markers", "integration: mark test as integration test (requires real API access)"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow running"
    )
    config.addinivalue_line(
        "markers", "unit: mark test as unit test"
    )