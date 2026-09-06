#!/usr/bin/env bash
# Build both copies under AddressSanitizer and run the same inputs through each.
#
# Every case asserts two things: that the vulnerable copy fails in the specific
# way the defect predicts, and that the fixed copy handles the same input
# correctly. A test that only checked the fix would not prove the fix was
# needed.
set -u

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(dirname "$here")"
build="$root/build"
cases="$here/cases"

mkdir -p "$build"

SAN="-fsanitize=address,undefined -fno-omit-frame-pointer -g -O1"
export ASAN_OPTIONS="detect_leaks=1:abort_on_error=0"

pass=0
fail=0

ok()   { printf '  ok   %s\n' "$1"; pass=$((pass + 1)); }
bad()  { printf '  FAIL %s\n     %s\n' "$1" "$2"; fail=$((fail + 1)); }

# --- build ------------------------------------------------------------------

printf 'building\n'
# shellcheck disable=SC2086
if ! gcc $SAN -o "$build/hdrparse-vulnerable" "$root/vulnerable/hdrparse.c" 2> "$build/build-vulnerable.log"; then
    printf '  FAIL vulnerable copy did not build\n'
    cat "$build/build-vulnerable.log"
    exit 1
fi
ok "vulnerable copy builds"
# shellcheck disable=SC2086
if ! gcc $SAN -Wall -Wextra -Werror -o "$build/hdrparse-fixed" "$root/fixed/hdrparse.c" 2> "$build/build-fixed.log"; then
    printf '  FAIL fixed copy did not build clean under -Wall -Wextra -Werror\n'
    cat "$build/build-fixed.log"
    exit 1
fi
ok "fixed copy builds clean under -Wall -Wextra -Werror"

VULN="$build/hdrparse-vulnerable"
FIXED="$build/hdrparse-fixed"

# run <binary> <case> -> writes $out and $err, sets $status
run() {
    out="$build/out.txt"; err="$build/err.txt"
    "$1" "$cases/$2" > "$out" 2> "$err"
    status=$?
}

# --- the format string is caught before the program ever runs ----------------

printf '\nCWE-134, a value used as a format string\n'
# shellcheck disable=SC2086
if gcc $SAN -Werror=format-security -o "$build/probe" "$root/vulnerable/hdrparse.c" 2> "$build/fmt-vulnerable.log"; then
    bad "vulnerable copy should be rejected by -Werror=format-security" "it compiled"
else
    if grep -q 'format-security' "$build/fmt-vulnerable.log"; then
        ok "vulnerable copy is rejected by -Werror=format-security"
    else
        bad "vulnerable copy failed to build for the wrong reason" "$(head -3 "$build/fmt-vulnerable.log")"
    fi
fi
# shellcheck disable=SC2086
if gcc $SAN -Werror=format-security -o "$build/probe" "$root/fixed/hdrparse.c" 2> /dev/null; then
    ok "fixed copy passes -Werror=format-security"
else
    bad "fixed copy should pass -Werror=format-security" "it did not compile"
fi

# --- well-formed input: both agree ------------------------------------------

printf '\nwell-formed input\n'
run "$VULN" good.txt;  vuln_status=$status; cp "$out" "$build/good-vulnerable.txt"
run "$FIXED" good.txt; fixed_status=$status; cp "$out" "$build/good-fixed.txt"
if [ "$vuln_status" -eq 0 ] && [ "$fixed_status" -eq 0 ]; then
    ok "both copies accept a well-formed header block"
else
    bad "both copies should accept well-formed input" "vulnerable exited $vuln_status, fixed exited $fixed_status"
fi
if diff -q "$build/good-vulnerable.txt" "$build/good-fixed.txt" > /dev/null; then
    ok "the fix does not change the output for well-formed input"
else
    bad "the fix changed the output for well-formed input" "$(diff "$build/good-vulnerable.txt" "$build/good-fixed.txt" | head -5)"
fi

# expect_asan <case> <sanitizer error substring> <human label>
expect_asan() {
    run "$VULN" "$1"
    if [ "$status" -eq 0 ]; then
        bad "$3: vulnerable copy should have been caught" "it exited 0"
    elif grep -q "$2" "$err"; then
        ok "$3: vulnerable copy aborts with $2"
        cp "$err" "$build/asan-${1%.txt}.txt"
    else
        bad "$3: vulnerable copy failed without reporting $2" "$(grep -m1 'ERROR' "$err")"
    fi
}

# expect_rejected <case> <message substring> <human label>
expect_rejected() {
    run "$FIXED" "$1"
    if [ "$status" -eq 1 ] && grep -q "$2" "$err"; then
        ok "$3: fixed copy exits 1 saying \"$(tr -d '\n' < "$err")\""
    else
        bad "$3: fixed copy should exit 1 mentioning \"$2\"" "exited $status: $(head -1 "$err")"
    fi
}

printf '\nCWE-787, unbounded copy into a fixed buffer\n'
expect_asan     long-name.txt "heap-buffer-overflow" "80-character Name into a 32-byte buffer"
expect_rejected long-name.txt "Name is 80 characters" "80-character Name into a 32-byte buffer"

printf '\nCWE-193, off-by-one on the terminator\n'
expect_asan     tag-boundary.txt "heap-buffer-overflow" "16-character Tag into a 16-byte buffer"
expect_rejected tag-boundary.txt "Tag is 16 characters" "16-character Tag into a 16-byte buffer"

printf '\nCWE-122, a length field taken on trust\n'
expect_asan     extra-roles.txt "heap-buffer-overflow" "five Role lines after a Roles count of 2"
expect_rejected extra-roles.txt "more Role lines than the Roles count of 2" "five Role lines after a Roles count of 2"

printf '\nCWE-416, a pointer kept past the free\n'
expect_asan     two-notes.txt "heap-use-after-free" "a second Note frees what first_note points at"
run "$FIXED" two-notes.txt
if [ "$status" -eq 0 ] && grep -q '^first : first note (10 characters)$' "$out" && grep -q '^note  : second note$' "$out"; then
    ok "a second Note frees what first_note points at: fixed copy keeps both notes correctly"
else
    bad "fixed copy should print both notes" "exited $status: $(tr '\n' '|' < "$out")"
fi

# --- summary ----------------------------------------------------------------

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
