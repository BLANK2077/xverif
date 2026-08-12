#include "analysis_repository.h"

#include "analysis_probe.h"
#include "core/common/sha256.h"
#include "core/session/request_deadline.h"

#include <cerrno>
#include <algorithm>
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

std::uint64_t AnalysisRepository::key_metadata_bytes(
    const AnalysisCacheKey& key) {
    return sizeof(AnalysisCacheKey) + key.protocol.size() +
           key.session_id.size() + key.normalized_semantics.size() +
           key.semantic_digest.size() + key.digest.size() + 64U;
}

std::uint64_t AnalysisRepository::cursor_metadata_bytes(
    const GenerationCursor& cursor) {
    return sizeof(GenerationCursor) + cursor.cursor_id.size() +
           cursor.direction.size() + key_metadata_bytes(cursor.key) + 64U;
}

std::uint64_t AnalysisRepository::binding_metadata_bytes(
    const std::string& session_id, const std::string& config_name,
    const std::string& digest) {
    return sizeof(std::string) * 3U + session_id.size() + config_name.size() +
           digest.size() + 96U;
}

void AnalysisRepository::add_resident_bytes(std::uint64_t bytes) {
    stats_.resident_estimated_bytes = saturating_add(
        stats_.resident_estimated_bytes, bytes);
    stats_.charged_bytes = saturating_add(stats_.charged_bytes, charge(bytes));
}

void AnalysisRepository::remove_resident_bytes(std::uint64_t bytes) {
    stats_.resident_estimated_bytes -=
        std::min(stats_.resident_estimated_bytes, bytes);
    const std::uint64_t charged = charge(bytes);
    stats_.charged_bytes -= std::min(stats_.charged_bytes, charged);
}

void AnalysisRepository::add_build_bytes(std::uint64_t bytes) {
    stats_.build_estimated_bytes = saturating_add(
        stats_.build_estimated_bytes, bytes);
    stats_.charged_bytes = saturating_add(stats_.charged_bytes, charge(bytes));
}

void AnalysisRepository::remove_build_bytes(std::uint64_t bytes) {
    stats_.build_estimated_bytes -=
        std::min(stats_.build_estimated_bytes, bytes);
    const std::uint64_t charged = charge(bytes);
    stats_.charged_bytes -= std::min(stats_.charged_bytes, charged);
}

void AnalysisRepository::add_metadata_bytes(std::uint64_t bytes) {
    stats_.metadata_estimated_bytes = saturating_add(
        stats_.metadata_estimated_bytes, bytes);
    stats_.charged_bytes = saturating_add(stats_.charged_bytes, charge(bytes));
}

void AnalysisRepository::remove_metadata_bytes(std::uint64_t bytes) {
    stats_.metadata_estimated_bytes -=
        std::min(stats_.metadata_estimated_bytes, bytes);
    const std::uint64_t charged = charge(bytes);
    stats_.charged_bytes -= std::min(stats_.charged_bytes, charged);
}

void AnalysisRepository::erase_generation_if_unreferenced(
    const AnalysisCacheKey& key) {
    const CanonicalStore* store = canonical_store_for_protocol(key.protocol);
    if (store != nullptr && store->find(key) != store->end()) return;
    for (const auto& cursor : cursors_)
        if (cursor.second.key == key) return;
    auto found = generations_.find(key);
    if (found == generations_.end()) return;
    remove_metadata_bytes(key_metadata_bytes(found->first));
    generations_.erase(found);
    if (stats_.generation_count > 0) --stats_.generation_count;
}

bool AnalysisRepository::erase_one_releasable_metadata() {
    if (!evicted_keys_.empty()) {
        auto victim = evicted_keys_.begin();
        for (auto it = evicted_keys_.begin(); it != evicted_keys_.end(); ++it)
            if (it->second < victim->second ||
                (it->second == victim->second && it->first < victim->first))
                victim = it;
        const AnalysisCacheKey key = victim->first;
        remove_metadata_bytes(key_metadata_bytes(victim->first));
        evicted_keys_.erase(victim);
        if (stats_.tombstone_count > 0) --stats_.tombstone_count;
        erase_generation_if_unreferenced(key);
        return true;
    }
    if (!cursors_.empty()) {
        auto victim = cursors_.begin();
        std::uint64_t victim_sequence = cursor_access_sequences_[victim->first];
        for (auto it = cursors_.begin(); it != cursors_.end(); ++it) {
            const std::uint64_t sequence = cursor_access_sequences_[it->first];
            if (sequence < victim_sequence ||
                (sequence == victim_sequence && it->first < victim->first)) {
                victim = it;
                victim_sequence = sequence;
            }
        }
        const AnalysisCacheKey key = victim->second.key;
        remove_metadata_bytes(cursor_metadata_bytes(victim->second));
        cursor_access_sequences_.erase(victim->first);
        cursors_.erase(victim);
        if (stats_.cursor_count > 0) --stats_.cursor_count;
        erase_generation_if_unreferenced(key);
        return true;
    }
    if (!stream_bindings_.empty()) {
        auto session = stream_bindings_.begin();
        auto binding = session->second.begin();
        if (binding != session->second.end()) {
            remove_metadata_bytes(binding_metadata_bytes(
                session->first, binding->first, binding->second));
            session->second.erase(binding);
            if (stats_.binding_count > 0) --stats_.binding_count;
            if (session->second.empty()) stream_bindings_.erase(session);
            return true;
        }
    }
    return false;
}

std::uint64_t AnalysisRepository::current_charged_bytes(
    const AnalysisCacheKey* exempt_canonical,
    const IndexKey* exempt_index,
    const AnalysisCacheKey* excluded_stream_ranges_for_full) const {
    std::uint64_t total = stats_.charged_bytes;
    if (exempt_canonical != nullptr) {
        const CanonicalStore* store =
            canonical_store_for_protocol(exempt_canonical->protocol);
        const auto found = store == nullptr ? CanonicalStore::const_iterator() :
                                             store->find(*exempt_canonical);
        if (store != nullptr && found != store->end()) {
            const std::uint64_t exempt = saturating_add(
                charge(found->second.resident_estimated_bytes),
                charge(found->second.build_estimated_bytes));
            total -= std::min(total, exempt);
        }
    }
    if (exempt_index != nullptr) {
        const auto found = indexes_.find(*exempt_index);
        if (found != indexes_.end()) {
            const std::uint64_t exempt = saturating_add(
                charge(found->second.resident_estimated_bytes),
                charge(found->second.build_estimated_bytes));
            total -= std::min(total, exempt);
        }
    }
    if (excluded_stream_ranges_for_full != nullptr) {
        for (const auto& item : stream_entries_) {
            if (!is_stream_sibling_range(
                    item.first, *excluded_stream_ranges_for_full))
                continue;
            const std::uint64_t excluded = saturating_add(
                charge(item.second.resident_estimated_bytes),
                charge(item.second.build_estimated_bytes));
            total -= std::min(total, excluded);
        }
        for (const auto& item : indexes_) {
            if (!is_stream_sibling_range(
                    item.first.canonical_key,
                    *excluded_stream_ranges_for_full))
                continue;
            const std::uint64_t excluded = saturating_add(
                charge(item.second.resident_estimated_bytes),
                charge(item.second.build_estimated_bytes));
            total -= std::min(total, excluded);
        }
    }
    return total;
}

std::uint64_t AnalysisRepository::current_resident_estimated_bytes() const {
    return stats_.resident_estimated_bytes;
}

std::uint64_t AnalysisRepository::current_build_estimated_bytes() const {
    return stats_.build_estimated_bytes;
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
    evict_to_budget(config_.hard_max_bytes, new_charge,
                    protected_canonical, protected_index, "hard_limit",
                    preserve_stream_ranges_for_full,
                    excluded_stream_ranges_for_full);
    while (saturating_add(
               current_charged_bytes(
                   nullptr, nullptr, excluded_stream_ranges_for_full),
               new_charge) > config_.hard_max_bytes &&
           erase_one_releasable_metadata()) {
        xdebug_core::request_deadline_checkpoint();
    }
    if (saturating_add(
            current_charged_bytes(
                nullptr, nullptr, excluded_stream_ranges_for_full),
            new_charge) > config_.hard_max_bytes) {
        set_memory_error(error, request_key);
        return false;
    }
    return true;
}

void AnalysisRepository::enforce_soft_budget(
    const AnalysisCacheKey* protected_canonical,
    const IndexKey* protected_index) {
    if (config_.soft_max_bytes == 0) return;
    const std::uint64_t metadata_charge = charge(stats_.metadata_estimated_bytes);
    evict_to_budget(saturating_add(config_.soft_max_bytes, metadata_charge), 0,
                    protected_canonical,
                    protected_index, "soft_lru");
}

void AnalysisRepository::evict_to_budget(
    std::uint64_t limit, std::uint64_t new_charge,
    const AnalysisCacheKey* protected_canonical,
    const IndexKey* protected_index, const std::string& reason,
    const AnalysisCacheKey* preserve_stream_ranges_for_full,
    const AnalysisCacheKey* excluded_stream_ranges_for_full) {
    if (saturating_add(current_charged_bytes(
                           nullptr, nullptr,
                           excluded_stream_ranges_for_full),
                       new_charge) <=
        limit)
        return;
    std::vector<IndexKey> index_candidates;
    for (const auto& item : indexes_) {
        if (item.second.state != ObjectState::Ready) continue;
        if (protected_index != nullptr && item.first == *protected_index)
            continue;
        if (preserve_stream_ranges_for_full != nullptr &&
            is_stream_sibling_range(item.first.canonical_key,
                                    *preserve_stream_ranges_for_full))
            continue;
        index_candidates.push_back(item.first);
    }
    std::sort(index_candidates.begin(), index_candidates.end(),
              [&](const IndexKey& lhs, const IndexKey& rhs) {
                  const IndexObject& a = indexes_.find(lhs)->second;
                  const IndexObject& b = indexes_.find(rhs)->second;
                  return a.access_sequence != b.access_sequence
                             ? a.access_sequence < b.access_sequence
                             : lhs < rhs;
              });
    for (const auto& key : index_candidates) {
        if (saturating_add(current_charged_bytes(
                               nullptr, nullptr,
                               excluded_stream_ranges_for_full),
                           new_charge) <= limit)
            return;
        xdebug_core::request_deadline_checkpoint();
        auto found = indexes_.find(key);
        if (found == indexes_.end()) continue;
        AnalysisCacheEvent event{
            "evict", key.canonical_key.protocol,
            key.canonical_key.session_id, key.canonical_key.summary(),
            "index:" + key.index_kind, reason,
            found->second.resident_estimated_bytes, 0, 0,
            found->second.access_sequence, key.canonical_generation};
        remove_resident_bytes(found->second.resident_estimated_bytes);
        remove_build_bytes(found->second.build_estimated_bytes);
        if (found->second.state == ObjectState::Ready && stats_.index_count > 0)
            --stats_.index_count;
        indexes_.erase(found);
        emit(event);
    }

    std::vector<AnalysisCacheKey> canonical_candidates;
    for (const CanonicalStore* store : {&apb_entries_, &axi_entries_,
                                        &stream_entries_}) {
        for (const auto& item : *store) {
            if (item.second.state != ObjectState::Ready) continue;
            if (protected_canonical != nullptr &&
                item.first == *protected_canonical)
                continue;
            if (preserve_stream_ranges_for_full != nullptr &&
                is_stream_sibling_range(item.first,
                                        *preserve_stream_ranges_for_full))
                continue;
            canonical_candidates.push_back(item.first);
        }
    }
    std::sort(canonical_candidates.begin(), canonical_candidates.end(),
              [&](const AnalysisCacheKey& lhs, const AnalysisCacheKey& rhs) {
                  const auto* lhs_store = canonical_store_for_protocol(lhs.protocol);
                  const auto* rhs_store = canonical_store_for_protocol(rhs.protocol);
                  const auto& a = lhs_store->find(lhs)->second;
                  const auto& b = rhs_store->find(rhs)->second;
                  return a.access_sequence != b.access_sequence
                             ? a.access_sequence < b.access_sequence
                             : lhs < rhs;
              });
    for (const auto& key : canonical_candidates) {
        if (saturating_add(current_charged_bytes(
                               nullptr, nullptr,
                               excluded_stream_ranges_for_full),
                           new_charge) <= limit)
            return;
        xdebug_core::request_deadline_checkpoint();
        const auto* store = canonical_store_for_protocol(key.protocol);
        if (store == nullptr || store->find(key) == store->end()) continue;
        erase_canonical_internal(key, reason, false);
        const auto inserted = evicted_keys_.emplace(key, next_access_sequence());
        if (inserted.second) {
            add_metadata_bytes(key_metadata_bytes(key));
            ++stats_.tombstone_count;
        } else {
            inserted.first->second = next_access_sequence();
        }
    }
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
        if (it->first.canonical_key == key) {
            remove_resident_bytes(it->second.resident_estimated_bytes);
            remove_build_bytes(it->second.build_estimated_bytes);
            if (it->second.state == ObjectState::Ready && stats_.index_count > 0)
                --stats_.index_count;
            it = indexes_.erase(it);
        }
        else ++it;
    }
    if (invalidate_cursors) {
        for (auto it = cursors_.begin(); it != cursors_.end();) {
            if (it->second.key == key) {
                remove_metadata_bytes(cursor_metadata_bytes(it->second));
                cursor_access_sequences_.erase(it->first);
                if (stats_.cursor_count > 0) --stats_.cursor_count;
                it = cursors_.erase(it);
            }
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
    remove_resident_bytes(found->second.resident_estimated_bytes);
    remove_build_bytes(found->second.build_estimated_bytes);
    if (found->second.state == ObjectState::Ready &&
        stats_.canonical_entry_count > 0)
        --stats_.canonical_entry_count;
    store->erase(found);
    erase_generation_if_unreferenced(key);
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
    const bool new_generation = generations_.find(key) == generations_.end();
    const std::uint64_t generation_metadata =
        new_generation ? charge(key_metadata_bytes(key)) : 0;
    if (!make_hard_room(saturating_add(charge(build_estimated_bytes),
                                       generation_metadata),
                        nullptr, nullptr,
                        error, key)) {
        emit(AnalysisCacheEvent{"build_failed", key.protocol, key.session_id,
                                key.summary(), "canonical", "hard_limit",
                                build_estimated_bytes});
        return AnalysisAcquireStatus::Rejected;
    }
    CanonicalObject object;
    object.type_tag = type_tag;
    auto generation = generations_.find(key);
    if (generation == generations_.end()) {
        generation = generations_.emplace(key, 0).first;
        add_metadata_bytes(key_metadata_bytes(key));
        ++stats_.generation_count;
    }
    object.generation = ++generation->second;
    object.build_estimated_bytes = build_estimated_bytes;
    object.access_sequence = next_access_sequence();
    (*store)[key] = object;
    add_build_bytes(build_estimated_bytes);
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
    remove_build_bytes(found->second.build_estimated_bytes);
    found->second.build_estimated_bytes = 0;
    const AnalysisCacheKey* replaced_stream_ranges =
        key.protocol == "stream" && key.scope == AnalysisCacheScope::Full
            ? &key : nullptr;
    if (!make_hard_room(charge(resident_estimated_bytes), &key, nullptr,
                        error, key, replaced_stream_ranges)) {
        store->erase(found);
        erase_generation_if_unreferenced(key);
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
    add_resident_bytes(resident_estimated_bytes);
    ++stats_.canonical_entry_count;
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
    auto tombstone = evicted_keys_.find(key);
    if (tombstone != evicted_keys_.end()) {
        remove_metadata_bytes(key_metadata_bytes(tombstone->first));
        evicted_keys_.erase(tombstone);
        if (stats_.tombstone_count > 0) --stats_.tombstone_count;
    }
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
    remove_build_bytes(found->second.build_estimated_bytes);
    found->second.build_estimated_bytes = 0;
    if (!make_hard_room(charge(build_estimated_bytes), &key, nullptr,
                        error, key)) {
        store->erase(found);
        erase_generation_if_unreferenced(key);
        emit(AnalysisCacheEvent{"build_failed", key.protocol, key.session_id,
                                key.summary(), "canonical", "hard_limit",
                                build_estimated_bytes});
        return false;
    }
    found = store->find(key);
    found->second.build_estimated_bytes = build_estimated_bytes;
    add_build_bytes(build_estimated_bytes);
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
    remove_build_bytes(bytes);
    store->erase(found);
    erase_generation_if_unreferenced(key);
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
    add_build_bytes(build_estimated_bytes);
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
    remove_build_bytes(found->second.build_estimated_bytes);
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
    add_resident_bytes(resident_estimated_bytes);
    ++stats_.index_count;
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
    remove_build_bytes(found->second.build_estimated_bytes);
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
    add_build_bytes(build_estimated_bytes);
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
    remove_build_bytes(bytes);
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
    const std::uint64_t bytes = cursor_metadata_bytes(cursor);
    auto existing = cursors_.find(cursor.cursor_id);
    const std::uint64_t old_bytes = existing == cursors_.end()
        ? 0 : cursor_metadata_bytes(existing->second);
    AnalysisCacheError error;
    if (bytes > old_bytes &&
        !make_hard_room(charge(bytes - old_bytes), &cursor.key, nullptr,
                        error, cursor.key))
        return false;
    existing = cursors_.find(cursor.cursor_id);
    if (existing != cursors_.end()) remove_metadata_bytes(old_bytes);
    else ++stats_.cursor_count;
    cursors_[cursor.cursor_id] = cursor;
    cursor_access_sequences_[cursor.cursor_id] = next_access_sequence();
    add_metadata_bytes(bytes);
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
    cursor_access_sequences_[cursor_id] = next_access_sequence();
    cursor = found->second;
    return true;
}

void AnalysisRepository::erase_cursor(const std::string& cursor_id) {
    auto found = cursors_.find(cursor_id);
    if (found == cursors_.end()) return;
    const AnalysisCacheKey key = found->second.key;
    remove_metadata_bytes(cursor_metadata_bytes(found->second));
    cursors_.erase(found);
    cursor_access_sequences_.erase(cursor_id);
    if (stats_.cursor_count > 0) --stats_.cursor_count;
    erase_generation_if_unreferenced(key);
}

void AnalysisRepository::invalidate(const AnalysisCacheKey& key,
                                    const std::string& reason) {
    auto tombstone = evicted_keys_.find(key);
    if (tombstone != evicted_keys_.end()) {
        remove_metadata_bytes(key_metadata_bytes(tombstone->first));
        evicted_keys_.erase(tombstone);
        if (stats_.tombstone_count > 0) --stats_.tombstone_count;
    }
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
    cursor_access_sequences_.clear();
    stream_bindings_.clear();
    evicted_keys_.clear();
    generations_.clear();
    stats_ = AnalysisRepositoryStats();
    stats_.access_sequence = access_sequence_;
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
        auto& bindings = stream_bindings_[session_id];
        auto existing = bindings.find(name);
        if (existing != bindings.end()) {
            remove_metadata_bytes(binding_metadata_bytes(
                session_id, name, existing->second));
        } else {
            ++stats_.binding_count;
        }
        bindings[name] = new_digest;
        add_metadata_bytes(binding_metadata_bytes(session_id, name, new_digest));
        evict_to_budget(config_.hard_max_bytes, 0, nullptr, nullptr,
                        "hard_limit");
        while (stats_.charged_bytes > config_.hard_max_bytes &&
               erase_one_releasable_metadata()) {
            xdebug_core::request_deadline_checkpoint();
        }
        if (!old_digest.empty() && old_digest != new_digest)
            old_digests.insert(old_digest);
    }
    for (const std::string& old_digest : old_digests) {
        xdebug_core::request_deadline_checkpoint();
        bool still_bound = false;
        const auto session = stream_bindings_.find(session_id);
        if (session != stream_bindings_.end()) {
            for (const auto& binding : session->second) {
                if (binding.second == old_digest) {
                    still_bound = true;
                    break;
                }
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
    AnalysisRepositoryStats value = stats_;
    value.access_sequence = access_sequence_;
    return value;
}

AnalysisRepositoryStats AnalysisRepository::debug_recomputed_stats() const {
    AnalysisRepositoryStats value;
    const auto add_charge = [&](std::uint64_t bytes) {
        value.charged_bytes = saturating_add(value.charged_bytes,
                                             charge(bytes));
    };
    for (const CanonicalStore* store : {&apb_entries_, &axi_entries_,
                                        &stream_entries_}) {
        for (const auto& item : *store) {
            if (item.second.state == ObjectState::Ready)
                ++value.canonical_entry_count;
            value.resident_estimated_bytes = saturating_add(
                value.resident_estimated_bytes,
                item.second.resident_estimated_bytes);
            value.build_estimated_bytes = saturating_add(
                value.build_estimated_bytes,
                item.second.build_estimated_bytes);
            add_charge(item.second.resident_estimated_bytes);
            add_charge(item.second.build_estimated_bytes);
        }
    }
    for (const auto& item : indexes_) {
        if (item.second.state == ObjectState::Ready) ++value.index_count;
        value.resident_estimated_bytes = saturating_add(
            value.resident_estimated_bytes,
            item.second.resident_estimated_bytes);
        value.build_estimated_bytes = saturating_add(
            value.build_estimated_bytes, item.second.build_estimated_bytes);
        add_charge(item.second.resident_estimated_bytes);
        add_charge(item.second.build_estimated_bytes);
    }
    value.generation_count = generations_.size();
    value.cursor_count = cursors_.size();
    value.tombstone_count = evicted_keys_.size();
    for (const auto& item : generations_) {
        value.metadata_estimated_bytes = saturating_add(
            value.metadata_estimated_bytes, key_metadata_bytes(item.first));
        add_charge(key_metadata_bytes(item.first));
    }
    for (const auto& item : cursors_) {
        value.metadata_estimated_bytes = saturating_add(
            value.metadata_estimated_bytes, cursor_metadata_bytes(item.second));
        add_charge(cursor_metadata_bytes(item.second));
    }
    for (const auto& session : stream_bindings_) {
        for (const auto& binding : session.second) {
            ++value.binding_count;
            value.metadata_estimated_bytes = saturating_add(
                value.metadata_estimated_bytes,
                binding_metadata_bytes(session.first, binding.first,
                                       binding.second));
            add_charge(binding_metadata_bytes(session.first, binding.first,
                                              binding.second));
        }
    }
    for (const auto& item : evicted_keys_) {
        value.metadata_estimated_bytes = saturating_add(
            value.metadata_estimated_bytes, key_metadata_bytes(item.first));
        add_charge(key_metadata_bytes(item.first));
    }
    value.access_sequence = access_sequence_;
    return value;
}

void AnalysisRepository::emit(const AnalysisCacheEvent& event) const {
    if (event_sink_) event_sink_(event);
    if (!analysis_probe().enabled()) return;
    const AnalysisRepositoryStats snapshot = stats();
    analysis_probe().record(
        event.event, event.protocol, event.key_summary,
        AnalysisProbeMetrics{snapshot.canonical_entry_count,
                             snapshot.index_count,
                             snapshot.resident_estimated_bytes,
                             snapshot.build_estimated_bytes, 0});
}

}  // namespace xdebug_waveform
