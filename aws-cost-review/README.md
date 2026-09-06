# Reading an AWS bill from the Terraform plan, before it arrives

A small stack, planned two ways, and a checker that reads the plan and says what
will drive the monthly bill. The untuned plan carries **$1,460.20/month** of fixed
cost; the tuned one carries **$340.22**, and the checker still reports the largest
remaining line, because reporting it is the point.

Nothing here is wrong in the untuned stack. It is what gets built when each piece
is added on its own and nobody adds up the monthly total afterwards.

## What it finds

| Rule | Untuned | Tuned |
|---|---|---|
| `rds-cost-drivers` | $1,322.52/mo — `db.m5.2xlarge`, multi-AZ, 500 GB gp2 | $340.22/mo — `db.m5.large`, multi-AZ, 200 GB gp3 |
| `nat-gateway-per-az` | $113.88/mo, $75.92 avoidable — three gateways | silent — one gateway |
| `ebs-gp2-not-gp3` | $23.80/mo, $4.76 avoidable | silent — gp3 |
| `log-group-never-expires` | two groups, kept forever | silent — 30 days |
| `lambda-memory-reserved-not-measured` | 3008 MB, 900 s timeout | silent — 512 MB, 30 s |
| `elastic-ip-idle` | **silent** — three addresses, three gateways | silent |

That last row matters as much as the others. A checker that flags everything tells
a client nothing about what to change, so a rule that stays quiet when it should is
tested as carefully as one that fires.

## Run it

```
cd lab
docker run --rm -v "$PWD:/work" -w /work hashicorp/terraform:1.9 init
docker run --rm -v "$PWD:/work" -w /work hashicorp/terraform:1.9 plan -out=plan.out
docker run --rm -v "$PWD:/work" -w /work hashicorp/terraform:1.9 show -json plan.out > plan.json
cd ..
python costcheck.py lab/plan.json --rates rates.example.json
python costcheck.py lab-tuned/plan.json --rates rates.example.json
python costcheck.py lab/plan.json --rates rates.example.json --fail-over 200   # exits 1
python -m unittest discover -s tests -v                                        # 26 tests
```

`plan.json` for both stacks is committed, so the checker and the tests run with
nothing installed but Python 3.10+. Terraform is only needed to regenerate them,
and on Windows the `docker run` lines need `MSYS_NO_PATHCONV=1` in Git Bash.

**The plan is produced offline.** `provider.tf` gives the AWS provider static fake
credentials and turns off credential validation, the STS account lookup and the
metadata endpoint check, so `terraform plan` describes the intended infrastructure
without an AWS account existing anywhere. That is the whole point of reviewing the
plan rather than the bill: it works before anything is built, and before anyone has
handed over access.

## Rates are an input, not a claim

`rates.example.json` carries a provenance line and a date, and the report prints
both:

```
Rates             : eu-central-1 on-demand list prices. SNAPSHOT - verify against
                    the AWS pricing pages before quoting a client. Rates are an
                    input to this tool, not a claim made by it.
Rates checked     : 2026-09-06
```

AWS prices change. A tool that hardcodes them starts lying quietly the moment they
do, and the client has no way to tell. Supplying them as a file means every number
in the output can be traced to a price somebody checked on a day, and re-running
against a fresh rates file is a one-line change rather than a code change.

## What it deliberately does not do

It reads intent from a plan, not usage from a bill. It can say a NAT gateway costs
a fixed amount per hour before a byte moves through it; it cannot say how many
bytes will. Rules that depend on usage — log storage growth, Lambda invocation
volume, NAT data processing — report the rate and the driver and are **excluded
from the totals**, and the report says so at the bottom rather than quietly folding
a guess into a number that looks precise.

The RDS rule is named `rds-cost-drivers`, not `rds-oversized`, for the same reason.
Whether an instance class is too big is a question about measured CPU and
connections, which a plan does not contain. What the plan does contain is the
arithmetic: the class, the multi-AZ doubling, the storage type and size. The report
shows that and says to measure for a week before resizing.

## Two failure modes the tests exist to catch

**A resource the tool cannot price vanishing from the report.** If an RDS class is
missing from the rates file, the total would silently be too low and read as
complete. `rds-unpriced-class` reports it with no figure instead, and a test asserts
that.

**Resources inside modules being missed.** Real stacks put things in modules. A
checker that only walks the root module returns a clean bill for a plan it never
looked at, which is worse than no tool at all. `resources()` walks child modules and
a test plants a gp2 volume in one.
