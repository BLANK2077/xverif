#pragma once

#include "json.hpp"

#include <memory>
#include <string>
#include <utility>
#include <vector>

namespace xdebug_waveform {

struct ApbConfig;
struct AxiConfig;
struct SignalList;
struct StreamConfig;
class StreamExpression;

using Json = nlohmann::ordered_json;

enum class ValueCollectionEntryKind {
    Signal,
    Expression
};

struct ValueCollectionDependency {
    ValueCollectionDependency(
        std::string dependency_alias,
        std::string dependency_path)
        : alias(std::move(dependency_alias)),
          path(std::move(dependency_path)) {}

    std::string alias;
    std::string path;
};

struct ValueCollectionEntry {
    std::string key;
    ValueCollectionEntryKind kind = ValueCollectionEntryKind::Signal;
    std::string path;
    std::string expression;
    std::vector<ValueCollectionDependency> dependencies;
    std::shared_ptr<StreamExpression> compiled_expression;
};

class ValueCollectionProvider {
public:
    virtual ~ValueCollectionProvider() = default;

    const std::string& kind() const { return kind_; }
    const std::string& name() const { return name_; }
    const std::vector<ValueCollectionEntry>& entries() const {
        return entries_;
    }

protected:
    ValueCollectionProvider(std::string kind, std::string name);

    std::string kind_;
    std::string name_;
    std::vector<ValueCollectionEntry> entries_;
};

std::unique_ptr<ValueCollectionProvider> make_signal_value_collection(
    const std::string& signal);
std::unique_ptr<ValueCollectionProvider> make_list_value_collection(
    const SignalList& list);
std::unique_ptr<ValueCollectionProvider> make_apb_value_collection(
    const ApbConfig& config);
std::unique_ptr<ValueCollectionProvider> make_axi_value_collection(
    const AxiConfig& config);
std::unique_ptr<ValueCollectionProvider> make_stream_value_collection(
    const StreamConfig& config,
    std::string& error);

Json value_collection_entry_json(const ValueCollectionEntry& entry);

} // namespace xdebug_waveform
