#include "core/run_manifest.h"

#include "core/errors.h"
#include "core/sha256.h"

#include <sys/stat.h>
#include <unistd.h>

#include <algorithm>
#include <cmath>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <optional>
#include <set>
#include <sstream>
#include <vector>

namespace xcov {

namespace {

namespace fs = std::filesystem;
using json = nlohmann::json;

constexpr const char* kHashVersion = "sha256-entry-tree-v2";
Error mismatch(const std::string& message) {
    return Error("RESOURCE_PROVENANCE_MISMATCH", message);
}

std::string read_text_file(const std::string& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        throw mismatch("run manifest is missing or cannot be resolved");
    }
    input.seekg(0, std::ios::end);
    const std::streamoff size = input.tellg();
    if (size < 0) {
        throw mismatch("run manifest is not valid JSON");
    }
    input.seekg(0, std::ios::beg);
    std::string text(static_cast<std::size_t>(size), '\0');
    input.read(&text[0], size);
    if (!input && !input.eof()) {
        throw mismatch("run manifest is missing or cannot be resolved");
    }
    return text;
}

// Strict JSON reader that rejects duplicate object keys (Python uses a closed
// canonical loader) and non-finite numbers.
class StrictJsonSax : public json::json_sax_t {
public:
    bool null() override { return add(json(nullptr)); }
    bool boolean(bool value) override { return add(json(value)); }
    bool number_integer(number_integer_t value) override {
        return add(json(value));
    }
    bool number_unsigned(number_unsigned_t value) override {
        return add(json(value));
    }
    bool number_float(number_float_t value, const string_t&) override {
        if (!std::isfinite(value)) {
            error_ = "non-finite number";
            return false;
        }
        return add(json(value));
    }
    bool string(string_t& value) override {
        return add(json(std::move(value)));
    }
    bool binary(binary_t&) override {
        error_ = "binary values are not valid manifest JSON";
        return false;
    }
    bool start_object(std::size_t) override {
        frames_.push_back(Frame{json::object(), std::string()});
        return true;
    }
    bool key(string_t& value) override {
        if (frames_.empty() || !frames_.back().value.is_object()) {
            error_ = "object key outside object";
            return false;
        }
        if (!frames_.back().pending_key.empty() ||
            frames_.back().value.contains(value)) {
            error_ = "duplicate object key";
            return false;
        }
        frames_.back().pending_key = value;
        return true;
    }
    bool end_object() override {
        if (frames_.empty() || !frames_.back().value.is_object() ||
            !frames_.back().pending_key.empty()) {
            error_ = "unterminated object";
            return false;
        }
        return close_frame();
    }
    bool start_array(std::size_t) override {
        frames_.push_back(Frame{json::array(), std::string()});
        return true;
    }
    bool end_array() override {
        if (frames_.empty() || !frames_.back().value.is_array()) {
            error_ = "unterminated array";
            return false;
        }
        return close_frame();
    }
    bool parse_error(std::size_t, const std::string&,
                     const nlohmann::detail::exception&) override {
        error_ = "parse error";
        return false;
    }

    const std::string& error() const { return error_; }
    bool has_root() const { return root_.has_value(); }
    json take_root() { return std::move(*root_); }

private:
    struct Frame {
        json value;
        std::string pending_key;
    };

    bool add(json value) {
        if (frames_.empty()) {
            if (root_.has_value()) {
                error_ = "multiple root values";
                return false;
            }
            root_ = std::move(value);
            return true;
        }
        Frame& frame = frames_.back();
        if (frame.value.is_object()) {
            if (frame.pending_key.empty()) {
                error_ = "object value without key";
                return false;
            }
            frame.value[frame.pending_key] = std::move(value);
            frame.pending_key.clear();
            return true;
        }
        if (frame.value.is_array()) {
            frame.value.push_back(std::move(value));
            return true;
        }
        error_ = "value outside container";
        return false;
    }

    bool close_frame() {
        Frame frame = std::move(frames_.back());
        frames_.pop_back();
        return add(std::move(frame.value));
    }

    std::vector<Frame> frames_;
    std::optional<json> root_;
    std::string error_;
};

json strict_json_parse(const std::string& text) {
    StrictJsonSax sax;
    if (!json::sax_parse(text, &sax)) {
        throw mismatch("run manifest is not valid JSON");
    }
    if (!sax.has_root()) throw mismatch("run manifest is not valid JSON");
    return sax.take_root();
}

bool object_only(const json& value, const std::set<std::string>& allowed,
                 const std::vector<std::string>& required) {
    if (!value.is_object()) return false;
    for (auto it = value.begin(); it != value.end(); ++it) {
        if (allowed.find(it.key()) == allowed.end()) return false;
    }
    for (const auto& key : required) {
        if (!value.contains(key)) return false;
    }
    return true;
}

bool json_int(const json& value, std::uint64_t* out) {
    if (value.is_number_unsigned()) {
        *out = value.get<std::uint64_t>();
        return true;
    }
    if (value.is_number_integer()) {
        const long long parsed = value.get<long long>();
        if (parsed < 0) return false;
        *out = static_cast<std::uint64_t>(parsed);
        return true;
    }
    return false;
}

bool json_string(const json& value, std::string* out) {
    if (!value.is_string()) return false;
    *out = value.get<std::string>();
    return true;
}

bool valid_hash(const std::string& text) {
    if (text.size() != 64) return false;
    for (char ch : text) {
        if (!((ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f'))) {
            return false;
        }
    }
    return true;
}

bool safe_resource_path(const std::string& text) {
    if (text.empty() || text.front() == '/') return false;
    std::size_t start = 0;
    while (start <= text.size()) {
        const std::size_t slash = text.find('/', start);
        const std::string part =
            text.substr(start, slash == std::string::npos
                                   ? std::string::npos
                                   : slash - start);
        if (part == "..") return false;
        if (slash == std::string::npos) break;
        start = slash + 1;
    }
    return true;
}

bool stat_changed(const struct stat& before, const struct stat& after) {
    if (before.st_dev != after.st_dev || before.st_ino != after.st_ino ||
        before.st_mode != after.st_mode || before.st_size != after.st_size) {
        return true;
    }
    if (before.st_mtim.tv_sec != after.st_mtim.tv_sec ||
        before.st_mtim.tv_nsec != after.st_mtim.tv_nsec) {
        return true;
    }
    return before.st_ctim.tv_sec != after.st_ctim.tv_sec ||
           before.st_ctim.tv_nsec != after.st_ctim.tv_nsec;
}

struct TreeEntry {
    std::string relative;
    char type = 'F';
    std::uint64_t size = 0;
    std::string digest;
};

void append_u64(std::string* out, std::uint64_t value) {
    for (int shift = 56; shift >= 0; shift -= 8) {
        out->push_back(static_cast<char>((value >> shift) & 0xffu));
    }
}

void update_tree_digest(std::string* out, const TreeEntry& entry) {
    out->push_back(entry.type);
    append_u64(out, entry.relative.size());
    out->append(entry.relative);
    append_u64(out, entry.size);
    append_u64(out, entry.digest.size());
    out->append(entry.digest);
}

std::string read_link_target(const std::string& path) {
    std::vector<char> buffer(256);
    while (true) {
        const ssize_t count =
            ::readlink(path.c_str(), buffer.data(), buffer.size());
        if (count < 0) {
            throw mismatch("run manifest resource cannot be hashed: vdb");
        }
        if (static_cast<std::size_t>(count) < buffer.size()) {
            return std::string(buffer.data(), static_cast<std::size_t>(count));
        }
        buffer.resize(buffer.size() * 2);
    }
}

void collect_directory(const fs::path& root, const fs::path& directory,
                       std::vector<TreeEntry>* entries,
                       std::uint64_t* file_count,
                       std::uint64_t* directory_count,
                       std::uint64_t* symlink_count,
                       std::uint64_t* total_size);

void collect_file(const fs::path& root, const fs::path& file,
                  const struct stat& before, std::vector<TreeEntry>* entries,
                  std::uint64_t* file_count, std::uint64_t* total_size) {
    TreeEntry entry;
    entry.relative = file.lexically_relative(root).generic_string();
    entry.type = 'F';
    entry.digest = sha256_file_raw(file.string());
    struct stat after;
    if (::lstat(file.c_str(), &after) != 0 || stat_changed(before, after)) {
        throw mismatch("run manifest resource cannot be hashed: vdb");
    }
    entry.size = static_cast<std::uint64_t>(after.st_size);
    entries->push_back(std::move(entry));
    ++*file_count;
    *total_size += static_cast<std::uint64_t>(after.st_size);
}

void collect_directory(const fs::path& root, const fs::path& directory,
                       std::vector<TreeEntry>* entries,
                       std::uint64_t* file_count,
                       std::uint64_t* directory_count,
                       std::uint64_t* symlink_count,
                       std::uint64_t* total_size) {
    struct stat directory_before;
    if (::lstat(directory.c_str(), &directory_before) != 0 ||
        !S_ISDIR(directory_before.st_mode)) {
        throw mismatch("run manifest resource cannot be hashed: vdb");
    }
    struct Node {
        fs::path path;
        struct stat info;
    };
    std::vector<Node> children;
    std::error_code ec;
    for (fs::directory_iterator it(directory, ec), end; !ec && it != end;
         it.increment(ec)) {
        Node node;
        node.path = it->path();
        if (::lstat(node.path.c_str(), &node.info) != 0) {
            throw mismatch("run manifest resource cannot be hashed: vdb");
        }
        children.push_back(std::move(node));
    }
    if (ec) throw mismatch("run manifest resource cannot be hashed: vdb");
    std::sort(children.begin(), children.end(),
              [](const Node& a, const Node& b) {
                  return a.path.filename().generic_string() <
                         b.path.filename().generic_string();
              });
    for (const auto& node : children) {
        const std::string relative =
            node.path.lexically_relative(root).generic_string();
        if (S_ISLNK(node.info.st_mode)) {
            TreeEntry entry;
            entry.relative = relative;
            entry.type = 'L';
            const std::string target = read_link_target(node.path.string());
            entry.size = target.size();
            entry.digest = sha256_raw(target);
            struct stat after;
            if (::lstat(node.path.c_str(), &after) != 0 ||
                stat_changed(node.info, after)) {
                throw mismatch("run manifest resource cannot be hashed: vdb");
            }
            entries->push_back(std::move(entry));
            ++*symlink_count;
        } else if (S_ISDIR(node.info.st_mode)) {
            TreeEntry entry;
            entry.relative = relative;
            entry.type = 'D';
            entries->push_back(std::move(entry));
            ++*directory_count;
            collect_directory(root, node.path, entries, file_count,
                              directory_count, symlink_count, total_size);
        } else if (S_ISREG(node.info.st_mode)) {
            collect_file(root, node.path, node.info, entries, file_count,
                         total_size);
        } else {
            throw mismatch("run manifest resource cannot be hashed: vdb");
        }
    }
    struct stat directory_after;
    if (::lstat(directory.c_str(), &directory_after) != 0 ||
        stat_changed(directory_before, directory_after)) {
        throw mismatch("run manifest resource cannot be hashed: vdb");
    }
}

std::string canonical_path(const fs::path& path, const std::string& message) {
    std::error_code ec;
    const fs::path resolved = fs::canonical(path, ec);
    if (ec) throw mismatch(message);
    return resolved.string();
}

} // namespace

ResourceIdentity resource_identity(const std::string& path) {
    ResourceIdentity identity;
    struct stat top_before;
    if (::lstat(path.c_str(), &top_before) != 0) {
        throw mismatch("run manifest resource cannot be hashed: vdb");
    }
    std::string payload = "xcov.resource.v2";
    payload.push_back('\0');
    if (S_ISREG(top_before.st_mode)) {
        identity.kind = "file";
        std::vector<TreeEntry> entries;
        std::uint64_t file_count = 0;
        std::uint64_t total_size = 0;
        collect_file(fs::path(path), fs::path(path), top_before, &entries,
                     &file_count, &total_size);
        // collect_file computes a relative path; the file identity uses "".
        entries.front().relative.clear();
        update_tree_digest(&payload, entries.front());
        identity.size_bytes = total_size;
        identity.file_count = file_count;
        identity.directory_count = 0;
        identity.symlink_count = 0;
    } else if (S_ISDIR(top_before.st_mode)) {
        identity.kind = "directory";
        std::vector<TreeEntry> entries;
        std::uint64_t file_count = 0;
        std::uint64_t directory_count = 1;
        std::uint64_t symlink_count = 0;
        std::uint64_t total_size = 0;
        collect_directory(fs::path(path), fs::path(path), &entries,
                          &file_count, &directory_count, &symlink_count,
                          &total_size);
        std::sort(entries.begin(), entries.end(),
                  [](const TreeEntry& a, const TreeEntry& b) {
                      if (a.relative != b.relative) {
                          return a.relative < b.relative;
                      }
                      return a.type < b.type;
                  });
        for (const auto& entry : entries) update_tree_digest(&payload, entry);
        identity.size_bytes = total_size;
        identity.file_count = file_count;
        identity.directory_count = directory_count;
        identity.symlink_count = symlink_count;
    } else {
        throw mismatch("run manifest resource cannot be hashed: vdb");
    }
    const std::string raw = sha256_raw(payload);
    static const char* kHex = "0123456789abcdef";
    identity.sha256.reserve(64);
    for (unsigned char byte : raw) {
        identity.sha256.push_back(kHex[byte >> 4]);
        identity.sha256.push_back(kHex[byte & 0x0f]);
    }
    return identity;
}

nlohmann::json validate_run_manifest(const nlohmann::json& target) {
    const json run_manifest =
        target.contains("run_manifest") ? target.at("run_manifest")
                                        : json(nullptr);
    if (run_manifest.is_null()) return nullptr;
    if (!run_manifest.is_string() ||
        run_manifest.get<std::string>().empty()) {
        throw mismatch("target.run_manifest must be a non-empty path");
    }
    const std::string manifest_text =
        read_text_file(run_manifest.get<std::string>());
    const json document = strict_json_parse(manifest_text);

    const std::set<std::string> root_keys = {"schema_version", "state",
                                             "resources"};
    const std::vector<std::string> root_required = {"schema_version", "state",
                                                    "resources"};
    if (!object_only(document, root_keys, root_required)) {
        throw mismatch("run manifest violates the closed contract at $");
    }
    if (!document.at("schema_version").is_string() ||
        document.at("schema_version").get<std::string>() !=
            "xcov.run-manifest.v2") {
        throw mismatch("run manifest violates the closed contract at "
                       "$.schema_version");
    }
    if (!document.at("state").is_string() ||
        document.at("state").get<std::string>() != "published") {
        throw mismatch("run manifest violates the closed contract at $.state");
    }
    const json resources = document.at("resources");
    if (!object_only(resources, {"vdb"}, {"vdb"})) {
        throw mismatch("run manifest violates the closed contract at "
                       "$.resources");
    }
    const json resource = resources.at("vdb");
    const std::set<std::string> resource_keys = {
        "path",         "kind",         "hash_version", "size_bytes",
        "file_count",   "directory_count", "symlink_count", "sha256"};
    const std::vector<std::string> resource_required = {
        "path",           "kind",            "hash_version", "size_bytes",
        "file_count",     "directory_count", "symlink_count", "sha256"};
    if (!object_only(resource, resource_keys, resource_required)) {
        throw mismatch("run manifest violates the closed contract at "
                       "$.resources.vdb");
    }
    std::string declared_path;
    std::string declared_kind;
    std::string declared_hash_version;
    std::string declared_sha;
    std::uint64_t declared_size = 0;
    std::uint64_t declared_files = 0;
    std::uint64_t declared_directories = 0;
    std::uint64_t declared_symlinks = 0;
    if (!json_string(resource.at("path"), &declared_path) ||
        !safe_resource_path(declared_path)) {
        throw mismatch("run manifest violates the closed contract at "
                       "$.resources.vdb.path");
    }
    if (!json_string(resource.at("kind"), &declared_kind) ||
        (declared_kind != "file" && declared_kind != "directory")) {
        throw mismatch("run manifest violates the closed contract at "
                       "$.resources.vdb.kind");
    }
    if (!json_string(resource.at("hash_version"), &declared_hash_version) ||
        declared_hash_version != kHashVersion) {
        throw mismatch("run manifest violates the closed contract at "
                       "$.resources.vdb.hash_version");
    }
    if (!json_int(resource.at("size_bytes"), &declared_size) ||
        !json_int(resource.at("file_count"), &declared_files) ||
        !json_int(resource.at("directory_count"), &declared_directories) ||
        !json_int(resource.at("symlink_count"), &declared_symlinks)) {
        throw mismatch("run manifest violates the closed contract at "
                       "$.resources.vdb");
    }
    if (!json_string(resource.at("sha256"), &declared_sha) ||
        !valid_hash(declared_sha)) {
        throw mismatch("run manifest violates the closed contract at "
                       "$.resources.vdb.sha256");
    }

    const fs::path manifest_path =
        fs::path(run_manifest.get<std::string>());
    const std::string manifest_canonical =
        canonical_path(manifest_path,
                       "run manifest is missing or cannot be resolved");
    const std::string vdb_text =
        target.contains("vdb") && target.at("vdb").is_string()
            ? target.at("vdb").get<std::string>()
            : std::string();
    if (vdb_text.empty()) {
        throw mismatch("target.vdb is required when run_manifest is provided");
    }
    const std::string expected_path =
        canonical_path(fs::path(manifest_canonical).parent_path() /
                           declared_path,
                       "run manifest is missing or cannot be resolved");
    const std::string actual_path =
        canonical_path(vdb_text,
                       "run manifest is missing or cannot be resolved");
    if (expected_path != actual_path) {
        throw mismatch("run manifest resource path does not match target: vdb");
    }
    ResourceIdentity actual;
    try {
        actual = resource_identity(actual_path);
    } catch (const Error&) {
        // Keep the provenance contract closed: unreadable resources are a
        // provenance mismatch, not an IO_ERROR escaping the gate.
        throw mismatch("run manifest resource cannot be hashed: vdb");
    }
    if (actual.kind != declared_kind || actual.size_bytes != declared_size ||
        actual.file_count != declared_files ||
        actual.directory_count != declared_directories ||
        actual.symlink_count != declared_symlinks ||
        actual.sha256 != declared_sha) {
        throw mismatch("run manifest resource identity does not match "
                       "target: vdb");
    }
    json details = document;
    details["manifest_path"] = manifest_canonical;
    return details;
}

} // namespace xcov
