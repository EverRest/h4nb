#!/usr/bin/env bash
# Compatibility wrapper. h4nb_study replaces this script (task T016). Use h4nb_study for new work.
# Usage: [DT_MAX="0.015625 0.0078125"] [OUT=dir] [BUILD=build] tools/eta_scan.sh <ic> <t_period> <diag> [devices] [eta list...]
# The script maps the arguments to keys: ic, t_ends=<t_period>, diag, devices, etas, dt_maxes=DT_MAX.
# H4NB_DRYRUN=1 prints the h4nb_study command and does not run it.
set -euo pipefail
[ $# -ge 3 ] || { echo "usage: tools/eta_scan.sh <ic> <t_period> <diag> [devices] [eta list...]" >&2; exit 2; }
ic=$1; T=$2; diag=$3; dev=${4:-0}; shift $(( $# < 4 ? $# : 4 ))
etas=${*:-"0.01 0.005 0.002 0.001 0.0005 0.00025"}
dts=${DT_MAX:-0.015625}
cmd=("${BUILD:-build}/h4nb_study" ic="$ic" out="${OUT:-eta_scan_out}" t_ends="$T" diag="$diag" devices="$dev"
     etas="${etas// /,}" dt_maxes="${dts// /,}")
echo "note: eta_scan.sh is a wrapper. h4nb_study is the main tool (h4nb_study help=1)." >&2
if [ "${H4NB_DRYRUN:-0}" = 1 ]; then echo "${cmd[*]}"; else exec "${cmd[@]}"; fi
