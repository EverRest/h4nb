#include <cstring>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include "h4nb/h4nb.hpp"

namespace h4nb {
namespace {
struct Header {
  char magic[8];
  uint32_t version;
  uint32_t reserved;
  uint64_t n;
  double time;
};
static_assert(sizeof(Header) == 32, "snapshot header must be 32 bytes");
constexpr char kMagic[8] = {'H', '4', 'N', 'B', 'S', 'N', 'A', 'P'};
}  // namespace

Particles load_text(const std::string& path) {
  std::ifstream f(path);
  if (!f) throw std::runtime_error("cannot open " + path);
  Particles p;
  std::string line;
  for (int ln = 1; std::getline(f, line); ++ln) {
    const size_t s = line.find_first_not_of(" \t\r");
    if (s == std::string::npos || line[s] == '#') continue;
    std::istringstream is(line);
    int64_t id;
    double m, x, y, z, vx, vy, vz;
    if (!(is >> id >> m >> x >> y >> z >> vx >> vy >> vz))
      throw std::runtime_error(path + ":" + std::to_string(ln) + ": Expected 'id m x y z vx vy vz'");
    p.id.push_back(id); p.m.push_back(m);
    p.x.push_back(x); p.y.push_back(y); p.z.push_back(z);
    p.vx.push_back(vx); p.vy.push_back(vy); p.vz.push_back(vz);
  }
  return p;
}

void write_snapshot(const std::string& path, const Particles& p, double time) {
  std::ofstream f(path, std::ios::binary);
  if (!f) throw std::runtime_error("cannot write " + path);
  Header h{};
  std::memcpy(h.magic, kMagic, 8);
  h.version = 1;
  h.n = p.size();
  h.time = time;
  f.write(reinterpret_cast<const char*>(&h), sizeof h);
  auto put = [&](const auto& v) { f.write(reinterpret_cast<const char*>(v.data()), std::streamsize(v.size() * 8)); };
  put(p.id); put(p.m); put(p.x); put(p.y); put(p.z); put(p.vx); put(p.vy); put(p.vz);
  if (!f) throw std::runtime_error("write failed: " + path);
}

Particles read_snapshot(const std::string& path, double* time) {
  std::ifstream f(path, std::ios::binary);
  if (!f) throw std::runtime_error("cannot open " + path);
  Header h{};
  f.read(reinterpret_cast<char*>(&h), sizeof h);
  if (!f || std::memcmp(h.magic, kMagic, 8) != 0 || h.version != 1)
    throw std::runtime_error(path + ": Not an h4nb v1 snapshot");
  Particles p;
  p.resize(h.n);
  auto get = [&](auto& v) { f.read(reinterpret_cast<char*>(v.data()), std::streamsize(v.size() * 8)); };
  get(p.id); get(p.m); get(p.x); get(p.y); get(p.z); get(p.vx); get(p.vy); get(p.vz);
  if (!f) throw std::runtime_error(path + ": Snapshot is truncated");
  if (time) *time = h.time;
  return p;
}

}  // namespace h4nb
