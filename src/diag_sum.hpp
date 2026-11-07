// Host reduction of the diagnostics (MPI-M1). Not part of the public API.
// One process and MPI call this one function. Thus both paths add the values in the same order, and give the same bits.
#pragma once
#include "h4nb/h4nb.hpp"

namespace h4nb {
// ph holds G rows of p.size() doubles. Row h starts at ph + h * p.size(). Row h is the potential of the sources of
// device h (one process) or of rank h (MPI). wd holds p.size() doubles in global order. Gc is Config::G.
// Returns K, U, E, P, L and W_diss. The caller sets time.
// The order: for each i in index order, phi = ((0 + row 0) + row 1) + ... (plain adds). Then one Neumaier sum over i
// for each value. Do not change this order: the bits of energy.dat depend on it.
Diagnostics diag_sum(const Particles& p, const double* ph, int G, const double* wd, double Gc);
}  // namespace h4nb
