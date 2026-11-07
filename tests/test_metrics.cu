// Unit tests for the host counter helpers in include/h4nb/h4nb.hpp. Host only, no GPU needed.
#include <cstdio>
#include "check.hpp"
#include "h4nb/h4nb.hpp"

using namespace h4nb;

int main() {
  // log2_bin: floor(log2(n)), and bin 0 for n = 0.
  CHECK(log2_bin(1) == 0);
  CHECK(log2_bin(2) == 1);
  CHECK(log2_bin(1023) == 9);
  CHECK(log2_bin(1024) == 10);
  // block_level: max_level - ctz(Tn). Tn = 1 is the finest step.
  CHECK(detail::block_level(5, 1) == 5);
  CHECK(detail::block_level(5, 2) == 4);
  CHECK(detail::block_level(5, 4) == 3);
  // A Tn on a coarser grid than dt_max gives level 0, not a negative index.
  CHECK(detail::block_level(5, 32) == 0);
  CHECK(detail::block_level(5, 64) == 0);
  // The start-up times are zero until a constructor sets them.
  const Metrics m{};
  CHECK(m.init_force_s == 0);
  CHECK(m.init_levels_s == 0);
  std::printf("test_metrics: ok\n");
  return 0;
}
