#!/bin/sh
# Exit code test for input errors (issue D2). Input errors exit with 2. No GPU needed.
# Usage: exit_codes.sh <h4nb_run> <h4nb_study>
# Each case checks the exit code and a word in the error text. The word shows the error is the one meant.
set -u
run=$1
study=$2
dir=$(mktemp -d) || exit 1
trap 'rm -rf "$dir"' EXIT
fails=0

# expect <code> <word> <command...>: the command must exit with <code> and print <word> on stderr.
expect() {
  want=$1
  word=$2
  shift 2
  rc=0
  "$@" >"$dir/out" 2>"$dir/err" || rc=$?
  if [ "$rc" -ne "$want" ] || ! grep -q -- "$word" "$dir/err"; then
    echo "FAIL: exit $rc, want $want, word '$word': $*" >&2
    cat "$dir/err" >&2
    fails=$((fails + 1))
  fi
}

printf '0 1 0 0 0 0 0 0\n1 0.001 1 0 0 0 0 1\n' >"$dir/ok.txt"
printf '0 1 0 0 0 0 0 0\n0 0.001 1 0 0 0 0 1\n' >"$dir/dup.txt"
printf '0 1 0 0 0 0 0 0\n' >"$dir/one.txt"

expect 2 "repeated ID" "$run" ic="$dir/dup.txt" out="$dir/r1" t_end=1      # bad ic: repeated ID
expect 2 "cannot open" "$run" ic="$dir/missing.txt" out="$dir/r2" t_end=1  # bad ic: missing file
expect 2 "nosuchkey" "$run" ic="$dir/ok.txt" out="$dir/r3" t_end=1 nosuchkey=1  # unknown key
expect 2 "G=-1 (cli): out of range (> 0)" "$run" ic="$dir/ok.txt" out="$dir/r4" t_end=1 G=-1           # bad G
expect 2 "must be >= 2" "$study" ic="$dir/one.txt" out="$dir/s1" diag=1               # one particle
expect 2 "eta_init" "$run" ic="$dir/ok.txt" out="$dir/r5" t_end=1 eta_init=-1         # bad eta_init (>= 0 is valid)
expect 2 "eta_init" "$study" ic="$dir/ok.txt" out="$dir/s2" diag=1 eta_init=-1        # bad eta_init (study)
expect 2 "energy_norm" "$run" ic="$dir/ok.txt" out="$dir/r6" t_end=1 energy_norm=l2  # bad energy_norm (run)
expect 2 "energy_norm" "$study" ic="$dir/ok.txt" out="$dir/s3" diag=1 energy_norm=l2 # bad energy_norm (study)

if [ "$fails" -ne 0 ]; then
  echo "exit_codes: $fails check(s) failed" >&2
  exit 1
fi
echo "exit_codes: all checks passed"
