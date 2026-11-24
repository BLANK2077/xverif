#pragma once

#include "coverage/ucapi_abi.h"

#include <json.hpp>

#include <map>
#include <tuple>
#include <string>
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

struct ScopeInfo {
    std::string name;
    std::string full_name;
    std::string parent;
    bool has_parent = false;
    ucapi::Handle handle = nullptr;
    std::map<MetricKind, MetricAggregate> metrics;      // self (code metrics)
    std::map<MetricKind, MetricAggregate> deep_metrics; // subtree aggregate
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
    };

    std::vector<FunctionalGroup> functional_groups() const;
    std::vector<AssertionRow> assertions() const;

    struct FunctionalGap {
        std::string scope;
        std::string covergroup;
        std::string coverpoint;
        std::string bin;
        std::string full_name;
    };
    std::vector<FunctionalGap> functional_gaps() const;

    /// Session-local exclusion operations (UCAPI report-time exclusion bits).
    void register_ref(const std::string& coverage_ref, const std::string& scope,
                      const std::string& metric, const std::string& name);
    bool locator_for_ref(const std::string& coverage_ref, std::string* scope,
                         std::string* metric, std::string* name) const;
    bool set_exclusion(const std::string& coverage_ref, bool excluded,
                       const std::string& reason = std::string());
    /// Exclude every coverable object under one instance subtree.
    bool exclude_leaf(const std::string& scope_name, const std::string& metric,
                      const std::string& name, const std::string& reason);
    std::size_t exclude_scope(const std::string& scope_name, bool recursive,
                              const std::string& reason);
    std::size_t restore_scope(const std::string& scope_name, bool recursive);
    std::size_t exclude_functional(const std::string& scope,
                                   const std::string& covergroup,
                                   const std::string& target_kind,
                                   const std::string& item,
                                   const std::string& reason);
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
    std::map<std::string, std::tuple<std::string, std::string, std::string>>
        ref_locators_;
};

const char* metric_key(MetricKind kind);
MetricKind metric_from_key(const std::string& key);

} // namespace xcov
