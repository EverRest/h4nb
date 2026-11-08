#!/usr/bin/env bash
# Test of tools/h4nb_pack.sh on a small fake run directory. No GPU needed.
# Usage: test_pack.sh <path to h4nb_pack.sh>
# Exit 77 (skipped) when a tool is missing. The script needs GNU-style find -printf, tar and sha256sum.
set -u
script=$(cd "$(dirname "$1")" && pwd)/$(basename "$1")  # absolute: the test changes directory
for t in tar sha256sum; do
  command -v "$t" >/dev/null 2>&1 || { echo "test_pack: $t not found, skipped"; exit 77; }
done
find . -maxdepth 0 -printf '' >/dev/null 2>&1 || { echo "test_pack: find has no -printf, skipped"; exit 77; }

fails=0
check() {  # check <description> <command...>
  desc=$1
  shift
  if ! "$@"; then
    echo "FAIL: $desc" >&2
    fails=$((fails + 1))
  fi
}

work=$(mktemp -d) || exit 1
trap 'rm -rf "$work"' EXIT
run="$work/run1"
mkdir -p "$run/sub"
echo cfg >"$run/config.used"
echo info >"$run/run_info.txt"
echo energy >"$run/energy.dat"
echo log >"$run/sub/stdout.log"
echo snap >"$run/state.snap"   # not packed without --snap
echo img >"$run/image.png"     # not a log or result type

# Run from an empty directory, so no slurm-*.out file is picked up.
cd "$work" || exit 1
archive="$work/out.tar.gz"
bash "$script" -o "$archive" "$run" >"$work/out.log" 2>&1 || { cat "$work/out.log" >&2; echo "FAIL: pack run exit" >&2; exit 1; }
check "archive created" test -s "$archive"
tar -tzf "$archive" >"$work/list"

# The archive holds the run name as the top folder, then the file names. No snapshot and no image.
check "config.used packed" grep -q '/run1/config.used$' "$work/list"
check "run_info.txt packed" grep -q '/run1/run_info.txt$' "$work/list"
check "dat packed" grep -q '/run1/energy.dat$' "$work/list"
check "log in subdirectory packed" grep -q '/run1/sub/stdout.log$' "$work/list"
check "manifest packed" grep -q 'MANIFEST.txt$' "$work/list"
check "snapshot not packed" sh -c "! grep -q '\.snap\$' '$work/list'"
check "image not packed" sh -c "! grep -q '\.png\$' '$work/list'"
check "exactly 5 files" test "$(grep -vc '/$' "$work/list")" -eq 5

# The manifest lists the packed files and gives a sha256 for each one.
tar -xzf "$archive" -C "$work"
man=$(ls "$work"/h4nb_logs_*/MANIFEST.txt 2>/dev/null | head -1)
check "manifest exists" test -n "$man"
check "manifest lists sub/stdout.log" grep -q 'run1/sub/stdout.log' "$man"
check "manifest has sha256 section" grep -q '== sha256 ==' "$man"

# With --snap the snapshot is packed too.
archive2="$work/snap.tar.gz"
bash "$script" --snap -o "$archive2" "$run" >/dev/null 2>&1
check "--snap packs the snapshot" sh -c "tar -tzf '$archive2' | grep -q 'state.snap$'"

# A missing run directory is an input error: exit 2.
bash "$script" -o "$work/x.tar.gz" "$work/nosuch" >/dev/null 2>&1
check "missing directory exits 2" test $? -eq 2

if [ "$fails" -ne 0 ]; then
  echo "test_pack: $fails check(s) failed" >&2
  exit 1
fi
echo "test_pack: OK"
