#include "axi_exporter.h"
#include "waveform/common/atomic_artifact_publisher.h"

#include <algorithm>
#include <sstream>

namespace xdebug_waveform {

std::string format_time(npiFsdbTime t);
std::string format_duration(npiFsdbTime t);

namespace {

bool in_window(npiFsdbTime time, npiFsdbTime begin, npiFsdbTime end) {
    return time >= begin && time <= end;
}

bool txn_less(const AxiExportTransaction& lhs, const AxiExportTransaction& rhs) {
    if (lhs.completion_time != rhs.completion_time)
        return lhs.completion_time < rhs.completion_time;
    if (lhs.addr_time != rhs.addr_time) return lhs.addr_time < rhs.addr_time;
    return lhs.seq < rhs.seq;
}

char sep_for(const std::string& format) {
    return format == "csv" ? ',' : '\t';
}

std::string sv_hex(const std::string& value) {
    return "'h" + value;
}

void write_header(std::ostream& out, char sep) {
    out << "seq" << sep << "completion_time" << sep << "addr_time" << sep
        << "first_data_time" << sep << "last_data_time" << sep << "latency" << sep
        << "phase_order" << sep << "response_dependency_violation" << sep
        << "id" << sep << "addr" << sep << "len" << sep << "size" << sep
        << "burst" << sep << "resp" << sep << "beat_count" << sep
        << "expected_beat_count" << "\n";
}

void write_txn(std::ostream& out, char sep, const AxiExportTransaction& txn) {
    npiFsdbTime latency = txn.completion_time >= txn.addr_time
        ? txn.completion_time - txn.addr_time : 0;
    out << txn.seq << sep << format_time(txn.completion_time) << sep
        << format_time(txn.addr_time) << sep << format_time(txn.first_data_time) << sep
        << format_time(txn.last_data_time) << sep << format_duration(latency) << sep
        << txn.phase_order << sep << (txn.response_dependency_violation ? "true" : "false") << sep
        << sv_hex(txn.id) << sep << sv_hex(txn.addr) << sep << sv_hex(txn.len) << sep
        << sv_hex(txn.size) << sep << sv_hex(txn.burst) << sep << sv_hex(txn.resp) << sep
        << txn.beat_count << sep << txn.expected_beat_count << "\n";
}

Json map_to_json(const std::map<std::string, int>& values) {
    Json out = Json::object();
    for (const auto& item : values) out[sv_hex(item.first)] = item.second;
    return out;
}

Json ids_json(const std::map<std::string, int>& counts) {
    Json out = Json::array();
    for (const auto& item : counts) out.push_back(sv_hex(item.first));
    return out;
}

AxiExportTransaction export_txn(const AxiTransaction& txn) {
    AxiExportTransaction out;
    out.seq = txn.seq;
    out.is_write = txn.is_write;
    out.addr_time = txn.addr_time;
    out.first_data_time = txn.first_data_time;
    out.last_data_time = txn.last_data_time;
    out.completion_time = txn.resp_time;
    out.id = txn.id;
    out.addr = txn.addr;
    out.len = txn.len;
    out.size = txn.size;
    out.burst = txn.burst;
    out.resp = txn.resp;
    out.beat_count = txn.data.size();
    out.expected_beat_count = txn.expected_beat_count;
    out.phase_order = txn.phase_order;
    out.response_dependency_violation = txn.response_dependency_violation;
    return out;
}

} // namespace

void AxiExporter::build(const AxiResult& canonical,
                        const AxiConfig& config,
                        npiFsdbTime begin,
                        npiFsdbTime end,
                        AxiExportResult& result) const {
    const std::string format = result.format;
    result = AxiExportResult();
    result.format = format;
    result.name = config.name;
    result.begin = begin;
    result.end = end;
    result.scan_begin = canonical.diagnostics.scan_begin;
    result.scan_end = canonical.diagnostics.scan_end;
    result.sample_count = canonical.diagnostics.sample_count;
    result.full_scan_count = canonical.diagnostics.full_scan_count;
    result.analysis_complete = canonical.diagnostics.analysis_complete;
    result.beat_count_mismatch_count = canonical.diagnostics.beat_count_mismatch_count;
    result.incomplete_write_count = canonical.diagnostics.incomplete_write_count;
    result.incomplete_read_count = canonical.diagnostics.incomplete_read_count;
    result.reset_cleared_write_count = canonical.diagnostics.reset_cleared_write_count;
    result.reset_cleared_read_count = canonical.diagnostics.reset_cleared_read_count;
    result.orphan_b_count = canonical.diagnostics.orphan_b_count;
    result.orphan_r_beat_count = canonical.diagnostics.orphan_r_beat_count;
    result.buffered_w_beat_count = canonical.diagnostics.buffered_w_beat_count;
    result.buffered_w_burst_count = canonical.diagnostics.buffered_w_burst_count;
    result.orphan_w_beat_count = canonical.diagnostics.orphan_w_beat_count;
    result.response_dependency_violation_count =
        canonical.diagnostics.response_dependency_violation_count;
    result.max_total_write_outstanding =
        canonical.diagnostics.max_total_write_outstanding;
    result.max_total_read_outstanding =
        canonical.diagnostics.max_total_read_outstanding;
    result.max_write_outstanding_by_id =
        canonical.diagnostics.max_write_outstanding_by_id;
    result.max_read_outstanding_by_id =
        canonical.diagnostics.max_read_outstanding_by_id;

    for (const auto& txn : canonical.writes) {
        if (!in_window(txn.resp_time, begin, end)) continue;
        AxiExportTransaction item = export_txn(txn);
        result.writes.push_back(item);
        ++result.write_count_by_id[item.id];
        ++result.burst_histogram[item.burst];
    }
    for (const auto& txn : canonical.reads) {
        if (!in_window(txn.resp_time, begin, end)) continue;
        AxiExportTransaction item = export_txn(txn);
        result.reads.push_back(item);
        ++result.read_count_by_id[item.id];
        ++result.burst_histogram[item.burst];
    }
    std::sort(result.writes.begin(), result.writes.end(), txn_less);
    std::sort(result.reads.begin(), result.reads.end(), txn_less);
}

bool AxiExporter::write_files(const std::string& output_prefix,
                              const AxiExportResult& result,
                              std::string& write_file,
                              std::string& read_file,
                              std::string& meta_file,
                              std::string& error) const {
    std::string suffix = result.format == "csv" ? ".csv" : ".tsv";
    write_file = output_prefix + ".write" + suffix;
    read_file = output_prefix + ".read" + suffix;
    meta_file = output_prefix + ".meta.json";
    char sep = sep_for(result.format);
    std::vector<AtomicArtifact> artifacts;
    artifacts.emplace_back(write_file, [&](std::ostream& out, std::string&) {
        write_header(out, sep);
        for (const auto& txn : result.writes) write_txn(out, sep, txn);
        return true;
    });
    artifacts.emplace_back(read_file, [&](std::ostream& out, std::string&) {
        write_header(out, sep);
        for (const auto& txn : result.reads) write_txn(out, sep, txn);
        return true;
    });
    artifacts.emplace_back(meta_file, [&](std::ostream& out, std::string&) {
        out << axi_export_meta_json(result, write_file, read_file, meta_file).dump(2) << "\n";
        return true;
    });
    return publish_atomic_artifact_set(artifacts, error);
}

Json axi_export_meta_json(const AxiExportResult& result,
                          const std::string& write_file,
                          const std::string& read_file,
                          const std::string& meta_file) {
    Json meta;
    meta["name"] = result.name;
    meta["format"] = result.format;
    meta["begin"] = format_time(result.begin);
    meta["end"] = format_time(result.end);
    meta["scan_begin"] = format_time(result.scan_begin);
    meta["scan_end"] = format_time(result.scan_end);
    meta["sample_count"] = result.sample_count;
    meta["full_scan_count"] = result.full_scan_count;
    meta["analysis_complete"] = result.analysis_complete;
    meta["write_file"] = write_file;
    meta["read_file"] = read_file;
    meta["meta_file"] = meta_file;
    meta["write_count"] = result.writes.size();
    meta["read_count"] = result.reads.size();
    meta["total_count"] = result.writes.size() + result.reads.size();
    meta["unique_write_ids"] = ids_json(result.write_count_by_id);
    meta["unique_read_ids"] = ids_json(result.read_count_by_id);
    meta["write_count_by_id"] = map_to_json(result.write_count_by_id);
    meta["read_count_by_id"] = map_to_json(result.read_count_by_id);
    meta["max_write_outstanding_by_id"] = map_to_json(result.max_write_outstanding_by_id);
    meta["max_read_outstanding_by_id"] = map_to_json(result.max_read_outstanding_by_id);
    meta["max_total_write_outstanding"] = result.max_total_write_outstanding;
    meta["max_total_read_outstanding"] = result.max_total_read_outstanding;
    meta["burst_histogram"] = map_to_json(result.burst_histogram);
    meta["beat_count_mismatch_count"] = result.beat_count_mismatch_count;
    meta["incomplete_write_count"] = result.incomplete_write_count;
    meta["incomplete_read_count"] = result.incomplete_read_count;
    meta["buffered_w_beat_count"] = result.buffered_w_beat_count;
    meta["buffered_w_burst_count"] = result.buffered_w_burst_count;
    meta["orphan_w_beat_count"] = result.orphan_w_beat_count;
    meta["orphan_b_count"] = result.orphan_b_count;
    meta["orphan_r_beat_count"] = result.orphan_r_beat_count;
    meta["response_dependency_violation_count"] = result.response_dependency_violation_count;
    meta["reset_cleared_write_count"] = result.reset_cleared_write_count;
    meta["reset_cleared_read_count"] = result.reset_cleared_read_count;
    return meta;
}

} // namespace xdebug_waveform
