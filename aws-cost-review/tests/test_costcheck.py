"""Tests for costcheck.

Two things these have to establish, not one. That each rule fires on the plan
that deserves it is the easy half; that each rule stops firing on the tuned plan
is what makes the report worth reading, because a checker that flags everything
tells a client nothing about what to change.

Run:  python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import costcheck  # noqa: E402

RATES = json.loads((ROOT / "rates.example.json").read_text(encoding="utf-8"))
UNTUNED = json.loads((ROOT / "lab" / "plan.json").read_text(encoding="utf-8"))
TUNED = json.loads((ROOT / "lab-tuned" / "plan.json").read_text(encoding="utf-8"))


def rules(plan: dict) -> set[str]:
    return {f["rule"] for f in costcheck.run(plan, RATES)}


def fixed_total(plan: dict) -> float:
    return sum(f["monthly"] for f in costcheck.run(plan, RATES) if f.get("monthly"))


def synthetic(resources: list[dict]) -> dict:
    return {"planned_values": {"root_module": {"resources": resources}}}


def resource(type_: str, name: str, **values) -> dict:
    return {"type": type_, "address": f"{type_}.{name}", "values": values}


class UntunedPlan(unittest.TestCase):
    """The plan as first written. Every rule that should fire, fires."""

    def test_nat_gateway_per_az_fires(self):
        self.assertIn("nat-gateway-per-az", rules(UNTUNED))

    def test_log_group_never_expires_fires(self):
        self.assertIn("log-group-never-expires", rules(UNTUNED))

    def test_retention_zero_counts_as_never(self):
        # One group omits retention_in_days and the other sets it to 0. Both mean
        # never expire, and a rule that only caught the missing one would miss half.
        finding = next(f for f in costcheck.run(UNTUNED, RATES)
                       if f["rule"] == "log-group-never-expires")
        self.assertEqual(len(finding["resources"]), 2)

    def test_rds_cost_drivers_fires(self):
        self.assertIn("rds-cost-drivers", rules(UNTUNED))

    def test_lambda_memory_fires(self):
        self.assertIn("lambda-memory-reserved-not-measured", rules(UNTUNED))

    def test_gp2_volume_fires(self):
        self.assertIn("ebs-gp2-not-gp3", rules(UNTUNED))

    def test_idle_eip_does_not_fire_when_every_address_is_used(self):
        # Three addresses, three gateways. Reporting these would be noise, and
        # noise is what stops a client reading the rest of the report.
        self.assertNotIn("elastic-ip-idle", rules(UNTUNED))

    def test_multi_az_doubles_the_instance_line(self):
        finding = next(f for f in costcheck.run(UNTUNED, RATES) if f["rule"] == "rds-cost-drivers")
        hourly = RATES["rds_instance_hourly"]["db.m5.2xlarge"]
        storage = 500 * RATES["rds_storage_per_gb_month"]["gp2"] * 2
        expected = hourly * RATES["hours_per_month"] * 2 + storage
        self.assertAlmostEqual(finding["monthly"], expected, places=6)

    def test_findings_are_ordered_by_cost(self):
        found = [f.get("monthly") or 0 for f in costcheck.run(UNTUNED, RATES)]
        self.assertEqual(found, sorted(found, reverse=True))


class TunedPlan(unittest.TestCase):
    """The plan after the review. The rules go quiet because the causes are gone."""

    def test_only_the_rds_driver_remains(self):
        self.assertEqual(rules(TUNED), {"rds-cost-drivers"})

    def test_the_remaining_finding_has_nothing_avoidable(self):
        finding = next(f for f in costcheck.run(TUNED, RATES) if f["rule"] == "rds-cost-drivers")
        self.assertIsNone(finding.get("monthly_avoidable"))

    def test_tuning_reduced_the_fixed_monthly_cost(self):
        self.assertLess(fixed_total(TUNED), fixed_total(UNTUNED))

    def test_one_nat_gateway_is_not_flagged(self):
        self.assertNotIn("nat-gateway-per-az", rules(TUNED))

    def test_gp3_is_not_flagged(self):
        self.assertNotIn("ebs-gp2-not-gp3", rules(TUNED))

    def test_512mb_lambda_is_not_flagged(self):
        self.assertNotIn("lambda-memory-reserved-not-measured", rules(TUNED))


class RulesInIsolation(unittest.TestCase):
    """Cases the two lab plans do not contain."""

    def test_idle_eip_fires_when_an_address_attaches_to_nothing(self):
        plan = synthetic([
            resource("aws_eip", "a"),
            resource("aws_eip", "b"),
            resource("aws_nat_gateway", "only", allocation_id=None),
        ])
        finding = next(f for f in costcheck.run(plan, RATES) if f["rule"] == "elastic-ip-idle")
        expected = 1 * RATES["eip_idle_hourly"] * RATES["hours_per_month"]
        self.assertAlmostEqual(finding["monthly"], expected, places=6)

    def test_unpriced_rds_class_is_reported_not_silently_skipped(self):
        # The dangerous failure for a cost tool is a resource it does not price
        # vanishing from the report, because the total then reads as complete.
        plan = synthetic([resource("aws_db_instance", "odd",
                                   instance_class="db.r7g.16xlarge", allocated_storage=100)])
        finding = next(f for f in costcheck.run(plan, RATES) if f["rule"] == "rds-unpriced-class")
        self.assertIn("db.r7g.16xlarge", finding["why"])
        self.assertIsNone(finding["monthly"])

    def test_single_nat_gateway_is_not_a_finding(self):
        plan = synthetic([resource("aws_nat_gateway", "only")])
        self.assertNotIn("nat-gateway-per-az", {f["rule"] for f in costcheck.run(plan, RATES)})

    def test_log_group_with_retention_is_not_a_finding(self):
        plan = synthetic([resource("aws_cloudwatch_log_group", "kept", retention_in_days=30)])
        self.assertEqual(costcheck.run(plan, RATES), [])

    def test_empty_plan_produces_no_findings(self):
        self.assertEqual(costcheck.run(synthetic([]), RATES), [])

    def test_resources_inside_child_modules_are_read(self):
        # Real stacks put things in modules. A checker that only walks the root
        # module reports a clean bill for a plan it never looked at.
        plan = {"planned_values": {"root_module": {"child_modules": [
            {"resources": [resource("aws_ebs_volume", "in_module", size=100, type="gp2")]}]}}}
        self.assertIn("ebs-gp2-not-gp3", {f["rule"] for f in costcheck.run(plan, RATES)})


class CommandLine(unittest.TestCase):

    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(ROOT / "costcheck.py"), str(ROOT / "lab" / "plan.json"),
             "--rates", str(ROOT / "rates.example.json"), *args],
            capture_output=True, text=True)

    def test_reports_and_exits_zero_without_a_threshold(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 0)
        self.assertIn("Fixed monthly cost identified", result.stdout)

    def test_prints_the_rate_provenance(self):
        # A number with no traceable source is the thing this tool exists to avoid.
        self.assertIn("SNAPSHOT", self.run_cli().stdout)

    def test_fail_over_exits_one_when_exceeded(self):
        result = self.run_cli("--fail-over", "100")
        self.assertEqual(result.returncode, 1)
        self.assertIn("exceeds", result.stderr)

    def test_fail_over_exits_zero_when_under(self):
        self.assertEqual(self.run_cli("--fail-over", "99999").returncode, 0)

    def test_json_output_is_valid_json(self):
        payload = json.loads(self.run_cli("--json").stdout)
        self.assertIn("fixed_monthly_total", payload)
        self.assertTrue(payload["findings"])


if __name__ == "__main__":
    unittest.main()
