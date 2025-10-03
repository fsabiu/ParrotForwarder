#!/usr/bin/env python3
"""
Test runner for ParrotForwarder

Convenience script to run all tests from the project root.
"""

import sys
import os
import subprocess

def run_test(test_file):
    """Run a specific test file."""
    test_path = os.path.join('tests', test_file)
    if not os.path.exists(test_path):
        print(f"Test file not found: {test_path}")
        return False
    
    print(f"\n{'='*60}")
    print(f"Running {test_file}")
    print(f"{'='*60}")
    
    try:
        result = subprocess.run([sys.executable, test_path], 
                              cwd=os.path.dirname(os.path.abspath(__file__)))
        return result.returncode == 0
    except Exception as e:
        print(f"Error running {test_file}: {e}")
        return False

def main():
    """Run all available tests."""
    print("ParrotForwarder Test Suite")
    print("=" * 60)
    
    # List of test files to run
    test_files = [
        'test_mediamtx_integration.py',
        'test_drone_connection.py', 
        'test_video_stream.py'
    ]
    
    results = []
    for test_file in test_files:
        if os.path.exists(os.path.join('tests', test_file)):
            success = run_test(test_file)
            results.append((test_file, success))
        else:
            print(f"Skipping {test_file} (not found)")
    
    # Summary
    print(f"\n{'='*60}")
    print("Test Results Summary")
    print(f"{'='*60}")
    
    passed = 0
    for test_file, success in results:
        status = "✓ PASS" if success else "✗ FAIL"
        print(f"{status} - {test_file}")
        if success:
            passed += 1
    
    print(f"\nPassed: {passed}/{len(results)} tests")
    
    if passed == len(results):
        print("🎉 All tests passed!")
        return 0
    else:
        print("⚠ Some tests failed.")
        return 1

if __name__ == '__main__':
    sys.exit(main())
