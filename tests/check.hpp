#pragma once
// CHECK / CHECK_NEAR: print the failing expression and exit(1) on the first failure. No framework.
#include <cmath>
#include <cstdio>
#include <cstdlib>

#define CHECK(cond)                                                                    \
  do {                                                                                 \
    if (!(cond)) {                                                                     \
      std::fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__, __LINE__, #cond);    \
      std::exit(1);                                                                    \
    }                                                                                  \
  } while (0)

#define CHECK_NEAR(a, b, tol)                                                                      \
  do {                                                                                             \
    const double a_ = (a), b_ = (b);                                                               \
    if (!(std::fabs(a_ - b_) <= (tol))) {                                                          \
      std::fprintf(stderr, "%s:%d: |%s - %s| = %.3e > %.3e (%.17g vs %.17g)\n", __FILE__, __LINE__, \
                   #a, #b, std::fabs(a_ - b_), double(tol), a_, b_);                               \
      std::exit(1);                                                                                \
    }                                                                                              \
  } while (0)
