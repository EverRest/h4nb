// h4nb_bench: pair rate for a grid sizes x tiles x bpsm (TZ 12, FR-024, FR-025, task T019).
// Usage: h4nb_bench [config=<file>] [sizes=16384,131072,1024000] [tiles=128] [bpsm=4] [devices=0] [fp64_peak=<TFLOP/s>]
//                   [out=bench] [key=value ...]
// "h4nb_bench help=1" prints all keys. The tool writes <out>/config.used, <out>/run_info.txt and <out>/bench.dat.
// For each combination (N, tile, blocks_per_sm), the tool builds a disk of N particles, central body included.
// It times the Simulation constructor. The constructor does the first force pass (N(N-1) pairs).
// The time also includes the upload and the first time steps. Thus pairs_per_s is a lower limit of the kernel rate.
// When segments > 0, the tool then advances segments * dt_max and prints the block-step rate (stdout only).
// gflops = 60 * pairs_per_s / 1e9. 60 FP64 FLOP per pair is the cost model of the plan and of research.md R6.
// It is a model, not a count of the instructions in the kernel.
// pct_peak = 100 * gflops / (1000 * fp64_peak). The column is in bench.dat only when fp64_peak > 0.
// Exit codes: 0 = done, 1 = runtime error (example: no CUDA device), 2 = settings error.
#include <chrono>
#include <cmath>
#include <cstdio>
#include <filesystem>
#include <string>
#include <vector>
#include "disk.hpp"
#include "h4nb/h4nb.hpp"
#include "run_info.hpp"
#include "settings.hpp"

using Clock = std::chrono::steady_clock;
static double since(Clock::time_point t) { return std::chrono::duration<double>(Clock::now() - t).count(); }

constexpr double kFlopPerPair = 60.0;  // Cost model of research.md R6 and of the plan section "Cost model".

static void declare(Settings& s) {
  using T = Setting;
  s.add("sizes", T::IntList, "16384,131072,1024000", "Particle counts N, central body included.", Range::ge(2));
  s.add("tiles", T::IntList, "128", "Values of tile to measure.", Range::one_of({"64", "128", "256"}));
  s.add("bpsm", T::IntList, "4", "Values of blocks_per_sm to measure.", Range::between(1, 16));
  s.add("devices", T::IntList, "0", "CUDA device IDs. A repeated ID emulates more GPUs on one card.", Range::ge(0));
  s.add("fp64_peak", T::Real, "0", "FP64 peak of all devices in TFLOP/s. 0: not set, no pct_peak column.", Range::ge(0));
  s.add("out", T::String, "bench", "Output directory for bench.dat, config.used and run_info.txt.");
  s.add("eta", T::Real, "0.01", "Aarseth accuracy parameter of the block steps.", Range::gt(0));
  s.add("eps", T::Real, "0", "Plummer softening length. The library receives eps^2.", Range::ge(0));
  s.add("seed", T::Int, "1", "Seed of the disk initial conditions.", Range::ge(0));
  s.add("segments", T::Int, "1", "Block-step time after the force pass, in units of dt_max=1/16. 0: no block steps.",
        Range::ge(0));
}

struct Row {
  int n, tile, bpsm;
  double pairs_per_s, gflops, wall;
};

int main(int argc, char** argv) try {
  Settings s;
  declare(s);
  s.parse(argc, argv);
  if (s.help()) {
    s.print_help(stdout, "h4nb_bench");
    return 0;
  }
  const std::vector<int> sizes = s.ints("sizes"), tiles = s.ints("tiles"), bpsm = s.ints("bpsm");
  for (const char* k : {"sizes", "tiles", "bpsm", "devices"})
    if (s.ints(k).empty()) s.fail(k, "the list is empty");
  const std::string out = s.str("out");
  if (out.empty()) s.fail("out", "empty directory name");
  const double peak = s.real("fp64_peak");
  const int segments = s.integer("segments");
  const uint64_t seed = uint64_t(s.integer("seed"));

  h4nb::Config c;
  c.devices = s.ints("devices");
  c.eta = s.real("eta");
  c.eps2 = std::pow(s.real("eps"), 2);  // The tool takes eps. The library takes eps^2.
  c.dt_max = 1.0 / 16;

  std::filesystem::create_directories(out);
  s.write_used(out + "/config.used", "h4nb_bench");
  write_run_info(out + "/run_info.txt", "h4nb_bench", c.devices, argc, argv);

  // Warm-up: the first Simulation creates the CUDA context on each device. It is not counted.
  { h4nb::Simulation w(make_disk(1023, 0.5, 1.0, 10.0, seed), c); w.stats(); }

  FILE* f = std::fopen((out + "/bench.dat").c_str(), "w");
  if (!f) throw std::runtime_error("cannot write " + out + "/bench.dat");
  std::string ids;
  for (int d : c.devices) ids += (ids.empty() ? "" : ",") + std::to_string(d);
  std::fprintf(f, "# h4nb_bench device_ids=%s eta=%g eps2=%g seed=%llu flop_per_pair=%g fp64_peak_tflops=%g\n", ids.c_str(),
               c.eta, c.eps2, (unsigned long long)seed, kFlopPerPair, peak);
  std::fprintf(f, "# N devices tile blocks_per_sm pairs_per_s gflops wall_s%s\n", peak > 0 ? " pct_peak" : "");
  std::printf("%9s %4s %4s %4s %10s %12s %9s %7s %10s %8s %12s\n", "N", "GPUs", "tile", "bpsm", "init_s", "init_pair/s",
              "GFLOP/s", "%peak", "step_s", "blocks", "step_pair/s");
  std::fflush(stdout);
  std::vector<Row> rows;
  for (int n : sizes) {
    const h4nb::Particles p = make_disk(n - 1, 0.5, 1.0, 10.0, seed);
    const double N = double(p.size());
    for (int tile : tiles)
      for (int b : bpsm) {
        c.tile = tile;
        c.blocks_per_sm = b;
        const auto t0 = Clock::now();
        h4nb::Simulation sim(p, c);
        const h4nb::Stats st0 = sim.stats();  // stats() waits for the devices. The first force pass is counted here.
        const double init = since(t0);
        const double rate = N * (N - 1) / init, gflops = kFlopPerPair * rate / 1e9;
        const double pct = peak > 0 ? 100.0 * gflops / (1000.0 * peak) : NAN;
        double step = 0, step_rate = NAN;
        long long blocks = 0;
        if (segments > 0) {
          const auto t1 = Clock::now();
          sim.advance_to(c.dt_max * segments);
          const h4nb::Stats st = sim.stats();
          step = since(t1);
          blocks = (long long)(st.block_steps - st0.block_steps);
          step_rate = double(st.active_total - st0.active_total) * N / step;
        }
        std::fprintf(f, "%d %zu %d %d %.6e %.3f %.6f", n, c.devices.size(), tile, b, rate, gflops, init);
        if (peak > 0) std::fprintf(f, " %.2f", pct);
        std::fprintf(f, "\n");
        std::fflush(f);
        std::printf("%9d %4zu %4d %4d %10.3f %12.3e %9.1f %7.1f %10.3f %8lld %12.3e\n", n, c.devices.size(), tile, b, init,
                    rate, gflops, pct, step, blocks, step_rate);
        std::fflush(stdout);
        rows.push_back({n, tile, b, rate, gflops, init});
      }
  }
  const bool ok = std::ferror(f) == 0;
  if (std::fclose(f) != 0 || !ok) throw std::runtime_error("cannot write " + out + "/bench.dat");
  // The best combination for each N: the highest pairs_per_s of the force pass.
  for (int n : sizes) {
    const Row* best = nullptr;
    for (const Row& r : rows)
      if (r.n == n && (!best || r.pairs_per_s > best->pairs_per_s)) best = &r;
    if (best)
      std::printf("best N=%d: tile=%d blocks_per_sm=%d pairs_per_s=%.3e gflops=%.1f\n", n, best->tile, best->bpsm,
                  best->pairs_per_s, best->gflops);
  }
  std::printf("h4nb_bench: wrote %s/bench.dat\n", out.c_str());
  return 0;
} catch (const std::exception& e) {
  return settings_main_error("h4nb_bench", e);
}
