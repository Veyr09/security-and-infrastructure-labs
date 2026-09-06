# Security and infrastructure labs

Ten small projects. Each one is a real problem, built and broken on purpose, then fixed, with the
evidence kept: real captured output rather than commands that ought to work, and tests that cover
the failure paths and the bad input rather than only the happy path.

They exist because "I can do X" is cheap to write. Every one of these runs.

## Security

| Lab | What it demonstrates |
|---|---|
| [`c-memory-safety`](c-memory-safety/) | Five memory-safety defects in a C header parser — CWE-787, CWE-193, CWE-122, CWE-416 and CWE-134 — each reproduced under AddressSanitizer and closed. 14 assertions. Includes one defect the sanitizer never catches, which is the point. |
| [`flask-api-review`](flask-api-review/) | A security review end to end: eight defects in a small Flask API, each proven by a test that attacks both copies and passes only against the fix. |
| [`multi-tenant-isolation`](multi-tenant-isolation/) | One timesheet service deployed three ways, and a probe that checks each deployment behaves the way its compose file claims. Cross-tenant reads, session replay, shared cache. |
| [`java-xxe`](java-xxe/) | What Java's `DocumentBuilderFactory` and `XMLInputFactory` do to an XML document out of the box, and the exact settings that stop it. Same four documents through a vulnerable and a hardened intake. |
| [`docker-port-hardening`](docker-port-hardening/) | A container publishing its port on every interface, closed and then **verified from outside the machine** — because localhost is where this check usually goes wrong. |

## Infrastructure and cost

| Lab | What it demonstrates |
|---|---|
| [`aws-cost-review`](aws-cost-review/) | Reads a Terraform plan and reports what will drive the monthly bill. The untuned stack carries $1,460.20/month of fixed cost, the tuned one $340.22. Planned offline with mock credentials, so it works before anything is built. 26 tests. |

## Tools and data

| Lab | What it demonstrates |
|---|---|
| [`csv-guard-rust`](csv-guard-rust/) | A dependency-free Rust CLI that validates a CSV against column rules in one streaming pass, explaining every rejection by line, column, value and reason. Memory is bounded by the widest record, not the file. |
| [`spreadsheet-cleanup`](spreadsheet-cleanup/) | Turns a messy orders export into a workbook you can use, and never drops a row silently — anything untrusted lands on an Issues sheet with its row number and the reason. |
| [`rates-sync`](rates-sync/) | Keeps an Excel workbook of ECB reference rates current, fetching only the days missing since the last row, so re-running it the same day changes nothing. |
| [`books-scraper`](books-scraper/) | A paginated scraper with paging, retries and rate limiting separated from the selectors, so pointing it at a different site is a change in one function. |

## How to read these

Every lab has a `README.md` with the exact commands and what they should print. `sample/` holds
output from a real run. Where a lab has a vulnerable copy, it is labelled and it is there so the
defect can be reproduced — **none of them should be deployed.**

Two habits run through all of them, and they are the ones worth judging the work by.

**A finding without a reproduction is not a finding.** Every defect here comes with the input that
triggers it and the output it produced, not a severity label.

**A test that cannot fail proves nothing.** The suites run the same inputs through the broken copy
and the fixed one, and assert that the broken copy actually breaks. Several also assert that a check
stays *silent* when it should, because a tool that flags everything tells you nothing about what to
change.

## Related

[`gitlab-security-research`](https://github.com/Veyr09/gitlab-security-research) — source-driven
review of GitLab's authorization architecture under its public bug bounty program: 21 access-control
hypotheses traced through the source to a verdict, and why each one is a dead end.
