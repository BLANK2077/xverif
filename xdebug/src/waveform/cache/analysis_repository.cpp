#include "analysis_repository.h"

#include "analysis_probe.h"
#include "core/common/sha256.h"
#include "core/session/request_deadline.h"

#include <cerrno>
#include <cctype>
#include <cmath>
#include <cstdlib>
#include <limits>
#include <sstream>
#include <sys/stat.h>
#include <tuple>
#include <vector>

namespace xdebug_waveform {
namespace {

std::uint64_t saturating_add(std::uint64_t lhs, std::uint64_t rhs) {
    const std::uint64_t maximum = std::numeric_limits<std::uint64_t>::max();
    return rhs > maximum - lhs ? maximum : lhs + rhs;
}

bool parse_unsigned_environment(const char* name, std::uint64_t default_value,
                                bool allow_zero, std::uint64_t& value,
                                std::string& error) {
    const char* raw = std::getenv(name);
    if (raw == nullptr) {
        value = default_value;
        return true;
    }
    if (!std::isdigit(static_cast<unsigned char>(raw[0]))) {
        error = std::string(name) + " must be an unsigned integer";
        return false;
    }
    errno = 0;
    char* end = nullptr;
    const unsigned long long parsed = std::strtoull(raw, &end, 10);
    if (errno != 0 || end == raw || *end != '\0' || (!allow_zero && parsed == 0)) {
        error = std::string(name) + (allow_zero
            ? " must be a non-negative integer without trailing characters"
            : " must be a positive integer without trailing characters");
        return false;
    }
    value = static_cast<std::uint64_t>(parsed);
    return true;
}

const char* scope_text(AnalysisCacheScope scope) {
    return scope == AnalysisCacheScope::Full ? "full" : "range";
}

}  // namespace

bool FsdbIdentity::operator==(const FsdbIdentity& other) const {
    return device == other.device && inode == other.inode &&
           size == other.size && mtime == other.mtime;
}

bool FsdbIdentity::operator<(const FsdbIdentity& other) const {
    return std::tie(device, inode, size, mtime) <
           std::tie(other.device, other.inode, other.size, other.mtime);
}

bool AnalysisCacheKey::operator==(const AnalysisCacheKey& other) const {
    return protocol == other.protocol && session_id == other.session_id &&
           fsdb == other.fsdb && fingerprint_version == other.fingerprint_version &&
           normalized_semantics == other.normalized_semantics &&
           semantic_digest == other.semantic_digest && scope == other.scope &&
           range_begin == other.range_begin && range_end == other.range_end;
}

bool AnalysisCacheKey::operator<(const AnalysisCacheKey& other) const {
    return std::tie(protocol, session_id, fsdb, fingerprint_version,
                    semantic_digest, normalized_semantics, scope,
                    range_begin, range_end) <
           std::tie(other.protocol, other.session_id, other.fsdb,
                    other.fingerprint_version, other.semantic_digest,
                    other.normalized_semantics, other.scope,
                    other.range_begin, other.range_end);
}

std::string AnalysisCacheKey::summary() const {
    return digest.size() <= 16 ? digest : digest.substr(0, 16);
}

AnalysisCacheKey make_analysis_cache_key(const std::string& protocol,
                                         const std::string& session_id,
                                         const FsdbIdentity& fsdb,
                                         std::uint32_t fingerprint_version,
                                         const std::string& normalized_semantics,
                                         AnalysisCacheScope scope,
                                         npiFsdbTime range_begin,
                                         npiFsdbTime range_end) {
    AnalysisCacheKey key;
    key.protocol = protocol;
    key.session_id = session_id;
    key.fsdb = fsdb;
    key.fingerprint_version = fingerprint_version;
    key.normalized_semantics = normalized_semantics;
    key.semantic_digest = xdebug_core::sha256_text(normalized_semantics);
    key.scope = scope;
    key.range_begin = scope == AnalysisCacheScope::Range ? range_begin : 0;
    key.range_end = scope == AnalysisCacheScope::Range ? range_end : 0;
    std::ostringstream material;
    material << "analysis-key-v1\n" << protocol << '\n' << session_id << '\n'
             << fsdb.device << '\n' << fsdb.inode << '\n' << fsdb.size << '\n'
             << fsdb.mtime << '\n' << fingerprint_version << '\n'
             << key.semantic_digest << '\n' << scope_text(scope) << '\n'
             << key.range_begin << '\n' << key.range_end;
    key.digest = xdebug_core::sha256_text(material.str());
    return key;
}

bool read_fsdb_identity(const std::string& path, FsdbIdentity& identity,
                        std::string& error) {
    struct stat info {};
    if (stat(path.c_str(), &info) != 0 || !S_ISREG(info.st_mode)) {
        error = "cannot stat regular FSDB file";
        return false;
    }
    identity.device = static_cast<std::uint64_t>(info.st_dev);
    identity.inode = static_cast<std::uint64_t>(info.st_ino);
    identity.size = static_cast<std::uint64_t>(info.st_size);
    identity.mtime = static_cast<std::int64_t>(info.st_mtime);
    return true;
}

bool analysis_cache_config_from_environment(AnalysisCacheConfig& config,
                                            std::string& error) {
    config = AnalysisCacheConfig();
    if (!parse_unsigned_environment("XDEBUG_ANALYSIS_CACHE_MAX_BYTES",
                                    kAnalysisCacheSoftDefaultBytes, true,
                                    config.soft_max_bytes, error) ||
        !parse_unsigned_environment("XDEBUG_ANALYSIS_CACHE_HARD_MAX_BYTES",
                                    kAnalysisCacheHardDefaultBytes, false,
                                    config.hard_max_bytes, error)) {
        return false;
    }
    if (config.soft_max_bytes > config.hard_max_bytes) {
        error = "XDEBUG_ANALYSIS_CACHE_MAX_BYTES must not exceed "
                "XDEBUG_ANALYSIS_CACHE_HARD_MAX_BYTES";
        return false;
    }
    return true;
}

bool AnalysisRepository::IndexKey::operator<(const IndexKey& other) const {
    return std::tie(canonical_key, canonical_generation, index_kind) <
           std::tie(other.canonical_key, other.canonical_generation,
                    other.index_kind);
}

bool AnalysisRepository::IndexKey::operator==(const IndexKey& other) const {
    return canonical_key == other.canonical_key &&
           canonical_generation == other.canonical_generation &&
           index_kind == other.index_kind;
}

AnalysisRepository::AnalysisRepository(const AnalysisCacheConfig& config,
                                       AnalysisCacheEventSink event_sink)
    : config_(config), event_sink_(std::move(event_sink)) {}

AnalysisRepository::CanonicalStore*
AnalysisRepository::canonical_store_for_protocol(const std::string& protocol) {
    if (protocol == "apb") return &apb_entries_;
    if (protocol == "axi") return &axi_entries_;
    if (protocol == "stream") return &stream_entries_;
    return nullptr;
}

const AnalysisRepository::CanonicalStore*
AnalysisRepository::canonical_store_for_protocol(
    const std::string& protocol) const {
    if (protocol == "apb") return &apb_entries_;
    if (protocol == "axi") return &axi_entries_;
    if (protocol == "stream") return &stream_entries_;
    return nullptr;
}

std::uint64_t AnalysisRepository::charge(std::uint64_t estimated_bytes) const {
    if (estimated_bytes == 0) return 0;
    const long double charged = static_cast<long double>(estimated_bytes) *
                                config_.estimator_safety_factor;
    if (charged >= static_cast<long double>(
                       std::numeric_limits<std::uint64_t>::max())) {
        return std::numeric_limits<std::uint64_t>::max();
    }
    return static_cast<std::uint64_t>(std::ceil(charged));
}

std::uint64_t AnalysisRepository::next_access_sequence() {
    if (access_sequence_ != std::numeric_limits<std::uint64_t>::max())
        ++access_sequence_;
    return access_sequence_;
}

std::uint64_t AnalysisRepository::current_charged_bytes(
    const AnalysisCacheKey* exempt_canonical,
    const IndexKey* exempt_index,
    const AnalysisCacheKey* excluded_stream_ranges_for_full) const {
    std::uint64_t total = 0;
    for (const CanonicalStore* store : {&apb_entries_, &axi_entries_,
                                        &stream_entries_}) {
        for (const auto& item : *store) {
            if (exempt_canonical != nullptr && item.first == *exempt_canonical)
                continue;
            if (excluded_stream_ranges_for_full != nullptr &&
                is_stream_sibling_range(
                    item.first, *excluded_stream_ranges_for_full))
                continue;
            total = saturating_add(
                total, charge(item.second.resident_estimated_bytes));
            total = saturating_add(
                total, charge(item.second.build_estimated_bytes));
        }
    }
    for (const auto& item : indexes_) {
        if (exempt_index != nullptr && item.first == *exempt_index) continue;
        if (excluded_stream_ranges_for_full != nullptr &&
            is_stream_sibling_range(
                item.first.canonical_key,
                *excluded_stream_ranges_for_full))
            continue;
        total = saturating_add(total, charge(item.second.resident_estimated_bytes));
        total = saturating_add(total, charge(item.second.build_estimated_bytes));
    }
    return total;
}

std::uint64_t AnalysisRepository::current_resident_estimated_bytes() const {
    std::uint64_t total = 0;
    for (const CanonicalStore* store : {&apb_entries_, &axi_entries_,
                                        &stream_entries_})
        for (const auto& item : *store)
            total = saturating_add(total,
                                   item.second.resident_estimated_bytes);
    for (const auto& item : indexes_)
        total = saturating_add(total, item.second.resident_estimated_bytes);
    return total;
}

std::uint64_t AnalysisRepository::current_build_estimated_bytes() const {
    std::uint64_t total = 0;
    for (const CanonicalStore* store : {&apb_entries_, &axi_entries_,
                                        &stream_entries_})
        for (const auto& item : *store)
            total = saturating_add(total, item.second.build_estimated_bytes);
    for (const auto& item : indexes_)
        total = saturating_add(total, item.second.build_estimated_bytes);
    return total;
}

void AnalysisRepository::set_memory_error(AnalysisCacheError& error,
                                          const AnalysisCacheKey& key) const {
    error.code = "ANALYSIS_MEMORY_LIMIT_EXCEEDED";
    error.message = "analysis cache build exceeds the configured hard memory limit";
    error.recoverable = true;
    error.current_estimated_bytes = current_resident_estimated_bytes();
    error.hard_max_bytes = config_.hard_max_bytes;
    error.protocol = key.protocol;
    error.key_summary = key.summary();
    error.suggestions = {
        "For stream analysis, explicitly retry with cache_scope=range or a smaller time_range.",
        "If range analysis still exceeds the limit, use x-npi for one-off offline analysis.",
    };
}

bool AnalysisRepository::make_hard_room(
    std::uint64_t new_charge,
    const AnalysisCacheKey* protected_canonical,
    const IndexKey* protected_index,
    AnalysisCacheError& error,
    const AnalysisCacheKey& request_key,
    const AnalysisCacheKey* excluded_stream_ranges_for_full) {
    const AnalysisCacheKey* preserve_stream_ranges_for_full =
        request_key.protocol == "stream" &&
        request_key.scope == AnalysisCacheScope::Full
            ? &request_key : nullptr;
    while (saturating_add(
               current_charged_bytes(
                   nullptr, nullptr, excluded_stream_ranges_for_full),
               new_charge) >
           config_.hard_max_bytes) {
        xdebug_core::request_deadline_checkpoint();
        if (evict_cold_index(
                protected_index, protected_canonical, "hard_limit",
                preserve_stream_ranges_for_full))
            continue;
        if (evict_cold_canonical(
                protected_canonical, "hard_limit",
                preserve_stream_ranges_for_full))
            continue;
        set_memory_error(error, request_key);
        return false;
    }
    return true;
}

void AnalysisRepository::enforce_soft_budget(
    const AnalysisCacheKey* protected_canonical,
    const IndexKey* protected_index) {
    if (config_.soft_max_bytes == 0) return;
    while (current_charged_bytes(nullptr, nullptr) > config_.soft_max_bytes) {
        xdebug_core::request_deadline_checkpoint();
        if (evict_cold_index(protected_index, protected_canonical, "soft_lru"))
            continue;
        if (evict_cold_canonical(protected_canonical, "soft_lru")) continue;
        break;
    }
}

bool AnalysisRepository::evict_cold_index(
    const IndexKey* protected_index,
    const AnalysisCacheKey*,
    const std::string& reason,
    const AnalysisCacheKey* preserve_stream_ranges_for_full) {
    auto candidate = indexes_.end();
    for (auto it = indexes_.begin(); it != indexes_.end(); ++it) {
        xdebug_core::request_deadline_checkpoint();
        if (it->second.state != ObjectState::Ready) continue;
        if (protected_index != nullptr && it->first == *protected_index) continue;
        if (preserve_stream_ranges_for_full != nullptr &&
            is_stream_sibling_range(
                it->first.canonical_key,
                *preserve_stream_ranges_for_full))
            continue;
        if (candidate == indexes_.end() ||
            it->second.access_sequence < candidate->second.access_sequence ||
            (it->second.access_sequence == candidate->second.access_sequence &&
             it->first < candidate->first)) {
            candidate = it;
        }
    }
    if (candidate == indexes_.end()) return false;
    AnalysisCacheEvent event;
    event.event = "evict";
    event.protocol = candidate->first.canonical_key.protocol;
    event.session_id = candidate->first.canonical_key.session_id;
    event.key_summary = candidate->first.canonical_key.summary();
    event.object_kind = "index:" + candidate->first.index_kind;
    event.reason = reason;
    event.estimated_bytes = candidate->second.resident_estimated_bytes;
    event.access_sequence = candidate->second.access_sequence;
    event.generation = candidate->first.canonical_generation;
    indexes_.erase(candidate);
    emit(event);
    return true;
}

bool AnalysisRepository::evict_cold_canonical(
    const AnalysisCacheKey* protected_canonical,
    const std::string& reason,
    const AnalysisCacheKey* preserve_stream_ranges_for_full) {
    CanonicalStore* candidate_store = nullptr;
    CanonicalStore::iterator candidate;
    for (CanonicalStore* store : {&apb_entries_, &axi_entries_,
                                  &stream_entries_}) {
        for (auto it = store->begin(); it != store->end(); ++it) {
            xdebug_core::request_deadline_checkpoint();
            if (it->second.state != ObjectState::Ready) continue;
            if (protected_canonical != nullptr &&
                it->first == *protected_canonical)
                continue;
            if (preserve_stream_ranges_for_full != nullptr &&
                is_stream_sibling_range(
                    it->first, *preserve_stream_ranges_for_full))
                continue;
            if (candidate_store == nullptr ||
                it->second.access_sequence <
                    candidate->second.access_sequence ||
                (it->second.access_sequence ==
                     candidate->second.access_sequence &&
                 it->first < candidate->first)) {
                candidate_store = store;
                candidate = it;
            }
        }
    }
    if (candidate_store == nullptr) return false;
    const AnalysisCacheKey key = candidate->first;
    erase_canonical_internal(key, reason, false);
    evicted_keys_.insert(key);
    return true;
}

bool AnalysisRepository::is_stream_sibling_range(
    const AnalysisCacheKey& candidate,
    const AnalysisCacheKey& full_key) {
    return full_key.protocol == "stream" &&
           full_key.scope == AnalysisCacheScope::Full &&
           candidate.protocol == "stream" &&
           candidate.scope == AnalysisCacheScope::Range &&
           candidate.session_id == full_key.session_id &&
           candidate.fsdb == full_key.fsdb &&
           candidate.fingerprint_version == full_key.fingerprint_version &&
           candidate.semantic_digest == full_key.semantic_digest &&
           candidate.normalized_semantics == full_key.normalized_semantics;
}

void AnalysisRepository::erase_stream_sibling_ranges(
    const AnalysisCacheKey& full_key) {
    std::vector<AnalysisCacheKey> ranges;
    for (const auto& item : stream_entries_)
        if (is_stream_sibling_range(item.first, full_key))
            ranges.push_back(item.first);
    for (const auto& range : ranges)
        erase_canonical_internal(range, "full_replaced_range", true);
}

void AnalysisRepository::erase_canonical_internal(
    const AnalysisCacheKey& key, const std::string& reason,
    bool invalidate_cursors) {
    CanonicalStore* store = canonical_store_for_protocol(key.protocol);
    if (store == nullptr) return;
    auto found = store->find(key);
    if (found == store->end()) return;
    const std::uint64_t generation = found->second.generation;
    for (auto it = indexes_.begin(); it != indexes_.end();) {
        if (it->first.canonical_key == key) it = indexes_.erase(it);
        else ++it;
    }
    if (invalidate_cursors) {
        for (auto it = cursors_.begin(); it != cursors_.end();) {
            if (it->second.key == key) it = cursors_.erase(it);
            else ++it;
        }
    }
    AnalysisCacheEvent event;
    event.event = invalidate_cursors ? "invalidate" : "evict";
    event.protocol = key.protocol;
    event.session_id = key.session_id;
    event.key_summary = key.summary();
    event.object_kind = "canonical";
    event.reason = reason;
    event.estimated_bytes = found->second.resident_estimated_bytes;
    event.access_sequence = found->second.access_sequence;
    event.generation = generation;
    store->erase(found);
    emit(event);
}

AnalysisAcquireStatus AnalysisRepository::begin_canonical(
    const AnalysisCacheKey& key, const std::string& type_tag,
    std::uint64_t build_estimated_bytes, AnalysisCacheError& error) {
    error = AnalysisCacheError();
    CanonicalStore* store = canonical_store_for_protocol(key.protocol);
    if (store == nullptr) {
        error.code = "ANALYSIS_CACHE_PROTOCOL_UNSUPPORTED";
        error.message = "analysis cache protocol must be apb, axi, or stream";
        return AnalysisAcquireStatus::Rejected;
    }
    auto found = store->find(key);
    if (found != store->end()) {
        if (found->second.state == ObjectState::Building) {
            error.code = "ANALYSIS_CACHE_REENTRANT_BUILD";
            error.message = "analysis cache key is already building in this engine";
            return AnalysisAcquireStatus::ReentrantBuild;
        }
        if (found->second.type_tag != type_tag) {
            error.code = "ANALYSIS_CACHE_TYPE_MISMATCH";
            error.message = "analysis cache key was requested with a different type";
            return AnalysisAcquireStatus::Rejected;
        }
        found->second.access_sequence = next_access_sequence();
        emit(AnalysisCacheEvent{"hit", key.protocol, key.session_id, key.summary(),
                                "canonical", "", found->second.resident_estimated_bytes,
                                0, 0, found->second.access_sequence,
                                found->second.generation});
        return AnalysisAcquireStatus::Hit;
    }
    if (!make_hard_room(charge(build_estimated_bytes), nullptr, nullptr,
                        error, key)) {
        emit(AnalysisCacheEvent{"build_failed", key.protocol, key.session_id,
                                key.summary(), "canonical", "hard_limit",
                                build_estimated_bytes});
        return AnalysisAcquireStatus::Rejected;
    }
    CanonicalObject object;
    object.type_tag = type_tag;
    object.generation = ++generations_[key];
    object.build_estimated_bytes = build_estimated_bytes;
    object.access_sequence = next_access_sequence();
    (*store)[key] = object;
    const bool after_evict = evicted_keys_.find(key) != evicted_keys_.end();
    emit(AnalysisCacheEvent{"miss", key.protocol, key.session_id, key.summary(),
                            "canonical",
                            after_evict ? "cache_miss_after_evict" : "cold",
                            build_estimated_bytes, 0, build_estimated_bytes,
                            object.access_sequence, object.generation});
    return AnalysisAcquireStatus::BuildStarted;
}

bool AnalysisRepository::publish_canonical_erased(
    const AnalysisCacheKey& key, const std::string& type_tag,
    const std::shared_ptr<const void>& value,
    std::uint64_t resident_estimated_bytes, AnalysisCacheError& error) {
    CanonicalStore* store = canonical_store_for_protocol(key.protocol);
    if (store == nullptr) {
        error.code = "ANALYSIS_CACHE_PROTOCOL_UNSUPPORTED";
        error.message = "analysis cache protocol must be apb, axi, or stream";
        return false;
    }
    auto found = store->find(key);
    if (found == store->end() ||
        found->second.state != ObjectState::Building ||
        found->second.type_tag != type_tag || !value) {
        error.code = "ANALYSIS_CACHE_BUILD_STATE_INVALID";
        error.message = "canonical publish requires the matching building entry";
        return false;
    }
    found->second.build_estimated_bytes = 0;
    const AnalysisCacheKey* replaced_stream_ranges =
        key.protocol == "stream" && key.scope == AnalysisCacheScope::Full
            ? &key : nullptr;
    if (!make_hard_room(charge(resident_estimated_bytes), &key, nullptr,
                        error, key, replaced_stream_ranges)) {
        store->erase(found);
        emit(AnalysisCacheEvent{"build_failed", key.protocol, key.session_id,
                                key.summary(), "canonical", "hard_limit",
                                resident_estimated_bytes});
        return false;
    }
    if (replaced_stream_ranges != nullptr)
        erase_stream_sibling_ranges(key);
    found = store->find(key);
    found->second.state = ObjectState::Ready;
    found->second.value = value;
    found->second.resident_estimated_bytes = resident_estimated_bytes;
    found->second.access_sequence = next_access_sequence();
    const std::uint64_t generation = found->second.generation;
    const bool oversize = config_.soft_max_bytes != 0 &&
                          charge(resident_estimated_bytes) >
                              config_.soft_max_bytes;
    enforce_soft_budget(&key, nullptr);
    if (oversize) {
        emit(AnalysisCacheEvent{"oversize_admitted", key.protocol,
                                key.session_id, key.summary(), "canonical",
                                "soft_budget", resident_estimated_bytes,
                                resident_estimated_bytes, 0,
                                found->second.access_sequence, generation});
    }
    emit(AnalysisCacheEvent{"build", key.protocol, key.session_id, key.summary(),
                            "canonical", "", resident_estimated_bytes,
                            resident_estimated_bytes, 0,
                            found->second.access_sequence, generation});
    evicted_keys_.erase(key);
    return true;
}

bool AnalysisRepository::update_canonical_build_bytes(
    const AnalysisCacheKey& key, std::uint64_t build_estimated_bytes,
    AnalysisCacheError& error) {
    CanonicalStore* store = canonical_store_for_protocol(key.protocol);
    if (store == nullptr) {
        error.code = "ANALYSIS_CACHE_PROTOCOL_UNSUPPORTED";
        error.message = "analysis cache protocol must be apb, axi, or stream";
        return false;
    }
    auto found = store->find(key);
    if (found == store->end() || found->second.state != ObjectState::Building) {
        error.code = "ANALYSIS_CACHE_BUILD_STATE_INVALID";
        error.message = "canonical build accounting requires a building entry";
        return false;
    }
    found->second.build_estimated_bytes = 0;
    if (!make_hard_room(charge(build_estimated_bytes), &key, nullptr,
                        error, key)) {
        store->erase(found);
        emit(AnalysisCacheEvent{"build_failed", key.protocol, key.session_id,
                                key.summary(), "canonical", "hard_limit",
                                build_estimated_bytes});
        return false;
    }
    found = store->find(key);
    found->second.build_estimated_bytes = build_estimated_bytes;
    return true;
}

void AnalysisRepository::fail_canonical(const AnalysisCacheKey& key,
                                        const std::string& reason) {
    CanonicalStore* store = canonical_store_for_protocol(key.protocol);
    if (store == nullptr) return;
    auto found = store->find(key);
    if (found == store->end() ||
        found->second.state != ObjectState::Building) return;
    const std::uint64_t bytes = found->second.build_estimated_bytes;
    store->erase(found);
    emit(AnalysisCacheEvent{"build_failed", key.protocol, key.session_id,
                            key.summary(), "canonical", reason, bytes});
}

void AnalysisRepository::fail_canonical_bad_alloc(
    const AnalysisCacheKey& key, AnalysisCacheError& error) {
    fail_canonical(key, "bad_alloc");
    set_memory_error(error, key);
}

std::shared_ptr<const void> AnalysisRepository::find_canonical_erased(
    const AnalysisCacheKey& key, const std::string& type_tag,
    std::uint64_t* generation, bool record_access) {
    CanonicalStore* store = canonical_store_for_protocol(key.protocol);
    if (store == nullptr) return std::shared_ptr<const void>();
    auto found = store->find(key);
    if (found == store->end() || found->second.state != ObjectState::Ready ||
        found->second.type_tag != type_tag) return std::shared_ptr<const void>();
    if (record_access) found->second.access_sequence = next_access_sequence();
    if (generation != nullptr) *generation = found->second.generation;
    if (record_access)
        emit(AnalysisCacheEvent{"hit", key.protocol, key.session_id, key.summary(),
                                "canonical", "", found->second.resident_estimated_bytes,
                                0, 0, found->second.access_sequence,
                                found->second.generation});
    return found->second.value;
}

AnalysisAcquireStatus AnalysisRepository::begin_index(
    const AnalysisCacheKey& canonical_key,
    std::uint64_t canonical_generation, const std::string& index_kind,
    const std::string& type_tag, std::uint64_t build_estimated_bytes,
    AnalysisCacheError& error) {
    error = AnalysisCacheError();
    CanonicalStore* store = canonical_store_for_protocol(canonical_key.protocol);
    if (store == nullptr) {
        error.code = "ANALYSIS_CACHE_PROTOCOL_UNSUPPORTED";
        error.message = "analysis cache protocol must be apb, axi, or stream";
        return AnalysisAcquireStatus::Rejected;
    }
    auto owner = store->find(canonical_key);
    if (owner == store->end() || owner->second.state != ObjectState::Ready ||
        owner->second.generation != canonical_generation) {
        error.code = "ANALYSIS_CACHE_GENERATION_STALE";
        error.message = "lazy index owner generation is not resident";
        return AnalysisAcquireStatus::Rejected;
    }
    IndexKey key{canonical_key, canonical_generation, index_kind};
    auto found = indexes_.find(key);
    if (found != indexes_.end()) {
        if (found->second.state == ObjectState::Building) {
            error.code = "ANALYSIS_CACHE_REENTRANT_BUILD";
            error.message = "lazy index key is already building in this engine";
            return AnalysisAcquireStatus::ReentrantBuild;
        }
        if (found->second.type_tag != type_tag) {
            error.code = "ANALYSIS_CACHE_TYPE_MISMATCH";
            error.message = "lazy index was requested with a different type";
            return AnalysisAcquireStatus::Rejected;
        }
        const std::uint64_t sequence = next_access_sequence();
        found->second.access_sequence = sequence;
        owner->second.access_sequence = sequence;
        emit(AnalysisCacheEvent{"hit", canonical_key.protocol,
                                canonical_key.session_id,
                                canonical_key.summary(), "index:" + index_kind,
                                "", found->second.resident_estimated_bytes,
                                0, 0, sequence, canonical_generation});
        return AnalysisAcquireStatus::Hit;
    }
    if (!make_hard_room(charge(build_estimated_bytes), &canonical_key, nullptr,
                        error, canonical_key)) return AnalysisAcquireStatus::Rejected;
    IndexObject object;
    object.type_tag = type_tag;
    object.build_estimated_bytes = build_estimated_bytes;
    object.access_sequence = next_access_sequence();
    indexes_[key] = object;
    emit(AnalysisCacheEvent{"miss", canonical_key.protocol,
                            canonical_key.session_id, canonical_key.summary(),
                            "index:" + index_kind, "cold", build_estimated_bytes,
                            0, build_estimated_bytes, object.access_sequence,
                            canonical_generation});
    return AnalysisAcquireStatus::BuildStarted;
}

bool AnalysisRepository::publish_index_erased(
    const AnalysisCacheKey& canonical_key,
    std::uint64_t canonical_generation, const std::string& index_kind,
    const std::string& type_tag, const std::shared_ptr<const void>& value,
    std::uint64_t resident_estimated_bytes, AnalysisCacheError& error) {
    IndexKey key{canonical_key, canonical_generation, index_kind};
    auto found = indexes_.find(key);
    if (found == indexes_.end() || found->second.state != ObjectState::Building ||
        found->second.type_tag != type_tag || !value) {
        error.code = "ANALYSIS_CACHE_BUILD_STATE_INVALID";
        error.message = "index publish requires the matching building object";
        return false;
    }
    found->second.build_estimated_bytes = 0;
    if (!make_hard_room(charge(resident_estimated_bytes), &canonical_key, &key,
                        error, canonical_key)) {
        indexes_.erase(found);
        return false;
    }
    found = indexes_.find(key);
    found->second.state = ObjectState::Ready;
    found->second.value = value;
    found->second.resident_estimated_bytes = resident_estimated_bytes;
    found->second.access_sequence = next_access_sequence();
    CanonicalStore* store = canonical_store_for_protocol(canonical_key.protocol);
    auto owner = store == nullptr ? CanonicalStore::iterator() :
                                    store->find(canonical_key);
    if (store != nullptr && owner != store->end())
        owner->second.access_sequence = found->second.access_sequence;
    const std::uint64_t combined = store == nullptr || owner == store->end()
        ? charge(resident_estimated_bytes)
        : saturating_add(charge(owner->second.resident_estimated_bytes),
                         charge(resident_estimated_bytes));
    const bool oversize = config_.soft_max_bytes != 0 &&
                          combined > config_.soft_max_bytes;
    enforce_soft_budget(&canonical_key, &key);
    if (oversize)
        emit(AnalysisCacheEvent{"oversize_admitted", canonical_key.protocol,
                                canonical_key.session_id,
                                canonical_key.summary(), "index:" + index_kind,
                                "soft_budget", resident_estimated_bytes});
    emit(AnalysisCacheEvent{"index_build", canonical_key.protocol,
                            canonical_key.session_id, canonical_key.summary(),
                            "index:" + index_kind, "", resident_estimated_bytes,
                            resident_estimated_bytes, 0,
                            found->second.access_sequence, canonical_generation});
    return true;
}

bool AnalysisRepository::update_index_build_bytes(
    const AnalysisCacheKey& canonical_key,
    std::uint64_t canonical_generation, const std::string& index_kind,
    std::uint64_t build_estimated_bytes, AnalysisCacheError& error) {
    IndexKey key{canonical_key, canonical_generation, index_kind};
    auto found = indexes_.find(key);
    if (found == indexes_.end() || found->second.state != ObjectState::Building) {
        error.code = "ANALYSIS_CACHE_BUILD_STATE_INVALID";
        error.message = "index build accounting requires a building object";
        return false;
    }
    found->second.build_estimated_bytes = 0;
    if (!make_hard_room(charge(build_estimated_bytes), &canonical_key, &key,
                        error, canonical_key)) {
        indexes_.erase(found);
        emit(AnalysisCacheEvent{"build_failed", canonical_key.protocol,
                                canonical_key.session_id,
                                canonical_key.summary(), "index:" + index_kind,
                                "hard_limit", build_estimated_bytes});
        return false;
    }
    found = indexes_.find(key);
    found->second.build_estimated_bytes = build_estimated_bytes;
    return true;
}

void AnalysisRepository::fail_index(const AnalysisCacheKey& canonical_key,
                                    std::uint64_t canonical_generation,
                                    const std::string& index_kind,
                                    const std::string& reason) {
    IndexKey key{canonical_key, canonical_generation, index_kind};
    auto found = indexes_.find(key);
    if (found == indexes_.end() || found->second.state != ObjectState::Building)
        return;
    const std::uint64_t bytes = found->second.build_estimated_bytes;
    indexes_.erase(found);
    emit(AnalysisCacheEvent{"build_failed", canonical_key.protocol,
                            canonical_key.session_id, canonical_key.summary(),
                            "index:" + index_kind, reason, bytes});
}

void AnalysisRepository::fail_index_bad_alloc(
    const AnalysisCacheKey& canonical_key,
    std::uint64_t canonical_generation,
    const std::string& index_kind,
    AnalysisCacheError& error) {
    fail_index(canonical_key, canonical_generation, index_kind, "bad_alloc");
    set_memory_error(error, canonical_key);
}

std::shared_ptr<const void> AnalysisRepository::find_index_erased(
    const AnalysisCacheKey& canonical_key,
    std::uint64_t canonical_generation, const std::string& index_kind,
    const std::string& type_tag) {
    IndexKey key{canonical_key, canonical_generation, index_kind};
    auto found = indexes_.find(key);
    CanonicalStore* store = canonical_store_for_protocol(canonical_key.protocol);
    if (store == nullptr) return std::shared_ptr<const void>();
    auto owner = store->find(canonical_key);
    if (found == indexes_.end() || owner == store->end() ||
        found->second.state != ObjectState::Ready ||
        found->second.type_tag != type_tag ||
        owner->second.generation != canonical_generation) {
        return std::shared_ptr<const void>();
    }
    const std::uint64_t sequence = next_access_sequence();
    found->second.access_sequence = sequence;
    owner->second.access_sequence = sequence;
    emit(AnalysisCacheEvent{"hit", canonical_key.protocol,
                            canonical_key.session_id, canonical_key.summary(),
                            "index:" + index_kind, "",
                            found->second.resident_estimated_bytes, 0, 0,
                            sequence, canonical_generation});
    return found->second.value;
}

std::shared_ptr<const void> AnalysisRepository::peek_index_erased(
    const AnalysisCacheKey& canonical_key,
    std::uint64_t canonical_generation, const std::string& index_kind,
    const std::string& type_tag) {
    IndexKey key{canonical_key, canonical_generation, index_kind};
    auto found = indexes_.find(key);
    CanonicalStore* store = canonical_store_for_protocol(canonical_key.protocol);
    if (store == nullptr) return std::shared_ptr<const void>();
    auto owner = store->find(canonical_key);
    if (found == indexes_.end() || owner == store->end() ||
        found->second.state != ObjectState::Ready ||
        found->second.type_tag != type_tag ||
        owner->second.generation != canonical_generation) {
        return std::shared_ptr<const void>();
    }
    return found->second.value;
}

bool AnalysisRepository::put_cursor(const GenerationCursor& cursor) {
    if (cursor.cursor_id.empty()) return false;
    cursors_[cursor.cursor_id] = cursor;
    return true;
}

bool AnalysisRepository::get_cursor(const std::string& cursor_id,
                                    GenerationCursor& cursor) const {
    auto found = cursors_.find(cursor_id);
    if (found == cursors_.end()) return false;
    cursor = found->second;
    return true;
}

bool AnalysisRepository::resume_cursor(const std::string& cursor_id,
                                       const AnalysisCacheKey& rebuilt_key,
                                       std::uint64_t rebuilt_generation,
                                       GenerationCursor& cursor) {
    auto found = cursors_.find(cursor_id);
    if (found == cursors_.end() || !(found->second.key == rebuilt_key))
        return false;
    found->second.generation = rebuilt_generation;
    cursor = found->second;
    return true;
}

void AnalysisRepository::erase_cursor(const std::string& cursor_id) {
    cursors_.erase(cursor_id);
}

void AnalysisRepository::invalidate(const AnalysisCacheKey& key,
                                    const std::string& reason) {
    evicted_keys_.erase(key);
    erase_canonical_internal(key, reason, true);
}

void AnalysisRepository::clear(const std::string& reason) {
    for (CanonicalStore* store : {&apb_entries_, &axi_entries_,
                                  &stream_entries_}) {
        while (!store->empty()) {
            xdebug_core::request_deadline_checkpoint();
            erase_canonical_internal(store->begin()->first, reason, true);
        }
    }
    indexes_.clear();
    cursors_.clear();
    stream_bindings_.clear();
    evicted_keys_.clear();
}

void AnalysisRepository::notify_stream_config_change(
    const std::string& session_id, const std::string& config_name,
    const std::string& old_semantic_digest,
    const std::string& new_semantic_digest) {
    notify_stream_config_changes(
        session_id,
        {{config_name, old_semantic_digest, new_semantic_digest}});
}

void AnalysisRepository::notify_stream_config_changes(
    const std::string& session_id,
    const std::vector<std::tuple<std::string, std::string, std::string>>&
        changes) {
    std::set<std::string> old_digests;
    for (const auto& change : changes) {
        xdebug_core::request_deadline_checkpoint();
        const std::string& name = std::get<0>(change);
        const std::string& old_digest = std::get<1>(change);
        const std::string& new_digest = std::get<2>(change);
        stream_bindings_[session_id][name] = new_digest;
        if (!old_digest.empty() && old_digest != new_digest)
            old_digests.insert(old_digest);
    }
    for (const std::string& old_digest : old_digests) {
        xdebug_core::request_deadline_checkpoint();
        bool still_bound = false;
        for (const auto& binding : stream_bindings_[session_id]) {
            if (binding.second == old_digest) {
                still_bound = true;
                break;
            }
        }
        if (still_bound) continue;
        std::vector<AnalysisCacheKey> invalid;
        for (const auto& item : stream_entries_)
            if (item.first.session_id == session_id &&
                item.first.semantic_digest == old_digest)
                invalid.push_back(item.first);
        for (const auto& key : invalid)
            invalidate(key, "stream_config_changed");
    }
}

AnalysisRepositoryStats AnalysisRepository::stats() const {
    AnalysisRepositoryStats value;
    for (const CanonicalStore* store : {&apb_entries_, &axi_entries_,
                                        &stream_entries_})
        for (const auto& item : *store)
            if (item.second.state == ObjectState::Ready)
                ++value.canonical_entry_count;
    for (const auto& item : indexes_)
        if (item.second.state == ObjectState::Ready) ++value.index_count;
    value.resident_estimated_bytes = current_resident_estimated_bytes();
    value.build_estimated_bytes = current_build_estimated_bytes();
    value.charged_bytes = current_charged_bytes(nullptr, nullptr);
    value.access_sequence = access_sequence_;
    return value;
}

void AnalysisRepository::emit(const AnalysisCacheEvent& event) const {
    if (event_sink_) event_sink_(event);
    const AnalysisRepositoryStats snapshot = stats();
    analysis_probe().record(
        event.event, event.protocol, event.key_summary,
        AnalysisProbeMetrics{snapshot.canonical_entry_count,
                             snapshot.index_count,
                             snapshot.resident_estimated_bytes,
                             snapshot.build_estimated_bytes, 0});
}

}  // namespace xdebug_waveform
