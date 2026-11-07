#!/usr/bin/env bash
# h4nb_pack.sh: packs the logs and the results of one or more runs into one .tar.gz archive.
# Send this archive back from the GPU machine or the cluster.
#
# Usage: tools/h4nb_pack.sh [-o ARCHIVE] [--snap] RUN_DIR [RUN_DIR ...]
#   RUN_DIR   An output directory of h4nb_run, h4nb_study or h4nb_bench (the value of out=).
#   -o        The archive name. Default: h4nb_logs_<host>_<UTC time>.tar.gz in the current directory.
#   --snap    Also pack the snapshots (*.snap). They can be large. By default the script does not pack them.
#
# The script packs these files from each RUN_DIR (also from subdirectories):
#   config.used, run_info.txt, *.dat, *.log, *.out, *.err, *.txt,
#   Nsight profiles (*.nsys-rep, *.qdrep, *.ncu-rep, *.sqlite), and with --snap the *.snap files.
# It also packs Slurm logs (slurm-*.out) from the current directory.
# It adds MANIFEST.txt with the host, the time, nvidia-smi output, the file list and sha256 sums.
#
# Save the screen output of a run in its directory, so that the script packs it:
#   build/h4nb_run config=configs/agn.cfg out=run1 2>&1 | tee run1/stdout.log
# (Create run1 first: mkdir -p run1.)
set -euo pipefail

archive="" snap=0 dirs=()
while [ $# -gt 0 ]; do
  case "$1" in
    -o) [ $# -ge 2 ] || { echo "h4nb_pack: -o needs a file name" >&2; exit 2; }; archive="$2"; shift 2 ;;
    --snap) snap=1; shift ;;
    -h|--help) sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) echo "h4nb_pack: unknown option $1" >&2; exit 2 ;;
    *) dirs+=("$1"); shift ;;
  esac
done
[ ${#dirs[@]} -gt 0 ] || { echo "h4nb_pack: give at least one RUN_DIR. See --help." >&2; exit 2; }
for d in "${dirs[@]}"; do [ -d "$d" ] || { echo "h4nb_pack: $d is not a directory" >&2; exit 2; }; done

host=$(hostname -s 2>/dev/null || hostname)
stamp=$(date -u +%Y%m%dT%H%M%SZ)
[ -n "$archive" ] || archive="h4nb_logs_${host}_${stamp}.tar.gz"

stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
root="$stage/h4nb_logs_${host}_${stamp}"
mkdir -p "$root"

patterns=(config.used run_info.txt '*.dat' '*.log' '*.out' '*.err' '*.txt' '*.nsys-rep' '*.qdrep' '*.ncu-rep' '*.sqlite')
[ "$snap" = 1 ] && patterns+=('*.snap')
find_args=()
for p in "${patterns[@]}"; do find_args+=(-o -name "$p"); done
find_args=("${find_args[@]:1}")

n=0
for d in "${dirs[@]}"; do
  # Remove a trailing "/". Otherwise the archive gets run1/run1/... paths.
  d=${d%/}
  # Keep the name of the run directory, so that two runs do not overwrite each other.
  name=$(basename "$(cd "$d" && pwd)")
  while IFS= read -r -d '' f; do
    rel=${f#"$d"/}
    mkdir -p "$root/$name/$(dirname "$rel")"
    cp -p "$f" "$root/$name/$rel"
    n=$((n + 1))
  done < <(find "$d" -type f \( "${find_args[@]}" \) -print0)
done
for f in slurm-*.out; do
  [ -f "$f" ] || continue
  mkdir -p "$root/slurm" && cp -p "$f" "$root/slurm/" && n=$((n + 1))
done
[ "$n" -gt 0 ] || { echo "h4nb_pack: no log or result files found" >&2; exit 1; }

{
  echo "h4nb_pack manifest"
  echo "host: $host"
  echo "time_utc: $stamp"
  echo "run_dirs: ${dirs[*]}"
  echo "snapshots: $([ "$snap" = 1 ] && echo packed || echo not packed)"
  echo
  echo "== nvidia-smi =="
  if command -v nvidia-smi >/dev/null 2>&1; then nvidia-smi 2>&1 || true; else echo "nvidia-smi: not found"; fi
  echo
  echo "== files (bytes, path) =="
  (cd "$root" && find . -type f ! -name MANIFEST.txt -printf '%s %P\n' | sort -k2)
  echo
  echo "== sha256 =="
  (cd "$root" && find . -type f ! -name MANIFEST.txt -print0 | sort -z | xargs -0 sha256sum)
} > "$root/MANIFEST.txt"

tar -C "$stage" -czf "$archive" "$(basename "$root")"
echo "h4nb_pack: $n files -> $archive ($(du -h "$archive" | cut -f1))"
