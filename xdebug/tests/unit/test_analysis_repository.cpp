#include "waveform/cache/analysis_repository.h"

#include <cassert>
#include <cstdlib>
#include <limits>
#include <memory>
#include <string>
#include <vector>

using namespace xdebug_waveform;

namespace {

struct FakeEntry {
    explicit FakeEntry(int value_arg) : value(value_arg) {}
    int value;
};

AnalysisCacheKey key(const std::string& protocol, const std::string& semantics,
                     AnalysisCacheScope scope = AnalysisCacheScope::Full,
                     npiFsdbTime begin = 0, npiFsdbTime end = 0) {
    FsdbIdentity fsdb;
    fsdb.device = 1;
    fsdb.inode = 2;
    fsdb.size = 3;
    fsdb.mtime = 4;
    return make_analysis_cache_key(protocol, "session-a", fsdb, 1,
                                   semantics, scope, begin, end);
}

std::shared_ptr<const FakeEntry> fake(int value) {
    return std::shared_ptr<const FakeEntry>(new FakeEntry(value));
}

void assert_incremental_stats(const AnalysisRepository& repository) {
    const AnalysisRepositoryStats incremental = repository.stats();
    const AnalysisRepositoryStats recomputed = repository.debug_recomputed_stats();
    assert(incremental.canonical_entry_count == recomputed.canonical_entry_count);
    assert(incremental.index_count == recomputed.index_count);
    assert(incremental.resident_estimated_bytes ==
           recomputed.resident_estimated_bytes);
    assert(incremental.build_estimated_bytes == recomputed.build_estimated_bytes);
    assert(incremental.charged_bytes == recomputed.charged_bytes);
    assert(incremental.metadata_estimated_bytes ==
           recomputed.metadata_estimated_bytes);
    assert(incremental.generation_count == recomputed.generation_count);
    assert(incremental.cursor_count == recomputed.cursor_count);
    assert(incremental.binding_count == recomputed.binding_count);
    assert(incremental.tombstone_count == recomputed.tombstone_count);
    assert(incremental.access_sequence == recomputed.access_sequence);
}

void publish(AnalysisRepository& repository, const AnalysisCacheKey& cache_key,
             int value, std::uint64_t bytes, std::uint64_t* generation = nullptr) {
    AnalysisCacheError error;
    assert(repository.begin_canonical(cache_key, "fake", bytes, error) ==
           AnalysisAcquireStatus::BuildStarted);
    assert_incremental_stats(repository);
    assert(repository.publish_canonical(cache_key, "fake", fake(value), bytes, error));
    assert_incremental_stats(repository);
    assert(repository.find_canonical<FakeEntry>(cache_key, "fake", generation)->value == value);
    assert_incremental_stats(repository);
}

void test_key_and_strict_environment() {
    const AnalysisCacheKey full = key("stream", "{\"clock\":\"clk\"}");
    const AnalysisCacheKey same = key("stream", "{\"clock\":\"clk\"}");
    const AnalysisCacheKey range = key("stream", "{\"clock\":\"clk\"}",
                                       AnalysisCacheScope::Range, 10, 20);
    assert(full == same);
    assert(full.digest == same.digest);
    assert(!(full == range));
    assert(full.semantic_digest.size() == 64);
    assert(full.summary().size() == 16);

    unsetenv("XDEBUG_ANALYSIS_CACHE_MAX_BYTES");
    unsetenv("XDEBUG_ANALYSIS_CACHE_HARD_MAX_BYTES");
    AnalysisCacheConfig config;
    std::string error;
    assert(analysis_cache_config_from_environment(config, error));
    assert(config.soft_max_bytes == kAnalysisCacheSoftDefaultBytes);
    assert(config.hard_max_bytes == kAnalysisCacheHardDefaultBytes);
    assert(config.estimator_safety_factor == 2.0);

    setenv("XDEBUG_ANALYSIS_CACHE_MAX_BYTES", "0", 1);
    setenv("XDEBUG_ANALYSIS_CACHE_HARD_MAX_BYTES", "99", 1);
    assert(analysis_cache_config_from_environment(config, error));
    assert(config.soft_max_bytes == 0 && config.hard_max_bytes == 99);
    for (const char* invalid : {"", "-1", "+1", "1x", " 1",
                                "18446744073709551616"}) {
        setenv("XDEBUG_ANALYSIS_CACHE_MAX_BYTES", invalid, 1);
        assert(!analysis_cache_config_from_environment(config, error));
    }
    setenv("XDEBUG_ANALYSIS_CACHE_MAX_BYTES", "100", 1);
    setenv("XDEBUG_ANALYSIS_CACHE_HARD_MAX_BYTES", "99", 1);
    assert(!analysis_cache_config_from_environment(config, error));
    setenv("XDEBUG_ANALYSIS_CACHE_MAX_BYTES", "0", 1);
    setenv("XDEBUG_ANALYSIS_CACHE_HARD_MAX_BYTES", "0", 1);
    assert(!analysis_cache_config_from_environment(config, error));
    unsetenv("XDEBUG_ANALYSIS_CACHE_MAX_BYTES");
    unsetenv("XDEBUG_ANALYSIS_CACHE_HARD_MAX_BYTES");
}

void test_build_state_failure_and_bad_alloc() {
    AnalysisCacheConfig config;
    config.soft_max_bytes = 0;
    config.hard_max_bytes = 16384;
    config.estimator_safety_factor = 1.0;
    AnalysisRepository repository(config);
    AnalysisCacheError error;
    const AnalysisCacheKey a = key("apb", "a");
    assert(repository.begin_canonical(a, "fake", 10, error) ==
           AnalysisAcquireStatus::BuildStarted);
    assert(repository.begin_canonical(a, "fake", 10, error) ==
           AnalysisAcquireStatus::ReentrantBuild);
    repository.fail_canonical(a, "injected_failure");
    assert_incremental_stats(repository);
    assert(repository.stats().canonical_entry_count == 0);
    assert(repository.stats().build_estimated_bytes == 0);

    const AnalysisCacheKey index_owner = key("apb", "index-owner");
    std::uint64_t index_generation = 0;
    publish(repository, index_owner, 8, 10, &index_generation);
    assert(repository.begin_index(index_owner, index_generation, "address",
                                  "fake-index", 10, error) ==
           AnalysisAcquireStatus::BuildStarted);
    assert(!repository.update_index_build_bytes(
        index_owner, index_generation, "address", 32768, error));
    assert_incremental_stats(repository);
    assert(error.code == "ANALYSIS_MEMORY_LIMIT_EXCEEDED");
    assert(repository.stats().index_count == 0);
    assert(repository.stats().build_estimated_bytes == 0);

    const AnalysisCacheKey growing = key("stream", "growing");
    assert(repository.begin_canonical(growing, "fake", 10, error) ==
           AnalysisAcquireStatus::BuildStarted);
    assert(!repository.update_canonical_build_bytes(growing, 32768, error));
    assert_incremental_stats(repository);
    assert(error.code == "ANALYSIS_MEMORY_LIMIT_EXCEEDED");
    assert(repository.stats().build_estimated_bytes == 0);

    const AnalysisCacheKey b = key("axi", "bad-alloc");
    auto result = repository.ensure_canonical<FakeEntry>(
        b, "fake", 20,
        []() -> std::shared_ptr<const FakeEntry> { throw std::bad_alloc(); },
        [](const FakeEntry&) -> std::uint64_t { return 20; }, error);
    assert(!result);
    assert(error.code == "ANALYSIS_MEMORY_LIMIT_EXCEEDED");
    assert(error.recoverable);
    assert(error.suggestions.size() == 2);
    assert(repository.stats().canonical_entry_count == 0);
    assert(repository.stats().build_estimated_bytes == 0);
}

void test_index_first_and_cross_protocol_lru() {
    AnalysisCacheConfig config;
    config.soft_max_bytes = 100;
    config.hard_max_bytes = 16384;
    config.estimator_safety_factor = 1.0;
    std::vector<AnalysisCacheEvent> events;
    AnalysisRepository repository(config, [&](const AnalysisCacheEvent& event) {
        events.push_back(event);
    });
    const AnalysisCacheKey apb = key("apb", "apb-a");
    const AnalysisCacheKey axi = key("axi", "axi-a");
    const AnalysisCacheKey stream = key("stream", "stream-a");
    std::uint64_t apb_generation = 0;
    publish(repository, apb, 1, 20, &apb_generation);
    publish(repository, axi, 2, 20);

    const std::uint64_t before_peek = repository.stats().access_sequence;
    assert(repository.peek_canonical<FakeEntry>(axi, "fake")->value == 2);
    assert(repository.stats().access_sequence == before_peek);

    AnalysisCacheError error;
    assert(repository.begin_index(apb, apb_generation, "address", "fake-index",
                                  20, error) == AnalysisAcquireStatus::BuildStarted);
    assert(repository.publish_index(apb, apb_generation, "address", "fake-index",
                                    fake(11), 20, error));
    const std::uint64_t before_index_peek = repository.stats().access_sequence;
    assert(repository.peek_index<FakeEntry>(apb, apb_generation, "address",
                                            "fake-index")->value == 11);
    assert(repository.stats().access_sequence == before_index_peek);
    publish(repository, stream, 3, 50);
    assert(repository.stats().canonical_entry_count == 3);
    assert(repository.stats().index_count == 0);
    assert_incremental_stats(repository);
    assert(!repository.find_index<FakeEntry>(apb, apb_generation, "address",
                                             "fake-index"));

    AnalysisCacheConfig tight = config;
    tight.soft_max_bytes = 60;
    AnalysisRepository pure_lru(tight);
    const AnalysisCacheKey a = key("apb", "pure-a");
    const AnalysisCacheKey b = key("axi", "pure-b");
    const AnalysisCacheKey c = key("stream", "pure-c");
    publish(pure_lru, a, 1, 30);
    publish(pure_lru, b, 2, 30);
    assert(pure_lru.find_canonical<FakeEntry>(a, "fake"));
    publish(pure_lru, c, 3, 30);
    assert(pure_lru.find_canonical<FakeEntry>(a, "fake"));
    assert(!pure_lru.find_canonical<FakeEntry>(b, "fake"));
    assert(pure_lru.find_canonical<FakeEntry>(c, "fake"));
    assert_incremental_stats(pure_lru);
}

void test_oversize_hard_limit_and_saturation() {
    AnalysisCacheConfig config;
    config.soft_max_bytes = 50;
    config.hard_max_bytes = 16384;
    config.estimator_safety_factor = 1.0;
    std::vector<AnalysisCacheEvent> events;
    AnalysisRepository repository(config, [&](const AnalysisCacheEvent& event) {
        events.push_back(event);
    });
    publish(repository, key("axi", "oversize"), 1, 80);
    assert(repository.stats().canonical_entry_count == 1);
    bool saw_oversize = false;
    for (const auto& event : events)
        if (event.event == "oversize_admitted") saw_oversize = true;
    assert(saw_oversize);

    AnalysisCacheConfig index_config = config;
    index_config.soft_max_bytes = 50;
    AnalysisRepository index_repository(index_config, [&](const AnalysisCacheEvent& event) {
        events.push_back(event);
    });
    const AnalysisCacheKey indexed = key("apb", "oversize-index");
    std::uint64_t generation = 0;
    publish(index_repository, indexed, 2, 20, &generation);
    AnalysisCacheError index_error;
    assert(index_repository.begin_index(indexed, generation, "address", "fake-index",
                                        40, index_error) ==
           AnalysisAcquireStatus::BuildStarted);
    assert(index_repository.publish_index(indexed, generation, "address", "fake-index",
                                          fake(3), 40, index_error));
    assert(index_repository.stats().canonical_entry_count == 1);
    assert(index_repository.stats().index_count == 1);

    AnalysisCacheError error;
    assert(repository.begin_canonical(key("stream", "too-large"), "fake", 32768,
                                      error) == AnalysisAcquireStatus::Rejected);
    assert(error.code == "ANALYSIS_MEMORY_LIMIT_EXCEEDED");
    assert(error.recoverable && error.hard_max_bytes == 16384);
    assert(error.suggestions.size() == 2);
    assert(repository.begin_canonical(
               key("stream", "saturated"), "fake",
               std::numeric_limits<std::uint64_t>::max(), error) ==
           AnalysisAcquireStatus::Rejected);

    auto mismatch = repository.ensure_apb<FakeEntry>(
        key("axi", "wrong-typed-store"), "fake", 1,
        []() { return fake(4); },
        [](const FakeEntry&) -> std::uint64_t { return 1; }, error);
    assert(!mismatch && error.code == "ANALYSIS_CACHE_PROTOCOL_MISMATCH");
    assert(repository.begin_canonical(key("custom", "unsupported"), "fake", 1,
                                      error) == AnalysisAcquireStatus::Rejected);
    assert(error.code == "ANALYSIS_CACHE_PROTOCOL_UNSUPPORTED");
    assert_incremental_stats(repository);
    assert_incremental_stats(index_repository);
}

void test_generation_cursor_and_config_invalidation() {
    AnalysisCacheConfig config;
    config.soft_max_bytes = 40;
    config.hard_max_bytes = 16384;
    config.estimator_safety_factor = 1.0;
    AnalysisRepository repository(config);
    const AnalysisCacheKey a = key("axi", "cursor-a");
    const AnalysisCacheKey b = key("apb", "cursor-b");
    std::uint64_t generation_one = 0;
    publish(repository, a, 1, 40, &generation_one);
    GenerationCursor cursor;
    cursor.cursor_id = "axi:axi0:write";
    cursor.key = a;
    cursor.generation = generation_one;
    cursor.direction = "write";
    cursor.position = 17;
    assert(repository.put_cursor(cursor));
    assert_incremental_stats(repository);
    publish(repository, b, 2, 40);
    assert(!repository.find_canonical<FakeEntry>(a, "fake"));
    assert(repository.get_cursor("axi:axi0:write", cursor));
    assert_incremental_stats(repository);

    std::uint64_t generation_two = 0;
    publish(repository, a, 3, 40, &generation_two);
    assert(generation_two > generation_one);
    assert(repository.resume_cursor("axi:axi0:write", a, generation_two,
                                    cursor));
    assert_incremental_stats(repository);
    assert(cursor.position == 17 && cursor.generation == generation_two);

    AnalysisCacheConfig unbounded = config;
    unbounded.soft_max_bytes = 0;
    AnalysisRepository stream_repository(unbounded);
    const AnalysisCacheKey old_key = key("stream", "old-semantics");
    publish(stream_repository, old_key, 9, 20);
    stream_repository.notify_stream_config_change(
        "session-a", "stream0", "", old_key.semantic_digest);
    stream_repository.notify_stream_config_change(
        "session-a", "stream0", old_key.semantic_digest,
        old_key.semantic_digest);
    assert(stream_repository.find_canonical<FakeEntry>(old_key, "fake"));
    stream_repository.notify_stream_config_change(
        "session-a", "stream0", old_key.semantic_digest,
        key("stream", "new-semantics").semantic_digest);
    assert_incremental_stats(stream_repository);
    assert(!stream_repository.find_canonical<FakeEntry>(old_key, "fake"));

    publish(stream_repository, old_key, 10, 20);
    const std::string new_digest = key("stream", "new-semantics").semantic_digest;
    stream_repository.notify_stream_config_changes(
        "session-a",
        {{"stream0", new_digest, old_key.semantic_digest},
         {"alias", std::string(), old_key.semantic_digest}});
    stream_repository.notify_stream_config_changes(
        "session-a",
        {{"stream0", old_key.semantic_digest, new_digest},
         {"alias", old_key.semantic_digest, old_key.semantic_digest}});
    assert(stream_repository.find_canonical<FakeEntry>(old_key, "fake"));
    stream_repository.notify_stream_config_change(
        "session-a", "alias", old_key.semantic_digest, new_digest);
    assert(!stream_repository.find_canonical<FakeEntry>(old_key, "fake"));
    assert_incremental_stats(stream_repository);

    repository.invalidate(a, "unit_invalidate");
    assert_incremental_stats(repository);
    repository.clear("unit_clear");
    assert_incremental_stats(repository);
    const AnalysisRepositoryStats cleared = repository.stats();
    assert(cleared.charged_bytes == 0);
    assert(cleared.metadata_estimated_bytes == 0);
    assert(cleared.generation_count == 0);
    assert(cleared.cursor_count == 0);
    assert(cleared.binding_count == 0);
    assert(cleared.tombstone_count == 0);
}

void test_stream_full_range_replacement_is_transactional() {
    AnalysisCacheConfig config;
    config.soft_max_bytes = 0;
    config.hard_max_bytes = 16384;
    config.estimator_safety_factor = 1.0;
    std::vector<AnalysisCacheEvent> events;
    AnalysisRepository repository(config, [&](const AnalysisCacheEvent& event) {
        events.push_back(event);
    });
    const AnalysisCacheKey full = key("stream", "stream-semantics");
    const AnalysisCacheKey range_a = key(
        "stream", "stream-semantics", AnalysisCacheScope::Range, 10, 20);
    const AnalysisCacheKey range_b = key(
        "stream", "stream-semantics", AnalysisCacheScope::Range, 30, 40);
    const AnalysisCacheKey other_range = key(
        "stream", "other-semantics", AnalysisCacheScope::Range, 10, 20);
    publish(repository, range_a, 1, 20);
    publish(repository, range_b, 2, 20);
    publish(repository, other_range, 3, 20);

    AnalysisCacheError error;
    assert(repository.begin_canonical(full, "fake", 10, error) ==
           AnalysisAcquireStatus::BuildStarted);
    assert(repository.publish_canonical(full, "fake", fake(4), 30, error));
    assert(repository.find_canonical<FakeEntry>(full, "fake")->value == 4);
    assert(!repository.find_canonical<FakeEntry>(range_a, "fake"));
    assert(!repository.find_canonical<FakeEntry>(range_b, "fake"));
    assert(repository.find_canonical<FakeEntry>(other_range, "fake")->value == 3);
    std::size_t replaced = 0;
    for (const auto& event : events)
        if (event.event == "invalidate" &&
            event.reason == "full_replaced_range")
            ++replaced;
    assert(replaced == 2);
    assert_incremental_stats(repository);

    AnalysisCacheConfig tight = config;
    tight.hard_max_bytes = 4096;
    AnalysisRepository failed_full(tight);
    publish(failed_full, range_a, 5, 20);
    assert(failed_full.begin_canonical(full, "fake", 10, error) ==
           AnalysisAcquireStatus::BuildStarted);
    assert(!failed_full.update_canonical_build_bytes(full, 8192, error));
    assert(error.code == "ANALYSIS_MEMORY_LIMIT_EXCEEDED");
    assert(failed_full.find_canonical<FakeEntry>(range_a, "fake")->value == 5);
    assert(!failed_full.find_canonical<FakeEntry>(full, "fake"));
    assert_incremental_stats(failed_full);
}

void test_metadata_churn_is_bounded_and_recomputable() {
    AnalysisCacheConfig config;
    config.soft_max_bytes = 64;
    config.hard_max_bytes = 4096;
    config.estimator_safety_factor = 1.0;
    AnalysisRepository repository(config);
    for (int i = 0; i < 64; ++i) {
        publish(repository, key("apb", "churn-" + std::to_string(i)), i, 64);
        assert(repository.stats().charged_bytes <= config.hard_max_bytes);
        assert_incremental_stats(repository);
    }
    assert(repository.stats().generation_count +
               repository.stats().tombstone_count < 64);
    repository.clear("churn_clear");
    assert_incremental_stats(repository);
}

}  // namespace

int main() {
    test_key_and_strict_environment();
    test_build_state_failure_and_bad_alloc();
    test_index_first_and_cross_protocol_lru();
    test_oversize_hard_limit_and_saturation();
    test_generation_cursor_and_config_invalidation();
    test_stream_full_range_replacement_is_transactional();
    test_metadata_churn_is_bounded_and_recomputable();
    return 0;
}
