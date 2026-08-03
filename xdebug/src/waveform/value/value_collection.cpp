#include "value_collection.h"

#include "waveform/apb/apb_config.h"
#include "waveform/axi/axi_config.h"
#include "waveform/list/signal_list.h"
#include "waveform/stream/stream_config.h"
#include "waveform/stream/stream_expr.h"

#include <map>
#include <set>
#include <utility>

namespace xdebug_waveform {
namespace {

class FixedValueCollectionProvider final : public ValueCollectionProvider {
public:
    FixedValueCollectionProvider(
        std::string kind,
        std::string name,
        std::vector<ValueCollectionEntry> entries)
        : ValueCollectionProvider(std::move(kind), std::move(name)) {
        entries_ = std::move(entries);
    }
};

ValueCollectionEntry signal_entry(
    const std::string& key,
    const std::string& path) {
    ValueCollectionEntry entry;
    entry.key = key;
    entry.kind = ValueCollectionEntryKind::Signal;
    entry.path = path;
    entry.dependencies.push_back({key, path});
    return entry;
}

void append_signal(
    std::vector<ValueCollectionEntry>& entries,
    const std::string& key,
    const std::string& path) {
    if (!path.empty()) entries.push_back(signal_entry(key, path));
}

bool append_stream_expression(
    std::vector<ValueCollectionEntry>& entries,
    const StreamConfig& config,
    const std::string& key,
    const std::string& text,
    std::string& error) {
    if (text.empty()) return true;
    std::shared_ptr<StreamExpression> expression(new StreamExpression());
    if (!expression->parse(text, error)) {
        error = key + " expression parse failed: " + error;
        return false;
    }
    ValueCollectionEntry entry;
    entry.key = key;
    entry.kind = ValueCollectionEntryKind::Expression;
    entry.expression = text;
    entry.compiled_expression = expression;
    for (const std::string& alias : expression->signals()) {
        const auto found = config.signals.find(alias);
        if (found == config.signals.end()) {
            error = key + " expression references unknown signal alias: " +
                alias;
            return false;
        }
        entry.dependencies.push_back({alias, found->second});
    }
    entries.push_back(std::move(entry));
    return true;
}

} // namespace

ValueCollectionProvider::ValueCollectionProvider(
    std::string kind,
    std::string name)
    : kind_(std::move(kind)),
      name_(std::move(name)) {}

std::unique_ptr<ValueCollectionProvider> make_signal_value_collection(
    const std::string& signal) {
    std::vector<ValueCollectionEntry> entries;
    entries.push_back(signal_entry(signal, signal));
    return std::unique_ptr<ValueCollectionProvider>(
        new FixedValueCollectionProvider(
            "signal", signal, std::move(entries)));
}

std::unique_ptr<ValueCollectionProvider> make_list_value_collection(
    const SignalList& list) {
    std::vector<ValueCollectionEntry> entries;
    for (const std::string& signal : list.signals) {
        entries.push_back(signal_entry(signal, signal));
    }
    return std::unique_ptr<ValueCollectionProvider>(
        new FixedValueCollectionProvider(
            "list", list.name, std::move(entries)));
}

std::unique_ptr<ValueCollectionProvider> make_apb_value_collection(
    const ApbConfig& config) {
    std::vector<ValueCollectionEntry> entries;
    append_signal(entries, "clock", config.clock_sample.clock);
    append_signal(entries, "reset", config.reset.signal);
    append_signal(entries, "paddr", config.paddr);
    append_signal(entries, "psel", config.psel);
    append_signal(entries, "penable", config.penable);
    append_signal(entries, "pwrite", config.pwrite);
    append_signal(entries, "pwdata", config.pwdata);
    append_signal(entries, "prdata", config.prdata);
    append_signal(entries, "pready", config.pready);
    append_signal(entries, "pslverr", config.pslverr);
    return std::unique_ptr<ValueCollectionProvider>(
        new FixedValueCollectionProvider(
            "apb", config.name, std::move(entries)));
}

std::unique_ptr<ValueCollectionProvider> make_axi_value_collection(
    const AxiConfig& config) {
    std::vector<ValueCollectionEntry> entries;
    append_signal(entries, "clock", config.clock_sample.clock);
    append_signal(entries, "reset", config.reset.signal);
    append_signal(entries, "aw.addr", config.awaddr);
    append_signal(entries, "aw.id", config.awid);
    append_signal(entries, "aw.len", config.awlen);
    append_signal(entries, "aw.size", config.awsize);
    append_signal(entries, "aw.burst", config.awburst);
    append_signal(entries, "aw.valid", config.awvalid);
    append_signal(entries, "aw.ready", config.awready);
    append_signal(entries, "w.data", config.wdata);
    append_signal(entries, "w.strb", config.wstrb);
    append_signal(entries, "w.last", config.wlast);
    append_signal(entries, "w.valid", config.wvalid);
    append_signal(entries, "w.ready", config.wready);
    append_signal(entries, "b.id", config.bid);
    append_signal(entries, "b.resp", config.bresp);
    append_signal(entries, "b.valid", config.bvalid);
    append_signal(entries, "b.ready", config.bready);
    append_signal(entries, "ar.addr", config.araddr);
    append_signal(entries, "ar.id", config.arid);
    append_signal(entries, "ar.len", config.arlen);
    append_signal(entries, "ar.size", config.arsize);
    append_signal(entries, "ar.burst", config.arburst);
    append_signal(entries, "ar.valid", config.arvalid);
    append_signal(entries, "ar.ready", config.arready);
    append_signal(entries, "r.id", config.rid);
    append_signal(entries, "r.data", config.rdata);
    append_signal(entries, "r.resp", config.rresp);
    append_signal(entries, "r.last", config.rlast);
    append_signal(entries, "r.valid", config.rvalid);
    append_signal(entries, "r.ready", config.rready);
    return std::unique_ptr<ValueCollectionProvider>(
        new FixedValueCollectionProvider(
            "axi", config.name, std::move(entries)));
}

std::unique_ptr<ValueCollectionProvider> make_stream_value_collection(
    const StreamConfig& config,
    std::string& error) {
    std::vector<ValueCollectionEntry> entries;
    if (!append_stream_expression(
            entries, config, "semantic.clock",
            config.clock_sample.clock, error)) {
        return nullptr;
    }
    if (config.has_reset) {
        append_signal(entries, "semantic.reset", config.reset.signal);
    }
    if (!append_stream_expression(
            entries, config, "semantic.vld", config.vld, error) ||
        !append_stream_expression(
            entries, config, "semantic.rdy", config.rdy, error) ||
        !append_stream_expression(
            entries, config, "semantic.bp", config.bp, error) ||
        !append_stream_expression(
            entries, config, "semantic.sop", config.sop, error) ||
        !append_stream_expression(
            entries, config, "semantic.eop", config.eop, error) ||
        !append_stream_expression(
            entries, config, "semantic.data", config.data, error) ||
        !append_stream_expression(
            entries, config, "semantic.channel_id",
            config.channel_id, error)) {
        return nullptr;
    }
    for (const auto& field : config.packet_stable_fields) {
        if (!append_stream_expression(
                entries,
                config,
                "packet_stable_fields." + field.first,
                field.second,
                error)) {
            return nullptr;
        }
    }
    for (const auto& field : config.beat_fields) {
        if (!append_stream_expression(
                entries,
                config,
                "beat_fields." + field.first,
                field.second,
                error)) {
            return nullptr;
        }
    }
    for (const auto& signal : config.signals) {
        append_signal(
            entries, "signals." + signal.first, signal.second);
    }
    return std::unique_ptr<ValueCollectionProvider>(
        new FixedValueCollectionProvider(
            "stream", config.name, std::move(entries)));
}

Json value_collection_entry_json(const ValueCollectionEntry& entry) {
    Json out = {
        {"key", entry.key},
        {"kind",
         entry.kind == ValueCollectionEntryKind::Signal
             ? "signal" : "expression"},
    };
    if (entry.kind == ValueCollectionEntryKind::Signal) {
        out["path"] = entry.path;
    } else {
        out["expression"] = entry.expression;
        out["dependencies"] = Json::array();
        for (const auto& dependency : entry.dependencies) {
            out["dependencies"].push_back(dependency.alias);
        }
    }
    return out;
}

} // namespace xdebug_waveform
