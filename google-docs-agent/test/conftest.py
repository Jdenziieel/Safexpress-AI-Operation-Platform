"""
Pytest configuration and shared fixtures for Google Docs Agent
Place this in: gdocs-agent/test/conftest.py
"""

import pytest
import sys
import os
from pathlib import Path
from unittest.mock import Mock

# Add parent directory to Python path
parent_dir = Path(__file__).parent.parent
sys.path.insert(0, str(parent_dir))

print(f"\n🔧 Google Docs Agent Test Configuration")
print(f"📁 Parent Directory: {parent_dir}")
print(f"🐍 Python Path: {sys.path[0]}\n")


# ============================================================
# PYTEST CONFIGURATION
# ============================================================

def pytest_configure(config):
    """Configure pytest with custom markers"""
    config.addinivalue_line(
        "markers", "unit: Unit tests for individual functions"
    )
    config.addinivalue_line(
        "markers", "integration: Integration tests for workflows"
    )
    config.addinivalue_line(
        "markers", "slow: Tests that take longer to run"
    )
    config.addinivalue_line(
        "markers", "api: Tests that hit API endpoints"
    )
    config.addinivalue_line(
        "markers", "agent: Tests involving AI agent"
    )
    config.addinivalue_line(
        "markers", "template: Tests involving template operations"
    )


def pytest_collection_modifyitems(config, items):
    """Auto-mark tests based on their class/function names"""
    for item in items:
        # Mark integration tests
        if "Integration" in item.nodeid:
            item.add_marker(pytest.mark.integration)
        # Mark API tests
        if "Endpoint" in item.nodeid or "execute_task" in item.nodeid:
            item.add_marker(pytest.mark.api)
        # Mark agent tests
        if "Agent" in item.nodeid or "Task" in item.nodeid:
            item.add_marker(pytest.mark.agent)
        # Mark template tests
        if "Template" in item.nodeid:
            item.add_marker(pytest.mark.template)


# ============================================================
# SESSION FIXTURES
# ============================================================

@pytest.fixture(scope="session")
def test_data_dir():
    """Return path to test data directory"""
    data_dir = Path(__file__).parent / "test_data"
    data_dir.mkdir(exist_ok=True)
    return data_dir


@pytest.fixture(scope="session")
def sample_document_content():
    """Sample document content for testing"""
    return {
        "simple": "This is a simple test document.",
        "formatted": "**Bold text** and *italic text*",
        "with_placeholders": "Meeting on [DATE] at [VENUE] with [ATTENDEES]",
        "long": "Lorem ipsum dolor sit amet. " * 50
    }


# ============================================================
# FUNCTION FIXTURES
# ============================================================

@pytest.fixture
def mock_credentials_dict():
    """Mock credentials dictionary"""
    return {
        "access_token": "mock_access_token_12345",
        "refresh_token": "mock_refresh_token_67890",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "mock_client_id.apps.googleusercontent.com",
        "client_secret": "mock_client_secret_abcdef"
    }


@pytest.fixture
def mock_document_response():
    """Mock Google Docs API document response"""
    return {
        'documentId': 'mock_doc_123',
        'title': 'Mock Test Document',
        'body': {
            'content': [
                {
                    'endIndex': 1,
                    'sectionBreak': {
                        'sectionStyle': {
                            'columnSeparatorStyle': 'NONE'
                        }
                    }
                },
                {
                    'startIndex': 1,
                    'endIndex': 25,
                    'paragraph': {
                        'elements': [
                            {
                                'startIndex': 1,
                                'endIndex': 25,
                                'textRun': {
                                    'content': 'This is test content.\n',
                                    'textStyle': {}
                                }
                            }
                        ]
                    }
                }
            ]
        }
    }


@pytest.fixture
def mock_agent():
    """Mock LangChain agent"""
    agent = Mock()
    agent.invoke.return_value = {
        "messages": [
            Mock(content='{"success": true, "document_id": "doc123", "document_url": "https://docs.google.com/document/d/doc123/edit"}')
        ]
    }
    return agent


@pytest.fixture
def mock_docs_service():
    """Mock Google Docs service with common operations"""
    service = Mock()
    
    # Mock create document
    create_mock = Mock()
    create_mock.execute.return_value = {
        'documentId': 'new_doc_123',
        'title': 'New Document'
    }
    service.documents().create.return_value = create_mock
    
    # Mock get document
    get_mock = Mock()
    get_mock.execute.return_value = {
        'documentId': 'doc123',
        'title': 'Test Document',
        'body': {
            'content': [
                {
                    'paragraph': {
                        'elements': [
                            {'textRun': {'content': 'Document content\n'}}
                        ]
                    }
                }
            ]
        }
    }
    service.documents().get.return_value = get_mock
    
    # Mock batch update
    batch_mock = Mock()
    batch_mock.execute.return_value = {'replies': []}
    service.documents().batchUpdate.return_value = batch_mock
    
    return service


@pytest.fixture
def mock_drive_service():
    """Mock Google Drive service for sharing operations"""
    service = Mock()
    
    # Mock create permission
    permission_mock = Mock()
    permission_mock.execute.return_value = {'id': 'permission123'}
    service.permissions().create.return_value = permission_mock
    
    return service


@pytest.fixture
def sample_tool_request(mock_credentials_dict):
    """Factory for creating tool-based requests"""
    def _create_request(tool: str, inputs: dict = None):
        return {
            "tool": tool,
            "inputs": inputs or {},
            "credentials_dict": mock_credentials_dict
        }
    return _create_request


@pytest.fixture
def sample_task_request(mock_credentials_dict):
    """Factory for creating task-based requests"""
    def _create_request(task: str, instruction: str = None, inputs: dict = None, expected_output: dict = None):
        request = {
            "task": task,
            "inputs": inputs or {},
            "credentials_dict": mock_credentials_dict
        }
        if instruction:
            request["instruction"] = instruction
        if expected_output:
            request["expected_output"] = expected_output
        return request
    return _create_request


# ============================================================
# MOCK DATA FIXTURES
# ============================================================

@pytest.fixture
def sample_template_structure():
    """Sample template structure for testing"""
    return {
        'title': 'Meeting Minutes Template',
        'documentId': 'template123',
        'content_blocks': [
            {'type': 'heading', 'content': 'Meeting Minutes'},
            {'type': 'paragraph', 'content': 'Date: [DATE]'},
            {'type': 'paragraph', 'content': 'Venue: [VENUE]'},
            {'type': 'paragraph', 'content': 'Attendees: [ATTENDEES]'},
            {'type': 'heading', 'content': 'Agenda'},
            {'type': 'paragraph', 'content': '[AGENDA_ITEMS]'},
        ],
        'placeholders': ['DATE', 'VENUE', 'ATTENDEES', 'AGENDA_ITEMS']
    }


@pytest.fixture
def sample_placeholder_values():
    """Sample placeholder values for testing"""
    return {
        'DATE': 'January 15, 2025',
        'VENUE': 'Conference Room A',
        'ATTENDEES': 'John Doe, Jane Smith, Bob Johnson',
        'AGENDA_ITEMS': '1. Project updates\n2. Budget review\n3. Next steps'
    }


# ============================================================
# CLEANUP
# ============================================================

@pytest.fixture(autouse=True)
def cleanup_after_test():
    """Cleanup after each test"""
    yield
    # Add any cleanup logic here if needed
    pass


def pytest_sessionfinish(session, exitstatus):
    """Print summary after all tests complete"""
    print("\n" + "="*70)
    print("  🎉 Google Docs Agent Test Session Complete!")
    print("="*70)
    
    if exitstatus == 0:
        print("  ✅ All tests passed successfully!")
    else:
        print(f"  ❌ Tests finished with exit status: {exitstatus}")
    
    print("="*70 + "\n")