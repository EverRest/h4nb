#!/usr/bin/env bash
# GPU checks that the Mac and the CPU container cannot do. Run this script on a host with a CUDA GPU.
# Usage: [ARCH=89] [SIZES=131072,262144] [OLD=285f3f9] [WORK=dir] tools/h4nb_gpu_check.sh
# Step 1 builds the old commit OLD (force_kernel without the P1 change).
#        It captures the golden hashes of tests/test_force_kernel.cu with --capture.
# Step 2 writes the hashes into tests/test_force_kernel.cu and registers the test in CMakeLists.txt again.
# Step 3 builds HEAD and runs all gpu tests (ctest -L gpu). The new test must report "bit-identical".
# Step 4 times the Simulation constructor with h4nb_bench on OLD and on HEAD.
#        OLD has no init_levels. The difference is the cost of the cold-start pass (issue A1).
#        If nsys is on the PATH, the script also prints the time of each kernel.
# The script edits two files in the working tree (step 2). It does not commit. Read "git diff" and commit yourself.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
ARCH=${ARCH:-native}
SIZES=${SIZES:-131072,262144}
OLD=${OLD:-285f3f9}
WORK=${WORK:-$(mktemp -d -t h4nb_gpu_check.XXXX)}
echo "work directory: $WORK"

cmake_build() {  # cmake_build <source dir> <build dir>
  cmake -S "$1" -B "$2" -DCMAKE_BUILD_TYPE=Release -DCMAKE_CUDA_ARCHITECTURES="$ARCH" >"$2.cfg.log"
  cmake --build "$2" -j >"$2.build.log"
}

# Step 1: golden hashes from the old kernel.
git worktree add --detach "$WORK/old-src" "$OLD" >/dev/null
trap 'git worktree remove --force "$WORK/old-src" >/dev/null 2>&1 || true' EXIT
cp tests/test_force_kernel.cu "$WORK/old-src/tests/"
echo 'h4nb_add_test(test_force_kernel tests/test_force_kernel.cu gpu)' >>"$WORK/old-src/CMakeLists.txt"
mkdir -p "$WORK/old"
cmake_build "$WORK/old-src" "$WORK/old"
"$WORK/old/test_force_kernel" --capture | tee "$WORK/golden.txt"
[ "$(grep -c ' hash 0x' "$WORK/golden.txt")" -eq 16 ] || { echo "error: expected 16 hashes" >&2; exit 1; }

# Step 2: write the hashes and register the test again.
init=$(awk '/ hash 0x/ { h[n++] = $6 } END { for (i = 0; i < n; i += 2) printf "    {%s, %s},\n", h[i], h[i + 1] }' \
  "$WORK/golden.txt")
INIT="$init" perl -0pi -e 's/(const uint64_t kGolden\[8\]\[2\] = \{\n).*?(\n\};)/$1$ENV{INIT}$2/s' tests/test_force_kernel.cu
grep -q 'h4nb_add_test(test_force_kernel' CMakeLists.txt ||
  sed -i.bak '/h4nb_add_test(test_physics_gpu /a h4nb_add_test(test_force_kernel tests/test_force_kernel.cu gpu)' CMakeLists.txt
rm -f CMakeLists.txt.bak

# Step 3: all gpu tests on HEAD, with the new golden values.
mkdir -p "$WORK/new"
cmake_build . "$WORK/new"
ctest --test-dir "$WORK/new" -L gpu --output-on-failure

# Step 4: constructor time on OLD and on HEAD (bench.dat), and kernel times if nsys is present.
for tree in old new; do
  "$WORK/$tree/h4nb_bench" sizes="$SIZES" tiles=128 out="$WORK/bench-$tree" >/dev/null
  echo "== bench.dat ($tree)"
  cat "$WORK/bench-$tree/bench.dat"
done
if command -v nsys >/dev/null; then
  nsys profile -o "$WORK/prof" --force-overwrite true "$WORK/new/h4nb_bench" sizes="$SIZES" tiles=128 \
    out="$WORK/bench-prof" >/dev/null
  nsys stats --report cuda_gpu_kern_sum "$WORK/prof.nsys-rep" | grep -E 'Time|force_kernel|init_level_kernel'
else
  echo "note: nsys is not on the PATH. Only the constructor times above are available."
fi
echo "done. Read 'git diff tests/test_force_kernel.cu CMakeLists.txt', then commit."
