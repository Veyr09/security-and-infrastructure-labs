"""Read a Terraform plan and report what will drive the monthly AWS bill.

Usage:
    terraform show -json plan.out > plan.json
    python costcheck.py plan.json --rates rates.example.json
    python costcheck.py plan.json --rates rates.example.json --fail-over 200

Rates are an input, not a claim. AWS list prices change, and a tool that hardcodes
them starts lying quietly the moment they do. The rates file carries its own
provenance line and this report prints it, so any number in the output can be
traced back to a price somebody checked on a date.

What this does not do: it reads intent from a plan, not usage from a bill. It can
say a NAT gateway costs a fixed amount per hour before a byte moves through it; it
cannot say how many bytes will. Where a rule depends on usage, the report says so
and leaves that part out of the totals.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# A NAT gateway is billed per hour whether or not traffic flows, so a second and
# third one for availability multiply a fixed cost rather than a usage-based one.
NAT_GATEWAYS_BEFORE_FLAGGING = 1
# Lambda cost is memory x duration. Above this, memory is worth measuring rather
# than assuming, because most handlers do not use what they reserve.
LAMBDA_MEMORY_MB_WORTH_CHECKING = 1024
# Retention absent or zero both mean "never expire" in CloudWatch Logs.
NEVER_EXPIRES = (None, 0)
GB_PER_MB = 1 / 1024
MULTI_AZ_MULTIPLIER = 2
DEFAULT_LAMBDA_TIMEOUT_SECONDS = 3
DEFAULT_LAMBDA_MEMORY_MB = 128


def resources(plan: dict) -> list[dict]:
    module = plan.get("planned_values", {}).get("root_module", {})
    found = list(module.get("resources", []))
    for child in module.get("child_modules", []):
        found.extend(child.get("resources", []))
    return found


def of_type(rs: list[dict], type_: str) -> list[dict]:
    return [r for r in rs if r.get("type") == type_]


def money(value: float) -> str:
    return f"${value:,.2f}"


def check_nat_gateways(rs, rates):
    gateways = of_type(rs, "aws_nat_gateway")
    if len(gateways) <= NAT_GATEWAYS_BEFORE_FLAGGING:
        return None
    hourly = rates["nat_gateway_hourly"]
    monthly = hourly * rates["hours_per_month"] * len(gateways)
    avoidable = hourly * rates["hours_per_month"] * (len(gateways) - 1)
    return {
        "rule": "nat-gateway-per-az",
        "resources": [g["address"] for g in gateways],
        "monthly": monthly,
        "monthly_avoidable": avoidable,
        "usage_dependent": (f"plus {money(rates['nat_gateway_per_gb'])}/GB processed, "
                            f"which a plan cannot predict"),
        "why": (f"{len(gateways)} NAT gateways at {money(hourly)}/hour each, billed whether or not "
                f"traffic flows. One per availability zone is the right answer when an AZ outage "
                f"must not take egress down, and the wrong answer when it was the default and "
                f"nobody priced it."),
        "options": [
            "Keep all three only if AZ-independent egress is a stated requirement.",
            "One NAT gateway shared across AZs: cheaper, and egress dies with that AZ.",
            "VPC endpoints for S3 and DynamoDB, so that traffic skips the NAT entirely.",
        ],
    }


def check_log_retention(rs, rates):
    groups = [g for g in of_type(rs, "aws_cloudwatch_log_group")
              if g.get("values", {}).get("retention_in_days") in NEVER_EXPIRES]
    if not groups:
        return None
    return {
        "rule": "log-group-never-expires",
        "resources": [g["address"] for g in groups],
        "monthly": None,
        "usage_dependent": (f"{money(rates['cloudwatch_logs_storage_per_gb_month'])}/GB-month "
                            f"against a volume that only grows"),
        "why": ("These log groups have no retention set, which in CloudWatch Logs means never "
                "expire. The bill is small in month one and is still being paid in year three for "
                "logs nobody will read. Cheapest line to fix, and the one most often missed."),
        "options": [
            "Set retention_in_days on every group: 30 days for application logs, longer only "
            "where a regulation names a number.",
            "Export to S3 with a lifecycle rule if something genuinely has to be kept.",
        ],
    }


def check_rds(rs, rates):
    findings = []
    for db in of_type(rs, "aws_db_instance"):
        values = db.get("values", {})
        klass = values.get("instance_class")
        hourly = rates["rds_instance_hourly"].get(klass)
        if hourly is None:
            findings.append({
                "rule": "rds-unpriced-class",
                "resources": [db["address"]],
                "monthly": None,
                "why": f"{klass} is not in the rates file, so its cost cannot be shown here.",
                "options": [f"Add {klass} to the rates file and re-run."],
            })
            continue
        multi_az = bool(values.get("multi_az"))
        multiplier = MULTI_AZ_MULTIPLIER if multi_az else 1
        instance_monthly = hourly * rates["hours_per_month"] * multiplier
        storage_gb = values.get("allocated_storage") or 0
        storage_type = values.get("storage_type") or "gp2"
        per_gb = rates["rds_storage_per_gb_month"].get(storage_type, 0)
        storage_monthly = storage_gb * per_gb * multiplier
        findings.append({
            "rule": "rds-cost-drivers",
            "resources": [db["address"]],
            "monthly": instance_monthly + storage_monthly,
            "why": (f"{klass} at {money(hourly)}/hour"
                    + (", doubled by multi_az" if multi_az else "")
                    + f", plus {storage_gb} GB of {storage_type} storage"
                    + (" also doubled by multi_az" if multi_az else "")
                    + ". Usually the largest single line in a small stack, and the instance class "
                      "is usually the number nobody revisited after launch."),
            "options": [
                "Measure CPU and connections for a week before resizing. A class chosen on a "
                "guess is not evidence for the next guess.",
                "gp3 storage instead of gp2 where the engine supports it.",
                "Multi-AZ earns its doubling for a production database and is worth questioning "
                "for anything else.",
            ],
        })
    return findings


def check_lambda_memory(rs, rates):
    findings = []
    for fn in of_type(rs, "aws_lambda_function"):
        values = fn.get("values", {})
        memory = values.get("memory_size") or DEFAULT_LAMBDA_MEMORY_MB
        if memory < LAMBDA_MEMORY_MB_WORTH_CHECKING:
            continue
        timeout = values.get("timeout") or DEFAULT_LAMBDA_TIMEOUT_SECONDS
        worst_case_gb_seconds = memory * GB_PER_MB * timeout
        per_run = rates["lambda_per_gb_second"] * worst_case_gb_seconds
        findings.append({
            "rule": "lambda-memory-reserved-not-measured",
            "resources": [fn["address"]],
            "monthly": None,
            "usage_dependent": (f"{money(per_run)} per invocation that runs to the full "
                                f"{timeout}s timeout"),
            "why": (f"{memory} MB reserved. Lambda bills memory multiplied by duration, so the "
                    f"reservation is paid on every invocation whether the handler uses it or not. "
                    f"More memory also buys more CPU, so cutting it blindly can cost more by "
                    f"making runs longer. This one needs measuring, not guessing."),
            "options": [
                "Read the Max Memory Used line the platform already writes to the log on every "
                "invocation. That is the measurement, and it is free.",
                "Tune memory against measured duration rather than downward on principle.",
            ],
        })
    return findings


def check_gp2_volumes(rs, rates):
    volumes = [v for v in of_type(rs, "aws_ebs_volume")
               if (v.get("values", {}).get("type") or "gp2") == "gp2"]
    if not volumes:
        return None
    gp2 = rates["ebs_per_gb_month"]["gp2"]
    gp3 = rates["ebs_per_gb_month"]["gp3"]
    total_gb = sum(v.get("values", {}).get("size") or 0 for v in volumes)
    return {
        "rule": "ebs-gp2-not-gp3",
        "resources": [v["address"] for v in volumes],
        "monthly": total_gb * gp2,
        "monthly_avoidable": total_gb * (gp2 - gp3),
        "why": (f"{total_gb} GB on gp2. gp3 is cheaper per GB and lets IOPS be set independently "
                f"of size, which is the reason gp2 volumes get over-provisioned in the first "
                f"place."),
        "options": ["Modify in place: gp2 to gp3 does not require detaching the volume."],
    }


def check_idle_eips(rs, rates):
    """Elastic IPs left over once every NAT gateway has one.

    Allocation ids are unknown until apply, so a plan cannot match an address to
    the gateway that will hold it. Counting is what a plan supports: more
    addresses than gateways means addresses nothing will attach to.
    """
    eips = of_type(rs, "aws_eip")
    gateways = of_type(rs, "aws_nat_gateway")
    idle = len(eips) - len(gateways)
    if idle <= 0:
        return None
    return {
        "rule": "elastic-ip-idle",
        "resources": [e["address"] for e in eips],
        "monthly": idle * rates["eip_idle_hourly"] * rates["hours_per_month"],
        "why": (f"{len(eips)} elastic IPs against {len(gateways)} NAT gateways, so {idle} will "
                f"attach to nothing. An elastic IP not attached to a running resource is billed "
                f"hourly."),
        "options": ["Release the ones nothing points at."],
    }


CHECKS = [check_nat_gateways, check_log_retention, check_rds,
          check_lambda_memory, check_gp2_volumes, check_idle_eips]


def run(plan: dict, rates: dict) -> list[dict]:
    rs = resources(plan)
    findings = []
    for check in CHECKS:
        result = check(rs, rates)
        if isinstance(result, list):
            findings.extend(result)
        elif result:
            findings.append(result)
    findings.sort(key=lambda f: f.get("monthly") or 0, reverse=True)
    return findings


def render(findings: list[dict], rates: dict, resource_count: int) -> str:
    lines = [
        "Terraform plan cost review",
        "=" * 72,
        f"Resources in plan : {resource_count}",
        f"Findings          : {len(findings)}",
        f"Rates             : {rates.get('_provenance', 'no provenance recorded')}",
        f"Rates checked     : {rates.get('_checked', 'unknown')}",
        "",
    ]
    fixed_total = sum(f["monthly"] for f in findings if f.get("monthly"))
    avoidable = sum(f.get("monthly_avoidable") or 0 for f in findings)
    for finding in findings:
        head = f"[{finding['rule']}]"
        if finding.get("monthly"):
            head += f"  {money(finding['monthly'])}/month"
        if finding.get("monthly_avoidable"):
            head += f"  ({money(finding['monthly_avoidable'])} of it avoidable)"
        lines.append(head)
        for address in finding["resources"]:
            lines.append(f"    {address}")
        lines.append(f"    {finding['why']}")
        if finding.get("usage_dependent"):
            lines.append(f"    Usage-dependent, excluded from the total: {finding['usage_dependent']}")
        for option in finding.get("options", []):
            lines.append(f"    - {option}")
        lines.append("")
    lines.append("-" * 72)
    lines.append(f"Fixed monthly cost identified : {money(fixed_total)}")
    lines.append(f"Of which avoidable outright   : {money(avoidable)}")
    lines.append("Usage-dependent lines are excluded from both totals, because a plan")
    lines.append("describes what will exist, not how hard it will be used.")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("plan", help="output of: terraform show -json plan.out")
    parser.add_argument("--rates", required=True)
    parser.add_argument("--fail-over", type=float, default=None,
                        help="exit 1 if the identified fixed monthly cost exceeds this")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    rates = json.loads(Path(args.rates).read_text(encoding="utf-8"))
    findings = run(plan, rates)
    total = sum(f["monthly"] for f in findings if f.get("monthly"))

    if args.json:
        print(json.dumps({"findings": findings, "fixed_monthly_total": total}, indent=2))
    else:
        print(render(findings, rates, len(resources(plan))))

    if args.fail_over is not None and total > args.fail_over:
        print(f"\nFAIL: {money(total)} exceeds the {money(args.fail_over)} threshold",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
