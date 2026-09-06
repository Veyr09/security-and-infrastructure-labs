# Five memory-safety defects in a small C parser, demonstrated and fixed

`hdrparse` reads a `Key: value` header block and prints a summary. There are two
copies of it. `vulnerable/` contains five defects of the kind that actually turn
up in C that parses input somebody else wrote. `fixed/` is the same program with
all five closed. The test suite runs the same inputs through both and asserts
that the vulnerable copy fails in the specific way each defect predicts, and
that the fixed copy handles the same input correctly.

That second half is the point. A test that only exercises the fix does not show
the fix was needed, and cannot tell you later if someone quietly reintroduces
the bug.

## Run it

```
bash tests/run_tests.sh
```

Needs `gcc` with AddressSanitizer. No other dependencies. Both copies are built
with `-fsanitize=address,undefined`; the fixed copy is additionally built with
`-Wall -Wextra -Werror` and has to compile clean.

Measured on Ubuntu 26.04 LTS under WSL2, gcc 15.2.0: **14 assertions, all passing.**
Captured output is in `sample/test-run.txt`.

## The five defects

| # | CWE | Where | What happens |
|---|---|---|---|
| 1 | CWE-787 | `strcpy(h.name, value)` | An 80-character `Name` is copied into a 32-byte buffer. |
| 2 | CWE-193 | `if (n > TAG_LEN) n = TAG_LEN;` | The limit forgets the terminator, so a 16-character `Tag` writes one byte past a 16-byte buffer. |
| 3 | CWE-122 | `h.roles[h.roles_seen++]` | The `Roles: 2` count is trusted and the `Role:` lines are never counted against it. |
| 4 | CWE-416 | `h.first_note = h.note` | A second `Note:` frees the allocation that `first_note` still points at. |
| 5 | CWE-134 | `printf(h.note)` | A value from the input is used as the format string. |

Numbers 1 to 4 abort under AddressSanitizer with the input files in
`tests/cases/`. Number 5 is caught earlier than that — see below.

## What a finding looks like

From `sample/asan-long-name.txt`, the report for defect 1:

```
==791==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x7c264a3e0060
WRITE of size 81 at 0x7c264a3e0060 thread T0
    #0 ... in strcpy
    #2 ... in main .../vulnerable/hdrparse.c:66

0x7c264a3e0060 is located 0 bytes after 32-byte region [0x7c264a3e0040,0x7c264a3e0060)
allocated by thread T0 here:
    #1 ... in main .../vulnerable/hdrparse.c:49
```

Write of 81 bytes, zero bytes past the end of a 32-byte region, with the line
that wrote it and the line that allocated it. That is the whole argument for
running a sanitizer rather than reading harder.

The same input against the fixed copy:

```
$ ./build/hdrparse-fixed tests/cases/long-name.txt
hdrparse: Name is 80 characters, limit is 31
$ echo $?
1
```

## Why the fixed copy refuses instead of truncating

Every over-long value is an error the caller is told about, not something
quietly shortened. Truncation turns a loud failure into a wrong answer, and a
wrong answer in a parser is how half a name ends up in a database three steps
later, where nobody connects it back to this program. The error names the field,
the length it got and the limit, because "invalid input" is not a bug report.

## The format string is caught before the program runs

`printf(h.note)` needs no sanitizer and no test input. The compiler already
knows:

```
vulnerable/hdrparse.c:96:9: error: format not a string literal and no format arguments
   96 |         printf(h.note);
      |         ^~~~~~
```

So the suite asserts that `gcc -Werror=format-security` **rejects** the
vulnerable copy and **accepts** the fixed one. Full output in
`sample/format-security.txt`. It is worth knowing which defects a build flag
removes for free, because those are the ones that should never reach a review.

## One thing that did not work, which is the useful part

The use-after-free was originally read by `printf("first : %s\n", h.first_note)`,
and **AddressSanitizer did not report it.** The program printed an empty field
and exited 0.

The reason is that glibc's `printf` walks the `%s` argument using functions
internal to libc, which are not instrumented and do not go through ASan's
interceptors. The same dangling pointer passed to `strlen` — which *is*
intercepted — is caught immediately. The line now reads:

```c
printf("first : %s (%zu characters)\n", h.first_note, strlen(h.first_note));
```

and the report appears:

```
==704==ERROR: AddressSanitizer: heap-use-after-free on address 0x7a527b5e0070
READ of size 2 at 0x7a527b5e0070 thread T0
    #0 ... in strlen
    #1 ... in main .../vulnerable/hdrparse.c:100

0x7a527b5e0070 is located 0 bytes inside of 11-byte region [...)
freed by thread T0 here:
    #1 ... in main .../vulnerable/hdrparse.c:82
previously allocated by thread T0 here:
    #1 ... in main .../vulnerable/hdrparse.c:83
```

Line 82 is the `free`, line 83 the `strdup` that replaced it, line 100 the read.
Full report in `sample/asan-two-notes.txt`.

The lesson is not about this program. It is that **a sanitizer that reports
nothing has not proved the code is clean** — it may simply not have been on the
path that touched the bad memory. That is the difference between "the tests
passed" and "the defect was demonstrated", and it is why every case here asserts
a specific error string rather than just a non-zero exit code.

## Files

- `vulnerable/hdrparse.c` — the five defects, each marked with its CWE
- `fixed/hdrparse.c` — the same program, all five closed
- `tests/run_tests.sh` — builds both, runs the corpus, 14 assertions
- `tests/cases/` — six input files, one per defect plus a well-formed control
- `sample/` — captured output from the run described above

## Honest scope

Built for this portfolio, not client work. `hdrparse` is a demonstration
program, not something to deploy. The defects are planted deliberately and are
not a report on anyone's code. Measurements are from one machine and one
compiler version.
