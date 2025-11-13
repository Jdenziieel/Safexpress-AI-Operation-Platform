"""
Pytest configuration and shared fixtures
Place this in: gdocs-agent/test/conftest.py
"""

import pytest
import sys
import os
from pathlib import Path

# Add parent directory to Python path
parent_dir = Path(__file__).parent.parent
sys.path.insert(0, str(parent_dir))

print(f"\n🔧 Test Configuration")
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


def pytest_collection_modifyitems(config, items):
    """Auto-mark tests based on their class/function names"""
    for item in items:
        # Mark integration tests
        if "Integration" in item.nodeid:
            item.add_marker(pytest.mark.integration)
        # Mark API tests
        if "Endpoint" in item.nodeid or "execute_task" in item.nodeid:
            item.add_marker(pytest.mark.api)


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
def sample_files(test_data_dir):
    """Create sample test files"""
    files = {}
    
    # Create sample text file
    text_file = test_data_dir / "sample.txt"
    text_file.write_text("This is a test file for Google Drive Agent")
    files["text"] = str(text_file)
    
    # Create sample JSON file
    json_file = test_data_dir / "data.json"
    json_file.write_text('{"test": "data", "status": "ok"}')
    files["json"] = str(json_file)
    
    return files


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
def mock_task_request_factory(mock_credentials_dict):
    """Factory for creating mock task requests"""
    def _create_request(tool: str, inputs: dict = None):
        return {
            "tool": tool,
            "inputs": inputs or {},
            "credentials_dict": mock_credentials_dict
        }
    return _create_request


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
    print("  🎉 Test Session Complete!")
    print("="*70)
    
    if exitstatus == 0:
        print("  ✅ All tests passed successfully!")
    else:
        print(f"  ❌ Tests finished with exit status: {exitstatus}")
    
    print("="*70 + "\n")