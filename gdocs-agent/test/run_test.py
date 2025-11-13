#!/usr/bin/env python3
"""
Comprehensive Test Runner for Google Docs Agent
Counts all tests, runs them, and provides detailed reporting
"""

import subprocess
import sys
from pathlib import Path
import json
import re

def count_tests_in_file(filepath: Path) -> dict:
    """Count test methods in a test file"""
    content = filepath.read_text()
    
    # Count test methods (functions starting with test_)
    test_methods = re.findall(r'def (test_\w+)\(', content)
    
    # Count test classes
    test_classes = re.findall(r'class (Test\w+)', content)
    
    # Group tests by class
    tests_by_class = {}
    current_class = None
    
    for line in content.split('\n'):
        class_match = re.match(r'class (Test\w+)', line)
        if class_match:
            current_class = class_match.group(1)
            tests_by_class[current_class] = []
        
        method_match = re.match(r'\s+def (test_\w+)\(', line)
        if method_match and current_class:
            tests_by_class[current_class].append(method_match.group(1))
    
    return {
        'total_methods': len(test_methods),
        'total_classes': len(test_classes),
        'test_methods': test_methods,
        'test_classes': test_classes,
        'tests_by_class': tests_by_class
    }


def print_test_breakdown(test_info: dict):
    """Print detailed test breakdown"""
    print("\n" + "="*70)
    print("📊 TEST FILE ANALYSIS")
    print("="*70)
    
    print(f"\n✅ Total Test Methods: {test_info['total_methods']}")
    print(f"📦 Total Test Classes: {test_info['total_classes']}")
    
    print("\n📋 Test Breakdown by Class:")
    print("-" * 70)
    
    total = 0
    for class_name, methods in test_info['tests_by_class'].items():
        count = len(methods)
        total += count
        print(f"\n  {class_name}: {count} tests")
        for i, method in enumerate(methods, 1):
            print(f"    {i}. {method}")
    
    print("\n" + "-" * 70)
    print(f"  TOTAL: {total} test methods")
    print("="*70 + "\n")


def run_pytest_collect():
    """Run pytest --collect-only to see what pytest finds"""
    print("\n" + "="*70)
    print("🔍 PYTEST COLLECTION (what pytest sees)")
    print("="*70 + "\n")
    
    result = subprocess.run(
        ['pytest', 'test/', '--collect-only', '-q'],
        capture_output=True,
        text=True
    )
    
    print(result.stdout)
    if result.stderr:
        print("Errors:", result.stderr)
    
    # Extract count from output
    match = re.search(r'(\d+) test', result.stdout)
    if match:
        return int(match.group(1))
    return 0


def run_tests_verbose():
    """Run pytest with verbose output"""
    print("\n" + "="*70)
    print("🧪 RUNNING TESTS")
    print("="*70 + "\n")
    
    result = subprocess.run(
        ['pytest', 'test/', '-v', '--tb=short', '--color=yes'],
        capture_output=False  # Show output in real-time
    )
    
    return result.returncode


def run_tests_with_coverage():
    """Run tests with coverage report"""
    print("\n" + "="*70)
    print("📈 RUNNING TESTS WITH COVERAGE")
    print("="*70 + "\n")
    
    result = subprocess.run(
        ['pytest', 'test/', '-v', '--cov=.', '--cov-report=term-missing'],
        capture_output=False
    )
    
    return result.returncode


def run_tests_by_marker():
    """Run tests grouped by markers"""
    markers = ['unit', 'integration', 'api', 'agent', 'template']
    
    print("\n" + "="*70)
    print("🏷️  TESTS BY MARKER")
    print("="*70 + "\n")
    
    for marker in markers:
        print(f"\n📌 Running {marker} tests...")
        result = subprocess.run(
            ['pytest', 'test/', '-m', marker, '-v', '--tb=line'],
            capture_output=True,
            text=True
        )
        
        # Count tests
        match = re.search(r'(\d+) passed', result.stdout)
        count = match.group(1) if match else "0"
        print(f"  ✓ {count} {marker} tests found")


def main():
    """Main test runner"""
    print("\n" + "="*70)
    print("🚀 GOOGLE DOCS AGENT TEST SUITE")
    print("="*70)
    
    # Check if test directory exists
    test_dir = Path('test')
    if not test_dir.exists():
        print(f"\n❌ Error: test/ directory not found")
        print(f"   Current directory: {Path.cwd()}")
        return 1
    
    # Find test files
    test_files = list(test_dir.glob('test_*.py'))
    print(f"\n📁 Found {len(test_files)} test file(s):")
    for f in test_files:
        print(f"   - {f}")
    
    # Analyze test file
    if test_files:
        test_file = test_files[0]  # Analyze first test file
        print(f"\n🔬 Analyzing: {test_file}")
        
        test_info = count_tests_in_file(test_file)
        print_test_breakdown(test_info)
    
    # Let pytest collect tests
    pytest_count = run_pytest_collect()
    
    print(f"\n📊 COMPARISON:")
    print(f"   Manual count: {test_info['total_methods']} test methods")
    print(f"   Pytest found: {pytest_count} tests")
    
    if test_info['total_methods'] != pytest_count:
        print(f"\n⚠️  Discrepancy detected!")
        print(f"   Difference: {abs(test_info['total_methods'] - pytest_count)}")
    else:
        print(f"\n✅ Counts match!")
    
    # Ask user what to run
    print("\n" + "="*70)
    print("Choose test mode:")
    print("="*70)
    print("  1. Run all tests (standard)")
    print("  2. Run all tests (verbose)")
    print("  3. Run with coverage")
    print("  4. Run by markers")
    print("  5. Run specific test class")
    print("  0. Exit")
    print("="*70)
    
    choice = input("\nEnter choice (1-5, 0 to exit): ").strip()
    
    if choice == '0':
        print("\n👋 Exiting...")
        return 0
    elif choice == '1':
        return subprocess.run(['pytest', 'test/', '--tb=short']).returncode
    elif choice == '2':
        return run_tests_verbose()
    elif choice == '3':
        return run_tests_with_coverage()
    elif choice == '4':
        run_tests_by_marker()
        return 0
    elif choice == '5':
        print("\nAvailable test classes:")
        for i, class_name in enumerate(test_info['test_classes'], 1):
            print(f"  {i}. {class_name}")
        
        class_choice = input("\nEnter class number: ").strip()
        try:
            idx = int(class_choice) - 1
            class_name = test_info['test_classes'][idx]
            return subprocess.run([
                'pytest', 'test/', '-k', class_name, '-v'
            ]).returncode
        except (ValueError, IndexError):
            print("Invalid choice")
            return 1
    else:
        print("Invalid choice")
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n❌ Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)