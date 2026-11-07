// h4nb_mkdisk: writes a disk initial condition (TZ 11.3, 11.4). It prints period estimates (TZ 6.3).
// Usage: h4nb_mkdisk n=<disk particles> frac=<disk mass / central mass> out=<file.txt|file.snap> [r_in=1] [r_out=10] [seed=1]
#include <cstdio>
#include "args.hpp"
#include "disk.hpp"

int main(int argc, char** argv) try {
  const Args a(argc, argv);
  if (!a.has("n") || !a.has("frac") || !a.has("out")) {
    std::fprintf(stderr, "usage: h4nb_mkdisk n=<count> frac=<mass ratio> out=<file.txt|file.snap>\n");
    return 1;
  }
  const h4nb::Particles p = make_disk(int(a.num("n", 0)), a.num("frac", 0), a.num("r_in", 1), a.num("r_out", 10),
                                      uint64_t(a.num("seed", 1)));
  const std::string out = a.str("out");
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
  std::fprintf(stderr, "h4nb_mkdisk: %s\n", e.what());
  return 1;
}
