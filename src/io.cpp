#include <cmath>
#include <cstring>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <unordered_map>
#include <vector>
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

// Check the particles after a loader reads them (research R5). Throw std::runtime_error at the first error.
// The text loader gives the line number of each record in "lines". The binary loader gives nullptr.
// Then the message names the index of the record.
void validate(const Particles& p, const std::string& path, const std::vector<int>* lines) {
  auto where = [&](size_t i) {
    return lines ? path + ":" + std::to_string((*lines)[i]) : path + ": index " + std::to_string(i);
  };
  auto fail = [&](size_t i, const char* field, const std::string& what, double got) {
    std::ostringstream os;
    os << where(i) << ": field " << field << ": " << what << ", got " << got;
    throw std::runtime_error(os.str());
  };
  const size_t n = p.size();
  if (n < 2) throw std::runtime_error(path + ": N = " + std::to_string(n) + ", must be >= 2");
  std::unordered_map<int64_t, size_t> seen;  // ID -> position of its first record
  seen.reserve(n);
  for (size_t i = 0; i < n; ++i) {
    const auto ins = seen.emplace(p.id[i], i);
    if (!ins.second) {
      const size_t j = ins.first->second;
      const std::string first = lines ? "line " + std::to_string((*lines)[j]) : "index " + std::to_string(j);
      throw std::runtime_error(where(i) + ": field id: repeated ID " + std::to_string(p.id[i]) + ", first at " + first);
    }
    if (!std::isfinite(p.m[i])) fail(i, "m", "must be finite", p.m[i]);
    if (!(p.m[i] > 0)) fail(i, "m", "must be > 0", p.m[i]);
    const std::vector<double>* v[6] = {&p.x, &p.y, &p.z, &p.vx, &p.vy, &p.vz};
    static const char* const name[6] = {"x", "y", "z", "vx", "vy", "vz"};
    for (int k = 0; k < 6; ++k)
      if (!std::isfinite((*v[k])[i])) fail(i, name[k], "must be finite", (*v[k])[i]);
  }
}
}  // namespace

Particles load_text(const std::string& path) {
  std::ifstream f(path);
  if (!f) throw std::runtime_error("cannot open " + path);
  Particles p;
  std::vector<int> lines;  // line number of each record, for the error messages
  std::string line;
  for (int ln = 1; std::getline(f, line); ++ln) {
    const size_t s = line.find_first_not_of(" \t\r");
    if (s == std::string::npos || line[s] == '#') continue;
    std::istringstream is(line);
    int64_t id;
    double m, x, y, z, vx, vy, vz;
    if (!(is >> id >> m >> x >> y >> z >> vx >> vy >> vz))
      throw std::runtime_error(path + ":" + std::to_string(ln) + ": Expected 'id m x y z vx vy vz'");
    std::string extra;
    if ((is >> extra) && extra[0] != '#')  // A '#' after the 8 fields starts a comment.
      throw std::runtime_error(path + ":" + std::to_string(ln) + ": More than 8 fields, extra text '" + extra + "'");
    p.id.push_back(id); p.m.push_back(m);
    p.x.push_back(x); p.y.push_back(y); p.z.push_back(z);
    p.vx.push_back(vx); p.vy.push_back(vy); p.vz.push_back(vz);
    lines.push_back(ln);
  }
  validate(p, path, &lines);
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
  validate(p, path, nullptr);
  if (time) *time = h.time;
  return p;
}

}  // namespace h4nb
