#pragma once

#include "coverage/ucapi_abi.h"

#include <json.hpp>

#include <array>
#include <cstdint>
#include <map>
#include <deque>
#include <set>
#include <tuple>
#include <string>
#include <unordered_map>
#include <vector>

namespace xcov {

enum class MetricKind {
    Line,
    Toggle,
    Branch,
    Condition,
    Fsm,
    Assert,
    Functional,
};

struct MetricAggregate {
    long covered = 0;
    long coverable = 0;
    long missing() const { return coverable > covered ? coverable - covered : 0; }
    double pct() const {
        return coverable > 0 ? 100.0 * static_cast<double>(covered) / coverable : 0.0;
    }
};

/// Compact key for the evicted-ref scope hint map (32-byte SHA-256 payload).
struct RefHashKey {
    std::array<unsigned char, 32> bytes{};
    bool operator==(const RefHashKey& other) const {
        return bytes == other.bytes;
    }
};

struct RefHashKeyHasher {
    std::size_t operator()(const RefHashKey& key) const {
        std::size_t value = 1469598103934665603ull;
        for (unsigned char byte : key.bytes) {
            value ^= byte;
            value *= 1099511628211ull;
        }
        return value;
    }
};

/// One leaf/assertion newly excluded by an instance-family operation.
struct ExclusionKey {
    std::string scope;
    std::string metric;
    std::string full_name;
    bool assertion = false;
    // Persistent UCAPI handles make the delta independent of non-unique
    // full_name paths (some FSM/line objects share a textual path).
    ucapi::Handle object_handle = nullptr;
    ucapi::Handle region_handle = nullptr;
};

struct ScopeInfo {
    std::string name;
    std::string full_name;
    std::string parent;         // navigation parent (may be synthetic)
    std::string metric_parent;  // nearest real ancestor for deep aggregation
    bool has_parent = false;
    ucapi::Handle handle = nullptr;
    std::map<MetricKind, MetricAggregate> metrics;      // self (code metrics)
    std::map<MetricKind, MetricAggregate> deep_metrics; // subtree aggregate
    // "Metric exists for this scope" flags. UCAPI returns a region for every
    // metric on every instance, so a zero-valued aggregate alone cannot tell
    // us whether URG would have emitted that metric key.
    std::set<MetricKind> present_metrics;
    std::set<MetricKind> deep_present;
};

/// UCAPI-backed coverage backend, semantically aligned with URG.
class UcapiBackend {
public:
    UcapiBackend(const std::string& vdb, const std::string& exclusion_policy);
    ~UcapiBackend();

    UcapiBackend(const UcapiBackend&) = delete;
    UcapiBackend& operator=(const UcapiBackend&) = delete;

    void close();

    const std::string& vdb() const { return vdb_; }
    const std::string& test_name() const { return test_name_; }
    std::string worker_kind() const { return "ucapi"; }

    const std::vector<std::string>& test_names() const { return test_names_; }
    const std::vector<ScopeInfo>& scopes() const { return scopes_; }

    /// Look up one instance by full name; nullptr when absent.
    const ScopeInfo* find_scope(const std::string& full_name) const;

    nlohmann::json summary() const;
    std::vector<std::string> top_scopes() const;

    /// All seven metric aggregates for one instance (URG subtree semantics).
    std::map<MetricKind, MetricAggregate> scope_metrics(const ScopeInfo& scope) const;

    /// Test-level assertion and functional totals (URG Assert/Group semantics).
    MetricAggregate assert_totals() const;
    MetricAggregate functional_totals() const;

    struct FunctionalGroup {
        std::string full_name;
        long covered = 0;
        long coverable = 0;
        // URG group score: arithmetic mean of direct coverpoint/cross pct.
        double score_pct = 0.0;
        int score_item_count = 0;
    };
    struct AssertionRow {
        std::string full_name;
        std::string name;
        int type = 0;
        long attempts = 0;
        long real_successes = 0;
        long all_successes = 0;
        long failures = 0;
        long incomplete = 0;
        bool excluded = false;
    };

    const std::vector<FunctionalGroup>& functional_groups() const;
    const std::vector<AssertionRow>& assertions() const;

    struct FunctionalGap {
        std::string scope;
        std::string covergroup;
        std::string coverpoint;
        std::string bin;
        std::string full_name;
    };
    const std::vector<FunctionalGap>& functional_gaps() const;

    /// Session-local exclusion operations (UCAPI report-time exclusion bits).
    void register_ref(const std::string& coverage_ref, const std::string& scope,
                      const std::string& metric, const std::string& name);
    /// Recompute aggregate metrics after exclusion mutations.
    void refresh_metrics();
    bool locator_for_ref(const std::string& coverage_ref, std::string* scope,
                         std::string* metric, std::string* name) const;
    /// found=false: ref unknown; excluded reflects the current report-time bit.
    bool exclusion_state(const std::string& coverage_ref, bool* excluded) const;
    bool set_exclusion(const std::string& coverage_ref, bool excluded,
                       const std::string& reason = std::string());
    /// Exclude every coverable object under one instance subtree.
    /// Assertions live on the test handle, not on instance regions.
    bool exclude_assertion(const std::string& full_name, bool excluded,
                           const std::string& reason);
    bool exclude_leaf(const std::string& scope_name, const std::string& metric,
                      const std::string& name, const std::string& reason);
    /// Clear one leaf's report-time exclusion (inverse of exclude_leaf).
    bool restore_leaf(const std::string& scope_name, const std::string& metric,
                      const std::string& name);
    /// Exclude every line-metric leaf in one instance whose source line matches.
    std::size_t exclude_line(const std::string& scope_name, int line_no,
                             const std::string& reason,
                             const std::string& source_file = std::string());
    /// Fully-qualified names of line-metric leaves at one source line.
    std::vector<std::string> line_leaf_full_names(
        const std::string& scope_name, int line_no,
        const std::string& source_file = std::string());
    std::size_t exclude_scope(
        const std::string& scope_name, bool recursive,
        const std::string& reason,
        std::vector<ExclusionKey>* changed_keys = nullptr);
    /// Clear exactly the objects recorded in an instance-family delta.
    std::size_t clear_exclusion_keys(const std::vector<ExclusionKey>& keys);
    /// Release persistent handles held by a delta without touching state.
    void release_exclusion_keys(const std::vector<ExclusionKey>& keys);
    /// True when any code leaf under the instance subtree is already covered
    /// (used for strict container preflight).
    bool scope_has_covered_objects(const std::string& scope_name,
                                   bool recursive) const;
    /// Exclude/restore assertions owned by one instance subtree (assertions
    /// live on the test handle, so the instance walk cannot reach them).
    std::size_t exclude_assertions(
        const std::string& scope_name, bool recursive, bool excluded,
        const std::string& reason,
        std::vector<ExclusionKey>* changed_keys = nullptr);
    std::size_t restore_scope(const std::string& scope_name, bool recursive);
    bool functional_target_exists(const std::string& scope,
                                  const std::string& covergroup,
                                  const std::string& target_kind,
                                  const std::string& item) const;
    std::size_t exclude_functional(const std::string& scope,
                                   const std::string& covergroup,
                                   const std::string& target_kind,
                                   const std::string& item,
                                   const std::string& reason,
                                   bool excluded = true);
    void save_exclusions(const std::string& path) const;
    void load_exclusions(const std::string& path);
    void unload_exclusions();
    std::size_t excluded_count() const;

    struct DecisionArm {
        std::string pattern;      // branch: "0001"; condition term: "0"
        std::string expression;   // full name, e.g. "((a)) = 0"
        int line_no = -1;
        long covered = 0;
        long coverable = 0;
    };

    struct DecisionGroup {
        std::string expression;   // container name, e.g. "(!rst_n)"
        std::string file;
        int line_no = -1;
        long covered = 0;
        long coverable = 0;
        long missing_gaps = 0;   // sum of (coverable-covered) over all leaves
        std::vector<DecisionArm> arms;
    };

    /// Decision/condition containers with their cross arms.
    /// `metric` selects "Branch" or "Condition".
    std::vector<DecisionGroup> decision_groups(const ScopeInfo& scope,
                                               const std::string& metric) const;

    struct LineLeaf {
        std::string name;
        std::string file;
        int line_no = -1;
        long covered = 0;
        long coverable = 0;
        std::string parent_kind;
    };

    /// All line leaves of one instance with source location and parent kind.
    std::vector<LineLeaf> line_leaves(const ScopeInfo& scope) const;

    struct CodeGap {
        std::string metric;
        std::string name;
        std::string full_name;
        long coverable = 0;
    };
    std::vector<CodeGap> code_gaps(const ScopeInfo& scope) const;

    struct CodeScan {
        std::vector<CodeGap> gaps;
        std::vector<LineLeaf> line_leaves;
        std::vector<DecisionGroup> condition_groups;
        std::vector<DecisionGroup> branch_groups;
    };

    /// One pass over the requested code metrics of one instance.
    /// `metrics` holds "line"/"toggle"/"branch"/"condition"/"fsm".
    CodeScan scan_code(const ScopeInfo& scope,
                       const std::set<std::string>& metrics) const;


    /// Children of one scope in hierarchy order.
    std::vector<const ScopeInfo*> children(const std::string& full_name) const;

    /// One row per coverable object, shaped like CanonicalCoverageBackend.items.
    nlohmann::json items(const std::string& scope,
                         bool functional_only) const;

private:
    void load_tests();
    void walk_instances();
    void aggregate_scope(ScopeInfo& scope);
    void finalize_scope_metrics();
    void fill_missing_scopes();
    void collect_leaf_rows(const ScopeInfo& scope, nlohmann::json& rows) const;

    std::string vdb_;
    std::string exclusion_policy_;
    std::string test_name_;
    ucapi::Handle design_ = nullptr;
    ucapi::Handle test_ = nullptr;
    std::vector<std::string> test_names_;
    std::vector<ScopeInfo> scopes_;
    std::map<std::string, std::size_t> scope_positions_;
    std::vector<std::string> top_scopes_;
    std::map<std::string, std::vector<std::string>> children_;
    std::vector<ucapi::Handle> persistent_handles_;
    // Instance handles must outlive metric rebuilds; keep them separate so
    // refresh_metrics() never releases a handle still referenced by scopes_.
    std::vector<ucapi::Handle> instance_handles_;
    // Cached full-scan results; invalidated by every exclusion mutation.
    mutable std::vector<FunctionalGap> functional_gap_cache_;
    mutable bool functional_gap_cache_valid_ = false;
    mutable std::vector<FunctionalGroup> functional_cache_;
    mutable bool functional_cache_valid_ = false;
    mutable std::vector<AssertionRow> assertion_cache_;
    mutable bool assertion_cache_valid_ = false;
    mutable bool metrics_dirty_ = false;
    void invalidate_caches() const {
        metrics_dirty_ = true;
        functional_cache_valid_ = false;
        functional_gap_cache_valid_ = false;
        assertion_cache_valid_ = false;
    }
    std::map<std::string, std::tuple<std::string, std::string, std::string>>
        ref_locators_;
    // FIFO eviction order for the bounded coverage_ref locator cache.
    std::deque<std::string> ref_locator_order_;
    std::size_t ref_locator_limit_ = 200000;
    // When the full locator cache evicts an entry, retain only its scope id so
    // a later lookup scans one instance instead of the whole tree.
    std::unordered_map<RefHashKey, std::uint32_t, RefHashKeyHasher>
        ref_scope_hints_;
    std::size_t ref_hint_limit_ = 2000000;
};


const char* metric_key(MetricKind kind);
MetricKind metric_from_key(const std::string& key);

} // namespace xcov
