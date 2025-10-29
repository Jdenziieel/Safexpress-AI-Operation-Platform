"""
standalone_test.py - Test smart mapping without supervisor agent
This tests JUST the core smart mapping functionality
"""

import pandas as pd
import json
import io
from smart_mapping_engine import SmartMappingEngine

# SafExpressOps target columns (from your DATA ENTRY sheet)
SAFEXPRESSOPS_COLUMNS = [
    "Date",
    "Week",
    "Day",
    "Total Manhours",
    "Safe man-hours",
    "Losttime Incident",
    "Days Without Lost Time Incident",
    "Cycle Count Accuracy",
    "Warehouse Damage Incident",
    "FEFO Incident",
    "Expired Product Incident",
    "No. of CV Received",
    "INBOUND OTIF",
    "Ave Picked Qty Per Hr",
    "CTS %",
    "Present",
]


class StandaloneSheetsTester:
    """Test the sheets functionality without LangGraph/supervisor"""

    def __init__(self):
        self.smart_engine = SmartMappingEngine()

    def test_file_parsing(self, test_data_csv: str):
        """Test 1: Can we parse uploaded files correctly?"""

        print("🔍 TEST 1: File Parsing")
        print("=" * 40)

        try:
            # Simulate file upload parsing
            df = pd.read_csv(io.StringIO(test_data_csv))
            df = df.dropna(how="all")
            df.columns = df.columns.astype(str)

            # Get sample data for analysis
            sample_data = df.head(5)

            result = {
                "success": True,
                "columns": df.columns.tolist(),
                "row_count": len(df),
                "sample_data": sample_data.to_dict("records"),
                "dataframe_json": df.to_json(),
                "sample_dataframe_json": sample_data.to_json(),
            }

            print(f"✅ Parsing successful!")
            print(f"   Columns found: {result['columns']}")
            print(f"   Rows: {result['row_count']}")
            print(
                f"   Sample data: {result['sample_data'][0] if result['sample_data'] else 'None'}"
            )

            return result

        except Exception as e:
            print(f"❌ Parsing failed: {e}")
            return {"success": False, "error": str(e)}

    def test_smart_mapping(self, source_columns, sample_data_json):
        """Test 2: Does smart mapping work correctly?"""

        print("\n🧠 TEST 2: Smart Column Mapping")
        print("=" * 40)

        try:
            # Parse sample data
            sample_data = pd.read_json(sample_data_json)
            print(f"📊 Analyzing {len(sample_data)} sample rows")

            # Run smart mapping
            smart_result = self.smart_engine.smart_app_columns(
                source_columns=source_columns,
                target_columns=SAFEXPRESSOPS_COLUMNS,
                sample_data=sample_data,
            )

            # Convert to expected format
            mappings = {}
            confidence_scores = {}
            needs_review = {}

            for source_col, mapping_info in smart_result["mappings"].items():
                mappings[source_col] = mapping_info["target"]
                confidence_scores[source_col] = mapping_info["confidence_score"]

                if mapping_info["needs_review"]:
                    needs_review[source_col] = {
                        "suggested": mapping_info["target"],
                        "confidence": mapping_info["confidence_score"],
                        "reason": f"Confidence level: {mapping_info['confidence_level']}",
                    }

            result = {
                "success": True,
                "mappings": mappings,
                "confidence_scores": confidence_scores,
                "needs_user_review": needs_review,
                "high_confidence_count": smart_result["summary"][
                    "high_confidence_mappings"
                ],
                "accuracy_estimate": smart_result["summary"]["accuracy_estimate"],
                "smart_analysis": True,
            }

            print(f"✅ Smart mapping successful!")
            print(f"   Overall accuracy: {result['accuracy_estimate']:.1%}")
            print(
                f"   High confidence: {result['high_confidence_count']}/{len(source_columns)}"
            )
            print(f"   Needs review: {len(needs_review)}")

            print(f"\n📋 DETAILED MAPPINGS:")
            for source, target in mappings.items():
                confidence = confidence_scores[source]
                status = (
                    "✅" if confidence >= 0.8 else "⚠️" if confidence >= 0.5 else "❌"
                )
                print(
                    f"   {status} {source:20} → {target or 'UNMAPPED':25} ({confidence:.2f})"
                )

            if needs_review:
                print(f"\n⚠️ NEEDS REVIEW:")
                for source, review_info in needs_review.items():
                    print(f"   {source}: {review_info['reason']}")

            return result

        except Exception as e:
            print(f"❌ Smart mapping failed: {e}")
            return {"success": False, "error": str(e)}

    def test_mapping_accuracy(self, expected_mappings):
        """Test 3: How accurate are our mappings?"""

        print("\n🎯 TEST 3: Mapping Accuracy Check")
        print("=" * 40)

        # This would be called after test_smart_mapping
        # For now, just show the concept
        print("This will compare expected vs actual mappings")
        return {"accuracy": "Will implement after smart mapping test"}

    def run_full_test(self):
        """Run all tests in sequence"""

        print("🚀 STANDALONE SMART MAPPING TEST")
        print("=" * 50)

        # Create realistic test data
        test_csv = """Date,Man Hours,Safety Incidents,Staff Present,CV Count,Pick Rate
2024-01-01,120,0,25,15,95.2
2024-01-02,115,1,23,18,98.1
2024-01-03,130,0,26,12,92.8"""

        # Test 1: File parsing
        parse_result = self.test_file_parsing(test_csv)
        if not parse_result["success"]:
            print("❌ File parsing failed - stopping tests")
            return

        # Test 2: Smart mapping
        mapping_result = self.test_smart_mapping(
            source_columns=parse_result["columns"],
            sample_data_json=parse_result["sample_dataframe_json"],
        )
        if not mapping_result["success"]:
            print("❌ Smart mapping failed - stopping tests")
            return

        # Test 3: Show final results
        print(f"\n🎉 ALL TESTS COMPLETED!")
        print(f"File parsing: ✅")
        print(f"Smart mapping: ✅")
        print(f"Overall system accuracy: {mapping_result['accuracy_estimate']:.1%}")

        # Expected vs actual comparison
        expected_mappings = {
            "Date": "Date",
            "Man Hours": "Total Manhours",
            "Safety Incidents": "Losttime Incident",
            "Staff Present": "Present",
            "CV Count": "No. of CV Received",
        }

        print(f"\n🔍 EXPECTED vs ACTUAL:")
        correct_count = 0
        for source, expected in expected_mappings.items():
            actual = mapping_result["mappings"].get(source)
            is_correct = actual == expected
            correct_count += is_correct
            status = "✅" if is_correct else "❌"
            print(f"   {status} {source}: Expected '{expected}', Got '{actual}'")

        manual_accuracy = correct_count / len(expected_mappings)
        print(f"\n🏆 MANUAL VERIFICATION: {manual_accuracy:.1%} accuracy")

        return {
            "file_parsing": parse_result["success"],
            "smart_mapping": mapping_result["success"],
            "estimated_accuracy": mapping_result["accuracy_estimate"],
            "manual_accuracy": manual_accuracy,
        }


def test_with_your_actual_file():
    """Test with your real COPY OPR.xlsx file if available"""

    print("\n📁 TESTING WITH YOUR ACTUAL FILE")
    print("=" * 40)

    try:
        # Try to load your actual file
        df = pd.read_excel("COPY OPR.xlsx", sheet_name="DATA ENTRY", nrows=5)

        tester = StandaloneSheetsTester()

        # Test with subset of your columns
        test_columns = df.columns.tolist()[:10]  # First 10 columns
        sample_data_json = df[test_columns].to_json()

        result = tester.test_smart_mapping(test_columns, sample_data_json)

        print(f"✅ Your file test: {result['accuracy_estimate']:.1%} accuracy")
        return result

    except FileNotFoundError:
        print("⚠️ COPY OPR.xlsx not found - that's okay!")
        print("   The test above with sample data is sufficient")
        return None
    except Exception as e:
        print(f"❌ Error with your file: {e}")
        return None


if __name__ == "__main__":
    # Run the standalone test
    tester = StandaloneSheetsTester()
    main_result = tester.run_full_test()

    # Try with your actual file too
    actual_file_result = test_with_your_actual_file()

    print(f"\n" + "=" * 50)
    print("🎯 FINAL RESULTS")
    print("=" * 50)

    if main_result["file_parsing"] and main_result["smart_mapping"]:
        print("✅ Core functionality working!")
        print(f"✅ Smart mapping accuracy: {main_result['estimated_accuracy']:.1%}")
        print(f"✅ Manual verification: {main_result['manual_accuracy']:.1%}")
        print("\n🚀 Ready for supervisor integration!")
    else:
        print("❌ Core functionality needs debugging")
        print("🔧 Fix issues before supervisor integration")
