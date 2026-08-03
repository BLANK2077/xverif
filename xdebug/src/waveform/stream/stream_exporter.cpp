#include "stream_exporter.h"

#include <fstream>
#include <sys/stat.h>

namespace xdebug_waveform {

std::string format_time(npiFsdbTime t);

namespace {

char sep_for(const std::string& format) {
    return format == "csv" ? ',' : '\t';
}

std::string cell(const StreamValue& value) {
    return stream_value_hex(value);
}

bool ensure_parent_dir(const std::string& path) {
    size_t slash = path.find_last_of('/');
    if (slash == std::string::npos) return true;
    std::string dir = path.substr(0, slash);
    if (dir.empty()) return true;
    std::string cur;
    if (dir[0] == '/') cur = "/";
    size_t pos = dir[0] == '/' ? 1 : 0;
    while (pos <= dir.size()) {
        size_t next = dir.find('/', pos);
        std::string part = dir.substr(pos, next == std::string::npos ? std::string::npos : next - pos);
        if (!part.empty()) {
            if (!cur.empty() && cur[cur.size() - 1] != '/') cur += "/";
            cur += part;
            mkdir(cur.c_str(), 0700);
        }
        if (next == std::string::npos) break;
        pos = next + 1;
    }
    return true;
}

bool write_meta(const std::string& output_file,
                const StreamConfig& config,
                const StreamAnalysis& analysis,
                const std::string& kind,
                std::string& meta_file,
                std::string& error) {
    meta_file = output_file + ".meta.json";
    Json meta;
    meta["stream"] = config.name;
    meta["kind"] = kind;
    meta["sampling_mode"] = "clock_edge";
    meta["clock"] = config.clock_sample.clock;
    meta["edge"] = clock_edge_kind_text(config.clock_sample.edge);
    if (config.clock_sample.edge != ClockEdgeKind::Negedge)
        meta["sample_point"] = clock_sample_point_text(config.clock_sample.sample_point);
    meta["sample_time_semantics"] = "time is sample_time";
    meta["handshake"] = stream_handshake_text(config);
    meta["packet_enabled"] = stream_packet_enabled(config);
    meta["row_count"] = kind == "packet" ? analysis.packets.size() : analysis.transfers.size();
    meta["summary"] = stream_summary_json(config, analysis);
    meta["fields"] = Json::array();
    if (!config.data.empty()) meta["fields"].push_back(Json{{"name", "data"}, {"expr", config.data}});
    for (const auto& kv : config.beat_fields) {
        meta["fields"].push_back(Json{{"name", kv.first}, {"expr", kv.second}, {"scope", "beat"}});
    }
    for (const auto& kv : config.packet_stable_fields) {
        meta["fields"].push_back(Json{{"name", kv.first}, {"expr", kv.second}, {"scope", "packet_stable"}});
    }
    std::ofstream out(meta_file.c_str());
    if (!out) {
        error = "failed to write meta file: " + meta_file;
        return false;
    }
    out << meta.dump(2) << "\n";
    return true;
}

} // namespace

bool StreamExporter::export_transfer_file(const std::string& output_file,
                                          const std::string& format,
                                          const StreamConfig& config,
                                          const StreamAnalysis& analysis,
                                          std::string& meta_file,
                                          std::string& error) {
    ensure_parent_dir(output_file);
    std::ofstream out(output_file.c_str());
    if (!out) {
        error = "failed to write output file: " + output_file;
        return false;
    }
    char sep = sep_for(format);
    out << "cycle" << sep << "time" << sep << "transfer" << sep << "stall" << sep
        << "vld" << sep << "rdy" << sep << "bp" << sep << "sop" << sep << "eop";
    if (!config.channel_id.empty()) out << sep << "channel_id";
    if (!config.data.empty()) out << sep << "data";
    for (const auto& kv : config.beat_fields) out << sep << kv.first;
    for (const auto& kv : config.packet_stable_fields) out << sep << "packet_stable_" << kv.first;
    out << "\n";
    for (const auto& row : analysis.transfers) {
        out << row.cycle << sep << format_time(row.time) << sep
            << (row.transfer ? 1 : 0) << sep << (row.stall ? 1 : 0) << sep
            << (row.vld ? 1 : 0) << sep << (row.rdy ? 1 : 0) << sep << (row.bp ? 1 : 0) << sep
            << (row.sop ? 1 : 0) << sep << (row.eop ? 1 : 0);
        if (!config.channel_id.empty()) out << sep << cell(row.channel);
        if (!config.data.empty()) out << sep << cell(row.fields.at("data"));
        for (const auto& kv : config.beat_fields) {
            auto it = row.fields.find(kv.first);
            out << sep << (it == row.fields.end() ? "" : cell(it->second));
        }
        for (const auto& kv : config.packet_stable_fields) {
            auto it = row.packet_stable_fields.find(kv.first);
            out << sep << (it == row.packet_stable_fields.end() ? "" : cell(it->second));
        }
        out << "\n";
    }
    return write_meta(output_file, config, analysis, "transfer", meta_file, error);
}

bool StreamExporter::export_packet_file(const std::string& output_file,
                                        const std::string& format,
                                        const StreamConfig& config,
                                        const StreamAnalysis& analysis,
                                        std::string& meta_file,
                                        std::string& error) {
    ensure_parent_dir(output_file);
    std::ofstream out(output_file.c_str());
    if (!out) {
        error = "failed to write output file: " + output_file;
        return false;
    }
    char sep = sep_for(format);
    out << "packet_index" << sep << "channel_id" << sep << "start_time" << sep << "end_time" << sep
        << "start_cycle" << sep << "end_cycle" << sep << "beat_count" << sep << "partial" << sep
        << "packet_stable_mismatch_count";
    for (const auto& kv : config.packet_stable_fields) out << sep << "packet_stable_" << kv.first;
    for (const auto& kv : config.beat_fields) out << sep << "first_" << kv.first << sep << "last_" << kv.first;
    if (!config.data.empty()) out << sep << "first_data" << sep << "last_data";
    out << "\n";
    for (const auto& packet : analysis.packets) {
        out << packet.packet_index << sep << (packet.channel.bits.empty() ? "" : cell(packet.channel))
            << sep << format_time(packet.start_time) << sep << format_time(packet.end_time)
            << sep << packet.start_cycle << sep << packet.end_cycle << sep << packet.beat_count << sep
            << ((packet.partial_begin || packet.partial_end) ? "true" : "false") << sep
            << packet.packet_stable_mismatches.size();
        for (const auto& kv : config.packet_stable_fields) {
            auto it = packet.packet_stable_fields.find(kv.first);
            out << sep << (it == packet.packet_stable_fields.end() ? "" : cell(it->second));
        }
        for (const auto& kv : config.beat_fields) {
            auto f = packet.first_fields.find(kv.first);
            auto l = packet.last_fields.find(kv.first);
            out << sep << (f == packet.first_fields.end() ? "" : cell(f->second))
                << sep << (l == packet.last_fields.end() ? "" : cell(l->second));
        }
        if (!config.data.empty()) {
            auto f = packet.first_fields.find("data");
            auto l = packet.last_fields.find("data");
            out << sep << (f == packet.first_fields.end() ? "" : cell(f->second))
                << sep << (l == packet.last_fields.end() ? "" : cell(l->second));
        }
        out << "\n";
    }
    return write_meta(output_file, config, analysis, "packet", meta_file, error);
}

bool StreamExporter::export_packet_beats_file(const std::string& output_file,
                                              const std::string& format,
                                              const StreamConfig& config,
                                              const StreamAnalysis& analysis,
                                              std::string& meta_file,
                                              std::string& error) {
    ensure_parent_dir(output_file);
    std::ofstream out(output_file.c_str());
    if (!out) {
        error = "failed to write output file: " + output_file;
        return false;
    }
    char sep = sep_for(format);
    out << "packet_index" << sep << "channel_id" << sep << "beat_index" << sep
        << "cycle" << sep << "time";
    if (!config.data.empty()) out << sep << "data";
    for (const auto& kv : config.beat_fields) out << sep << kv.first;
    for (const auto& kv : config.packet_stable_fields) out << sep << "packet_stable_" << kv.first;
    out << "\n";
    for (const auto& packet : analysis.packets) {
        for (const auto& beat : packet.beats) {
            out << packet.packet_index << sep << (packet.channel.bits.empty() ? "" : cell(packet.channel))
                << sep << beat.beat_index << sep << beat.cycle << sep << format_time(beat.time);
            if (!config.data.empty()) {
                auto it = beat.fields.find("data");
                out << sep << (it == beat.fields.end() ? "" : cell(it->second));
            }
            for (const auto& kv : config.beat_fields) {
                auto it = beat.fields.find(kv.first);
                out << sep << (it == beat.fields.end() ? "" : cell(it->second));
            }
            for (const auto& kv : config.packet_stable_fields) {
                auto it = packet.packet_stable_fields.find(kv.first);
                out << sep << (it == packet.packet_stable_fields.end() ? "" : cell(it->second));
            }
            out << "\n";
        }
    }
    return write_meta(output_file, config, analysis, "packet_beats", meta_file, error);
}

} // namespace xdebug_waveform
