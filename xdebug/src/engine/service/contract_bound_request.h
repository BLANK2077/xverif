#pragma once

#include "json.hpp"

#include <map>
#include <set>
#include <string>
#include <type_traits>
#include <utility>
#include <vector>

namespace xdebug_design {

using ContractJson = nlohmann::ordered_json;

class ContractBoundRequest;

class ContractJsonView {
public:
    ContractJsonView();

    bool exists() const;
    bool is_null() const;
    bool is_object() const;
    bool is_array() const;
    bool is_string() const;
    bool is_boolean() const;
    bool is_number_integer() const;
    bool empty() const;
    size_t size() const;

    bool contains(const std::string& key) const;
    ContractJsonView operator[](const std::string& key) const;
    ContractJsonView operator[](size_t index) const;

    template <typename ValueType>
    ValueType get() const {
        using Decayed = typename std::decay<ValueType>::type;
        static_assert(
            !std::is_same<Decayed, ContractJson>::value,
            "JSON objects and arrays require consume_subtree(consumer_id)");
        consume_scalar();
        return value_->template get<ValueType>();
    }

    template <typename ValueType>
    ValueType value(
        const std::string& key,
        const ValueType& default_value) const {
        using Decayed = typename std::decay<ValueType>::type;
        static_assert(
            !std::is_same<Decayed, ContractJson>::value,
            "JSON objects and arrays require consume_subtree(consumer_id)");
        ContractJsonView item = (*this)[key];
        return item.exists()
            ? item.template get<ValueType>()
            : default_value;
    }

    std::string value(
        const std::string& key,
        const char* default_value) const;

    // This is the only escape hatch from the tracked view to a raw JSON
    // subtree.  It must name the typed parser/domain consumer taking
    // ownership of every provided descendant leaf.
    ContractJson consume_subtree(
        const std::string& consumer_id) const;
    void consume(const std::string& consumer_id) const;

    const std::string& path() const { return path_; }

private:
    friend class ContractBoundRequest;

    ContractJsonView(
        const ContractJson* value,
        ContractBoundRequest* owner,
        std::string path);

    void consume_scalar() const;

    const ContractJson* value_;
    ContractBoundRequest* owner_;
    std::string path_;
};

class ContractBoundRequest {
public:
    ContractBoundRequest(
        const ContractJson& request,
        std::string action,
        bool track_limits = false);
    ContractBoundRequest(
        const ContractJson& request,
        std::string action,
        bool track_args,
        bool track_target,
        bool track_limits);

    ContractJsonView args();
    ContractJsonView target();
    ContractJsonView limits();
    ContractJson consume_args_request(
        const std::string& consumer_id);
    void consume_target(
        const std::string& consumer_id);

    const std::string& action() const { return action_; }
    std::vector<std::string> unconsumed_paths() const;
    const std::map<std::string, std::string>& consumers() const {
        return consumed_by_;
    }

private:
    friend class ContractJsonView;

    static void collect_leaf_paths(
        const ContractJson& value,
        const std::string& path,
        std::set<std::string>& paths);
    void consume_scalar_path(const std::string& path);
    void consume_subtree_path(
        const std::string& path,
        const std::string& consumer_id);

    const ContractJson& request_;
    std::string action_;
    std::set<std::string> provided_leaves_;
    std::set<std::string> consumed_leaves_;
    std::map<std::string, std::string> consumed_by_;
};

}  // namespace xdebug_design
