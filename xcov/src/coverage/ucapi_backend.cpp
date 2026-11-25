#include "coverage/ucapi_backend.h"

#include "coverage/ucapi_loader.h"
#include "coverage/coverage_ref.h"
#include "core/errors.h"

#include <sys/stat.h>

#include <algorithm>
#include <functional>
#include <cstdio>
#include <cstdlib>
#include <cstring>

namespace xcov {

namespace {
inline bool debug_enabled() {
    static const bool enabled = std::getenv("XCOV_CPP_DEBUG") != nullptr;
    return enabled;
}
} // namespace

namespace {

std::string safe_str(char* text) {
    return text == nullptr ? std::string() : std::string(text);
}

bool is_directory(const std::string& path) {
    struct stat info;
    return ::stat(path.c_str(), &info) == 0 && S_ISDIR(info.st_mode);
}

bool is_leaf_type(int type) {
    switch (type) {
        case ucapi::kBlock:
        case ucapi::kSequence:
        case ucapi::kCrossObj:
        case ucapi::kIntegerValue:
        case ucapi::kScalarValue:
        case ucapi::kVectorValue:
        case ucapi::kValueSet:
            return true;
        default:
            return false;
    }
}

} // namespace

const char* metric_key(MetricKind kind) {
    switch (kind) {
        case MetricKind::Line: return "line";
        case MetricKind::Toggle: return "toggle";
        case MetricKind::Branch: return "branch";
        case MetricKind::Condition: return "condition";
        case MetricKind::Fsm: return "fsm";
        case MetricKind::Assert: return "assert";
        case MetricKind::Functional: return "functional";
    }
    return "line";
}

MetricKind metric_from_key(const std::string& key) {
    if (key == "line") return MetricKind::Line;
    if (key == "toggle") return MetricKind::Toggle;
    if (key == "branch") return MetricKind::Branch;
    if (key == "condition") return MetricKind::Condition;
    if (key == "fsm") return MetricKind::Fsm;
    if (key == "assert") return MetricKind::Assert;
    return MetricKind::Functional;
}

UcapiBackend::UcapiBackend(const std::string& vdb, const std::string& exclusion_policy)
    : vdb_(vdb), exclusion_policy_(exclusion_policy) {
    // Coverage refs are session-local handles. Large multi-scope exports used
    // to grow this map linearly with every exported leaf (~1 MB per leaf
    // scope); keep a bounded FIFO cache and fall back to the (slower) full-tree
    // locator scan when an entry has been evicted. 0 disables the cache.
    if (const char* raw_limit = std::getenv("XVERIF_XCOV_REF_LOCATOR_MAX")) {
        char* end = nullptr;
        const unsigned long long parsed = std::strtoull(raw_limit, &end, 10);
        if (end != raw_limit && *end == '\0') {
            ref_locator_limit_ = static_cast<std::size_t>(parsed);
        }
    }
    if (const char* raw_hints = std::getenv("XVERIF_XCOV_REF_HINT_MAX")) {
        char* end = nullptr;
        const unsigned long long parsed = std::strtoull(raw_hints, &end, 10);
        if (end != raw_hints && *end == '\0') {
            ref_hint_limit_ = static_cast<std::size_t>(parsed);
        }
    }
    const UcapiLibrary& api = UcapiLibrary::instance();
    if (!is_directory(vdb_)) {
        throw Error("VDB_OPEN_FAILED", "coverage database is not a directory",
                    {{"vdb", vdb_}});
    }
    design_ = api.load(ucapi::kDesignObj, nullptr, vdb_.c_str());
    if (design_ == nullptr) {
        const std::string ucapi_error = api.last_error();
        if (debug_enabled() && !ucapi_error.empty()) {
            std::fprintf(stderr, "ucapi load failed: %s\n", ucapi_error.c_str());
        }
        throw Error("VDB_OPEN_FAILED", "failed to load coverage database",
                    {{"vdb", vdb_}});
    }
    try {
        if (exclusion_policy_ == "strict" && api.configure != nullptr) {
            api.configure(ucapi::kConfigExcludeMode, "strict");
        }
        load_tests();
        walk_instances();
        fill_missing_scopes();
        finalize_scope_metrics();
    } catch (...) {
        close();
        throw;
    }
}

UcapiBackend::~UcapiBackend() {
    close();
}

void UcapiBackend::close() {
    const UcapiLibrary* api_ptr = nullptr;
    try {
        api_ptr = &UcapiLibrary::instance();
    } catch (...) {
        api_ptr = nullptr;
    }
    if (api_ptr != nullptr) {
        for (auto handle : persistent_handles_) {
            if (handle != nullptr) api_ptr->release(handle);
        }
        persistent_handles_.clear();
        for (auto handle : instance_handles_) {
            if (handle != nullptr) api_ptr->release(handle);
        }
        instance_handles_.clear();
        if (test_ != nullptr) {
            api_ptr->unload(test_);
            test_ = nullptr;
        }
        if (design_ != nullptr) {
            api_ptr->unload(design_);
            design_ = nullptr;
        }
    }
    scopes_.clear();
    scope_positions_.clear();
    top_scopes_.clear();
    children_.clear();
}

void UcapiBackend::load_tests() {
    const UcapiLibrary& api = UcapiLibrary::instance();
    ucapi::Handle names = api.iterate(design_, ucapi::kAvailableTests);
    if (names != nullptr) {
        ucapi::Handle item;
        while ((item = api.scan(names)) != nullptr) {
            const std::string name = safe_str(api.get_str(item, ucapi::kName));
            if (!name.empty()) test_names_.push_back(name);
        }
        api.release(names);
    }
    if (test_names_.empty()) {
        throw Error("VDB_OPEN_FAILED", "coverage database has no tests",
                    {{"vdb", vdb_}});
    }
    test_ = api.load(ucapi::kTestObj, design_, test_names_.front().c_str());
    if (test_ == nullptr) {
        const std::string ucapi_error = api.last_error();
        if (debug_enabled() && !ucapi_error.empty()) {
            std::fprintf(stderr, "ucapi test load failed: %s\n",
                         ucapi_error.c_str());
        }
        throw Error("VDB_OPEN_FAILED", "failed to load coverage test",
                    {{"vdb", vdb_}, {"test", test_names_.front()}});
    }
    for (std::size_t index = 1; index < test_names_.size(); ++index) {
        ucapi::Handle merged =
            api.load_merge(ucapi::kTestObj, test_, test_names_[index].c_str());
        if (merged == nullptr) {
            throw Error("VDB_OPEN_FAILED", "failed to merge coverage test",
                        {{"vdb", vdb_}, {"test", test_names_[index]}});
        }
        test_ = merged;
    }
    test_name_ = test_names_.size() == 1 ? test_names_.front() : "merged";
}

void UcapiBackend::walk_instances() {
    const UcapiLibrary& api = UcapiLibrary::instance();
    struct Pending {
        ucapi::Handle handle;
        std::string parent;
    };
    std::vector<Pending> stack;
    ucapi::Handle roots = api.iterate(design_, ucapi::kInstances);
    if (roots != nullptr) {
        ucapi::Handle item;
        while ((item = api.scan(roots)) != nullptr) {
            ucapi::Handle persistent = api.make_persistent(item);
            instance_handles_.push_back(persistent);
            stack.push_back({persistent, std::string()});
        }
        api.release(roots);
    }
    while (!stack.empty()) {
        Pending current = stack.back();
        stack.pop_back();
        ScopeInfo scope;
        scope.handle = current.handle;
        scope.full_name = safe_str(api.get_str(current.handle, ucapi::kFullName));
        const std::string ucapi_name =
            safe_str(api.get_str(current.handle, ucapi::kName));
        if (scope.full_name.empty()) scope.full_name = ucapi_name;
        const std::size_t last_dot = scope.full_name.rfind('.');
        scope.name = last_dot == std::string::npos
                         ? scope.full_name
                         : scope.full_name.substr(last_dot + 1);
        scope.parent = current.parent;
        scope.has_parent = !current.parent.empty();
        aggregate_scope(scope);
        if (!scope.has_parent) top_scopes_.push_back(scope.full_name);
        if (scope.has_parent) children_[current.parent].push_back(scope.full_name);
        scope_positions_[scope.full_name] = scopes_.size();
        scopes_.push_back(scope);

        ucapi::Handle kids = api.iterate(current.handle, ucapi::kInstances);
        if (kids != nullptr) {
            std::vector<ucapi::Handle> pending;
            ucapi::Handle kid;
            while ((kid = api.scan(kids)) != nullptr) {
                ucapi::Handle persistent = api.make_persistent(kid);
                instance_handles_.push_back(persistent);
                pending.push_back(persistent);
            }
            api.release(kids);
            for (auto it = pending.rbegin(); it != pending.rend(); ++it) {
                stack.push_back({*it, scope.full_name});
            }
        }
    }
}

void UcapiBackend::refresh_metrics() {
    if (!metrics_dirty_) return;
    const UcapiLibrary& api = UcapiLibrary::instance();
    for (auto handle : persistent_handles_) {
        if (handle != nullptr) api.release(handle);
    }
    persistent_handles_.clear();
    for (auto& scope : scopes_) {
        scope.metrics.clear();
        scope.deep_metrics.clear();
        scope.present_metrics.clear();
        scope.deep_present.clear();
        if (scope.handle == nullptr) continue;  // synthetic generate level
        aggregate_scope(scope);
    }
    fill_missing_scopes();
    finalize_scope_metrics();
    metrics_dirty_ = false;
}

void UcapiBackend::aggregate_scope(ScopeInfo& scope) {
    const UcapiLibrary& api = UcapiLibrary::instance();
    ucapi::Handle metrics = api.iterate(test_, ucapi::kMetrics);
    if (metrics == nullptr) return;
    ucapi::Handle metric;
    while ((metric = api.scan(metrics)) != nullptr) {
        if (api.is_assert_metric(metric) || api.is_testbench_metric(metric) ||
            api.is_path_metric(metric)) {
            continue;
        }
        MetricKind kind;
        if (api.is_line_metric(metric)) kind = MetricKind::Line;
        else if (api.is_tgl_metric(metric)) kind = MetricKind::Toggle;
        else {
            const std::string name = safe_str(api.get_str(metric, ucapi::kName));
            if (name == "Branch") kind = MetricKind::Branch;
            else if (name == "Condition") kind = MetricKind::Condition;
            else if (name == "Fsm") kind = MetricKind::Fsm;
            else continue;
        }
        ucapi::Handle persistent_metric = api.make_persistent(metric);
        persistent_handles_.push_back(persistent_metric);
        ucapi::Handle region =
            api.get_qualified_handle(scope.handle, persistent_metric, ucapi::kIdentity);
        if (region == nullptr) continue;
        MetricAggregate aggregate;
        const bool is_fsm = kind == MetricKind::Fsm;
        ucapi::Handle objects = api.iterate(region, ucapi::kObjects);
        if (objects != nullptr) {
            ucapi::Handle object;
            while ((object = api.scan(objects)) != nullptr) {
                ucapi::Handle persistent_object = api.make_persistent(object);
                const int type =
                    api.get(persistent_object, region, nullptr, ucapi::kType);
                if (type == ucapi::kContainer) {
                    if (is_fsm) {
                        ucapi::Handle inner =
                            api.iterate(persistent_object, ucapi::kObjects);
                        if (inner != nullptr) {
                            ucapi::Handle child;
                            while ((child = api.scan(inner)) != nullptr) {
                                if (safe_str(api.get_str(child, ucapi::kName)) ==
                                    "transitions") {
                                    ucapi::Handle persistent_child =
                                        api.make_persistent(child);
                                    aggregate.covered += api.get(
                                        persistent_child, region, test_,
                                        ucapi::kCovered);
                                    aggregate.coverable += api.get(
                                        persistent_child, region, test_,
                                        ucapi::kCoverable);
                                    api.release(persistent_child);
                                }
                            }
                            api.release(inner);
                        }
                    } else {
                        aggregate.covered += api.get(persistent_object, region,
                                                     test_, ucapi::kCovered);
                        aggregate.coverable += api.get(persistent_object, region,
                                                       test_, ucapi::kCoverable);
                    }
                } else if (is_leaf_type(type)) {
                    aggregate.covered += api.get(persistent_object, region, test_,
                                                 ucapi::kCovered);
                    aggregate.coverable += api.get(persistent_object, region, test_,
                                                   ucapi::kCoverable);
                }
                api.release(persistent_object);
            }
            api.release(objects);
        }
        api.release(region);
        scope.metrics[kind] = aggregate;
        if (aggregate.covered > 0 || aggregate.coverable > 0) {
            scope.present_metrics.insert(kind);
        }
    }
    api.release(metrics);
}

// URG reports generate blocks as scopes; UCAPI may fold them into their
// children. Recreate the missing intermediate levels so hierarchy actions match.
void UcapiBackend::fill_missing_scopes() {
    std::vector<std::string> missing;
    for (const auto& scope : scopes_) {
        std::size_t dot = scope.full_name.find('.');
        while (dot != std::string::npos) {
            const std::string prefix = scope.full_name.substr(0, dot);
            if (scope_positions_.find(prefix) == scope_positions_.end() &&
                std::find(missing.begin(), missing.end(), prefix) == missing.end()) {
                missing.push_back(prefix);
            }
            dot = scope.full_name.find('.', dot + 1);
        }
    }
    std::sort(missing.begin(), missing.end(),
              [](const std::string& a, const std::string& b) {
                  return a.size() < b.size();
              });
    for (const auto& full : missing) {
        ScopeInfo scope;
        const std::size_t dot = full.rfind('.');
        scope.full_name = full;
        scope.name = dot == std::string::npos ? full : full.substr(dot + 1);
        if (dot != std::string::npos) {
            scope.parent = full.substr(0, dot);
            scope.has_parent = true;
        }
        scope.handle = nullptr;
        scope_positions_[full] = scopes_.size();
        scopes_.push_back(scope);
        if (scope.has_parent) {
            children_[scope.parent].push_back(full);
        } else {
            top_scopes_.push_back(full);
        }
    }
    // Re-parent real instances under the deepest existing full_name prefix so
    // the hierarchy matches URG's generate-block view.
    for (auto& scope : scopes_) {
        if (scope.handle == nullptr || !scope.has_parent) continue;
        std::string best;
        std::size_t pos = scope.full_name.find('.');
        while (pos != std::string::npos) {
            const std::string prefix = scope.full_name.substr(0, pos);
            if (scope_positions_.count(prefix) > 0) best = prefix;
            pos = scope.full_name.find('.', pos + 1);
        }
        if (best.empty() || best == scope.parent) continue;
        auto& old_siblings = children_[scope.parent];
        old_siblings.erase(
            std::remove(old_siblings.begin(), old_siblings.end(), scope.full_name),
            old_siblings.end());
        children_[best].push_back(scope.full_name);
        scope.parent = best;
    }
    // Deep aggregation must skip synthetic levels: point every real scope at
    // its nearest real ancestor.
    for (auto& scope : scopes_) {
        scope.metric_parent = scope.parent;
        if (scope.handle == nullptr) continue;
        std::string node = scope.parent;
        while (!node.empty()) {
            auto pos = scope_positions_.find(node);
            if (pos == scope_positions_.end()) break;
            if (scopes_[pos->second].handle != nullptr) {
                scope.metric_parent = node;
                break;
            }
            node = scopes_[pos->second].parent;
        }
    }
}

void UcapiBackend::finalize_scope_metrics() {
    const UcapiLibrary& api = UcapiLibrary::instance();
    ucapi::Handle metrics = api.iterate(test_, ucapi::kMetrics);
    if (metrics != nullptr) {
        ucapi::Handle metric;
        while ((metric = api.scan(metrics)) != nullptr) {
            if (api.is_testbench_metric(metric)) {
                ucapi::Handle groups =
                    api.qualified_iterate(test_, metric, ucapi::kDefinitions);
                if (groups != nullptr) {
                    ucapi::Handle group;
                    while ((group = api.scan(groups)) != nullptr) {
                        ucapi::Handle persistent_group = api.make_persistent(group);
                        ucapi::Handle variants = api.qualified_iterate(
                            persistent_group, metric, ucapi::kDefinitions);
                        if (variants != nullptr) {
                            ucapi::Handle variant;
                            while ((variant = api.scan(variants)) != nullptr) {
                                ucapi::Handle persistent_variant =
                                    api.make_persistent(variant);
                                const std::string full = safe_str(
                                    api.get_str(persistent_variant, ucapi::kFullName));
                                const std::size_t marker = full.find("::");
                                if (marker != std::string::npos) {
                                    auto pos = scope_positions_.find(
                                        full.substr(0, marker));
                                    if (pos != scope_positions_.end()) {
                                        MetricAggregate& entry =
                                            scopes_[pos->second]
                                                .metrics[MetricKind::Functional];
                                        entry.covered += api.get(
                                            persistent_variant, nullptr, test_,
                                            ucapi::kCovered);
                                        entry.coverable += api.get(
                                            persistent_variant, nullptr, test_,
                                            ucapi::kCoverable);
                                    }
                                }
                                api.release(persistent_variant);
                            }
                            api.release(variants);
                        }
                        api.release(persistent_group);
                    }
                    api.release(groups);
                }
            } else if (api.is_assert_metric(metric)) {
                ucapi::Handle objects =
                    api.qualified_iterate(test_, metric, ucapi::kObjects);
                if (objects != nullptr) {
                    ucapi::Handle object;
                    while ((object = api.scan(objects)) != nullptr) {
                        ucapi::Handle persistent = api.make_persistent(object);
                        const std::string full =
                            safe_str(api.get_str(persistent, ucapi::kFullName));
                        const std::size_t dot = full.rfind('.');
                        const std::string scope_name =
                            dot == std::string::npos ? full : full.substr(0, dot);
                        // Assertions can live in generate blocks that have
                        // no coverage instance of their own; URG attributes
                        // them to the nearest real ancestor scope.
                        std::size_t mount_index = scopes_.size();
                        std::string node = scope_name;
                        while (!node.empty()) {
                            auto pos = scope_positions_.find(node);
                            if (pos != scope_positions_.end() &&
                                scopes_[pos->second].handle != nullptr) {
                                mount_index = pos->second;
                                break;
                            }
                            const std::size_t parent_dot = node.rfind('.');
                            if (parent_dot == std::string::npos) break;
                            node = node.substr(0, parent_dot);
                        }
                        if (mount_index != scopes_.size()) {
                            const int type = api.get_assert_type(persistent);
                            long real_successes = 0;
                            long all_successes = 0;
                            ucapi::Handle blocks =
                                api.iterate(persistent, ucapi::kObjects);
                            if (blocks != nullptr) {
                                ucapi::Handle block;
                                while ((block = api.scan(blocks)) != nullptr) {
                                    const std::string name =
                                        safe_str(api.get_str(block, ucapi::kName));
                                    if (name != "realsuccesses" &&
                                        name != "allsuccesses") {
                                        continue;
                                    }
                                    const long count = api.get(block, persistent, test_,
                                                               ucapi::kCovCount);
                                    if (name == "realsuccesses") real_successes = count;
                                    else all_successes = count;
                                }
                                api.release(blocks);
                            }
                            const int assert_status =
                                api.get(persistent, nullptr, test_,
                                        ucapi::kCovStatus);
                            const bool assert_excluded =
                                assert_status >= 0 &&
                                (assert_status &
                                 ucapi::kStatusExcludedAtReportTime) != 0;
                            const long hit =
                                (type == ucapi::kAssertionTypeCoverProperty
                                     ? all_successes
                                     : real_successes) > 0
                                    ? 1
                                    : 0;
                            if (assert_excluded) {
                                api.release(persistent);
                                continue;
                            }
                            MetricAggregate& entry =
                                scopes_[mount_index].metrics[MetricKind::Assert];
                            entry.covered += hit;
                            entry.coverable += 1;
                        }
                        api.release(persistent);
                    }
                    api.release(objects);
                }
            }
        }
        api.release(metrics);
    }

    // Assert/functional aggregates are appended after aggregate_scope();
    // derive presence once from the final self maps.
    for (auto& scope : scopes_) {
        for (const auto& item : scope.metrics) {
            if (item.second.covered > 0 || item.second.coverable > 0) {
                scope.present_metrics.insert(item.first);
            }
        }
        scope.deep_metrics = scope.metrics;
        scope.deep_present = scope.present_metrics;
    }
    std::vector<std::size_t> order(scopes_.size());
    for (std::size_t i = 0; i < order.size(); ++i) order[i] = i;
    std::sort(order.begin(), order.end(), [&](std::size_t a, std::size_t b) {
        return scopes_[a].full_name.size() > scopes_[b].full_name.size();
    });
    for (std::size_t index : order) {
        ScopeInfo& scope = scopes_[index];
        if (!scope.has_parent) continue;
        const std::string& agg_parent =
            scope.metric_parent.empty() ? scope.parent : scope.metric_parent;
        auto pos = scope_positions_.find(agg_parent);
        if (pos == scope_positions_.end()) continue;
        ScopeInfo& parent = scopes_[pos->second];
        for (const auto& item : scope.deep_metrics) {
            MetricAggregate& entry = parent.deep_metrics[item.first];
            entry.covered += item.second.covered;
            entry.coverable += item.second.coverable;
        }
        for (MetricKind kind : scope.deep_present) {
            parent.deep_present.insert(kind);
        }
    }
}

MetricAggregate UcapiBackend::assert_totals() const {
    MetricAggregate aggregate;
    for (const auto& row : assertions()) {
        const long success = row.type == 1 ? row.all_successes : row.real_successes;
        aggregate.covered += success > 0 ? 1 : 0;
        aggregate.coverable += 1;
    }
    return aggregate;
}

MetricAggregate UcapiBackend::functional_totals() const {
    MetricAggregate aggregate;
    for (const auto& group : functional_groups()) {
        aggregate.covered += group.covered;
        aggregate.coverable += group.coverable;
    }
    return aggregate;
}

const std::vector<UcapiBackend::FunctionalGroup>& UcapiBackend::functional_groups() const {
    if (functional_cache_valid_) return functional_cache_;
    const UcapiLibrary& api = UcapiLibrary::instance();
    std::vector<FunctionalGroup> out;
    ucapi::Handle metrics = api.iterate(test_, ucapi::kMetrics);
    if (metrics == nullptr) {
        functional_cache_valid_ = true;
        return functional_cache_;
    }
    ucapi::Handle metric;
    while ((metric = api.scan(metrics)) != nullptr) {
        if (!api.is_testbench_metric(metric)) continue;
        ucapi::Handle groups = api.qualified_iterate(test_, metric, ucapi::kDefinitions);
        if (groups == nullptr) continue;
        ucapi::Handle group;
        while ((group = api.scan(groups)) != nullptr) {
            ucapi::Handle persistent_group = api.make_persistent(group);
            ucapi::Handle variants =
                api.qualified_iterate(persistent_group, metric, ucapi::kDefinitions);
            if (variants != nullptr) {
                ucapi::Handle variant;
                while ((variant = api.scan(variants)) != nullptr) {
                    ucapi::Handle persistent_variant = api.make_persistent(variant);
                    FunctionalGroup row;
                    row.full_name =
                        safe_str(api.get_str(persistent_variant, ucapi::kFullName));
                    row.covered =
                        api.get(persistent_variant, nullptr, test_, ucapi::kCovered);
                    row.coverable =
                        api.get(persistent_variant, nullptr, test_, ucapi::kCoverable);
                    double pct_total = 0.0;
                    ucapi::Handle children =
                        api.iterate(persistent_variant, ucapi::kObjects);
                    if (children != nullptr) {
                        ucapi::Handle child;
                        while ((child = api.scan(children)) != nullptr) {
                            ucapi::Handle persistent_child =
                                api.make_persistent(child);
                            const int child_type =
                                api.get(persistent_child, persistent_variant, nullptr,
                                        ucapi::kType);
                            if (child_type == ucapi::kContainer) {
                                const long child_covered = api.get(
                                    persistent_child, persistent_variant, test_,
                                    ucapi::kCovered);
                                const long child_coverable = api.get(
                                    persistent_child, persistent_variant, test_,
                                    ucapi::kCoverable);
                                if (child_coverable > 0) {
                                    pct_total += 100.0 *
                                                 static_cast<double>(child_covered) /
                                                 static_cast<double>(child_coverable);
                                    row.score_item_count += 1;
                                }
                            }
                            api.release(persistent_child);
                        }
                        api.release(children);
                    }
                    if (row.score_item_count > 0) {
                        row.score_pct = pct_total / row.score_item_count;
                    }
                    out.push_back(row);
                    api.release(persistent_variant);
                }
                api.release(variants);
            }
            api.release(persistent_group);
        }
        api.release(groups);
    }
    api.release(metrics);
    functional_cache_ = std::move(out);
    functional_cache_valid_ = true;
    return functional_cache_;
}

const std::vector<UcapiBackend::AssertionRow>& UcapiBackend::assertions() const {
    if (assertion_cache_valid_) return assertion_cache_;
    const UcapiLibrary& api = UcapiLibrary::instance();
    std::vector<AssertionRow> out;
    ucapi::Handle metrics = api.iterate(test_, ucapi::kMetrics);
    if (metrics == nullptr) {
        assertion_cache_valid_ = true;
        return assertion_cache_;
    }
    ucapi::Handle metric;
    while ((metric = api.scan(metrics)) != nullptr) {
        if (!api.is_assert_metric(metric)) continue;
        ucapi::Handle objects = api.qualified_iterate(test_, metric, ucapi::kObjects);
        if (objects == nullptr) continue;
        ucapi::Handle object;
        while ((object = api.scan(objects)) != nullptr) {
            ucapi::Handle persistent = api.make_persistent(object);
            AssertionRow row;
            row.full_name = safe_str(api.get_str(persistent, ucapi::kFullName));
            row.name = safe_str(api.get_str(persistent, ucapi::kName));
            const std::size_t name_dot = row.name.rfind('.');
            if (name_dot != std::string::npos) {
                row.name = row.name.substr(name_dot + 1);
            }
            row.type = api.get_assert_type(persistent);
            ucapi::Handle blocks = api.iterate(persistent, ucapi::kObjects);
            if (blocks != nullptr) {
                ucapi::Handle block;
                while ((block = api.scan(blocks)) != nullptr) {
                    const std::string name = safe_str(api.get_str(block, ucapi::kName));
                    const long count =
                        api.get(block, persistent, test_, ucapi::kCovCount);
                    if (name == "attempts") row.attempts = count;
                    else if (name == "realsuccesses") row.real_successes = count;
                    else if (name == "allsuccesses") row.all_successes = count;
                    else if (name == "failures") row.failures = count;
                    else if (name == "incompletes") row.incomplete = count;
                }
                api.release(blocks);
            }
            const int status = api.get(persistent, nullptr, test_,
                                       ucapi::kCovStatus);
            if (status >= 0 &&
                (status & ucapi::kStatusExcludedAtReportTime) != 0) {
                row.excluded = true;
                row.attempts = 0;
                row.real_successes = 0;
                row.all_successes = 0;
                row.failures = 0;
                row.incomplete = 0;
            }
            out.push_back(row);
            api.release(persistent);
        }
        api.release(objects);
    }
    api.release(metrics);
    assertion_cache_ = std::move(out);
    assertion_cache_valid_ = true;
    return assertion_cache_;
}

const std::vector<UcapiBackend::FunctionalGap>& UcapiBackend::functional_gaps() const {
    if (functional_gap_cache_valid_) return functional_gap_cache_;
    const UcapiLibrary& api = UcapiLibrary::instance();
    std::vector<FunctionalGap> out;
    ucapi::Handle metrics = api.iterate(test_, ucapi::kMetrics);
    if (metrics == nullptr) {
        functional_gap_cache_valid_ = true;
        return functional_gap_cache_;
    }
    ucapi::Handle metric;
    while ((metric = api.scan(metrics)) != nullptr) {
        if (!api.is_testbench_metric(metric)) continue;
        ucapi::Handle groups = api.qualified_iterate(test_, metric, ucapi::kDefinitions);
        if (groups == nullptr) continue;
        ucapi::Handle group;
        while ((group = api.scan(groups)) != nullptr) {
            ucapi::Handle persistent_group = api.make_persistent(group);
            ucapi::Handle variants =
                api.qualified_iterate(persistent_group, metric, ucapi::kDefinitions);
            if (variants != nullptr) {
                ucapi::Handle variant;
                while ((variant = api.scan(variants)) != nullptr) {
                    ucapi::Handle persistent_variant = api.make_persistent(variant);
                    const std::string variant_full = safe_str(
                        api.get_str(persistent_variant, ucapi::kFullName));
                    // A fully excluded covergroup reports zero coverable; skip
                    // it so its bins stop showing up as gaps.
                    if (api.get(persistent_variant, nullptr, test_,
                                ucapi::kCoverable) == 0) {
                        api.release(persistent_variant);
                        continue;
                    }
                    ucapi::Handle coverpoints =
                        api.iterate(persistent_variant, ucapi::kObjects);
                    if (coverpoints != nullptr) {
                        ucapi::Handle coverpoint;
                        while ((coverpoint = api.scan(coverpoints)) != nullptr) {
                            const std::string cp_name =
                                safe_str(api.get_str(coverpoint, ucapi::kName));
                            ucapi::Handle bin_groups =
                                api.iterate(coverpoint, ucapi::kObjects);
                            if (bin_groups != nullptr) {
                                ucapi::Handle bin_group;
                                while ((bin_group = api.scan(bin_groups)) != nullptr) {
                                    ucapi::Handle bins =
                                        api.iterate(bin_group, ucapi::kObjects);
                                    if (bins != nullptr) {
                                        ucapi::Handle bin;
                                        while ((bin = api.scan(bins)) != nullptr) {
                                            const long covered = api.get(
                                                bin, persistent_variant, test_,
                                                ucapi::kCovered);
                                            const long coverable = api.get(
                                                bin, persistent_variant, test_,
                                                ucapi::kCoverable);
                                            if (coverable > covered) {
                                                FunctionalGap gap;
                                                const std::size_t marker =
                                                    variant_full.find("::");
                                                gap.scope =
                                                    marker == std::string::npos
                                                        ? std::string()
                                                        : variant_full.substr(0, marker);
                                                gap.covergroup = variant_full;
                                                gap.coverpoint = cp_name;
                                                gap.bin = safe_str(
                                                    api.get_str(bin, ucapi::kName));
                                                gap.full_name = variant_full + "." +
                                                                cp_name + "." + gap.bin;
                                                out.push_back(gap);
                                            }
                                        }
                                        api.release(bins);
                                    }
                                }
                                api.release(bin_groups);
                            }
                        }
                        api.release(coverpoints);
                    }
                    api.release(persistent_variant);
                }
                api.release(variants);
            }
            api.release(persistent_group);
        }
        api.release(groups);
    }
    api.release(metrics);
    functional_gap_cache_ = std::move(out);
    functional_gap_cache_valid_ = true;
    return functional_gap_cache_;
}

namespace {

void collect_leaf_gaps(const UcapiLibrary& api, ucapi::Handle obj,
                       ucapi::Handle region, ucapi::Handle test,
                       const std::string& metric, const std::string& scope_name,
                       std::vector<UcapiBackend::CodeGap>* out, bool fsm,
                       bool in_transitions) {
    const int type = api.get(obj, region, nullptr, ucapi::kType);
    const std::string name = safe_str(api.get_str(obj, ucapi::kName));
    if (is_leaf_type(type)) {
        if (fsm && !in_transitions) return;
        const long covered = api.get(obj, region, test, ucapi::kCovered);
        const long coverable = api.get(obj, region, test, ucapi::kCoverable);
        if (coverable > 0 && covered == 0) {
            UcapiBackend::CodeGap gap;
            gap.metric = metric;
            gap.name = name;
            gap.full_name = scope_name + "." + name;
            gap.coverable = coverable;
            out->push_back(gap);
        }
        return;
    }
    if (type != ucapi::kContainer) return;
    const bool now = in_transitions || (fsm && name == "transitions");
    ucapi::Handle kids = api.iterate(obj, ucapi::kObjects);
    if (kids == nullptr) return;
    ucapi::Handle kid;
    while ((kid = api.scan(kids)) != nullptr) {
        collect_leaf_gaps(api, kid, region, test, metric, scope_name, out, fsm,
                          now);
    }
    api.release(kids);
}

} // namespace

namespace {

bool ref_matches(const nlohmann::json& row, const std::string& wanted) {
    return coverage_ref(row) == wanted;
}

std::string ucapi_metric_key(const std::string& name) {
    if (name == "Line") return "line";
    if (name == "Tgl") return "toggle";
    if (name == "Branch") return "branch";
    if (name == "Condition") return "condition";
    if (name == "Fsm") return "fsm";
    if (name == "Assert") return "assert";
    if (name == "testbench") return "functional";
    return name;
}

bool match_leaf_recursive(const UcapiLibrary& api, ucapi::Handle obj,
                          ucapi::Handle region, const std::string& metric,
                          const std::string& scope_name,
                          const std::string& wanted, ucapi::Handle* out_obj,
                          nlohmann::json* out_row) {
    const int type = api.get(obj, region, nullptr, ucapi::kType);
    if (is_leaf_type(type)) {
        nlohmann::json row = nlohmann::json::object();
        row["metric"] = metric;
        row["scope"] = scope_name;
        row["type"] = coverage_type_for_metric(metric);
        const std::string name = safe_str(api.get_str(obj, ucapi::kName));
        row["name"] = name;
        row["full_name"] = scope_name + "." + name;
        if (coverage_ref(row) != wanted) return false;
        *out_obj = api.make_persistent(obj);
        if (out_row != nullptr) *out_row = row;
        return true;
    }
    if (type != ucapi::kContainer) return false;
    ucapi::Handle kids = api.iterate(obj, ucapi::kObjects);
    if (kids == nullptr) return false;
    ucapi::Handle kid;
    bool found = false;
    while (!found && (kid = api.scan(kids)) != nullptr) {
        found = match_leaf_recursive(api, kid, region, metric, scope_name,
                                     wanted, out_obj, out_row);
    }
    api.release(kids);
    return found;
}

// Find one coverable object by its session-local coverage_ref.
bool find_by_ref(const UcapiLibrary& api, ucapi::Handle test,
                 const std::vector<ScopeInfo>& scopes, int hinted_scope,
                 const std::string& wanted, ucapi::Handle* out_obj,
                 ucapi::Handle* out_region, nlohmann::json* out_row) {
    if (debug_enabled()) {
        std::fprintf(stderr, "find_by_ref start scopes=%zu wanted=%s\n",
                     scopes.size(), wanted.c_str());
    }
    ucapi::Handle metrics = api.iterate(test, ucapi::kMetrics);
    if (metrics == nullptr) {
        if (debug_enabled()) std::fprintf(stderr, "no metrics\n");
        return false;
    }
    std::vector<const ScopeInfo*> scopes_to_scan;
    if (hinted_scope >= 0 &&
        static_cast<std::size_t>(hinted_scope) < scopes.size() &&
        scopes[static_cast<std::size_t>(hinted_scope)].handle != nullptr) {
        scopes_to_scan.push_back(&scopes[static_cast<std::size_t>(hinted_scope)]);
    } else {
        for (const auto& scope : scopes) scopes_to_scan.push_back(&scope);
    }
    ucapi::Handle metric;
    while ((metric = api.scan(metrics)) != nullptr) {
        if (api.is_assert_metric(metric)) {
            // Assertion refs live on the test handle, not on instance
            // regions; resolve them by full_name so an evicted locator still
            // works.
            ucapi::Handle objects =
                api.qualified_iterate(test, metric, ucapi::kObjects);
            if (objects != nullptr) {
                ucapi::Handle object;
                bool found = false;
                while (!found && (object = api.scan(objects)) != nullptr) {
                    ucapi::Handle persistent = api.make_persistent(object);
                    const std::string full = safe_str(
                        api.get_str(persistent, ucapi::kFullName));
                    const std::size_t dot = full.rfind('.');
                    nlohmann::json row = nlohmann::json::object();
                    row["metric"] = "assert";
                    row["scope"] = dot == std::string::npos
                                       ? std::string()
                                       : full.substr(0, dot);
                    // export.assert builds the ref identity with type
                    // "assert" (not npiCovAssert); match it exactly.
                    row["type"] = "assert";
                    row["name"] = safe_str(
                        api.get_str(persistent, ucapi::kName));
                    row["full_name"] = full;
                    if (ref_matches(row, wanted)) {
                        *out_obj = persistent;
                        *out_region = nullptr;
                        if (out_row != nullptr) *out_row = row;
                        found = true;
                    } else {
                        api.release(persistent);
                    }
                }
                api.release(objects);
                if (found) {
                    api.release(metrics);
                    return true;
                }
            }
            continue;
        }
        if (api.is_testbench_metric(metric) || api.is_path_metric(metric)) {
            continue;
        }
        const std::string mname = safe_str(api.get_str(metric, ucapi::kName));
        ucapi::Handle persistent_metric = api.make_persistent(metric);
        for (const ScopeInfo* scope_ptr : scopes_to_scan) {
            const ScopeInfo& scope = *scope_ptr;
            if (scope.handle == nullptr) continue;
            ucapi::Handle region = api.get_qualified_handle(
                scope.handle, persistent_metric, ucapi::kIdentity);
            if (region == nullptr) continue;
            ucapi::Handle objects = api.iterate(region, ucapi::kObjects);
            if (debug_enabled()) {
                static int once = 0;
                if (once < 3) {
                    ++once;
                    std::fprintf(stderr, "dbg scope=%s metric=%s region=%p objects=%p\n",
                                 scope.full_name.c_str(), mname.c_str(),
                                 (void*)region, (void*)objects);
                }
            }
            if (objects != nullptr) {
                // Nested container leaves (toggle transitions, branch arms,
                // condition terms) need their accumulated path to reproduce
                // the exported coverage_ref identity after a locator-cache
                // eviction.
                std::function<bool(ucapi::Handle, const std::string&)> visit =
                    [&](ucapi::Handle object,
                        const std::string& parent_path) -> bool {
                    const int type =
                        api.get(object, region, nullptr, ucapi::kType);
                    const std::string name =
                        safe_str(api.get_str(object, ucapi::kName));
                    const std::string path =
                        parent_path.empty() ? name : parent_path + "." + name;
                    if (is_leaf_type(type)) {
                        nlohmann::json row = nlohmann::json::object();
                        row["metric"] = ucapi_metric_key(mname);
                        row["scope"] = scope.full_name;
                        row["type"] =
                            coverage_type_for_metric(ucapi_metric_key(mname));
                        row["name"] = name;
                        row["full_name"] = scope.full_name + "." + path;
                        if (ref_matches(row, wanted)) {
                            *out_obj = api.make_persistent(object);
                            *out_region = api.make_persistent(region);
                            if (out_row != nullptr) *out_row = row;
                            return true;
                        }
                        return false;
                    }
                    if (type != ucapi::kContainer) return false;
                    ucapi::Handle kids = api.iterate(object, ucapi::kObjects);
                    if (kids == nullptr) return false;
                    ucapi::Handle kid;
                    bool found = false;
                    while (!found && (kid = api.scan(kids)) != nullptr) {
                        found = visit(kid, path);
                    }
                    api.release(kids);
                    return found;
                };
                ucapi::Handle object;
                bool found = false;
                while (!found && (object = api.scan(objects)) != nullptr) {
                    found = visit(object, "");
                }
                api.release(objects);
                if (found) {
                    api.release(region);
                    api.release(persistent_metric);
                    api.release(metrics);
                    return true;
                }
            }
            api.release(region);
        }
        api.release(persistent_metric);
    }
    api.release(metrics);
    return false;
}

} // namespace

namespace {

bool ref_hash_key(const std::string& coverage_ref_value, RefHashKey* key) {
    static const std::string kPrefix = "xcovref.v1:";
    if (coverage_ref_value.compare(0, kPrefix.size(), kPrefix) != 0) {
        return false;
    }
    const std::string hex = coverage_ref_value.substr(kPrefix.size());
    if (hex.size() != 64) return false;
    auto nibble = [](char ch) -> int {
        if (ch >= '0' && ch <= '9') return ch - '0';
        if (ch >= 'a' && ch <= 'f') return ch - 'a' + 10;
        if (ch >= 'A' && ch <= 'F') return ch - 'A' + 10;
        return -1;
    };
    for (std::size_t index = 0; index < 32; ++index) {
        const int high = nibble(hex[index * 2]);
        const int low = nibble(hex[index * 2 + 1]);
        if (high < 0 || low < 0) return false;
        key->bytes[index] = static_cast<unsigned char>((high << 4) | low);
    }
    return true;
}

} // namespace

void UcapiBackend::register_ref(const std::string& coverage_ref_value,
                                const std::string& scope,
                                const std::string& metric,
                                const std::string& name) {
    auto add_scope_hint = [&](const std::string& ref,
                              const std::string& hinted_scope) {
        if (ref_hint_limit_ == 0) return;
        RefHashKey key;
        if (!ref_hash_key(ref, &key)) return;
        auto position = scope_positions_.find(hinted_scope);
        if (position == scope_positions_.end()) return;
        if (ref_scope_hints_.size() >= ref_hint_limit_ &&
            ref_scope_hints_.find(key) == ref_scope_hints_.end()) {
            // unordered_map has no FIFO order; dropping any hint only costs a
            // slower fallback and never changes correctness.
            ref_scope_hints_.erase(ref_scope_hints_.begin());
        }
        ref_scope_hints_[key] = static_cast<std::uint32_t>(position->second);
    };
    if (ref_locator_limit_ == 0) {
        add_scope_hint(coverage_ref_value, scope);
        return;
    }
    const auto existing = ref_locators_.find(coverage_ref_value);
    if (existing == ref_locators_.end()) {
        while (ref_locators_.size() >= ref_locator_limit_ &&
               !ref_locator_order_.empty()) {
            const std::string evicted = ref_locator_order_.front();
            auto evicted_it = ref_locators_.find(evicted);
            if (evicted_it != ref_locators_.end()) {
                add_scope_hint(evicted, std::get<0>(evicted_it->second));
                ref_locators_.erase(evicted_it);
            }
            ref_locator_order_.pop_front();
        }
        ref_locator_order_.push_back(coverage_ref_value);
    }
    ref_locators_[coverage_ref_value] = std::make_tuple(scope, metric, name);
}

namespace {

bool find_leaf_in_subtree(const UcapiLibrary& api, ucapi::Handle obj,
                          ucapi::Handle region, const std::string& scope_prefix,
                          const std::string& wanted_full,
                          const std::string& parent_path,
                          ucapi::Handle* out_obj, bool allow_name_fallback) {
    const int type = api.get(obj, region, nullptr, ucapi::kType);
    const std::string name = safe_str(api.get_str(obj, ucapi::kName));
    const std::string path =
        parent_path.empty() ? name : parent_path + "." + name;
    if (is_leaf_type(type)) {
        // Prefer the canonical path; fall back to the bare leaf name for CSV
        // selector rows, which carry the object name only.
        if (scope_prefix + path == wanted_full ||
            (allow_name_fallback && name == wanted_full)) {
            *out_obj = api.make_persistent(obj);
            return true;
        }
        return false;
    }
    if (type != ucapi::kContainer) return false;
    ucapi::Handle kids = api.iterate(obj, ucapi::kObjects);
    if (kids == nullptr) return false;
    ucapi::Handle kid;
    bool found = false;
    while (!found && (kid = api.scan(kids)) != nullptr) {
        found = find_leaf_in_subtree(api, kid, region, scope_prefix, wanted_full,
                                     path, out_obj, allow_name_fallback);
    }
    api.release(kids);
    return found;
}

// Find one coverable leaf by scope/metric/name through the metric-qualified
// region of that instance.
bool find_leaf_by_locator(const UcapiLibrary& api, ucapi::Handle test,
                          const ScopeInfo& scope, const std::string& metric,
                          const std::string& name, ucapi::Handle* out_obj,
                          ucapi::Handle* out_region) {
    ucapi::Handle metrics = api.iterate(test, ucapi::kMetrics);
    if (metrics == nullptr) return false;
    ucapi::Handle metric_handle;
    while ((metric_handle = api.scan(metrics)) != nullptr) {
        const std::string mname = safe_str(api.get_str(metric_handle, ucapi::kName));
        if (ucapi_metric_key(mname) != metric) continue;
        ucapi::Handle persistent_metric = api.make_persistent(metric_handle);
        ucapi::Handle region = api.get_qualified_handle(scope.handle,
                                                        persistent_metric,
                                                        ucapi::kIdentity);
        if (region == nullptr) {
            api.release(persistent_metric);
            continue;
        }
        ucapi::Handle objects = api.iterate(region, ucapi::kObjects);
        if (objects != nullptr) {
            ucapi::Handle object;
            bool found = false;
            std::vector<ucapi::Handle> candidates;
            while ((object = api.scan(objects)) != nullptr) {
                ucapi::Handle hit = nullptr;
                if (find_leaf_in_subtree(api, object, region,
                                         scope.full_name + ".", name, "", &hit,
                                         false)) {
                    *out_obj = hit;
                    found = true;
                    break;
                }
                if (find_leaf_in_subtree(api, object, region,
                                         scope.full_name + ".", name, "", &hit,
                                         true)) {
                    candidates.push_back(hit);
                }
            }
            api.release(objects);
            // Bare-name fallback only when exactly one object matches.
            if (!found && candidates.size() == 1) {
                *out_obj = candidates.front();
                found = true;
            } else if (!found) {
                for (auto handle : candidates) api.release(handle);
            }
            if (found) {
                *out_region = api.make_persistent(region);
                api.release(region);
                api.release(persistent_metric);
                api.release(metrics);
                return true;
            }
        }
        api.release(region);
        api.release(persistent_metric);
    }
    api.release(metrics);
    return false;
}

} // namespace

bool UcapiBackend::locator_for_ref(const std::string& coverage_ref_value,
                                   std::string* scope, std::string* metric,
                                   std::string* name) const {
    auto it = ref_locators_.find(coverage_ref_value);
    if (it == ref_locators_.end()) return false;
    *scope = std::get<0>(it->second);
    *metric = std::get<1>(it->second);
    *name = std::get<2>(it->second);
    return true;
}

bool UcapiBackend::exclusion_state(const std::string& coverage_ref_value,
                                   bool* excluded) const {
    const UcapiLibrary& api = UcapiLibrary::instance();
    auto locator = ref_locators_.find(coverage_ref_value);
    if (locator == ref_locators_.end()) return false;
    const std::string& scope_name = std::get<0>(locator->second);
    const std::string& metric = std::get<1>(locator->second);
    const std::string& full_name = std::get<2>(locator->second);
    if (metric == "assert") {
        ucapi::Handle metrics = api.iterate(test_, ucapi::kMetrics);
        if (metrics == nullptr) return false;
        ucapi::Handle m;
        bool found = false;
        while (!found && (m = api.scan(metrics)) != nullptr) {
            if (!api.is_assert_metric(m)) continue;
            ucapi::Handle objects = api.qualified_iterate(test_, m, ucapi::kObjects);
            if (objects == nullptr) continue;
            ucapi::Handle object;
            while ((object = api.scan(objects)) != nullptr) {
                ucapi::Handle persistent = api.make_persistent(object);
                if (safe_str(api.get_str(persistent, ucapi::kFullName)) == full_name) {
                    const int status =
                        api.get(persistent, nullptr, test_, ucapi::kCovStatus);
                    *excluded = status >= 0 &&
                                (status & ucapi::kStatusExcludedAtReportTime) != 0;
                    found = true;
                    api.release(persistent);
                    break;
                }
                api.release(persistent);
            }
            api.release(objects);
        }
        api.release(metrics);
        return found;
    }
    const ScopeInfo* scope = find_scope(scope_name);
    if (scope == nullptr || scope->handle == nullptr) return false;
    ucapi::Handle object = nullptr;
    ucapi::Handle region = nullptr;
    ucapi::Handle persistent_metric = nullptr;
    ucapi::Handle metrics = api.iterate(test_, ucapi::kMetrics);
    if (metrics == nullptr) return false;
    ucapi::Handle m;
    bool found = false;
    while (!found && (m = api.scan(metrics)) != nullptr) {
        const std::string key = ucapi_metric_key(safe_str(api.get_str(m, ucapi::kName)));
        if (key != metric) continue;
        persistent_metric = api.make_persistent(m);
        region = api.get_qualified_handle(scope->handle, persistent_metric,
                                          ucapi::kIdentity);
        if (region == nullptr) {
            api.release(persistent_metric);
            persistent_metric = nullptr;
            continue;
        }
        ucapi::Handle objects = api.iterate(region, ucapi::kObjects);
        if (objects != nullptr) {
            ucapi::Handle o;
            while ((o = api.scan(objects)) != nullptr) {
                found = find_leaf_in_subtree(api, o, region,
                                             scope->full_name + ".", full_name, "",
                                             &object, true);
                if (found) break;
            }
            api.release(objects);
        }
        if (!found) {
            api.release(region);
            api.release(persistent_metric);
            region = nullptr;
            persistent_metric = nullptr;
        }
    }
    api.release(metrics);
    if (!found) return false;
    const int status = api.get(object, region, test_, ucapi::kCovStatus);
    *excluded = status >= 0 &&
                (status & ucapi::kStatusExcludedAtReportTime) != 0;
    api.release(object);
    api.release(region);
    api.release(persistent_metric);
    return true;
}

bool UcapiBackend::set_exclusion(const std::string& coverage_ref_value,
                                 bool excluded,
                                 const std::string& reason) {
    const UcapiLibrary& api = UcapiLibrary::instance();
    ucapi::Handle object = nullptr;
    ucapi::Handle region = nullptr;
    if (debug_enabled()) {
        std::fprintf(stderr, "set_exclusion refs=%zu lookup=%d\n",
                     ref_locators_.size(),
                     (int)(ref_locators_.find(coverage_ref_value) !=
                           ref_locators_.end()));
    }
    auto locator = ref_locators_.find(coverage_ref_value);
    if (locator != ref_locators_.end() &&
        std::get<1>(locator->second) == "assert") {
        if (exclude_assertion(std::get<2>(locator->second), excluded, reason)) {
            return true;
        }
    }
    if (locator != ref_locators_.end()) {
        const std::string& scope_name = std::get<0>(locator->second);
        const ScopeInfo* scope = find_scope(scope_name);
        if (scope != nullptr) {
            const bool found = find_leaf_by_locator(
                api, test_, *scope, std::get<1>(locator->second),
                std::get<2>(locator->second), &object, &region);
            if (debug_enabled()) {
                std::fprintf(stderr, "locator scope=%s metric=%s name=%s found=%d\n",
                             std::get<0>(locator->second).c_str(),
                             std::get<1>(locator->second).c_str(),
                             std::get<2>(locator->second).c_str(), (int)found);
            }
        }
    }
    if (object == nullptr) {
        nlohmann::json row;
        int hinted_scope = -1;
        RefHashKey hint_key;
        if (ref_hash_key(coverage_ref_value, &hint_key)) {
            auto hint = ref_scope_hints_.find(hint_key);
            if (hint != ref_scope_hints_.end()) {
                hinted_scope = static_cast<int>(hint->second);
            }
        }
        if (!find_by_ref(api, test_, scopes_, hinted_scope, coverage_ref_value,
                         &object, &region, &row)) {
            return false;
        }
        // The locator cache is bounded; a full-scan hit lets us repopulate it
        // so a subsequent remove/export can address the same object quickly.
        if (row.contains("scope") && row.contains("metric") &&
            row.contains("full_name")) {
            register_ref(coverage_ref_value, row.at("scope").get<std::string>(),
                         row.at("metric").get<std::string>(),
                         row.at("full_name").get<std::string>());
        }
    }
    const int status = api.get(object, region, test_, ucapi::kCovStatus);
    int updated = status;
    if (excluded) {
        updated |= ucapi::kStatusExcludedAtReportTime;
    } else {
        updated &= ~ucapi::kStatusExcludedAtReportTime;
    }
    invalidate_caches();
    const int rc = api.set(object, region, test_, ucapi::kCovStatus, updated);
    if (rc == 0 && excluded && !reason.empty()) {
        api.set_annotation(object, "cov_comment", reason.c_str());
        api.set_durable(region, test_, object, 1);
    }
    api.release(object);
    api.release(region);
    return rc == 0;
}

namespace {

std::size_t exclude_subtree(const UcapiLibrary& api, ucapi::Handle obj,
                            ucapi::Handle region, ucapi::Handle test,
                            bool excluded, const std::string& reason,
                            char* annotation_written, bool strict,
                            const std::string& scope_name,
                            const std::string& metric,
                            const std::string& parent_path,
                            std::vector<ExclusionKey>* changed_keys) {
    const int type = api.get(obj, region, nullptr, ucapi::kType);
    if (is_leaf_type(type)) {
        if (excluded && strict) {
            const long covered = api.get(obj, region, test, ucapi::kCovered);
            if (covered > 0) return 0;  // strict: excluding covered is illegal
        }
        const int status = api.get(obj, region, test, ucapi::kCovStatus);
        int updated = status;
        if (excluded) {
            updated |= ucapi::kStatusExcludedAtReportTime;
        } else {
            updated &= ~ucapi::kStatusExcludedAtReportTime;
        }
        if (updated == status) return 0;
        api.set(obj, region, test, ucapi::kCovStatus, updated);
        if (changed_keys != nullptr && excluded) {
            const std::string leaf_name =
                safe_str(api.get_str(obj, ucapi::kName));
            ExclusionKey key;
            key.scope = scope_name;
            key.metric = metric;
            key.full_name = scope_name + "." +
                            (parent_path.empty()
                                 ? leaf_name
                                 : parent_path + "." + leaf_name);
            key.object_handle = api.make_persistent(obj);
            key.region_handle = api.make_persistent(region);
            changed_keys->push_back(std::move(key));
        }
        // Writing one annotation per leaf made recursive instance exclusion
        // quadratic on large designs; one durable annotation per request is
        // enough to carry the reason into the EL.
        if (excluded && !reason.empty() && annotation_written != nullptr &&
            *annotation_written == 0) {
            ucapi::Handle persistent = api.make_persistent(obj);
            api.set_annotation(persistent, "cov_comment", reason.c_str());
            api.set_durable(region, test, persistent, 1);
            api.release(persistent);
            *annotation_written = 1;
        }
        return 1;
    }
    if (type != ucapi::kContainer) return 0;
    std::size_t changed = 0;
    ucapi::Handle kids = api.iterate(obj, ucapi::kObjects);
    if (kids == nullptr) return 0;
    ucapi::Handle kid;
    const std::string node_name = safe_str(api.get_str(obj, ucapi::kName));
    const std::string child_path =
        parent_path.empty() ? node_name : parent_path + "." + node_name;
    while ((kid = api.scan(kids)) != nullptr) {
        changed += exclude_subtree(api, kid, region, test, excluded, reason,
                                   annotation_written, strict, scope_name,
                                   metric, child_path, changed_keys);
    }
    api.release(kids);
    return changed;
}

} // namespace

bool UcapiBackend::exclude_assertion(const std::string& full_name,
                                    bool excluded,
                                    const std::string& reason) {
    const UcapiLibrary& api = UcapiLibrary::instance();
    ucapi::Handle metrics = api.iterate(test_, ucapi::kMetrics);
    if (metrics == nullptr) return false;
    ucapi::Handle metric;
    bool done = false;
    while (!done && (metric = api.scan(metrics)) != nullptr) {
        if (!api.is_assert_metric(metric)) continue;
        ucapi::Handle objects = api.qualified_iterate(test_, metric, ucapi::kObjects);
        if (objects == nullptr) continue;
        ucapi::Handle object;
        while ((object = api.scan(objects)) != nullptr) {
            ucapi::Handle persistent = api.make_persistent(object);
            const std::string name = safe_str(api.get_str(persistent, ucapi::kFullName));
            if (name == full_name) {
                const int status = api.get(persistent, nullptr, test_,
                                           ucapi::kCovStatus);
                int updated = status < 0
                                  ? (excluded ? ucapi::kStatusExcludedAtReportTime : 0)
                                  : (excluded
                                         ? status | ucapi::kStatusExcludedAtReportTime
                                         : status & ~ucapi::kStatusExcludedAtReportTime);
                if (excluded && exclusion_policy_ == "strict") {
                    const long covered =
                        api.get(persistent, nullptr, test_, ucapi::kCovered);
                    if (covered > 0) {
                        api.release(persistent);
                        done = false;
                        break;
                    }
                }
                invalidate_caches();
                const int rc = api.set(persistent, nullptr, test_,
                                       ucapi::kCovStatus, updated);
                if (rc == 0 && excluded && !reason.empty()) {
                    api.set_annotation(persistent, "cov_comment", reason.c_str());
                    api.set_durable(nullptr, test_, persistent, 1);
                }
                if (debug_enabled()) {
                    std::fprintf(stderr,
                                 "exclude_assertion name=%s set_rc=%d updated=%d\n",
                                 full_name.c_str(), rc, updated);
                }
                api.release(persistent);
                done = rc == 0;
                break;
            }
            api.release(persistent);
        }
        api.release(objects);
    }
    if (metrics != nullptr) api.release(metrics);
    return done;
}

std::size_t UcapiBackend::exclude_assertions(
    const std::string& scope_name, bool recursive, bool excluded,
    const std::string& reason,
    std::vector<ExclusionKey>* changed_keys) {
    const UcapiLibrary& api = UcapiLibrary::instance();
    ucapi::Handle metrics = api.iterate(test_, ucapi::kMetrics);
    if (metrics == nullptr) return 0;
    std::size_t changed = 0;
    std::set<std::string> annotated_scopes;
    auto owning_instance = [&](const std::string& assert_scope) {
        // Assertions declared in generate blocks belong to the nearest real
        // instance ancestor; URG attributes them there.
        std::string node = assert_scope;
        while (!node.empty()) {
            auto pos = scope_positions_.find(node);
            if (pos != scope_positions_.end() &&
                scopes_[pos->second].handle != nullptr) {
                return node;
            }
            const std::size_t dot = node.rfind('.');
            if (dot == std::string::npos) break;
            node = node.substr(0, dot);
        }
        return std::string();
    };
    ucapi::Handle metric;
    while ((metric = api.scan(metrics)) != nullptr) {
        if (!api.is_assert_metric(metric)) continue;
        ucapi::Handle objects = api.qualified_iterate(test_, metric, ucapi::kObjects);
        if (objects == nullptr) continue;
        ucapi::Handle object;
        while ((object = api.scan(objects)) != nullptr) {
            ucapi::Handle persistent = api.make_persistent(object);
            const std::string full =
                safe_str(api.get_str(persistent, ucapi::kFullName));
            const std::size_t dot = full.rfind('.');
            const std::string assert_scope =
                dot == std::string::npos ? std::string() : full.substr(0, dot);
            const std::string owning = owning_instance(assert_scope);
            const bool in_scope =
                owning == scope_name ||
                (recursive && owning.size() > scope_name.size() &&
                 owning.compare(0, scope_name.size(), scope_name) == 0 &&
                 owning[scope_name.size()] == '.');
            if (!in_scope) {
                api.release(persistent);
                continue;
            }
            if (excluded && exclusion_policy_ == "strict") {
                const long covered =
                    api.get(persistent, nullptr, test_, ucapi::kCovered);
                if (covered > 0) {
                    api.release(persistent);
                    continue;
                }
            }
            bool keep_persistent = false;
            const int status =
                api.get(persistent, nullptr, test_, ucapi::kCovStatus);
            int updated = status < 0
                              ? (excluded ? ucapi::kStatusExcludedAtReportTime : 0)
                              : (excluded
                                     ? status | ucapi::kStatusExcludedAtReportTime
                                     : status &
                                           ~ucapi::kStatusExcludedAtReportTime);
            if (updated != status &&
                api.set(persistent, nullptr, test_, ucapi::kCovStatus,
                        updated) == 0) {
                ++changed;
                if (changed_keys != nullptr && excluded) {
                    ExclusionKey key;
                    key.scope = owning;
                    key.metric = "assert";
                    key.full_name = full;
                    key.assertion = true;
                    // Transfer ownership of the persistent handle to the
                    // delta instead of creating a second one.
                    key.object_handle = persistent;
                    changed_keys->push_back(std::move(key));
                    keep_persistent = true;
                }
                if (excluded && !reason.empty() &&
                    annotated_scopes.insert(owning).second) {
                    api.set_annotation(persistent, "cov_comment", reason.c_str());
                    api.set_durable(nullptr, test_, persistent, 1);
                }
            }
            if (!keep_persistent) api.release(persistent);
        }
        api.release(objects);
    }
    api.release(metrics);
    if (changed > 0) invalidate_caches();
    return changed;
}

bool UcapiBackend::exclude_leaf(const std::string& scope_name,
                                const std::string& metric,
                                const std::string& name,
                                const std::string& reason) {
    const UcapiLibrary& api = UcapiLibrary::instance();
    const ScopeInfo* scope = find_scope(scope_name);
    if (scope == nullptr || scope->handle == nullptr) return false;
    ucapi::Handle object = nullptr;
    ucapi::Handle region = nullptr;
    if (!find_leaf_by_locator(api, test_, *scope, metric, name, &object, &region)) {
        return false;
    }
    if (exclusion_policy_ == "strict") {
        const long covered = api.get(object, region, test_, ucapi::kCovered);
        if (covered > 0) {
            api.release(object);
            api.release(region);
            return false;
        }
    }
    invalidate_caches();
    const int status = api.get(object, region, test_, ucapi::kCovStatus);
    const int updated = status | ucapi::kStatusExcludedAtReportTime;
    const int rc = api.set(object, region, test_, ucapi::kCovStatus, updated);
    if (rc == 0 && !reason.empty()) {
        api.set_annotation(object, "cov_comment", reason.c_str());
        api.set_durable(region, test_, object, 1);
    }
    api.release(object);
    api.release(region);
    return rc == 0;
}

bool UcapiBackend::restore_leaf(const std::string& scope_name,
                                const std::string& metric,
                                const std::string& name) {
    const UcapiLibrary& api = UcapiLibrary::instance();
    const ScopeInfo* scope = find_scope(scope_name);
    if (scope == nullptr || scope->handle == nullptr) return false;
    ucapi::Handle object = nullptr;
    ucapi::Handle region = nullptr;
    if (!find_leaf_by_locator(api, test_, *scope, metric, name, &object,
                              &region)) {
        return false;
    }
    const int status = api.get(object, region, test_, ucapi::kCovStatus);
    const int updated = status & ~ucapi::kStatusExcludedAtReportTime;
    const int rc = updated == status
                       ? 0
                       : api.set(object, region, test_, ucapi::kCovStatus,
                                 updated);
    api.release(object);
    api.release(region);
    invalidate_caches();
    return rc == 0;
}

void UcapiBackend::release_exclusion_keys(
    const std::vector<ExclusionKey>& keys) {
    const UcapiLibrary& api = UcapiLibrary::instance();
    for (const auto& key : keys) {
        if (key.object_handle != nullptr) api.release(key.object_handle);
        if (key.region_handle != nullptr) api.release(key.region_handle);
    }
}

std::size_t UcapiBackend::clear_exclusion_keys(
    const std::vector<ExclusionKey>& keys) {
    const UcapiLibrary& api = UcapiLibrary::instance();
    std::size_t processed = 0;
    for (const auto& key : keys) {
        if (key.object_handle != nullptr) {
            const int status =
                api.get(key.object_handle, key.region_handle, test_,
                        ucapi::kCovStatus);
            int updated = status;
            updated &= ~ucapi::kStatusExcludedAtReportTime;
            if (updated != status) {
                api.set(key.object_handle, key.region_handle, test_,
                        ucapi::kCovStatus, updated);
            }
            api.release(key.object_handle);
            if (key.region_handle != nullptr) api.release(key.region_handle);
            ++processed;
            continue;
        }
        restore_leaf(key.scope, key.metric, key.full_name);
        ++processed;
    }
    if (processed > 0) invalidate_caches();
    return processed;
}

std::size_t UcapiBackend::exclude_line(const std::string& scope_name,
                                      int line_no,
                                      const std::string& reason,
                                      const std::string& source_file) {
    const UcapiLibrary& api = UcapiLibrary::instance();
    const ScopeInfo* scope = find_scope(scope_name);
    if (scope == nullptr || scope->handle == nullptr || line_no <= 0) return 0;
    ucapi::Handle metrics = api.iterate(test_, ucapi::kMetrics);
    if (metrics == nullptr) return 0;
    std::size_t changed = 0;
    std::size_t matched = 0;
    bool strict_skipped = false;
    bool annotation_written = false;
    ucapi::Handle metric;
    while ((metric = api.scan(metrics)) != nullptr) {
        if (!api.is_line_metric(metric)) continue;
        ucapi::Handle persistent_metric = api.make_persistent(metric);
        ucapi::Handle region = api.get_qualified_handle(
            scope->handle, persistent_metric, ucapi::kIdentity);
        if (region != nullptr) {
            std::vector<ucapi::Handle> leaves;
            std::function<void(ucapi::Handle)> collect = [&](ucapi::Handle obj) {
                const int type = api.get(obj, region, nullptr, ucapi::kType);
                if (is_leaf_type(type)) {
                    const int object_line =
                        api.get(obj, region, test_, ucapi::kLineNo);
                    const std::string object_file =
                        safe_str(api.get_str(obj, ucapi::kFileName));
                    const bool file_matches =
                        source_file.empty() || object_file == source_file ||
                        (object_file.size() > source_file.size() &&
                         object_file.compare(object_file.size() -
                                                 source_file.size(),
                                             source_file.size(),
                                             source_file) == 0 &&
                         object_file[object_file.size() -
                                     source_file.size() - 1] == '/');
                    if (object_line == line_no && file_matches) {
                        leaves.push_back(api.make_persistent(obj));
                    }
                    return;
                }
                if (type != ucapi::kContainer) return;
                ucapi::Handle kids = api.iterate(obj, ucapi::kObjects);
                if (kids == nullptr) return;
                ucapi::Handle kid;
                while ((kid = api.scan(kids)) != nullptr) collect(kid);
                api.release(kids);
            };
            ucapi::Handle objects = api.iterate(region, ucapi::kObjects);
            if (objects != nullptr) {
                ucapi::Handle object;
                while ((object = api.scan(objects)) != nullptr) collect(object);
                api.release(objects);
            }
            for (ucapi::Handle leaf : leaves) {
                ++matched;
                if (exclusion_policy_ == "strict") {
                    const long covered =
                        api.get(leaf, region, test_, ucapi::kCovered);
                    if (covered > 0) {
                        strict_skipped = true;
                        api.release(leaf);
                        continue;
                    }
                }
                const int status = api.get(leaf, region, test_, ucapi::kCovStatus);
                const int updated = status | ucapi::kStatusExcludedAtReportTime;
                if (updated != status &&
                    api.set(leaf, region, test_, ucapi::kCovStatus, updated) == 0) {
                    ++changed;
                    if (!reason.empty() && !annotation_written) {
                        api.set_annotation(leaf, "cov_comment", reason.c_str());
                        api.set_durable(region, test_, leaf, 1);
                        annotation_written = true;
                    }
                }
                api.release(leaf);
            }
            api.release(region);
        }
        api.release(persistent_metric);
    }
    api.release(metrics);
    if (changed > 0) invalidate_caches();
    if (strict_skipped) return 0;
    return changed > 0 ? changed : matched;
}

bool UcapiBackend::scope_has_covered_objects(const std::string& scope_name,
                                            bool recursive) const {
    const UcapiLibrary& api = UcapiLibrary::instance();
    std::vector<const ScopeInfo*> targets;
    for (const auto& scope : scopes_) {
        if (scope.handle == nullptr) continue;
        if (scope.full_name == scope_name ||
            (recursive && scope.full_name.size() > scope_name.size() &&
             scope.full_name.compare(0, scope_name.size(), scope_name) == 0 &&
             scope.full_name[scope_name.size()] == '.')) {
            targets.push_back(&scope);
        }
    }
    ucapi::Handle metrics = api.iterate(test_, ucapi::kMetrics);
    if (metrics == nullptr) return false;
    ucapi::Handle metric;
    bool covered_found = false;
    while (!covered_found && (metric = api.scan(metrics)) != nullptr) {
        if (api.is_assert_metric(metric) || api.is_testbench_metric(metric) ||
            api.is_path_metric(metric)) {
            continue;
        }
        ucapi::Handle persistent_metric = api.make_persistent(metric);
        for (const ScopeInfo* scope : targets) {
            if (covered_found) break;
            ucapi::Handle region = api.get_qualified_handle(
                scope->handle, persistent_metric, ucapi::kIdentity);
            if (region == nullptr) continue;
            std::function<bool(ucapi::Handle)> visit = [&](ucapi::Handle obj) {
                const int type = api.get(obj, region, nullptr, ucapi::kType);
                if (is_leaf_type(type)) {
                    return api.get(obj, region, test_, ucapi::kCovered) > 0;
                }
                if (type != ucapi::kContainer) return false;
                ucapi::Handle kids = api.iterate(obj, ucapi::kObjects);
                if (kids == nullptr) return false;
                ucapi::Handle kid;
                bool found = false;
                while (!found && (kid = api.scan(kids)) != nullptr) {
                    found = visit(kid);
                }
                api.release(kids);
                return found;
            };
            ucapi::Handle objects = api.iterate(region, ucapi::kObjects);
            if (objects != nullptr) {
                ucapi::Handle object;
                while (!covered_found && (object = api.scan(objects)) != nullptr) {
                    covered_found = visit(object);
                }
                api.release(objects);
            }
            api.release(region);
        }
        api.release(persistent_metric);
    }
    api.release(metrics);
    if (covered_found) return true;
    // Assertions live on the test handle; strict instance add must also see
    // covered assertions owned by the subtree.
    metrics = api.iterate(test_, ucapi::kMetrics);
    if (metrics == nullptr) return false;
    while (!covered_found && (metric = api.scan(metrics)) != nullptr) {
        if (!api.is_assert_metric(metric)) continue;
        ucapi::Handle objects =
            api.qualified_iterate(test_, metric, ucapi::kObjects);
        if (objects == nullptr) continue;
        ucapi::Handle object;
        while (!covered_found && (object = api.scan(objects)) != nullptr) {
            ucapi::Handle persistent = api.make_persistent(object);
            const std::string full =
                safe_str(api.get_str(persistent, ucapi::kFullName));
            std::string node = full;
            const std::size_t dot = node.rfind('.');
            if (dot != std::string::npos) node = node.substr(0, dot);
            while (!node.empty() && scope_positions_.find(node) ==
                                        scope_positions_.end()) {
                const std::size_t parent_dot = node.rfind('.');
                if (parent_dot == std::string::npos) {
                    node.clear();
                    break;
                }
                node = node.substr(0, parent_dot);
            }
            const bool in_scope =
                node == scope_name ||
                (recursive && node.size() > scope_name.size() &&
                 node.compare(0, scope_name.size(), scope_name) == 0 &&
                 node[scope_name.size()] == '.');
            if (in_scope &&
                api.get(persistent, nullptr, test_, ucapi::kCovered) > 0) {
                covered_found = true;
            }
            api.release(persistent);
        }
        api.release(objects);
    }
    api.release(metrics);
    return covered_found;
}

std::size_t UcapiBackend::exclude_scope(
    const std::string& scope_name, bool recursive,
    const std::string& reason,
    std::vector<ExclusionKey>* changed_keys) {
    invalidate_caches();
    const UcapiLibrary& api = UcapiLibrary::instance();
    std::vector<const ScopeInfo*> targets;
    for (const auto& scope : scopes_) {
        const bool match =
            scope.full_name == scope_name ||
            (recursive && scope.full_name.size() > scope_name.size() &&
             scope.full_name.compare(0, scope_name.size(), scope_name) == 0 &&
             scope.full_name[scope_name.size()] == '.');
        if (match) targets.push_back(&scope);
    }
    std::size_t changed = 0;
    ucapi::Handle metrics = api.iterate(test_, ucapi::kMetrics);
    if (metrics == nullptr) return 0;
    ucapi::Handle metric;
    while ((metric = api.scan(metrics)) != nullptr) {
        if (api.is_assert_metric(metric) || api.is_testbench_metric(metric) ||
            api.is_path_metric(metric)) {
            continue;
        }
        // One durable annotation per excluded INSTANCE section (one per
        // metric section) instead of one per leaf.
        const std::string mname =
            ucapi_metric_key(safe_str(api.get_str(metric, ucapi::kName)));
        std::vector<char> annotation_written(targets.size(), 0);
        ucapi::Handle persistent_metric = api.make_persistent(metric);
        for (std::size_t target_index = 0; target_index < targets.size();
             ++target_index) {
            const ScopeInfo* scope = targets[target_index];
            if (scope->handle == nullptr) continue;
            ucapi::Handle raw_region = api.get_qualified_handle(
                scope->handle, persistent_metric, ucapi::kIdentity);
            if (raw_region == nullptr) continue;
            ucapi::Handle region = api.make_persistent(raw_region);
            api.release(raw_region);
            ucapi::Handle objects = api.iterate(region, ucapi::kObjects);
            if (objects != nullptr) {
                ucapi::Handle object;
                while ((object = api.scan(objects)) != nullptr) {
                    changed += exclude_subtree(
                        api, object, region, test_, true, reason,
                        &annotation_written[target_index],
                        exclusion_policy_ == "strict", scope->full_name,
                        ucapi_metric_key(mname), "", changed_keys);
                }
                api.release(objects);
            }
            api.release(region);
        }
        api.release(persistent_metric);
    }
    api.release(metrics);
    (void)reason;
    changed += exclude_assertions(scope_name, recursive, true, reason,
                                  changed_keys);
    return changed;
}

std::size_t UcapiBackend::restore_scope(const std::string& scope_name,
                                        bool recursive) {
    invalidate_caches();
    const UcapiLibrary& api = UcapiLibrary::instance();
    std::vector<const ScopeInfo*> targets;
    for (const auto& scope : scopes_) {
        const bool match =
            scope.full_name == scope_name ||
            (recursive && scope.full_name.size() > scope_name.size() &&
             scope.full_name.compare(0, scope_name.size(), scope_name) == 0 &&
             scope.full_name[scope_name.size()] == '.');
        if (match) targets.push_back(&scope);
    }
    std::size_t changed = 0;
    ucapi::Handle metrics = api.iterate(test_, ucapi::kMetrics);
    if (metrics == nullptr) return 0;
    ucapi::Handle metric;
    while ((metric = api.scan(metrics)) != nullptr) {
        if (api.is_assert_metric(metric) || api.is_testbench_metric(metric) ||
            api.is_path_metric(metric)) {
            continue;
        }
        ucapi::Handle persistent_metric = api.make_persistent(metric);
        for (const ScopeInfo* scope : targets) {
            if (scope->handle == nullptr) continue;
            ucapi::Handle region = api.get_qualified_handle(
                scope->handle, persistent_metric, ucapi::kIdentity);
            if (region == nullptr) continue;
            ucapi::Handle objects = api.iterate(region, ucapi::kObjects);
            if (objects != nullptr) {
                ucapi::Handle object;
                while ((object = api.scan(objects)) != nullptr) {
                    changed += exclude_subtree(api, object, region, test_, false,
                                               std::string(), nullptr, false,
                                               scope->full_name, "", "",
                                               nullptr);
                }
                api.release(objects);
            }
            api.release(region);
        }
        api.release(persistent_metric);
    }
    api.release(metrics);
    changed += exclude_assertions(scope_name, recursive, false, std::string(),
                                  nullptr);
    return changed;
}

namespace {

std::size_t exclude_leaf_node(const UcapiLibrary& api, ucapi::Handle obj,
                              ucapi::Handle region, ucapi::Handle test,
                              const std::string& reason, bool excluded = true,
                              bool strict = false) {
    const int type = api.get(obj, region, test, ucapi::kType);
    if (type != ucapi::kContainer) {
        if (excluded && strict) {
            const long covered = api.get(obj, region, test, ucapi::kCovered);
            if (covered > 0) return 0;
        }
        const int status = api.get(obj, region, test, ucapi::kCovStatus);
        int updated = status < 0
                          ? (excluded ? ucapi::kStatusExcludedAtReportTime : 0)
                          : (excluded ? status | ucapi::kStatusExcludedAtReportTime
                                      : status & ~ucapi::kStatusExcludedAtReportTime);
        if (updated == status) return 0;
        api.set(obj, region, test, ucapi::kCovStatus, updated);
        if (excluded && !reason.empty()) {
            api.set_annotation(obj, "cov_comment", reason.c_str());
            api.set_durable(region, test, obj, 1);
        }
        return 1;
    }
    if (type != ucapi::kContainer) return 0;
    std::size_t changed = 0;
    ucapi::Handle kids = api.iterate(obj, ucapi::kObjects);
    if (kids == nullptr) return 0;
    ucapi::Handle kid;
    while ((kid = api.scan(kids)) != nullptr) {
        changed += exclude_leaf_node(api, kid, region, test, reason, excluded,
                                     strict);
    }
    api.release(kids);
    return changed;
}

} // namespace

bool UcapiBackend::functional_target_exists(const std::string& scope,
                                           const std::string& covergroup,
                                           const std::string& target_kind,
                                           const std::string& item) const {
    const UcapiLibrary& api = UcapiLibrary::instance();
    ucapi::Handle metrics = api.iterate(test_, ucapi::kMetrics);
    if (metrics == nullptr) return false;
    ucapi::Handle metric;
    bool found = false;
    while (!found && (metric = api.scan(metrics)) != nullptr) {
        if (!api.is_testbench_metric(metric)) continue;
        ucapi::Handle groups =
            api.qualified_iterate(test_, metric, ucapi::kDefinitions);
        if (groups == nullptr) continue;
        ucapi::Handle group;
        while (!found && (group = api.scan(groups)) != nullptr) {
            ucapi::Handle persistent_group = api.make_persistent(group);
            ucapi::Handle variants = api.qualified_iterate(
                persistent_group, metric, ucapi::kDefinitions);
            if (variants != nullptr) {
                ucapi::Handle variant;
                while (!found && (variant = api.scan(variants)) != nullptr) {
                    ucapi::Handle persistent_variant =
                        api.make_persistent(variant);
                    const std::string full_name = safe_str(
                        api.get_str(persistent_variant, ucapi::kFullName));
                    const bool name_match =
                        full_name == covergroup ||
                        (!scope.empty() &&
                         full_name == scope + "::" + covergroup);
                    if (name_match) {
                        if (target_kind == "covergroup") {
                            found = true;
                        } else {
                            ucapi::Handle kids = api.iterate(
                                persistent_variant, ucapi::kObjects);
                            if (kids != nullptr) {
                                ucapi::Handle kid;
                                while ((kid = api.scan(kids)) != nullptr) {
                                    if (safe_str(api.get_str(kid, ucapi::kName)) ==
                                        item) {
                                        found = true;
                                        break;
                                    }
                                }
                                api.release(kids);
                            }
                        }
                    }
                    api.release(persistent_variant);
                }
                api.release(variants);
            }
            api.release(persistent_group);
        }
        api.release(groups);
    }
    api.release(metrics);
    return found;
}

std::size_t UcapiBackend::exclude_functional(const std::string& scope,
                                             const std::string& covergroup,
                                             const std::string& target_kind,
                                             const std::string& item,
                                             const std::string& reason,
                                             bool excluded) {
    invalidate_caches();
    const UcapiLibrary& api = UcapiLibrary::instance();
    std::size_t changed = 0;
    ucapi::Handle metrics = api.iterate(test_, ucapi::kMetrics);
    if (metrics == nullptr) return 0;
    ucapi::Handle metric;
    while ((metric = api.scan(metrics)) != nullptr) {
        if (!api.is_testbench_metric(metric)) continue;
        ucapi::Handle groups = api.qualified_iterate(test_, metric, ucapi::kDefinitions);
        if (groups == nullptr) continue;
        ucapi::Handle group;
        while ((group = api.scan(groups)) != nullptr) {
            ucapi::Handle persistent_group = api.make_persistent(group);
            ucapi::Handle variants =
                api.qualified_iterate(persistent_group, metric, ucapi::kDefinitions);
            if (variants != nullptr) {
                ucapi::Handle variant;
                while ((variant = api.scan(variants)) != nullptr) {
                    ucapi::Handle persistent_variant = api.make_persistent(variant);
                    const std::string full_name = safe_str(
                        api.get_str(persistent_variant, ucapi::kFullName));
                    const bool name_match =
                        full_name == covergroup ||
                        (!scope.empty() &&
                         full_name == scope + "::" + covergroup);
                    if (name_match) {
                        if (target_kind == "covergroup") {
                            changed += exclude_leaf_node(
                                api, persistent_variant, nullptr, test_, reason,
                                excluded, exclusion_policy_ == "strict");
                        } else {
                            ucapi::Handle kids =
                                api.iterate(persistent_variant, ucapi::kObjects);
                            if (kids != nullptr) {
                                ucapi::Handle kid;
                                while ((kid = api.scan(kids)) != nullptr) {
                                    const std::string kid_name = safe_str(
                                        api.get_str(kid, ucapi::kName));
                                    if (kid_name == item) {
                                        changed += exclude_leaf_node(
                                            api, kid, nullptr, test_, reason,
                                            excluded,
                                            exclusion_policy_ == "strict");
                                    }
                                }
                                api.release(kids);
                            }
                        }
                    }
                    api.release(persistent_variant);
                }
                api.release(variants);
            }
            api.release(persistent_group);
        }
        api.release(groups);
    }
    api.release(metrics);
    return changed;
}

void UcapiBackend::save_exclusions(const std::string& path) const {
    const UcapiLibrary& api = UcapiLibrary::instance();
    const int rc = api.save_exclude_file(test_, path.c_str(), "w");
    if (rc != 0) {
        throw Error("EXCLUSION_SAVE_FAILED", "failed to save exclusion file",
                    {{"path", path}, {"returncode", rc < 0 ? 0 : rc}});
    }
}

void UcapiBackend::load_exclusions(const std::string& path) {
    invalidate_caches();
    const UcapiLibrary& api = UcapiLibrary::instance();
    const int rc = api.load_exclude_file(test_, path.c_str());
    if (rc != 0) {
        throw Error("EXCLUSION_LOAD_FAILED", "failed to load exclusion file",
                    {{"path", path}, {"returncode", rc < 0 ? 0 : rc}});
    }
}

void UcapiBackend::unload_exclusions() {
    invalidate_caches();
    const UcapiLibrary& api = UcapiLibrary::instance();
    // UCAPI applies report-time exclusion bits on the test handle; unloading
    // from the design handle silently does nothing.
    if (test_ != nullptr) api.unload_exclusion(test_);
    if (design_ != nullptr) api.unload_exclusion(design_);
}

std::size_t UcapiBackend::excluded_count() const {
    return 0;
}

namespace {

void collect_line_leaves(const UcapiLibrary& api, ucapi::Handle obj,
                         ucapi::Handle region, ucapi::Handle test,
                         const std::string& parent_kind,
                         std::vector<UcapiBackend::LineLeaf>* out) {
    const int type = api.get(obj, region, nullptr, ucapi::kType);
    const std::string name = safe_str(api.get_str(obj, ucapi::kName));
    if (is_leaf_type(type)) {
        UcapiBackend::LineLeaf leaf;
        leaf.name = name;
        leaf.file = safe_str(api.get_str(obj, ucapi::kFileName));
        leaf.line_no = api.get(obj, region, test, ucapi::kLineNo);
        leaf.covered = api.get(obj, region, test, ucapi::kCovered);
        leaf.coverable = api.get(obj, region, test, ucapi::kCoverable);
        leaf.parent_kind = parent_kind;
        out->push_back(leaf);
        return;
    }
    if (type != ucapi::kContainer) return;
    ucapi::Handle kids = api.iterate(obj, ucapi::kObjects);
    if (kids == nullptr) return;
    ucapi::Handle kid;
    while ((kid = api.scan(kids)) != nullptr) {
        collect_line_leaves(api, kid, region, test, name, out);
    }
    api.release(kids);
}

} // namespace

namespace {

void collect_decision_groups(const UcapiLibrary& api, ucapi::Handle obj,
                             ucapi::Handle region, ucapi::Handle test,
                             std::vector<UcapiBackend::DecisionGroup>* out) {
    const int type = api.get(obj, region, test, ucapi::kType);
    if (type == ucapi::kContainer) {
        bool has_arms = false;
        std::vector<UcapiBackend::DecisionArm> arms;
        ucapi::Handle kids = api.iterate(obj, ucapi::kObjects);
        if (kids != nullptr) {
            ucapi::Handle kid;
            while ((kid = api.scan(kids)) != nullptr) {
                const int kid_type = api.get(kid, region, test, ucapi::kType);
                if (kid_type == ucapi::kCrossObj) {
                    has_arms = true;
                    UcapiBackend::DecisionArm arm;
                    arm.pattern = safe_str(api.get_str(kid, ucapi::kName));
                    arm.expression = safe_str(api.get_str(kid, ucapi::kFullName));
                    arm.line_no = api.get(kid, region, test, ucapi::kLineNo);
                    arm.covered = api.get(kid, region, test, ucapi::kCovered);
                    arm.coverable = api.get(kid, region, test, ucapi::kCoverable);
                    arms.push_back(arm);
                }
            }
            api.release(kids);
        }
        if (has_arms) {
            long missing_gaps = 0;
            std::function<void(ucapi::Handle)> count_missing =
                [&](ucapi::Handle node) {
                    const int node_type =
                        api.get(node, region, test, ucapi::kType);
                    if (is_leaf_type(node_type)) {
                        const long covered =
                            api.get(node, region, test, ucapi::kCovered);
                        const long coverable =
                            api.get(node, region, test, ucapi::kCoverable);
                        if (coverable > covered) missing_gaps += coverable - covered;
                        return;
                    }
                    if (node_type != ucapi::kContainer) return;
                    ucapi::Handle nested = api.iterate(node, ucapi::kObjects);
                    if (nested == nullptr) return;
                    ucapi::Handle child;
                    while ((child = api.scan(nested)) != nullptr) {
                        count_missing(child);
                    }
                    api.release(nested);
                };
            for (const auto& arm : arms) {
                (void)arm;
            }
            ucapi::Handle arm_objects = api.iterate(obj, ucapi::kObjects);
            if (arm_objects != nullptr) {
                ucapi::Handle child;
                while ((child = api.scan(arm_objects)) != nullptr) {
                    count_missing(child);
                }
                api.release(arm_objects);
            }
            UcapiBackend::DecisionGroup group;
            group.expression = safe_str(api.get_str(obj, ucapi::kName));
            group.file = safe_str(api.get_str(obj, ucapi::kFileName));
            group.line_no = api.get(obj, region, test, ucapi::kLineNo);
            group.covered = api.get(obj, region, test, ucapi::kCovered);
            group.coverable = api.get(obj, region, test, ucapi::kCoverable);
            group.missing_gaps = missing_gaps;
            group.arms = std::move(arms);
            if (group.missing_gaps > 0) out->push_back(group);
            return;
        }
        ucapi::Handle kids2 = api.iterate(obj, ucapi::kObjects);
        if (kids2 == nullptr) return;
        ucapi::Handle kid;
        while ((kid = api.scan(kids2)) != nullptr) {
            collect_decision_groups(api, kid, region, test, out);
        }
        api.release(kids2);
        return;
    }
}

} // namespace

std::vector<UcapiBackend::DecisionGroup> UcapiBackend::decision_groups(
    const ScopeInfo& scope, const std::string& metric) const {
    const UcapiLibrary& api = UcapiLibrary::instance();
    std::vector<DecisionGroup> out;
    if (scope.handle == nullptr) return out;
    ucapi::Handle metrics = api.iterate(test_, ucapi::kMetrics);
    if (metrics == nullptr) return out;
    ucapi::Handle m;
    while ((m = api.scan(metrics)) != nullptr) {
        const std::string name = safe_str(api.get_str(m, ucapi::kName));
        if (name != metric) continue;
        ucapi::Handle persistent_metric = api.make_persistent(m);
        ucapi::Handle region = api.get_qualified_handle(
            scope.handle, persistent_metric, ucapi::kIdentity);
        if (region != nullptr) {
            ucapi::Handle objects = api.iterate(region, ucapi::kObjects);
            if (objects != nullptr) {
                ucapi::Handle object;
                while ((object = api.scan(objects)) != nullptr) {
                    collect_decision_groups(api, object, region, test_, &out);
                }
                api.release(objects);
            }
            api.release(region);
        }
        api.release(persistent_metric);
    }
    api.release(metrics);
    return out;
}

namespace {

void collect_code_node(const UcapiLibrary& api, ucapi::Handle obj,
                       ucapi::Handle region, ucapi::Handle test,
                       const std::string& metric, const std::string& scope_name,
                       const std::string& parent_path, bool fsm,
                       bool in_transitions, UcapiBackend::CodeScan* scan) {
    const int type = api.get(obj, region, nullptr, ucapi::kType);
    const std::string name = safe_str(api.get_str(obj, ucapi::kName));
    if (is_leaf_type(type)) {
        const bool in_fsm_transitions = !fsm || in_transitions;
        if (in_fsm_transitions) {
            const long covered = api.get(obj, region, test, ucapi::kCovered);
            const long coverable = api.get(obj, region, test, ucapi::kCoverable);
            if (coverable > 0 && covered == 0) {
                UcapiBackend::CodeGap gap;
                gap.name = name;
                gap.full_name = parent_path.empty()
                                    ? scope_name + "." + name
                                    : scope_name + "." + parent_path + "." + name;
                gap.metric = metric;
                gap.coverable = coverable;
                scan->gaps.push_back(gap);
            }
            if (metric == "line") {
                UcapiBackend::LineLeaf leaf;
                leaf.name = name;
                leaf.file = safe_str(api.get_str(obj, ucapi::kFileName));
                leaf.line_no = api.get(obj, region, test, ucapi::kLineNo);
                leaf.covered = covered;
                leaf.coverable = coverable;
                // Line groups only need the immediate construct kind.
                const std::size_t dot = parent_path.rfind('.');
                leaf.parent_kind = dot == std::string::npos
                                       ? parent_path
                                       : parent_path.substr(dot + 1);
                scan->line_leaves.push_back(leaf);
            }
        }
        return;
    }
    if (type != ucapi::kContainer) return;
    const bool now = in_transitions || (fsm && name == "transitions");
    const std::string child_path =
        parent_path.empty() ? name : parent_path + "." + name;
    ucapi::Handle kids = api.iterate(obj, ucapi::kObjects);
    if (kids == nullptr) return;
    ucapi::Handle kid;
    while ((kid = api.scan(kids)) != nullptr) {
        collect_code_node(api, kid, region, test, metric, scope_name, child_path,
                          fsm, now, scan);
    }
    api.release(kids);
}

} // namespace

std::vector<UcapiBackend::LineLeaf> UcapiBackend::line_leaves(
    const ScopeInfo& scope) const {
    const UcapiLibrary& api = UcapiLibrary::instance();
    std::vector<LineLeaf> out;
    if (scope.handle == nullptr) return out;
    ucapi::Handle metrics = api.iterate(test_, ucapi::kMetrics);
    if (metrics == nullptr) return out;
    ucapi::Handle metric;
    while ((metric = api.scan(metrics)) != nullptr) {
        if (!api.is_line_metric(metric)) continue;
        ucapi::Handle persistent_metric = api.make_persistent(metric);
        ucapi::Handle region = api.get_qualified_handle(
            scope.handle, persistent_metric, ucapi::kIdentity);
        if (region != nullptr) {
            ucapi::Handle objects = api.iterate(region, ucapi::kObjects);
            if (objects != nullptr) {
                ucapi::Handle object;
                while ((object = api.scan(objects)) != nullptr) {
                    collect_line_leaves(api, object, region, test_, "",
                                        &out);
                }
                api.release(objects);
            }
            api.release(region);
        }
        api.release(persistent_metric);
    }
    api.release(metrics);
    return out;
}

UcapiBackend::CodeScan UcapiBackend::scan_code(
    const ScopeInfo& scope, const std::set<std::string>& metrics) const {
    const UcapiLibrary& api = UcapiLibrary::instance();
    CodeScan scan;
    if (scope.handle == nullptr) return scan;
    ucapi::Handle metric_list = api.iterate(test_, ucapi::kMetrics);
    if (metric_list == nullptr) return scan;
    ucapi::Handle metric;
    while ((metric = api.scan(metric_list)) != nullptr) {
        std::string key;
        bool fsm = false;
        if (api.is_line_metric(metric)) {
            key = "line";
        } else if (api.is_tgl_metric(metric)) {
            key = "toggle";
        } else {
            const std::string name = safe_str(api.get_str(metric, ucapi::kName));
            if (name == "Branch") key = "branch";
            else if (name == "Condition") key = "condition";
            else if (name == "Fsm") { key = "fsm"; fsm = true; }
        }
        if (key.empty() || metrics.find(key) == metrics.end()) continue;
        ucapi::Handle persistent_metric = api.make_persistent(metric);
        ucapi::Handle raw_region = api.get_qualified_handle(
            scope.handle, persistent_metric, ucapi::kIdentity);
        if (raw_region != nullptr) {
            ucapi::Handle region = api.make_persistent(raw_region);
            api.release(raw_region);
            ucapi::Handle objects = api.iterate(region, ucapi::kObjects);
            if (objects != nullptr) {
                ucapi::Handle object;
                while ((object = api.scan(objects)) != nullptr) {
                    collect_code_node(api, object, region, test_, key,
                                      scope.full_name, "", fsm, false, &scan);
                }
                api.release(objects);
            }
            api.release(region);
        }
        api.release(persistent_metric);
    }
    api.release(metric_list);
    return scan;
}

std::vector<UcapiBackend::CodeGap> UcapiBackend::code_gaps(
    const ScopeInfo& scope) const {
    const UcapiLibrary& api = UcapiLibrary::instance();
    std::vector<CodeGap> out;
    ucapi::Handle metrics = api.iterate(test_, ucapi::kMetrics);
    if (metrics == nullptr) return out;
    ucapi::Handle metric;
    while ((metric = api.scan(metrics)) != nullptr) {
        if (api.is_assert_metric(metric) || api.is_testbench_metric(metric) ||
            api.is_path_metric(metric)) {
            continue;
        }
        const std::string name = safe_str(api.get_str(metric, ucapi::kName));
        MetricKind kind;
        if (api.is_line_metric(metric)) kind = MetricKind::Line;
        else if (api.is_tgl_metric(metric)) kind = MetricKind::Toggle;
        else if (name == "Branch") kind = MetricKind::Branch;
        else if (name == "Condition") kind = MetricKind::Condition;
        else if (name == "Fsm") kind = MetricKind::Fsm;
        else continue;
        ucapi::Handle persistent_metric = api.make_persistent(metric);
        ucapi::Handle region = scope.handle == nullptr
            ? nullptr
            : api.get_qualified_handle(scope.handle, persistent_metric,
                                       ucapi::kIdentity);
        if (region == nullptr) {
            api.release(persistent_metric);
            continue;
        }
        ucapi::Handle objects = api.iterate(region, ucapi::kObjects);
        if (objects != nullptr) {
            ucapi::Handle object;
            while ((object = api.scan(objects)) != nullptr) {
                collect_leaf_gaps(api, object, region, test_, metric_key(kind),
                                  scope.full_name, &out,
                                  kind == MetricKind::Fsm, false);
            }
            api.release(objects);
        }
        api.release(region);
        api.release(persistent_metric);
    }
    api.release(metrics);
    return out;
}

nlohmann::json UcapiBackend::summary() const {
    nlohmann::json data = nlohmann::json::object();
    data["test_count"] = test_names_.size();
    data["top_scope_count"] = top_scopes_.size();
    return data;
}

std::vector<std::string> UcapiBackend::top_scopes() const {
    return top_scopes_;
}

const ScopeInfo* UcapiBackend::find_scope(const std::string& full_name) const {
    auto pos = scope_positions_.find(full_name);
    if (pos == scope_positions_.end()) return nullptr;
    return &scopes_[pos->second];
}

std::map<MetricKind, MetricAggregate> UcapiBackend::scope_metrics(
    const ScopeInfo& scope) const {
    return scope.deep_metrics;
}

std::vector<const ScopeInfo*> UcapiBackend::children(
    const std::string& full_name) const {
    std::vector<const ScopeInfo*> out;
    auto it = children_.find(full_name);
    if (it == children_.end()) return out;
    for (const auto& name : it->second) {
        const ScopeInfo* found = find_scope(name);
        if (found != nullptr) out.push_back(found);
    }
    return out;
}

void UcapiBackend::collect_leaf_rows(const ScopeInfo& scope,
                                     nlohmann::json& rows) const {
    const UcapiLibrary& api = UcapiLibrary::instance();
    ucapi::Handle metrics = api.iterate(test_, ucapi::kMetrics);
    if (metrics == nullptr) return;
    ucapi::Handle metric;
    while ((metric = api.scan(metrics)) != nullptr) {
        if (api.is_assert_metric(metric) || api.is_testbench_metric(metric) ||
            api.is_path_metric(metric)) {
            continue;
        }
        const std::string name = safe_str(api.get_str(metric, ucapi::kName));
        MetricKind kind;
        if (api.is_line_metric(metric)) kind = MetricKind::Line;
        else if (api.is_tgl_metric(metric)) kind = MetricKind::Toggle;
        else if (name == "Branch") kind = MetricKind::Branch;
        else if (name == "Condition") kind = MetricKind::Condition;
        else if (name == "Fsm") kind = MetricKind::Fsm;
        else continue;
        if (kind == MetricKind::Fsm) continue;
        ucapi::Handle persistent_metric = api.make_persistent(metric);
        ucapi::Handle region = scope.handle == nullptr
            ? nullptr
            : api.get_qualified_handle(scope.handle, persistent_metric,
                                       ucapi::kIdentity);
        if (region == nullptr) {
            api.release(persistent_metric);
            continue;
        }
        ucapi::Handle objects = api.iterate(region, ucapi::kObjects);
        if (objects != nullptr) {
            ucapi::Handle object;
            while ((object = api.scan(objects)) != nullptr) {
                const int type = api.get(object, region, nullptr, ucapi::kType);
                if (!is_leaf_type(type)) continue;
                nlohmann::json row = nlohmann::json::object();
                row["coverage_kind"] = "code";
                row["metric"] = metric_key(kind);
                row["type"] = coverage_type_for_metric(metric_key(kind));
                row["scope"] = scope.full_name;
                row["name"] = safe_str(api.get_str(object, ucapi::kName));
                row["full_name"] =
                    scope.full_name + "." + row["name"].get<std::string>();
                const long covered = api.get(object, region, test_, ucapi::kCovered);
                const long coverable = api.get(object, region, test_, ucapi::kCoverable);
                row["covered"] = covered;
                row["coverable"] = coverable;
                row["missing"] = coverable > covered ? coverable - covered : 0;
                row["coverage_pct"] =
                    coverable > 0 ? 100.0 * static_cast<double>(covered) /
                                        static_cast<double>(coverable)
                                  : 0.0;
                rows.push_back(row);
            }
            api.release(objects);
        }
        api.release(region);
        api.release(persistent_metric);
    }
    api.release(metrics);
}

nlohmann::json UcapiBackend::items(const std::string& scope,
                                   bool functional_only) const {
    (void)functional_only;
    nlohmann::json rows = nlohmann::json::array();
    const ScopeInfo* found = find_scope(scope);
    if (found != nullptr) collect_leaf_rows(*found, rows);
    return rows;
}

} // namespace xcov
