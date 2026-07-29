"""Fail if the portable suite skipped anything.

`pytest` exits 0 on a run where tests were skipped, so "the suite passed" and
"the suite ran" are different statements and only the second one is worth
anything before a release. This project has been bitten by the difference more
than once, which is why the check is asserted rather than eyeballed.

It lives in a file instead of inline in each workflow because three copies of
the same twelve lines is how the artifact list once drifted: the copies do not
fail when they disagree, they just stop meaning the same thing.

Usage: python scripts/check_no_skips.py <junit-xml>
"""
import sys
import xml.etree.ElementTree as ET


def main(report_path: str) -> int:
    suite = ET.parse(report_path).getroot().find("testsuite")
    if suite is None:
        print(f"{report_path} contains no testsuite element", file=sys.stderr)
        return 1

    total = int(suite.get("tests", 0))
    if not total:
        # A report of zero tests is the failure mode this guard exists for in
        # its purest form: nothing ran, nothing failed, the workflow is green.
        print(f"{report_path} reports no tests at all", file=sys.stderr)
        return 1

    skipped = [f'{case.get("classname")}::{case.get("name")}'
               for case in suite.iter("testcase")
               if case.find("skipped") is not None]
    if skipped:
        print(f"{len(skipped)} test(s) skipped in the portable suite: {skipped}",
              file=sys.stderr)
        return 1

    print(f"{total} tests, no skips")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
