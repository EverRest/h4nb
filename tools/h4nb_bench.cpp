// h4nb_bench: pair rate for a list of N (TZ 12: "benchmark results for different N").
// Usage: h4nb_bench [n=16384,131072,1024000] [devices=0] [eta=0.01] [segments=1] [out=<dir>]
// With out, the tool writes <out>/run_info.txt. It creates the directory.
#include <chrono>
#include <cstdio>
#include <filesystem>
#include "args.hpp"
#include "disk.hpp"
#include "run_info.hpp"

using Clock = std::chrono::steady_clock;
static double since(Clock::time_point t) { return std::chrono::duration<double>(Clock::now() - t).count(); }

int main(int argc, char** argv) try {
  const Args a(argc, argv);
  h4nb::Config c;
  c.devices = a.ints("devices", "0");
  c.eta = a.num("eta", 0.01);
  c.dt_max = 1.0 / 16;
  const int segments = int(a.num("segments", 1));
  if (a.has("out")) {
    std::filesystem::create_directories(a.str("out"));
    write_run_info(a.str("out") + "/run_info.txt", "h4nb_bench", c.devices, argc, argv);
  }
  std::printf("%9s %4s %10s %12s %11s %10s %8s %12s\n", "N", "GPUs", "init_s", "init_pair/s", "GFLOP/s(60)",
              "step_s", "blocks", "step_pair/s");
  for (int n : a.ints("n", "16384,131072,1024000")) {
    const h4nb::Particles p = make_disk(n - 1, 0.5, 1.0, 10.0, 1);
    const double N = double(p.size());
    const auto t0 = Clock::now();
    h4nb::Simulation s(p, c);
    const double init = since(t0);
    const h4nb::Stats st0 = s.stats();  // The first force pass is counted here, not in the step.
    const auto t1 = Clock::now();
    s.advance_to(c.dt_max * segments);
    const double step = since(t1);
    const h4nb::Stats st = s.stats();
    const int64_t blocks = st.block_steps - st0.block_steps, active = st.active_total - st0.active_total;
    std::printf("%9d %4zu %10.3f %12.3e %11.1f %10.3f %8lld %12.3e\n", n, c.devices.size(), init, N * (N - 1) / init,
                60.0 * N * (N - 1) / init / 1e9, step, (long long)blocks, double(active) * N / step);
  }
  return 0;
} catch (const std::exception& e) {
  std::fprintf(stderr, "h4nb_bench: %s\n", e.what());
  return 1;
}
