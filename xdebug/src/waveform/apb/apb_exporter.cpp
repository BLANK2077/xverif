#include "apb_exporter.h"

#include "core/npi/time_contract.h"
#include "core/session/request_deadline.h"
#include "core/value/logic_value.h"
#include "waveform/common/atomic_artifact_publisher.h"

#include <fstream>
#include <map>
#include <set>

namespace xdebug_waveform {
namespace {

std::string rendered_value(const std::string& raw, int width) {
    return xdebug_core::render_logic_value(
        xdebug_core::logic_value_from_fsdb_raw(raw, 'h', width));
}

std::string csv_field(const std::string& value, char separator) {
    if (separator != ',' ||
        value.find_first_of(",\"\r\n") == std::string::npos)
        return value;
    std::string escaped = "\"";
    for (char ch : value) {
        escaped += ch;
        if (ch == '"') escaped += '"';
    }
    return escaped + "\"";
}

Json meta_json(npiFsdbFileHandle fsdb, const ApbExportResult& result,
               const std::string& data_path, const std::string& meta_path,
               std::uint64_t data_bytes) {
    return Json{{"name", result.name},
                {"format", result.format},
                {"requested_range", {{"begin", xdebug_core::format_time(fsdb, result.begin)},
                                      {"end", xdebug_core::format_time(fsdb, result.end)}}},
                {"scanned_range", {{"begin", xdebug_core::format_time(fsdb, result.scan_begin)},
                                    {"end", xdebug_core::format_time(fsdb, result.scan_end)}}},
                {"scanned_transaction_count", result.scanned_transaction_count},
                {"in_range_transaction_count", result.in_range_count},
                {"matched_transaction_count", result.transactions.size()},
                {"matched_write_count", result.write_count},
                {"matched_read_count", result.read_count},
                {"unresolved_filter_count", result.unresolved_filter_count},
                {"sample_count", result.sample_count},
                {"full_scan_count", result.full_scan_count},
                {"analysis_complete", result.analysis_complete},
                {"value_width_complete", result.value_width_complete},
                {"width_diagnostics", result.width_diagnostics},
                {"data_path", data_path},
                {"meta_path", meta_path},
                {"artifact_bytes", data_bytes}};
}

}  // namespace

Json apb_export_transaction_json(npiFsdbFileHandle fsdb,
                                 const ApbTransaction& transaction) {
    return Json{{"time", xdebug_core::format_time(fsdb, transaction.time)},
                {"direction", transaction.is_write ? "write" : "read"},
                {"addr", rendered_value(transaction.addr, transaction.addr_width)},
                {"data", rendered_value(transaction.data, transaction.data_width)},
                {"has_error", transaction.has_error}};
}

void ApbExporter::build(
    const std::string& name, const ApbResult& canonical,
    const Selector& selector, npiFsdbTime begin, npiFsdbTime end,
    ApbExportResult& result) const {
    const std::string format = result.format;
    result = ApbExportResult();
    result.name = name;
    result.format = format;
    result.begin = begin;
    result.end = end;
    result.scan_begin = canonical.diagnostics.scan_begin;
    result.scan_end = canonical.diagnostics.scan_end;
    result.scanned_transaction_count = canonical.all.size();
    result.sample_count = canonical.diagnostics.sample_count;
    result.full_scan_count = canonical.diagnostics.full_scan_count;
    result.analysis_complete = canonical.diagnostics.analysis_complete;
    for (const ApbTransaction* transaction : canonical.all) {
        xdebug_core::request_deadline_checkpoint();
        if (!transaction || transaction->time < begin || transaction->time > end)
            continue;
        ++result.in_range_count;
        const ValueFilterMatch match = selector(*transaction);
        if (match == ValueFilterMatch::Unresolved) {
            ++result.unresolved_filter_count;
            result.analysis_complete = false;
            continue;
        }
        if (match != ValueFilterMatch::Yes) continue;
        result.transactions.push_back(transaction);
        if (transaction->is_write) ++result.write_count;
        else ++result.read_count;
    }
    std::map<std::string, int> observed_widths;
    std::set<std::string> diagnosed;
    auto inspect_width = [&](const std::string& signal,
                             const std::string& role, int width) {
        const std::string key = signal + "\x1f" + role;
        const auto diagnostic = [&](const std::string& reason) {
            const std::string diagnostic_key = key + "\x1f" + reason;
            if (!diagnosed.insert(diagnostic_key).second) return;
            result.width_diagnostics.push_back({
                {"signal", signal.empty() ? Json(nullptr) : Json(signal)},
                {"role", role},
                {"reason", reason},
            });
        };
        if (width <= 0) {
            diagnostic("npi_range_size_unavailable");
            return;
        }
        const auto existing = observed_widths.find(key);
        if (existing == observed_widths.end()) {
            observed_widths[key] = width;
        } else if (existing->second != width) {
            diagnostic("conflicting_signal_widths");
        }
    };
    for (const ApbTransaction* transaction : result.transactions) {
        inspect_width(transaction->addr_signal, "artifact.addr",
                      transaction->addr_width);
        inspect_width(transaction->data_signal, "artifact.data",
                      transaction->data_width);
    }
    result.value_width_complete = result.width_diagnostics.empty();
}

bool ApbExporter::write_files(
    const std::string& output_prefix, npiFsdbFileHandle fsdb,
    const ApbExportResult& result, std::string& data_path,
    std::string& meta_path, std::uint64_t& data_bytes,
    std::string& error) const {
    data_path = output_prefix + (result.format == "csv" ? ".csv" : ".tsv");
    meta_path = output_prefix + ".meta.json";
    const char separator = result.format == "csv" ? ',' : '\t';
    std::vector<AtomicArtifact> artifacts;
    artifacts.emplace_back(data_path, [&](std::ostream& out, std::string&) {
        out << "time" << separator << "direction" << separator << "addr"
            << separator << "data" << separator << "has_error\n";
        for (const ApbTransaction* transaction : result.transactions) {
            xdebug_core::request_deadline_checkpoint();
            const Json row = apb_export_transaction_json(fsdb, *transaction);
            out << csv_field(row["time"].get<std::string>(), separator) << separator
                << row["direction"].get<std::string>() << separator
                << csv_field(row["addr"].get<std::string>(), separator) << separator
                << csv_field(row["data"].get<std::string>(), separator) << separator
                << (row["has_error"].get<bool>() ? "true" : "false") << '\n';
        }
        return true;
    });
    artifacts.emplace_back(meta_path, [&](std::ostream& out, std::string&) {
        out << meta_json(fsdb, result, data_path, meta_path,
                         artifacts.front().bytes).dump(2)
            << '\n';
        return true;
    });
    if (!publish_atomic_artifact_set(artifacts, error)) return false;
    data_bytes = artifacts.front().bytes;
    return true;
}

}  // namespace xdebug_waveform
