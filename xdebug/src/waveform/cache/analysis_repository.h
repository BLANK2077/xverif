#pragma once

#include "npi_fsdb.h"

#include <cstddef>
#include <cstdint>
#include <functional>
#include <map>
#include <memory>
#include <new>
#include <set>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

namespace xdebug_waveform {

constexpr std::uint64_t kAnalysisCacheSoftDefaultBytes = 1073741824ULL;
constexpr std::uint64_t kAnalysisCacheHardDefaultBytes = 2147483648ULL;
constexpr double kAnalysisCacheEstimatorSafetyFactor = 2.0;

struct FsdbIdentity {
    std::uint64_t device = 0;
    std::uint64_t inode = 0;
    std::uint64_t size = 0;
    std::int64_t mtime = 0;

    bool operator==(const FsdbIdentity& other) const;
    bool operator<(const FsdbIdentity& other) const;
};

enum class AnalysisCacheScope { Full, Range };

struct AnalysisCacheKey {
    std::string protocol;
    std::string session_id;
    FsdbIdentity fsdb;
    std::uint32_t fingerprint_version = 1;
    std::string normalized_semantics;
    std::string semantic_digest;
    AnalysisCacheScope scope = AnalysisCacheScope::Full;
    npiFsdbTime range_begin = 0;
    npiFsdbTime range_end = 0;
    std::string digest;

    bool operator==(const AnalysisCacheKey& other) const;
    bool operator<(const AnalysisCacheKey& other) const;
    std::string summary() const;
};

AnalysisCacheKey make_analysis_cache_key(const std::string& protocol,
                                         const std::string& session_id,
                                         const FsdbIdentity& fsdb,
                                         std::uint32_t fingerprint_version,
                                         const std::string& normalized_semantics,
                                         AnalysisCacheScope scope,
                                         npiFsdbTime range_begin = 0,
                                         npiFsdbTime range_end = 0);
bool read_fsdb_identity(const std::string& path, FsdbIdentity& identity,
                        std::string& error);

struct AnalysisCacheConfig {
    std::uint64_t soft_max_bytes = kAnalysisCacheSoftDefaultBytes;
    std::uint64_t hard_max_bytes = kAnalysisCacheHardDefaultBytes;
    double estimator_safety_factor = kAnalysisCacheEstimatorSafetyFactor;
};

bool analysis_cache_config_from_environment(AnalysisCacheConfig& config,
                                            std::string& error);

struct AnalysisCacheError {
    std::string code;
    std::string message;
    bool recoverable = false;
    std::uint64_t current_estimated_bytes = 0;
    std::uint64_t hard_max_bytes = 0;
    std::string protocol;
    std::string key_summary;
    std::vector<std::string> suggestions;

    bool empty() const { return code.empty(); }
};

struct AnalysisCacheEvent {
    AnalysisCacheEvent(
        std::string event_value = std::string(),
        std::string protocol_value = std::string(),
        std::string session_value = std::string(),
        std::string key_value = std::string(),
        std::string object_value = std::string(),
        std::string reason_value = std::string(),
        std::uint64_t estimated_value = 0,
        std::uint64_t resident_value = 0,
        std::uint64_t build_value = 0,
        std::uint64_t access_value = 0,
        std::uint64_t generation_value = 0)
        : event(std::move(event_value)),
          protocol(std::move(protocol_value)),
          session_id(std::move(session_value)),
          key_summary(std::move(key_value)),
          object_kind(std::move(object_value)),
          reason(std::move(reason_value)),
          estimated_bytes(estimated_value),
          resident_estimated_bytes(resident_value),
          build_estimated_bytes(build_value),
          access_sequence(access_value),
          generation(generation_value) {}

    std::string event;
    std::string protocol;
    std::string session_id;
    std::string key_summary;
    std::string object_kind;
    std::string reason;
    std::uint64_t estimated_bytes = 0;
    std::uint64_t resident_estimated_bytes = 0;
    std::uint64_t build_estimated_bytes = 0;
    std::uint64_t access_sequence = 0;
    std::uint64_t generation = 0;
};

using AnalysisCacheEventSink = std::function<void(const AnalysisCacheEvent&)>;

enum class AnalysisAcquireStatus {
    Hit,
    BuildStarted,
    ReentrantBuild,
    Rejected,
};

struct AnalysisRepositoryStats {
    std::size_t canonical_entry_count = 0;
    std::size_t index_count = 0;
    std::uint64_t resident_estimated_bytes = 0;
    std::uint64_t build_estimated_bytes = 0;
    std::uint64_t charged_bytes = 0;
    std::uint64_t metadata_estimated_bytes = 0;
    std::size_t generation_count = 0;
    std::size_t cursor_count = 0;
    std::size_t binding_count = 0;
    std::size_t tombstone_count = 0;
    std::uint64_t access_sequence = 0;
};

struct GenerationCursor {
    std::string cursor_id;
    AnalysisCacheKey key;
    std::uint64_t generation = 0;
    std::string direction;
    std::size_t position = 0;
};

class AnalysisRepository {
public:
    explicit AnalysisRepository(
        const AnalysisCacheConfig& config = AnalysisCacheConfig(),
        AnalysisCacheEventSink event_sink = AnalysisCacheEventSink());

    AnalysisAcquireStatus begin_canonical(const AnalysisCacheKey& key,
                                          const std::string& type_tag,
                                          std::uint64_t build_estimated_bytes,
                                          AnalysisCacheError& error);
    bool publish_canonical_erased(const AnalysisCacheKey& key,
                                  const std::string& type_tag,
                                  const std::shared_ptr<const void>& value,
                                  std::uint64_t resident_estimated_bytes,
                                  AnalysisCacheError& error);
    bool update_canonical_build_bytes(const AnalysisCacheKey& key,
                                      std::uint64_t build_estimated_bytes,
                                      AnalysisCacheError& error);
    void fail_canonical(const AnalysisCacheKey& key,
                        const std::string& reason = "build_failed");
    void fail_canonical_bad_alloc(const AnalysisCacheKey& key,
                                  AnalysisCacheError& error);

    template <typename T>
    bool publish_canonical(const AnalysisCacheKey& key,
                           const std::string& type_tag,
                           const std::shared_ptr<const T>& value,
                           std::uint64_t resident_estimated_bytes,
                           AnalysisCacheError& error) {
        return publish_canonical_erased(
            key, type_tag, std::static_pointer_cast<const void>(value),
            resident_estimated_bytes, error);
    }

    template <typename T>
    std::shared_ptr<const T> find_canonical(const AnalysisCacheKey& key,
                                            const std::string& type_tag,
                                            std::uint64_t* generation = nullptr) {
        std::shared_ptr<const void> value = find_canonical_erased(
            key, type_tag, generation);
        return std::static_pointer_cast<const T>(value);
    }

    template <typename T>
    std::shared_ptr<const T> peek_canonical(
        const AnalysisCacheKey& key, const std::string& type_tag,
        std::uint64_t* generation = nullptr) {
        return std::static_pointer_cast<const T>(
            find_canonical_erased(key, type_tag, generation, false));
    }

    template <typename T, typename Builder, typename Estimator>
    std::shared_ptr<const T> ensure_canonical(
        const AnalysisCacheKey& key, const std::string& type_tag,
        std::uint64_t build_estimated_bytes, Builder builder,
        Estimator estimator, AnalysisCacheError& error,
        std::uint64_t* generation = nullptr) {
        const AnalysisAcquireStatus status = begin_canonical(
            key, type_tag, build_estimated_bytes, error);
        if (status == AnalysisAcquireStatus::Hit)
            return std::static_pointer_cast<const T>(
                find_canonical_erased(key, type_tag, generation, false));
        if (status != AnalysisAcquireStatus::BuildStarted)
            return std::shared_ptr<const T>();
        try {
            std::shared_ptr<const T> value = builder();
            if (!value) {
                fail_canonical(key, "builder_returned_null");
                error.code = "ANALYSIS_BUILD_FAILED";
                error.message = "analysis builder returned no result";
                return std::shared_ptr<const T>();
            }
            if (!publish_canonical(key, type_tag, value, estimator(*value), error))
                return std::shared_ptr<const T>();
            return std::static_pointer_cast<const T>(
                find_canonical_erased(key, type_tag, generation, false));
        } catch (const std::bad_alloc&) {
            fail_canonical(key, "bad_alloc");
            set_memory_error(error, key);
            return std::shared_ptr<const T>();
        } catch (...) {
            fail_canonical(key, "builder_exception");
            throw;
        }
    }

    template <typename T, typename Builder, typename Estimator>
    std::shared_ptr<const T> ensure_apb(
        const AnalysisCacheKey& key, const std::string& type_tag,
        std::uint64_t build_estimated_bytes, Builder builder,
        Estimator estimator, AnalysisCacheError& error,
        std::uint64_t* generation = nullptr) {
        return ensure_protocol<T>("apb", key, type_tag, build_estimated_bytes,
                                  builder, estimator, error, generation);
    }

    template <typename T, typename Builder, typename Estimator>
    std::shared_ptr<const T> ensure_axi(
        const AnalysisCacheKey& key, const std::string& type_tag,
        std::uint64_t build_estimated_bytes, Builder builder,
        Estimator estimator, AnalysisCacheError& error,
        std::uint64_t* generation = nullptr) {
        return ensure_protocol<T>("axi", key, type_tag, build_estimated_bytes,
                                  builder, estimator, error, generation);
    }

    template <typename T, typename Builder, typename Estimator>
    std::shared_ptr<const T> ensure_stream(
        const AnalysisCacheKey& key, const std::string& type_tag,
        std::uint64_t build_estimated_bytes, Builder builder,
        Estimator estimator, AnalysisCacheError& error,
        std::uint64_t* generation = nullptr) {
        return ensure_protocol<T>("stream", key, type_tag,
                                  build_estimated_bytes, builder, estimator,
                                  error, generation);
    }

    AnalysisAcquireStatus begin_index(const AnalysisCacheKey& canonical_key,
                                      std::uint64_t canonical_generation,
                                      const std::string& index_kind,
                                      const std::string& type_tag,
                                      std::uint64_t build_estimated_bytes,
                                      AnalysisCacheError& error);
    bool publish_index_erased(const AnalysisCacheKey& canonical_key,
                              std::uint64_t canonical_generation,
                              const std::string& index_kind,
                              const std::string& type_tag,
                              const std::shared_ptr<const void>& value,
                              std::uint64_t resident_estimated_bytes,
                              AnalysisCacheError& error);
    bool update_index_build_bytes(const AnalysisCacheKey& canonical_key,
                                  std::uint64_t canonical_generation,
                                  const std::string& index_kind,
                                  std::uint64_t build_estimated_bytes,
                                  AnalysisCacheError& error);
    void fail_index(const AnalysisCacheKey& canonical_key,
                    std::uint64_t canonical_generation,
                    const std::string& index_kind,
                    const std::string& reason = "build_failed");
    void fail_index_bad_alloc(const AnalysisCacheKey& canonical_key,
                              std::uint64_t canonical_generation,
                              const std::string& index_kind,
                              AnalysisCacheError& error);

    template <typename T>
    bool publish_index(const AnalysisCacheKey& canonical_key,
                       std::uint64_t canonical_generation,
                       const std::string& index_kind,
                       const std::string& type_tag,
                       const std::shared_ptr<const T>& value,
                       std::uint64_t resident_estimated_bytes,
                       AnalysisCacheError& error) {
        return publish_index_erased(
            canonical_key, canonical_generation, index_kind, type_tag,
            std::static_pointer_cast<const void>(value),
            resident_estimated_bytes, error);
    }

    template <typename T>
    std::shared_ptr<const T> find_index(const AnalysisCacheKey& canonical_key,
                                        std::uint64_t canonical_generation,
                                        const std::string& index_kind,
                                        const std::string& type_tag) {
        return std::static_pointer_cast<const T>(find_index_erased(
            canonical_key, canonical_generation, index_kind, type_tag));
    }

    template <typename T>
    std::shared_ptr<const T> peek_index(
        const AnalysisCacheKey& canonical_key,
        std::uint64_t canonical_generation,
        const std::string& index_kind,
        const std::string& type_tag) {
        return std::static_pointer_cast<const T>(peek_index_erased(
            canonical_key, canonical_generation, index_kind, type_tag));
    }

    bool put_cursor(const GenerationCursor& cursor);
    bool get_cursor(const std::string& cursor_id, GenerationCursor& cursor) const;
    bool resume_cursor(const std::string& cursor_id,
                       const AnalysisCacheKey& rebuilt_key,
                       std::uint64_t rebuilt_generation,
                       GenerationCursor& cursor);
    void erase_cursor(const std::string& cursor_id);

    void invalidate(const AnalysisCacheKey& key,
                    const std::string& reason = "explicit");
    void clear(const std::string& reason = "session_exit");
    void notify_stream_config_change(const std::string& session_id,
                                     const std::string& config_name,
                                     const std::string& old_semantic_digest,
                                     const std::string& new_semantic_digest);
    void notify_stream_config_changes(
        const std::string& session_id,
        const std::vector<std::tuple<std::string, std::string, std::string>>&
            changes);

    AnalysisRepositoryStats stats() const;
    AnalysisRepositoryStats debug_recomputed_stats() const;
    const AnalysisCacheConfig& config() const { return config_; }

private:
    template <typename T, typename Builder, typename Estimator>
    std::shared_ptr<const T> ensure_protocol(
        const char* expected_protocol, const AnalysisCacheKey& key,
        const std::string& type_tag, std::uint64_t build_estimated_bytes,
        Builder builder, Estimator estimator, AnalysisCacheError& error,
        std::uint64_t* generation) {
        if (key.protocol != expected_protocol) {
            error = AnalysisCacheError();
            error.code = "ANALYSIS_CACHE_PROTOCOL_MISMATCH";
            error.message = std::string("expected ") + expected_protocol +
                            " analysis cache key";
            return std::shared_ptr<const T>();
        }
        return ensure_canonical<T>(key, type_tag, build_estimated_bytes,
                                   builder, estimator, error, generation);
    }

    enum class ObjectState { Building, Ready };
    struct CanonicalObject {
        ObjectState state = ObjectState::Building;
        std::string type_tag;
        std::shared_ptr<const void> value;
        std::uint64_t generation = 0;
        std::uint64_t resident_estimated_bytes = 0;
        std::uint64_t build_estimated_bytes = 0;
        std::uint64_t access_sequence = 0;
    };
    struct IndexKey {
        IndexKey() = default;
        IndexKey(const AnalysisCacheKey& key, std::uint64_t generation,
                 std::string kind)
            : canonical_key(key), canonical_generation(generation),
              index_kind(std::move(kind)) {}
        AnalysisCacheKey canonical_key;
        std::uint64_t canonical_generation = 0;
        std::string index_kind;
        bool operator<(const IndexKey& other) const;
        bool operator==(const IndexKey& other) const;
    };
    struct IndexObject {
        ObjectState state = ObjectState::Building;
        std::string type_tag;
        std::shared_ptr<const void> value;
        std::uint64_t resident_estimated_bytes = 0;
        std::uint64_t build_estimated_bytes = 0;
        std::uint64_t access_sequence = 0;
    };
    using CanonicalStore = std::map<AnalysisCacheKey, CanonicalObject>;

    CanonicalStore* canonical_store_for_protocol(const std::string& protocol);
    const CanonicalStore* canonical_store_for_protocol(
        const std::string& protocol) const;

    std::shared_ptr<const void> find_canonical_erased(
        const AnalysisCacheKey& key, const std::string& type_tag,
        std::uint64_t* generation, bool record_access = true);
    std::shared_ptr<const void> find_index_erased(
        const AnalysisCacheKey& canonical_key,
        std::uint64_t canonical_generation,
        const std::string& index_kind,
        const std::string& type_tag);
    std::shared_ptr<const void> peek_index_erased(
        const AnalysisCacheKey& canonical_key,
        std::uint64_t canonical_generation,
        const std::string& index_kind,
        const std::string& type_tag);

    std::uint64_t charge(std::uint64_t estimated_bytes) const;
    std::uint64_t next_access_sequence();
    std::uint64_t current_charged_bytes(const AnalysisCacheKey* exempt_canonical,
                                        const IndexKey* exempt_index,
                                        const AnalysisCacheKey*
                                            excluded_stream_ranges_for_full =
                                                nullptr) const;
    std::uint64_t current_resident_estimated_bytes() const;
    std::uint64_t current_build_estimated_bytes() const;
    static std::uint64_t key_metadata_bytes(const AnalysisCacheKey& key);
    static std::uint64_t cursor_metadata_bytes(const GenerationCursor& cursor);
    static std::uint64_t binding_metadata_bytes(
        const std::string& session_id, const std::string& config_name,
        const std::string& digest);
    void add_resident_bytes(std::uint64_t bytes);
    void remove_resident_bytes(std::uint64_t bytes);
    void add_build_bytes(std::uint64_t bytes);
    void remove_build_bytes(std::uint64_t bytes);
    void add_metadata_bytes(std::uint64_t bytes);
    void remove_metadata_bytes(std::uint64_t bytes);
    void erase_generation_if_unreferenced(const AnalysisCacheKey& key);
    bool erase_one_releasable_metadata();
    void evict_to_budget(std::uint64_t limit, std::uint64_t new_charge,
                         const AnalysisCacheKey* protected_canonical,
                         const IndexKey* protected_index,
                         const std::string& reason,
                         const AnalysisCacheKey*
                             preserve_stream_ranges_for_full = nullptr,
                         const AnalysisCacheKey*
                             excluded_stream_ranges_for_full = nullptr);
    bool make_hard_room(std::uint64_t new_charge,
                        const AnalysisCacheKey* protected_canonical,
                        const IndexKey* protected_index,
                        AnalysisCacheError& error,
                        const AnalysisCacheKey& request_key,
                        const AnalysisCacheKey*
                            excluded_stream_ranges_for_full = nullptr);
    void enforce_soft_budget(const AnalysisCacheKey* protected_canonical,
                             const IndexKey* protected_index);
    static bool is_stream_sibling_range(
        const AnalysisCacheKey& candidate,
        const AnalysisCacheKey& full_key);
    void erase_stream_sibling_ranges(const AnalysisCacheKey& full_key);
    void erase_canonical_internal(const AnalysisCacheKey& key,
                                  const std::string& reason,
                                  bool invalidate_cursors);
    void emit(const AnalysisCacheEvent& event) const;
    void set_memory_error(AnalysisCacheError& error,
                          const AnalysisCacheKey& key) const;

    AnalysisCacheConfig config_;
    AnalysisCacheEventSink event_sink_;
    CanonicalStore apb_entries_;
    CanonicalStore axi_entries_;
    CanonicalStore stream_entries_;
    std::map<IndexKey, IndexObject> indexes_;
    std::map<AnalysisCacheKey, std::uint64_t> generations_;
    std::map<AnalysisCacheKey, std::uint64_t> evicted_keys_;
    std::map<std::string, GenerationCursor> cursors_;
    std::map<std::string, std::uint64_t> cursor_access_sequences_;
    std::map<std::string, std::map<std::string, std::string>> stream_bindings_;
    std::uint64_t access_sequence_ = 0;
    AnalysisRepositoryStats stats_;
};

}  // namespace xdebug_waveform
