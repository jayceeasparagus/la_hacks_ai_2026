"""python -m policy.cli "<policy>" --zones policy/tests/fixtures/zones_demo.json"""

import argparse
import json
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

from policy import llm
from policy.compiler import compile_policy_with_info
from policy.contracts import Zone
from policy.describe import describe_rule

DEFAULT_ZONES = Path(__file__).parent / "tests" / "fixtures" / "zones_demo.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile a plain-English policy into PolicyLens rules.")
    parser.add_argument("prompt", help="the policy text")
    parser.add_argument("--zones", type=Path, default=DEFAULT_ZONES, help="JSON list of zones")
    parser.add_argument("--json", action="store_true", help="print the raw CompileResult JSON")
    parser.add_argument("-v", "--verbose", action="store_true", help="show log lines")
    args = parser.parse_args()

    load_dotenv()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    zones = [Zone.model_validate(z) for z in json.loads(args.zones.read_text(encoding="utf-8"))]
    print(f"model: {'FAKE (offline fallback)' if llm.fake_mode() else llm.policy_model()}")

    result, info = compile_policy_with_info(args.prompt, zones)
    if args.json:
        print(result.model_dump_json(indent=2))
    else:
        _print_table(result, zones)
    print(f"\nlatency: {info.latency_ms} ms   source: {info.source}")


def _print_table(result, zones) -> None:
    zone_names = {z.id: z.name for z in zones}
    rows = [("id", "name", "zone", "condition", "duration", "severity")]
    for r in result.rules:
        rows.append((r.id, r.name, zone_names.get(r.zone, r.zone), describe_rule(r, zones),
                     f"{r.duration_seconds:g} s", r.severity))
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    print()
    for i, row in enumerate(rows):
        print("  ".join(cell.ljust(w) for cell, w in zip(row, widths)))
        if i == 0:
            print("  ".join("-" * w for w in widths))
    if not result.rules:
        print("(no rules)")
    for title, items in (("warnings", result.warnings), ("unsupported", result.unsupported)):
        if items:
            print(f"\n{title}:")
            for item in items:
                print(f"  - {item}")


if __name__ == "__main__":
    sys.exit(main())
