// h4nb_mkdisk: writes a disk initial condition (TZ 11.3, 11.4). It prints period estimates (TZ 6.3).
// Usage: h4nb_mkdisk n=<disk particles> frac=<disk mass / central mass> out=<file.txt|file.snap> [r_in=1] [r_out=10] [seed=1]
//        [config=<file>] [help=1]
// The keys follow contracts/run-config.md. A settings error gives exit code 2. Other errors give exit code 1.
#include <cstdio>
#include "disk.hpp"
#include "settings.hpp"

int main(int argc, char** argv) try {
  Settings s;
  s.add("n", Setting::Int, "", "Number of disk particles.", Range::ge(1)).required = true;
  s.add("frac", Setting::Real, "", "Disk mass / central mass.", Range::gt(0)).required = true;
  s.add("out", Setting::String, "", "Output file. .snap is binary. Other names are text.").required = true;
  s.add("r_in", Setting::Real, "1", "Inner disk radius.", Range::gt(0));
  s.add("r_out", Setting::Real, "10", "Outer disk radius. It must be larger than r_in.", Range::gt(0));
  s.add("seed", Setting::Int, "1", "Random seed.", Range::ge(0));
  s.parse(argc, argv);
  if (s.help()) { s.print_help(stdout, "h4nb_mkdisk"); return 0; }
  if (!(s.real("r_out") > s.real("r_in"))) s.fail("r_out", "must be larger than r_in");
  const h4nb::Particles p = make_disk(s.integer("n"), s.real("frac"), s.real("r_in"), s.real("r_out"),
                                      uint64_t(s.integer("seed")));
  const std::string out = s.str("out");
  if (out.size() > 5 && out.compare(out.size() - 5, 5, ".snap") == 0) {
    h4nb::write_snapshot(out, p, 0.0);
  } else {
    FILE* f = std::fopen(out.c_str(), "w");
    if (!f) throw std::runtime_error("cannot write " + out);
    std::fprintf(f, "# id m x y z vx vy vz\n");
    for (size_t i = 0; i < p.size(); ++i)
      std::fprintf(f, "%lld %.17g %.17g %.17g %.17g %.17g %.17g %.17g\n", (long long)p.id[i], p.m[i], p.x[i], p.y[i],
                   p.z[i], p.vx[i], p.vy[i], p.vz[i]);
    std::fclose(f);
  }
  const Periods T = periods(p);
  std::printf("N=%zu periods: mean=%.6g median=%.6g mass_weighted=%.6g\n", p.size(), T.mean, T.median, T.mass_weighted);
  return 0;
} catch (const std::exception& e) {
  return settings_main_error("h4nb_mkdisk", e);
}
