#!/usr/bin/env bash
# Convergence study (TZ 3.6, 15.4, 16): eta and dt_max against max |dE/E|. The run is sampled every <diag>,
# so energy.dat of one run already gives max |dE/E| as a function of the integration time.
# Usage: [DT_MAX="0.015625 0.0078125"] tools/eta_scan.sh <ic> <t_period> <diag> [devices] [eta list...]
#   t_period, diag and every dt_max must be multiples of the smallest dt_max (default 1/64).
set -euo pipefail
ic=$1; T=$2; diag=$3; dev=${4:-0}; shift $(( $# < 4 ? $# : 4 ))
etas=${*:-"0.01 0.005 0.002 0.001 0.0005 0.00025"}
dts=${DT_MAX:-0.015625}
bin=${BUILD:-build}/h4nb_run
printf "%-12s %-10s %-14s %-14s %s\n" dt_max eta max_dE_E mean_dE_E wall_s
for dt in $dts; do
  for eta in $etas; do
    out=$(mktemp -d)
    start=$(date +%s.%N)
    "$bin" ic="$ic" out="$out" t_end="$T" diag="$diag" eta="$eta" dt_max="$dt" devices="$dev" > /dev/null
    end=$(date +%s.%N)
    printf "%-12s %-10s %-14s %-14s %.1f\n" "$dt" "$eta" "$(tail -n1 "$out/energy.dat" | awk '{print $6}')" \
      "$(tail -n1 "$out/energy.dat" | awk '{print $7}')" "$(echo "$end - $start" | bc)"
    rm -rf "$out"
  done
done
