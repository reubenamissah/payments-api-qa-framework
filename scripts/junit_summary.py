"""Print a Markdown test summary from a JUnit XML file (used for the GitHub Actions job summary)."""
import sys
import xml.etree.ElementTree as ET


def main(path: str) -> None:
    root = ET.parse(path).getroot()
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    total, failures = int(suite.get("tests")), int(suite.get("failures"))
    errors, skipped = int(suite.get("errors")), int(suite.get("skipped"))
    passed = total - failures - errors - skipped
    print("### API test results\n")
    print("| Total | Passed | Failed | Errors | Skipped | Duration |")
    print("|---|---|---|---|---|---|")
    print(f"| {total} | {passed} | {failures} | {errors} | {skipped} | {float(suite.get('time')):.1f}s |")
    bad = [c for c in suite.iter("testcase") if c.find("failure") is not None or c.find("error") is not None]
    if bad:
        print("\n**Failing tests**\n")
        for case in bad:
            print(f"- `{case.get('classname')}::{case.get('name')}`")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "reports/junit.xml")
