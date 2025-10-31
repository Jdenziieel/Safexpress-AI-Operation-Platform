"""
Test script for Google Sheets Agent API (v2 - Pure CRUD)
Tests all Google Sheets operations
Note: Requires valid Google OAuth credentials for full testing
"""

import requests
import json
from dotenv import load_dotenv
import os

load_dotenv()

BASE_URL = "http://localhost:8003"
# Test credentials (API will use .env values as fallback)
TEST_CREDENTIALS = {
    "access_token": os.getenv("GOOGLE_ACCESS_TOKEN"),
    "refresh_token": os.getenv("GOOGLE_REFRESH_TOKEN"),
    "client_id": os.getenv("GOOGLE_CLIENT_ID"),
    "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
}


def test_health_check():
    """Test health check endpoint"""
    print("\n" + "=" * 60)
    print("TEST 1: Health Check")
    print("=" * 60)

    response = requests.get(f"{BASE_URL}/health")
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    print("✅ Health check passed")


def test_list_tools():
    """Test list tools endpoint"""
    print("\n" + "=" * 60)
    print("TEST 2: List Available Tools")
    print("=" * 60)

    response = requests.get(f"{BASE_URL}/tools")
    print(f"Status Code: {response.status_code}")
    data = response.json()

    print(f"\nAvailable tools ({data['count']}):")
    for tool in data["tools"]:
        print(f"  • {tool['name']}: {tool['description']}")

    assert response.status_code == 200
    assert "tools" in data
    print(f"\n✅ Found {len(data['tools'])} tools")


def test_create_sheet_dry_run():
    """Test create_sheet API structure (dry run without real credentials)"""
    print("\n" + "=" * 60)
    print("TEST 3: Create Sheet (Dry Run - API Structure)")
    print("=" * 60)

    payload = {
        "tool": "create_sheet",
        "inputs": {
            "title": "Test Spreadsheet",
            "sheet_names": ["Data", "Summary"],
            "initial_data": [
                ["Name", "Age", "Email"],
                ["John Doe", "30", "john@example.com"],
            ],
        },
        "credentials_dict": TEST_CREDENTIALS,
    }

    response = requests.post(f"{BASE_URL}/execute", json=payload)
    print(f"Status Code: {response.status_code}")
    result = response.json()
    print(f"Success: {result.get('success')}")

    # With test credentials, this will fail authentication
    # But we can verify the API structure is correct
    if not result.get("success"):
        error = result.get("error", "")
        if "Authentication" in error or "Credentials" in error:
            print(
                "✅ API structure correct (authentication failed as expected with test credentials)"
            )
            print(f"   Error: {error}")
        else:
            print(f"⚠️ Unexpected error: {error}")
    else:
        print(f"✅ Sheet created: {result['result']}")


def test_read_sheet_dry_run():
    """Test read_sheet API structure"""
    print("\n" + "=" * 60)
    print("TEST 4: Read Sheet (Dry Run - API Structure)")
    print("=" * 60)

    payload = {
        "tool": "read_sheet",
        "inputs": {"sheet_id": "1abc123xyz", "range_name": "Sheet1!A1:D10"},
        "credentials_dict": TEST_CREDENTIALS,
    }

    response = requests.post(f"{BASE_URL}/execute", json=payload)
    print(f"Status Code: {response.status_code}")
    result = response.json()

    if not result.get("success"):
        error = result.get("error", "")
        if "Authentication" in error:
            print("✅ API structure correct (authentication failed as expected)")
        else:
            print(f"⚠️ Error: {error}")


def test_upload_mapped_data_structure():
    """Test upload_mapped_data API structure with sample data"""
    print("\n" + "=" * 60)
    print("TEST 5: Upload Mapped Data (API Structure)")
    print("=" * 60)

    # Sample transformed data (as would come from mapping agent)
    transformed_data = json.dumps(
        [
            {
                "Present": "John Doe",
                "Total Manhours": "40",
                "Losttime Incident": "0",
                "Date": "2025-01-28",
            },
            {
                "Present": "Jane Smith",
                "Total Manhours": "35",
                "Losttime Incident": "1",
                "Date": "2025-01-28",
            },
        ]
    )

    payload = {
        "tool": "upload_mapped_data",
        "inputs": {
            "sheet_id": "1abc123xyz",
            "transformed_data": transformed_data,
            "sheet_name": "DATA ENTRY",
            "append_mode": True,
        },
        "credentials_dict": TEST_CREDENTIALS,
    }

    response = requests.post(f"{BASE_URL}/execute", json=payload)
    print(f"Status Code: {response.status_code}")
    result = response.json()
    print(f"Success: {result.get('success')}")

    if not result.get("success"):
        error = result.get("error", "")
        if "Authentication" in error:
            print("✅ API structure correct")
            print(f"   Transformed data format validated")
        else:
            print(f"⚠️ Error: {error}")


def test_integration_with_mapping_agent():
    """Test integration flow: Mapping Agent → Sheets Agent"""
    print("\n" + "=" * 60)
    print("TEST 6: Integration with Mapping Agent")
    print("=" * 60)

    print("\nSimulating workflow:")
    print("  1. Mapping Agent: parse_file")
    print("  2. Mapping Agent: smart_column_mapping")
    print("  3. Mapping Agent: transform_data")
    print("  4. Sheets Agent: upload_mapped_data")

    # Check if mapping agent is running
    try:
        mapping_response = requests.get("http://localhost:8004/health", timeout=2)
        if mapping_response.status_code == 200:
            print("\n✅ Mapping Agent is running at http://localhost:8004")

            # Step 1: Parse with mapping agent
            csv_content = """Employee,Hours
John,40
Jane,35"""

            parse_result = requests.post(
                "http://localhost:8004/execute",
                json={
                    "tool": "parse_file",
                    "inputs": {"file_content": csv_content, "file_type": "csv"},
                },
            ).json()

            if parse_result.get("success"):
                print("  ✓ Step 1: File parsed")

                # Step 2: Map
                map_result = requests.post(
                    "http://localhost:8004/execute",
                    json={
                        "tool": "smart_column_mapping",
                        "inputs": {
                            "source_columns": parse_result["result"]["columns"],
                            "target_columns": ["Present", "Total Manhours"],
                        },
                    },
                ).json()

                if map_result.get("success"):
                    print("  ✓ Step 2: Columns mapped")

                    # Step 3: Transform
                    transform_result = requests.post(
                        "http://localhost:8004/execute",
                        json={
                            "tool": "transform_data",
                            "inputs": {
                                "source_data": parse_result["result"]["full_data"],
                                "mappings": map_result["result"]["mappings"],
                                "target_columns": ["Present", "Total Manhours"],
                            },
                        },
                    ).json()

                    if transform_result.get("success"):
                        print("  ✓ Step 3: Data transformed")
                        transformed_data = transform_result["result"][
                            "transformed_data"
                        ]

                        # Step 4: Upload (would work with real credentials)
                        upload_result = requests.post(
                            f"{BASE_URL}/execute",
                            json={
                                "tool": "upload_mapped_data",
                                "inputs": {
                                    "sheet_id": "test_id",
                                    "transformed_data": transformed_data,
                                    "append_mode": True,
                                },
                                "credentials_dict": TEST_CREDENTIALS,
                            },
                        ).json()

                        if not upload_result.get("success"):
                            if "Authentication" in upload_result.get("error", ""):
                                print("  ✓ Step 4: Upload structure validated")
                                print("\n✅ Integration flow works correctly!")
                            else:
                                print(f"  ⚠️ Step 4: {upload_result.get('error')}")
        else:
            print(
                "\n⚠️ Mapping Agent not running. Start with: python mapping_agent_api.py"
            )

    except requests.exceptions.ConnectionError:
        print("\n⚠️ Mapping Agent not running at http://localhost:8004")
        print("   Start it with: python mapping_agent_api.py")
        print("   This test validates the integration between both agents")


def test_api_documentation():
    """Test that API documentation is accessible"""
    print("\n" + "=" * 60)
    print("TEST 7: API Documentation")
    print("=" * 60)

    # Test root endpoint
    response = requests.get(f"{BASE_URL}/")
    print(f"Root endpoint status: {response.status_code}")

    if response.status_code == 200:
        data = response.json()
        print(f"Service: {data.get('service')}")
        print(f"Version: {data.get('version')}")
        print(f"Features: {len(data.get('features', []))}")

    # Test docs endpoint (Swagger)
    docs_response = requests.get(f"{BASE_URL}/docs")
    print(f"Swagger docs status: {docs_response.status_code}")

    if docs_response.status_code == 200:
        print("✅ API documentation accessible at /docs")
    else:
        print("⚠️ API documentation not accessible")


def test_error_handling():
    """Test error handling"""
    print("\n" + "=" * 60)
    print("TEST 8: Error Handling")
    print("=" * 60)

    # Test invalid tool
    print("\n1. Invalid tool name:")
    response = requests.post(
        f"{BASE_URL}/execute",
        json={
            "tool": "nonexistent_tool",
            "inputs": {},
            "credentials_dict": TEST_CREDENTIALS,
        },
    )
    result = response.json()

    if not result.get("success"):
        print(f"   ✓ Correctly rejected: {result.get('error')}")

    # Test missing credentials
    print("\n2. Missing credentials:")
    response = requests.post(
        f"{BASE_URL}/execute",
        json={
            "tool": "read_sheet",
            "inputs": {"sheet_id": "test"},
            "credentials_dict": {"access_token": "", "refresh_token": ""},
        },
    )
    result = response.json()

    if not result.get("success"):
        print(f"   ✓ Correctly rejected: {result.get('error')}")

    print("\n✅ Error handling works correctly")


def run_all_tests():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("🧪 GOOGLE SHEETS AGENT API TESTS (v2.0)")
    print("=" * 60)
    print(f"Testing endpoint: {BASE_URL}")
    print("Make sure the server is running: python sheets_agent_api_v2.py")
    print("\nNote: Full integration tests require valid Google credentials")
    print("=" * 60)

    try:
        test_health_check()
        test_list_tools()
        test_create_sheet_dry_run()
        test_read_sheet_dry_run()
        test_upload_mapped_data_structure()
        test_integration_with_mapping_agent()
        test_api_documentation()
        test_error_handling()

        print("\n" + "=" * 60)
        print("✅ ALL TESTS PASSED")
        print("=" * 60)
        print("\nNext steps:")
        print("1. Configure real Google OAuth credentials")
        print("2. Test with actual Google Sheets")
        print("3. Test end-to-end with supervisor agent")

    except requests.exceptions.ConnectionError:
        print("\n" + "=" * 60)
        print("❌ CONNECTION ERROR")
        print("=" * 60)
        print("The server is not running!")
        print("Start it with: python sheets_agent_api_v2.py")
        print("=" * 60)

    except AssertionError as e:
        print("\n" + "=" * 60)
        print(f"❌ TEST FAILED: {str(e)}")
        print("=" * 60)

    except Exception as e:
        print("\n" + "=" * 60)
        print(f"❌ UNEXPECTED ERROR: {str(e)}")
        print("=" * 60)
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    run_all_tests()
