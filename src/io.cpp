#include <cerrno>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <system_error>
#include <sstream>
#include <stdexcept>
#include <unordered_map>
#include <vector>
#include "h4nb/h4nb.hpp"
#include "io.hpp"

// The snapshot is raw bytes. It is little-endian by definition (contracts/file-formats.md section 2).
static_assert(__BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__, "h4nb snapshots need a little-endian host");

namespace h4nb {
namespace {
// Parse a whole token as a number. Same rule as tools/settings.hpp: no text may remain after the number.
bool parse_int(const std::string& t, int64_t& v) {
  char* end = nullptr;
  errno = 0;
  v = std::strtoll(t.c_str(), &end, 10);
  return *end == '\0' && errno != ERANGE;
}
bool parse_real(const std::string& t, double& v) {
  char* end = nullptr;
  errno = 0;
  v = std::strtod(t.c_str(), &end);
  return *end == '\0' && errno != ERANGE;
}

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

void validate_particles(const Particles& p, const std::string& path) { validate(p, path, nullptr); }

Particles load_text(const std::string& path) {
  std::ifstream f(path);
  if (!f) throw std::runtime_error("cannot open " + path);
  Particles p;
  std::vector<int> lines;  // line number of each record, for the error messages
  std::string line;
  for (int ln = 1; std::getline(f, line); ++ln) {
    const size_t s = line.find_first_not_of(" \t\r");
    if (s == std::string::npos || line[s] == '#') continue;
    auto where = [&] { return path + ":" + std::to_string(ln); };
    std::istringstream is(line.substr(0, line.find('#')));  // Text after '#' is a comment.
    std::string tok[8];
    for (auto& t : tok)
      if (!(is >> t)) throw std::runtime_error(where() + ": Expected 'id m x y z vx vy vz'");
    std::string extra;
    if (is >> extra) throw std::runtime_error(where() + ": More than 8 fields, extra text '" + extra + "'");
    // Each field is one token. A value such as "1.5" in the ID field is an error, not a field shift.
    int64_t id = 0;
    if (!parse_int(tok[0], id)) throw std::runtime_error(where() + ": field id: not an integer '" + tok[0] + "'");
    static const char* const name[7] = {"m", "x", "y", "z", "vx", "vy", "vz"};
    double v[7] = {};
    for (int k = 0; k < 7; ++k)
      if (!parse_real(tok[k + 1], v[k]))
        throw std::runtime_error(where() + ": field " + name[k] + ": not a number '" + tok[k + 1] + "'");
    p.id.push_back(id); p.m.push_back(v[0]);
    p.x.push_back(v[1]); p.y.push_back(v[2]); p.z.push_back(v[3]);
    p.vx.push_back(v[4]); p.vy.push_back(v[5]); p.vz.push_back(v[6]);
    lines.push_back(ln);
  }
  validate(p, path, &lines);
  return p;
}

void publish_file(const std::string& tmp, const std::string& path) {
  std::error_code ec;
  std::filesystem::rename(tmp, path, ec);
  if (ec) {
    std::filesystem::remove(tmp, ec);
    throw std::runtime_error("cannot write " + path + ": " + ec.message());
  }
}

void write_snapshot(const std::string& path, const Particles& p, double time) {
  // Every array must have N values. A short array would make a file that the reader rejects.
  const size_t n = p.size();
  const size_t sizes[8] = {p.id.size(), p.m.size(), p.x.size(), p.y.size(), p.z.size(), p.vx.size(), p.vy.size(), p.vz.size()};
  for (size_t s : sizes)
    if (s != n) throw std::runtime_error("cannot write " + path + ": the particle arrays differ in size");
  // Write to a temporary name. The data reaches path only after a checked close (D1).
  const std::string tmp = path + ".tmp";
  std::ofstream f(tmp, std::ios::binary);
  if (!f) throw std::runtime_error("cannot write " + path);
  Header h{};
  std::memcpy(h.magic, kMagic, 8);
  h.version = 1;
  h.n = n;
  h.time = time;
  f.write(reinterpret_cast<const char*>(&h), sizeof h);
  auto put = [&](const auto& v) { f.write(reinterpret_cast<const char*>(v.data()), std::streamsize(v.size() * 8)); };
  put(p.id); put(p.m); put(p.x); put(p.y); put(p.z); put(p.vx); put(p.vy); put(p.vz);
  f.close();  // Buffered data is written here. A failed flush sets the fail bit.
  if (!f) {
    std::error_code ec;
    std::filesystem::remove(tmp, ec);
    throw std::runtime_error("write failed: " + path);
  }
  publish_file(tmp, path);
}

Particles read_snapshot(const std::string& path, double* time) {
  std::ifstream f(path, std::ios::binary);
  if (!f) throw std::runtime_error("cannot open " + path);
  Header h{};
  f.read(reinterpret_cast<char*>(&h), sizeof h);
  if (!f || std::memcmp(h.magic, kMagic, 8) != 0 || h.version != 1)
    throw std::runtime_error(path + ": Not an h4nb v1 snapshot");
  // Check the file size before the allocation. The file must hold 32 + 64 * n bytes, no more and no less.
  if (h.n > SIZE_MAX / 64)
    throw std::runtime_error(path + ": N = " + std::to_string(h.n) + " is too large for a snapshot");
  std::error_code ec;
  const uintmax_t size = std::filesystem::file_size(path, ec);
  if (ec) throw std::runtime_error("cannot read the size of " + path);
  const uintmax_t want = 32 + 64 * uintmax_t(h.n);
  if (size < want) throw std::runtime_error(path + ": Snapshot is truncated");
  if (size > want)
    throw std::runtime_error(path + ": " + std::to_string(size - want) + " trailing bytes after the data");
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
