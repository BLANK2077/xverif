#include "stream_analyzer.h"
#include "core/output/completeness.h"

#include "../cache/analysis_probe.h"
#include "../cache/analysis_size_estimator.h"
#include "../server/fsdb_scan_utils.h"
#include "../server/fsdb_value_reader.h"
#include "core/value/logic_value.h"

#include "npi_fsdb.h"
#include "npi_L1.h"

#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <map>
#include <set>

namespace xdebug_waveform {

std::string format_time(npiFsdbTime t);

namespace {

constexpr std::uint32_t kStreamFingerprintVersion = 1;
const char* kStreamBaseTypeTag = "stream_base_analysis.v1";

void issue(std::vector<StreamValidationIssue>& issues,
           const std::string& severity,
           const std::string& code,
           const std::string& message) {
    issues.push_back(StreamValidationIssue{severity, code, message});
}

std::vector<std::string> sorted_signals(const std::set<std::string>& signals) {
    return std::vector<std::string>(signals.begin(), signals.end());
}

StreamValue x_value() {
    return StreamValue{"x", false};
}

unsigned long long parse_user_u64(const std::string& text, bool& ok, std::string& error) {
    xdebug_core::LogicValue literal =
        xdebug_core::parse_user_logic_literal(text);
    if (!literal.valid) {
        ok = false;
        error = literal.error;
        return 0;
    }
    if (xdebug_core::logic_value_has_xz(literal) ||
        literal.bits.size() > 63) {
        ok = false;
        error = "match value must be a known literal up to 63 bits: " + text;
        return 0;
    }
    unsigned long long out = 0;
    for (char c : literal.bits) {
        out <<= 1ULL;
        if (c == '1') out |= 1ULL;
    }
    ok = true;
    return out;
}

bool value_u64(const StreamValue& value, unsigned long long& out) {
    if (!value.known || value.bits.size() > 63) return false;
    out = 0;
    for (char c : value.bits) {
        out <<= 1ULL;
        if (c == '1') out |= 1ULL;
        else if (c != '0') return false;
    }
    return true;
}

bool stream_value_equal(const StreamValue& a, const StreamValue& b) {
    return a.known == b.known && a.bits == b.bits;
}

ValueFilterMatch match_filter_fields(const std::map<std::string, StreamValue>& fields,
                                     const StreamFilter& filter) {
    ValueFilterMatch combined = ValueFilterMatch::Yes;
    for (const auto& item : filter.fields) {
        auto value = fields.find(item.first);
        if (value == fields.end()) {
            combined = value_filter_and(combined, ValueFilterMatch::Unresolved);
            continue;
        }
        xdebug_core::LogicValue logic =
            xdebug_core::logic_value_from_bits(
                value->second.bits,
                static_cast<int>(value->second.bits.size()));
        const ValueFilterMatch result = match_value_filter(item.second, logic);
        combined = value_filter_and(combined, result);
        if (combined == ValueFilterMatch::No) return combined;
    }
    return combined;
}

std::map<std::string, StreamValue> filter_view(const StreamRow& row) {
    std::map<std::string, StreamValue> fields = row.fields;
    fields.insert(row.packet_stable_fields.begin(), row.packet_stable_fields.end());
    return fields;
}

std::string stream_value_key(const StreamValue& value) {
    return value.bits.empty() ? "<none>" : value.bits;
}

std::string sample_bits_from_raw(std::string text) {
    if (text.size() >= 2 && text[0] == '\'' &&
        (text[1] == 'b' || text[1] == 'B' || text[1] == 'h' || text[1] == 'H' ||
         text[1] == 'd' || text[1] == 'D')) {
        text = text.substr(2);
    }
    std::string bits;
    for (char c : text) {
        if (c == '_' || std::isspace(static_cast<unsigned char>(c))) continue;
        if (c == '0' || c == '1' || c == 'x' || c == 'X' || c == 'z' || c == 'Z') {
            bits.push_back(static_cast<char>(std::tolower(static_cast<unsigned char>(c))));
        }
    }
    return bits.empty() ? "x" : bits;
}

Json fields_json(const std::map<std::string, StreamValue>& fields) {
    Json out = Json::object();
    for (const auto& kv : fields) out[kv.first] = stream_value_json(kv.second);
    return out;
}

Json packet_stable_mismatches_json(const std::vector<StreamPacketStableMismatch>& mismatches) {
    Json arr = Json::array();
    for (const auto& mismatch : mismatches) {
        arr.push_back({{"field", mismatch.field},
                       {"cycle", mismatch.cycle},
                       {"time", format_time(mismatch.time)},
                       {"expected", stream_value_json(mismatch.expected)},
                       {"actual", stream_value_json(mismatch.actual)}});
    }
    return arr;
}

Json beat_json(const StreamBeat& beat) {
    return Json{{"cycle", beat.cycle},
                {"time", format_time(beat.time)},
                {"beat_index", beat.beat_index},
                {"fields", fields_json(beat.fields)}};
}

Json beat_preview_json(const std::vector<StreamBeat>& beats) {
    Json head = Json::array();
    Json tail = Json::array();
    size_t n = beats.size();
    size_t head_count = std::min<size_t>(5, n);
    for (size_t i = 0; i < head_count; ++i) head.push_back(beat_json(beats[i]));
    if (n > 5) {
        size_t tail_start = n > 10 ? n - 5 : 5;
        for (size_t i = tail_start; i < n; ++i) tail.push_back(beat_json(beats[i]));
    }
    Json preview = {{"head", head}, {"tail", tail}};
    xdebug_core::set_completeness(
        preview,
        true,
        true,
        n > 10,
        n,
        head.size() + tail.size(),
        n > 10
            ? std::vector<std::string>{"response_beats"}
            : std::vector<std::string>{});
    return preview;
}

} // namespace

struct StreamAnalyzer::Compiled {
    StreamExpression clock;
    StreamExpression vld;
    StreamExpression rdy;
    StreamExpression bp;
    StreamExpression sop;
    StreamExpression eop;
    StreamExpression data;
    StreamExpression channel;
    std::map<std::string, StreamExpression> packet_stable_fields;
    std::map<std::string, StreamExpression> beat_fields;
    std::set<std::string> deps;
    std::map<std::string, std::string> dep_paths;
};

constexpr const char* kResetDependency = "__xdebug_reset";

bool StreamAnalyzer::compile(npiFsdbFileHandle file, const StreamConfig& config, Compiled& c,
                             std::vector<StreamValidationIssue>* issues, std::string& error) {
    auto parse_one = [&](const std::string& label, const std::string& text, StreamExpression& expr) -> bool {
        if (text.empty()) return true;
        std::string parse_error;
        if (!expr.parse(text, parse_error)) {
            error = label + " expression parse failed: " + parse_error;
            return false;
        }
        for (const auto& sig : expr.signals()) c.deps.insert(sig);
        return true;
    };

    if (!parse_one("clock", config.clock_sample.clock, c.clock)) return false;
    if (!c.clock.is_plain_signal()) {
        if (issues) issue(*issues, "WARNING", "CLOCK_COMPLEX",
            "clock expression is not a plain signal; edge detection uses expression dependency changes");
    }
    if (config.has_reset) {
        c.deps.insert(kResetDependency);
        c.dep_paths[kResetDependency] = config.reset.signal;
    }
    if (!parse_one("vld", config.vld, c.vld)) return false;
    if (!parse_one("rdy", config.rdy, c.rdy)) return false;
    if (!parse_one("bp", config.bp, c.bp)) return false;
    if (!parse_one("sop", config.sop, c.sop)) return false;
    if (!parse_one("eop", config.eop, c.eop)) return false;
    if (!parse_one("data", config.data, c.data)) return false;
    if (!parse_one("channel_id", config.channel_id, c.channel)) return false;
    for (const auto& kv : config.packet_stable_fields) {
        StreamExpression expr;
        if (!parse_one("packet_stable_fields." + kv.first, kv.second, expr)) return false;
        c.packet_stable_fields[kv.first] = std::move(expr);
    }
    for (const auto& kv : config.beat_fields) {
        StreamExpression expr;
        if (!parse_one("beat_fields." + kv.first, kv.second, expr)) return false;
        c.beat_fields[kv.first] = std::move(expr);
    }

    for (const auto& sig : c.deps) {
        if (sig == kResetDependency) {
            npiFsdbSigHandle reset = npi_fsdb_sig_by_name(file, config.reset.signal.c_str(), NULL);
            NPI_INT32 reset_width = 0;
            if (!reset) {
                error = "reset signal not found: " + config.reset.signal;
                return false;
            }
            if (!npi_fsdb_sig_property(npiFsdbSigRangeSize, reset, &reset_width) || reset_width != 1) {
                error = "reset signal must resolve to exactly one bit: " + config.reset.signal;
                return false;
            }
            continue;
        }
        auto alias = config.signals.find(sig);
        if (alias == config.signals.end()) {
            error = "stream " + config.name + " expression references unknown signal alias: " + sig;
            return false;
        }
        c.dep_paths[sig] = alias->second;
        if (!npi_fsdb_sig_by_name(file, alias->second.c_str(), NULL)) {
            error = "signal not found for alias " + sig + ": " + alias->second;
            return false;
        }
    }
    return true;
}

bool StreamAnalyzer::validate_static(npiFsdbFileHandle file, const StreamConfig& config,
                                     std::vector<StreamValidationIssue>& issues,
                                     std::string& error) {
    issues.clear();
    if (!stream_name_valid(config.name)) issue(issues, "ERROR", "INVALID_NAME", "invalid stream name");
    if (config.data.empty() && config.beat_fields.empty() && config.packet_stable_fields.empty())
        issue(issues, "ERROR", "MISSING_DATA", "stream requires data, packet_stable_fields, or beat_fields");
    if ((config.sop.empty()) != (config.eop.empty()))
        issue(issues, "ERROR", "PACKET_PAIR", "sop/eop must be configured together");
    if ((config.channel_id_valid == "sop" || config.channel_id_valid == "eop") && !stream_packet_enabled(config))
        issue(issues, "ERROR", "CHANNEL_VALID_REQUIRES_PACKET", "channel_id_valid=sop/eop requires sop/eop");
    if ((config.channel_id_valid == "sop" || config.channel_id_valid == "eop") && config.channel_id.empty())
        issue(issues, "ERROR", "CHANNEL_VALID_REQUIRES_CHANNEL", "channel_id_valid=sop/eop requires channel_id");
    if (config.allow_interleaving) {
        if (!stream_packet_enabled(config))
            issue(issues, "ERROR", "INTERLEAVING_REQUIRES_PACKET", "allow_interleaving requires sop/eop");
        if (config.channel_id.empty())
            issue(issues, "ERROR", "INTERLEAVING_REQUIRES_CHANNEL", "allow_interleaving requires channel_id");
        if (config.channel_id_valid != "every_beat")
            issue(issues, "ERROR", "INTERLEAVING_REQUIRES_EVERY_BEAT_CHANNEL", "allow_interleaving requires channel_id_valid=every_beat");
    }

    Compiled compiled;
    if (!compile(file, config, compiled, &issues, error)) {
        issue(issues, "ERROR", "COMPILE_FAILED", error);
        return false;
    }
    return true;
}

void StreamAnalyzer::configure_repository(
    AnalysisRepository* repository, const std::string& session_id,
    const FsdbIdentity& fsdb_identity) {
    repository_ = repository;
    session_id_ = session_id;
    fsdb_identity_ = fsdb_identity;
    last_cache_error_ = AnalysisCacheError();
}

AnalysisCacheKey StreamAnalyzer::cache_key(
    const StreamConfig& config, AnalysisCacheScope scope,
    npiFsdbTime begin, npiFsdbTime end) const {
    return make_analysis_cache_key(
        "stream", session_id_, fsdb_identity_, kStreamFingerprintVersion,
        normalized_stream_config_semantics(config), scope, begin, end);
}

bool StreamAnalyzer::build_base(npiFsdbFileHandle file,
                                const StreamConfig& config,
                                const StreamQueryOptions& options,
                                StreamBaseAnalysis& base,
                                std::string& error,
                                const AnalysisCacheKey* build_key) {
    base = StreamBaseAnalysis();
    base.requested_begin = options.begin;
    base.requested_end = options.end;
    ClockSampleSpec clock_sample = config.clock_sample;
    if (!normalize_clock_sample_spec(file, clock_sample, error)) return false;
    Compiled compiled;
    if (!compile(file, config, compiled, nullptr, error)) return false;

    if (!config.data.empty()) base.field_schema.push_back("data");
    for (const auto& item : config.beat_fields) {
        if (std::find(base.field_schema.begin(), base.field_schema.end(),
                      item.first) == base.field_schema.end())
            base.field_schema.push_back(item.first);
    }
    for (const auto& item : config.packet_stable_fields)
        base.packet_stable_field_schema.push_back(item.first);
    for (const auto& name : base.field_schema)
        base.field_columns[name] = std::vector<StreamValue>();
    for (const auto& name : base.packet_stable_field_schema)
        base.packet_stable_field_columns[name] = std::vector<StreamValue>();

    std::vector<std::string> deps = sorted_signals(compiled.deps);
    std::vector<std::string> clock_deps = sorted_signals(compiled.clock.signals());
    if (clock_deps.empty()) {
        error = "clock expression has no signal dependency";
        return false;
    }
    std::vector<ClockSampleSignal> clock_signals;
    for (const auto& sig_name : clock_deps) {
        auto path_it = compiled.dep_paths.find(sig_name);
        if (path_it == compiled.dep_paths.end()) {
            error = "clock dependency alias missing from stream signals: " + sig_name;
            return false;
        }
        npiFsdbSigHandle sig = npi_fsdb_sig_by_name(
            file, path_it->second.c_str(), NULL);
        if (!sig) {
            error = "signal not found for alias " + sig_name + ": " +
                path_it->second;
            return false;
        }
        clock_signals.push_back({sig_name, path_it->second, sig});
    }
    std::vector<ClockSampleSignal> sample_signals;
    for (const auto& sig_name : deps) {
        auto path_it = compiled.dep_paths.find(sig_name);
        if (path_it == compiled.dep_paths.end()) {
            error = "sample dependency alias missing from stream signals: " + sig_name;
            return false;
        }
        npiFsdbSigHandle sig = npi_fsdb_sig_by_name(
            file, path_it->second.c_str(), NULL);
        if (!sig) {
            error = "signal not found for alias " + sig_name + ": " +
                path_it->second;
            return false;
        }
        sample_signals.push_back({sig_name, path_it->second, sig});
    }

    struct PacketBuildState {
        bool active = false;
        std::size_t packet_index = 0;
        std::map<std::string, StreamValue> stable_fields;
    };
    PacketBuildState single_packet;
    std::map<std::string, PacketBuildState> channel_packets;
    auto finish_packet = [&](PacketBuildState& state, bool partial_end) {
        if (!state.active) return;
        base.packets[state.packet_index].partial_end = partial_end;
        state = PacketBuildState();
    };
    auto start_packet = [&](PacketBuildState& state,
                            const std::map<std::string, StreamValue>& stable,
                            const StreamValue& channel,
                            bool partial_begin) {
        if (state.active) finish_packet(state, true);
        state.active = true;
        state.packet_index = base.packets.size();
        state.stable_fields = stable;
        StreamBasePacket packet;
        packet.partial_begin = partial_begin;
        if (config.channel_id_valid == "sop" ||
            config.channel_id_valid == "every_beat") {
            packet.channel = channel;
        }
        base.packets.push_back(std::move(packet));
    };
    auto append_packet = [&](PacketBuildState& state,
                             std::size_t transfer_ordinal,
                             bool eop,
                             const StreamValue& channel,
                             const std::map<std::string, StreamValue>& stable) {
        StreamBasePacket& packet = base.packets[state.packet_index];
        packet.transfer_ordinals.push_back(transfer_ordinal);
        if (config.channel_id_valid == "eop" && eop)
            packet.channel = channel;
        if (config.channel_id_valid == "every_beat" &&
            packet.channel.bits.empty()) packet.channel = channel;
        for (const auto& item : stable) {
            auto expected = state.stable_fields.find(item.first);
            if (expected == state.stable_fields.end()) {
                state.stable_fields[item.first] = item.second;
                continue;
            }
            if (!stream_value_equal(expected->second, item.second)) {
                StreamBaseStableMismatch mismatch;
                mismatch.transfer_ordinal = transfer_ordinal;
                mismatch.field = item.first;
                mismatch.expected = expected->second;
                mismatch.actual = item.second;
                packet.stable_mismatches.push_back(std::move(mismatch));
            }
        }
    };

    ClockExpressionSampleScanner scanner(
        file, clock_sample.edge, clock_sample.sample_point);
    int sample_count = 0;
    bool sample_truncated = false;
    bool budget_failed = false;
    const AnalysisRepositoryStats repository_stats = repository_ == nullptr
        ? AnalysisRepositoryStats() : repository_->stats();
    analysis_probe().record(
        "scan", "stream", config.name,
        AnalysisProbeMetrics{repository_stats.canonical_entry_count,
                             repository_stats.index_count,
                             repository_stats.resident_estimated_bytes,
                             repository_stats.build_estimated_bytes, 1});
    const bool scan_ok = scanner.scan(
        clock_signals, sample_signals, options.begin, options.end,
        npiFsdbBinStrVal, 'b', -1,
        [&](const std::map<std::string, std::string>& raw_values,
            bool& known, bool& one, std::string& eval_error) -> bool {
            std::map<std::string, StreamValue> clock_values;
            for (const auto& sig_name : clock_deps) {
                auto it = raw_values.find(sig_name);
                if (it == raw_values.end()) {
                    eval_error = "clock dependency missing: " + sig_name;
                    return false;
                }
                const std::string bits = sample_bits_from_raw(it->second);
                clock_values[sig_name] = StreamValue{
                    bits, bits.find_first_of("xz") == std::string::npos};
            }
            StreamValue clock_value;
            std::string expr_error;
            if (!compiled.clock.evaluate(
                    clock_values, clock_value, expr_error)) {
                eval_error = "clock evaluate failed: " + expr_error;
                return false;
            }
            known = clock_value.known;
            one = stream_value_truthy(clock_value, false);
            return true;
        },
        [&](const ClockSample& sample) -> bool {
            std::map<std::string, StreamValue> values;
            for (size_t i = 0; i < deps.size(); ++i) {
                const std::string raw = i < sample.values.size()
                    ? sample.values[i] : "'bx";
                const std::string bits = sample_bits_from_raw(raw);
                values[deps[i]] = StreamValue{
                    bits, bits.find_first_of("xz") == std::string::npos};
            }
            auto eval = [&](StreamExpression& expr,
                            const std::string& label) -> StreamValue {
                if (expr.text().empty()) return StreamValue{"0", true};
                StreamValue out;
                std::string eval_error;
                if (!expr.evaluate(values, out, eval_error)) {
                    error = label + " evaluate failed: " + eval_error;
                    return x_value();
                }
                return out;
            };

            StreamValue reset_v{"0", true};
            if (config.has_reset) reset_v = values[kResetDependency];
            const StreamValue vld_v = eval(compiled.vld, "vld");
            if (!error.empty()) return false;
            const StreamValue rdy_v = config.rdy.empty()
                ? StreamValue{"1", true} : eval(compiled.rdy, "rdy");
            if (!error.empty()) return false;
            const StreamValue bp_v = config.bp.empty()
                ? StreamValue{"0", true} : eval(compiled.bp, "bp");
            if (!error.empty()) return false;
            const StreamValue sop_v = config.sop.empty()
                ? StreamValue{"0", true} : eval(compiled.sop, "sop");
            if (!error.empty()) return false;
            const StreamValue eop_v = config.eop.empty()
                ? StreamValue{"0", true} : eval(compiled.eop, "eop");
            if (!error.empty()) return false;

            StreamSampleMetadata metadata;
            metadata.time = sample.time;
            metadata.reset = config.has_reset &&
                reset_is_active(config.reset, reset_v.bits);
            metadata.vld = stream_value_truthy(vld_v, false);
            metadata.rdy = stream_value_truthy(rdy_v, false);
            metadata.bp = stream_value_truthy(bp_v, true);
            metadata.sop = stream_value_truthy(sop_v, false);
            metadata.eop = stream_value_truthy(eop_v, false);
            metadata.control_xz_count =
                (stream_value_has_xz(reset_v) ? 1 : 0) +
                (stream_value_has_xz(vld_v) ? 1 : 0) +
                (stream_value_has_xz(rdy_v) ? 1 : 0) +
                (stream_value_has_xz(bp_v) ? 1 : 0) +
                (stream_value_has_xz(sop_v) ? 1 : 0) +
                (stream_value_has_xz(eop_v) ? 1 : 0);
            bool flow = true;
            if (!config.rdy.empty()) flow = flow && metadata.rdy;
            if (!config.bp.empty()) flow = flow && !metadata.bp;
            metadata.transfer = metadata.vld && flow && !metadata.reset;
            if (!config.rdy.empty() && !config.bp.empty()) {
                metadata.stall = metadata.vld &&
                    (!metadata.rdy || metadata.bp);
                if (!metadata.rdy && metadata.bp)
                    metadata.stall_reason = "rdy_low_and_bp_high";
                else if (!metadata.rdy)
                    metadata.stall_reason = "rdy_low";
                else if (metadata.bp)
                    metadata.stall_reason = "bp_high";
            } else if (!config.rdy.empty()) {
                metadata.stall = metadata.vld && !metadata.rdy;
                if (metadata.stall) metadata.stall_reason = "rdy_low";
            } else if (!config.bp.empty()) {
                metadata.stall = metadata.vld && metadata.bp;
                if (metadata.stall) metadata.stall_reason = "bp_high";
            }

            std::map<std::string, StreamValue> fields;
            std::map<std::string, StreamValue> stable_fields;
            if (!config.data.empty()) {
                fields["data"] = eval(compiled.data, "data");
                if (!error.empty()) return false;
            }
            for (auto& item : compiled.beat_fields) {
                fields[item.first] = eval(
                    item.second, "beat_fields." + item.first);
                if (!error.empty()) return false;
            }
            for (auto& item : compiled.packet_stable_fields) {
                stable_fields[item.first] = eval(
                    item.second, "packet_stable_fields." + item.first);
                if (!error.empty()) return false;
            }
            StreamValue channel;
            if (!config.channel_id.empty()) {
                channel = eval(compiled.channel, "channel_id");
                if (!error.empty()) return false;
            }
            for (const auto& item : fields)
                if (stream_value_has_xz(item.second))
                    ++metadata.data_xz_count;
            for (const auto& item : stable_fields)
                if (stream_value_has_xz(item.second))
                    ++metadata.data_xz_count;

            if (!base.has_scanned_samples) {
                base.scanned_begin = sample.time;
                base.has_scanned_samples = true;
            }
            base.scanned_end = sample.time;
            const std::size_t sample_id = base.samples.size();
            if (metadata.transfer) {
                const std::size_t ordinal =
                    base.transfer_sample_ids.size();
                metadata.transfer_ordinal = static_cast<int>(ordinal);
                base.transfer_sample_ids.push_back(sample_id);
                for (const auto& name : base.field_schema)
                    base.field_columns[name].push_back(fields[name]);
                for (const auto& name : base.packet_stable_field_schema)
                    base.packet_stable_field_columns[name].push_back(
                        stable_fields[name]);
                base.channels.push_back(channel);

                if (stream_packet_enabled(config)) {
                    PacketBuildState* state = &single_packet;
                    if (config.allow_interleaving) {
                        if (channel.bits.empty() ||
                            stream_value_has_xz(channel)) {
                            error = "interleaved packet stream requires known "
                                    "channel_id on every transfer";
                            return false;
                        }
                        state = &channel_packets[stream_value_key(channel)];
                    } else if (config.channel_id_valid == "every_beat" &&
                               single_packet.active &&
                               !base.packets[single_packet.packet_index]
                                    .channel.bits.empty() &&
                               !stream_value_equal(
                                    base.packets[single_packet.packet_index]
                                        .channel,
                                    channel)) {
                        error = "non-interleaved packet channel_id changed "
                                "within a packet";
                        return false;
                    }
                    if (metadata.sop)
                        start_packet(*state, stable_fields, channel, false);
                    else if (!state->active && metadata.eop)
                        start_packet(*state, stable_fields, channel, true);
                    if (state->active) {
                        append_packet(*state, ordinal, metadata.eop,
                                      channel, stable_fields);
                        if (metadata.eop) finish_packet(*state, false);
                    }
                }
            }
            base.samples.push_back(std::move(metadata));
            const std::size_t observed_samples = base.samples.size();
            if (build_key != nullptr &&
                (observed_samples & (observed_samples - 1)) == 0 &&
                !repository_->update_canonical_build_bytes(
                    *build_key,
                    estimate_stream_base_analysis_bytes(base),
                    last_cache_error_)) {
                budget_failed = true;
                error = last_cache_error_.message;
                return false;
            }
            return true;
        }, error, sample_count, sample_truncated);
    if (budget_failed) return false;
    if (!scan_ok) {
        if (build_key == nullptr) {
            analysis_probe().record(
                "build_failed", "stream", config.name,
                AnalysisProbeMetrics{0, 0, 0, 0, 0});
        }
        return false;
    }
    finish_packet(single_packet, true);
    for (auto& item : channel_packets) finish_packet(item.second, true);
    base.analysis_complete = !sample_truncated;
    return true;
}

StreamQueryView::StreamQueryView(const StreamBaseAnalysis& base,
                                 const StreamConfig& config,
                                 const StreamQueryOptions& options)
    : base_(base), config_(config), options_(options) {}

StreamRow StreamQueryView::transfer_row(std::size_t sample_id, int cycle) const {
    StreamRow row;
    if (sample_id >= base_.samples.size()) return row;
    const StreamSampleMetadata& sample = base_.samples[sample_id];
    row.cycle = cycle;
    row.time = sample.time;
    row.reset = sample.reset;
    row.vld = sample.vld;
    row.rdy = sample.rdy;
    row.bp = sample.bp;
    row.sop = sample.sop;
    row.eop = sample.eop;
    row.transfer = sample.transfer;
    row.stall = sample.stall;
    row.stall_reason = sample.stall_reason;
    row.control_xz_count = sample.control_xz_count;
    row.data_xz_count = sample.data_xz_count;
    if (sample.transfer_ordinal < 0) return row;
    const std::size_t ordinal =
        static_cast<std::size_t>(sample.transfer_ordinal);
    for (const auto& name : base_.field_schema) {
        auto column = base_.field_columns.find(name);
        if (column != base_.field_columns.end() &&
            ordinal < column->second.size())
            row.fields[name] = column->second[ordinal];
    }
    for (const auto& name : base_.packet_stable_field_schema) {
        auto column = base_.packet_stable_field_columns.find(name);
        if (column != base_.packet_stable_field_columns.end() &&
            ordinal < column->second.size())
            row.packet_stable_fields[name] = column->second[ordinal];
    }
    if (ordinal < base_.channels.size()) row.channel = base_.channels[ordinal];
    return row;
}

bool StreamQueryView::materialize(StreamAnalysis& analysis,
                                  std::string& error) const {
    analysis = StreamAnalysis();
    analysis.requested_begin = options_.begin;
    analysis.requested_end = options_.end;
    analysis.analysis_complete = base_.analysis_complete;
    const bool has_channel_filter = !options_.channel_filter.empty();
    unsigned long long channel_filter_value = 0;
    if (has_channel_filter) {
        bool ok = false;
        channel_filter_value = parse_user_u64(
            options_.channel_filter, ok, error);
        if (!ok) {
            if (error.empty())
                error = "invalid channel filter: " + options_.channel_filter;
            return false;
        }
    }

    auto begin_it = std::lower_bound(
        base_.samples.begin(), base_.samples.end(), options_.begin,
        [](const StreamSampleMetadata& sample, npiFsdbTime time) {
            return sample.time < time;
        });
    auto end_it = std::upper_bound(
        base_.samples.begin(), base_.samples.end(), options_.end,
        [](npiFsdbTime time, const StreamSampleMetadata& sample) {
            return time < sample.time;
        });
    const std::size_t begin_index =
        static_cast<std::size_t>(begin_it - base_.samples.begin());
    const std::size_t end_index =
        static_cast<std::size_t>(end_it - base_.samples.begin());

    int packet_index = 0;
    StreamStallWindow current_stall;
    bool in_stall = false;
    struct PacketState {
        bool active = false;
        StreamPacket packet;
    };
    PacketState single_packet;
    std::map<std::string, PacketState> channel_packets;
    auto finish_stall = [&](npiFsdbTime end_time, int end_cycle) {
        if (!in_stall) return;
        current_stall.end_time = end_time;
        current_stall.end_cycle = end_cycle;
        analysis.stalls.push_back(current_stall);
        in_stall = false;
    };
    auto finish_packet = [&](PacketState& state, bool partial_end) {
        if (!state.active) return;
        state.packet.partial_end = partial_end;
        analysis.packet_stable_mismatch_count +=
            static_cast<int>(state.packet.packet_stable_mismatches.size());
        if (state.packet.partial_begin || state.packet.partial_end)
            ++analysis.partial_packet_count;
        else
            ++analysis.complete_packet_count;
        bool retain = true;
        if (options_.filter.enabled) {
            bool channel_ok = true;
            if (has_channel_filter) {
                unsigned long long got = 0;
                channel_ok = value_u64(state.packet.channel, got) &&
                    got == channel_filter_value;
            }
            ValueFilterMatch result = ValueFilterMatch::No;
            const bool missing_boundary =
                (options_.filter.position == "sop" &&
                 state.packet.partial_begin) ||
                (options_.filter.position == "eop" &&
                 state.packet.partial_end);
            if (channel_ok) {
                if (missing_boundary) {
                    result = ValueFilterMatch::Unresolved;
                } else {
                    const auto& fields = options_.filter.position == "sop"
                        ? state.packet.first_filter_fields
                        : state.packet.last_filter_fields;
                    result = match_filter_fields(fields, options_.filter);
                }
            }
            retain = result == ValueFilterMatch::Yes;
            if (result == ValueFilterMatch::Unresolved)
                ++analysis.unresolved_filter_count;
            if (retain) {
                ++analysis.matched_packet_count;
                if (!analysis.has_matched_packet_evidence) {
                    analysis.first_matched_packet = state.packet;
                    analysis.has_matched_packet_evidence = true;
                }
                analysis.last_matched_packet = state.packet;
            }
        }
        if (retain) {
            const int retain_limit = options_.retain_limit == 0
                ? options_.limit : options_.retain_limit;
            if (options_.filter.enabled &&
                (retain_limit <= 0 ||
                 static_cast<int>(analysis.packets.size()) < retain_limit)) {
                analysis.packets.push_back(state.packet);
            } else if (options_.filter.enabled) {
                analysis.response_truncated = true;
            } else if (options_.query_kind.empty()) {
                // Export and other internal callers require the complete
                // packet table materialized in the request view.
                analysis.packets.push_back(state.packet);
            } else if (options_.query_kind == "first_packet") {
                if (analysis.packets.empty())
                    analysis.packets.push_back(state.packet);
            } else if (options_.query_kind == "last_packet") {
                if (analysis.packets.empty())
                    analysis.packets.push_back(state.packet);
                else
                    analysis.packets.front() = state.packet;
            } else if (options_.query_kind == "packet_at") {
                if (state.packet.packet_index == options_.packet_index)
                    analysis.packets.push_back(state.packet);
            } else if (options_.query_kind == "packet_window" &&
                       (retain_limit <= 0 ||
                        static_cast<int>(analysis.packets.size()) <
                            retain_limit)) {
                analysis.packets.push_back(state.packet);
            }
        }
        state = PacketState();
    };
    auto start_packet = [&](PacketState& state, const StreamRow& row,
                            bool partial_begin) {
        if (state.active) finish_packet(state, true);
        state.active = true;
        state.packet = StreamPacket();
        state.packet.packet_index = packet_index++;
        state.packet.start_cycle = row.cycle;
        state.packet.end_cycle = row.cycle;
        state.packet.start_time = row.time;
        state.packet.end_time = row.time;
        state.packet.partial_begin = partial_begin;
        state.packet.packet_stable_fields = row.packet_stable_fields;
        if (config_.channel_id_valid == "sop" ||
            config_.channel_id_valid == "every_beat")
            state.packet.channel = row.channel;
    };
    auto append_packet_beat = [&](PacketState& state, StreamRow& row) {
        row.packet_index = state.packet.packet_index;
        row.beat_index = state.packet.beat_count;
        state.packet.end_cycle = row.cycle;
        state.packet.end_time = row.time;
        ++state.packet.beat_count;
        if (state.packet.first_fields.empty())
            state.packet.first_fields = row.fields;
        state.packet.last_fields = row.fields;
        const auto fields = filter_view(row);
        if (state.packet.first_filter_fields.empty())
            state.packet.first_filter_fields = fields;
        state.packet.last_filter_fields = fields;
        if (config_.channel_id_valid == "eop" && row.eop)
            state.packet.channel = row.channel;
        if (config_.channel_id_valid == "every_beat" &&
            state.packet.channel.bits.empty())
            state.packet.channel = row.channel;
        for (const auto& item : row.packet_stable_fields) {
            auto expected = state.packet.packet_stable_fields.find(item.first);
            if (expected == state.packet.packet_stable_fields.end()) {
                state.packet.packet_stable_fields[item.first] = item.second;
                continue;
            }
            if (!stream_value_equal(expected->second, item.second)) {
                StreamPacketStableMismatch mismatch;
                mismatch.field = item.first;
                mismatch.cycle = row.cycle;
                mismatch.time = row.time;
                mismatch.expected = expected->second;
                mismatch.actual = item.second;
                state.packet.packet_stable_mismatches.push_back(
                    std::move(mismatch));
            }
        }
        StreamBeat beat;
        beat.cycle = row.cycle;
        beat.time = row.time;
        beat.beat_index = row.beat_index;
        beat.fields = row.fields;
        state.packet.beats.push_back(std::move(beat));
    };

    int cycle = 0;
    for (std::size_t sample_id = begin_index;
         sample_id < end_index; ++sample_id, ++cycle) {
        const StreamSampleMetadata& sample = base_.samples[sample_id];
        if (!analysis.has_scanned_samples) {
            analysis.scanned_begin = sample.time;
            analysis.has_scanned_samples = true;
        }
        analysis.scanned_end = sample.time;
        ++analysis.clock_edges;
        if (sample.vld) ++analysis.vld_cycles;
        if (sample.stall) ++analysis.stall_cycles;
        if (sample.vld && sample.rdy && sample.bp &&
            !config_.rdy.empty() && !config_.bp.empty())
            ++analysis.ready_bp_conflict_count;
        analysis.control_xz_count += sample.control_xz_count;
        analysis.data_xz_count += sample.data_xz_count;

        if (sample.stall) {
            if (!in_stall) {
                in_stall = true;
                current_stall = StreamStallWindow();
                current_stall.start_cycle = cycle;
                current_stall.start_time = sample.time;
                current_stall.reason = sample.stall_reason;
            }
            ++current_stall.cycles;
        } else {
            finish_stall(sample.time, cycle);
        }

        if (!sample.transfer) continue;
        StreamRow row = transfer_row(sample_id, cycle);
        ++analysis.transfer_count;
        bool channel_ok = !has_channel_filter;
        if (has_channel_filter) {
            unsigned long long got = 0;
            channel_ok = value_u64(row.channel, got) &&
                got == channel_filter_value;
        }
        if (stream_packet_enabled(config_)) {
            PacketState* state = &single_packet;
            if (config_.allow_interleaving) {
                if (row.channel.bits.empty() ||
                    stream_value_has_xz(row.channel)) {
                    error = "interleaved packet stream requires known "
                            "channel_id on every transfer";
                    return false;
                }
                state = &channel_packets[stream_value_key(row.channel)];
            } else if (config_.channel_id_valid == "every_beat" &&
                       single_packet.active &&
                       !single_packet.packet.channel.bits.empty() &&
                       !stream_value_equal(single_packet.packet.channel,
                                           row.channel)) {
                error = "non-interleaved packet channel_id changed within a packet";
                return false;
            }
            if (row.sop) start_packet(*state, row, false);
            else if (!state->active && row.eop)
                start_packet(*state, row, true);
            if (state->active) {
                append_packet_beat(*state, row);
                if (row.eop) finish_packet(*state, false);
            }
        }
        bool selected = channel_ok;
        if (options_.filter.enabled && !stream_packet_enabled(config_)) {
            const ValueFilterMatch result = channel_ok
                ? match_filter_fields(filter_view(row), options_.filter)
                : ValueFilterMatch::No;
            if (result == ValueFilterMatch::Unresolved)
                ++analysis.unresolved_filter_count;
            selected = result == ValueFilterMatch::Yes;
            if (selected) ++analysis.matched_transfer_count;
        }
        if (selected &&
            (!options_.filter.enabled || !stream_packet_enabled(config_))) {
            if (!analysis.has_transfer_evidence) {
                analysis.first_transfer = row;
                analysis.has_transfer_evidence = true;
            }
            analysis.last_transfer = row;
            const int retain_limit = options_.retain_limit == 0
                ? options_.limit : options_.retain_limit;
            if (retain_limit <= 0 ||
                static_cast<int>(analysis.transfers.size()) < retain_limit)
                analysis.transfers.push_back(row);
            else
                analysis.response_truncated = true;
        }
    }
    const npiFsdbTime finish_time = begin_index == end_index
        ? options_.end : base_.samples[end_index - 1].time;
    finish_stall(finish_time, cycle);
    finish_packet(single_packet, true);
    for (auto& item : channel_packets) finish_packet(item.second, true);
    std::sort(analysis.packets.begin(), analysis.packets.end(),
              [](const StreamPacket& a, const StreamPacket& b) {
                  if (a.start_time != b.start_time)
                      return a.start_time < b.start_time;
                  return a.packet_index < b.packet_index;
              });
    return true;
}

bool StreamAnalyzer::analyze(npiFsdbFileHandle file,
                             const StreamConfig& config,
                             const StreamQueryOptions& options,
                             StreamAnalysis& analysis,
                             std::string& error) {
    analysis_probe().record(
        "miss", "stream", config.name,
        AnalysisProbeMetrics{0, 0, 0, 0, 0});
    StreamBaseAnalysis base;
    if (!build_base(file, config, options, base, error)) return false;
    StreamQueryView view(base, config, options);
    if (!view.materialize(analysis, error)) {
        analysis_probe().record(
            "build_failed", "stream", config.name,
            AnalysisProbeMetrics{0, 0, 0, 0, 0});
        return false;
    }
    analysis_probe().record(
        "build", "stream", config.name,
        AnalysisProbeMetrics{0, 0, 0,
            estimate_stream_base_analysis_bytes(base), 0});
    return true;
}

bool StreamAnalyzer::analyze_cached(
    npiFsdbFileHandle file, const StreamConfig& config,
    const StreamQueryOptions& options, AnalysisCacheScope cache_scope,
    StreamAnalysis& analysis, std::string& error) {
    last_cache_error_ = AnalysisCacheError();
    if (repository_ == nullptr) {
        last_cache_error_.code = "ANALYSIS_REPOSITORY_UNAVAILABLE";
        last_cache_error_.message =
            "stream analysis repository is not configured";
        error = last_cache_error_.message;
        return false;
    }

    npiFsdbTime minimum = 0;
    npiFsdbTime maximum = 0;
    npi_fsdb_min_time(file, &minimum);
    npi_fsdb_max_time(file, &maximum);
    const AnalysisCacheKey full_key = cache_key(
        config, AnalysisCacheScope::Full, minimum, maximum);
    AnalysisCacheKey selected_key = cache_scope == AnalysisCacheScope::Full
        ? full_key
        : cache_key(config, AnalysisCacheScope::Range,
                    options.begin, options.end);
    std::shared_ptr<const StreamBaseAnalysis> base;
    {
        const AnalysisAcquireStatus acquire = repository_->begin_canonical(
            selected_key, kStreamBaseTypeTag, sizeof(StreamBaseAnalysis),
            last_cache_error_);
        if (acquire == AnalysisAcquireStatus::Hit) {
            base = repository_->peek_canonical<StreamBaseAnalysis>(
                selected_key, kStreamBaseTypeTag);
        } else if (acquire == AnalysisAcquireStatus::BuildStarted) {
            try {
                std::shared_ptr<StreamBaseAnalysis> building(
                    new StreamBaseAnalysis());
                StreamQueryOptions build_options = options;
                if (selected_key.scope == AnalysisCacheScope::Full) {
                    build_options.begin = minimum;
                    build_options.end = maximum;
                } else {
                    build_options.begin = selected_key.range_begin;
                    build_options.end = selected_key.range_end;
                }
                if (!build_base(file, config, build_options, *building,
                                error, &selected_key)) {
                    repository_->fail_canonical(selected_key, "scan_failed");
                    return false;
                }
                const std::uint64_t resident_bytes =
                    estimate_stream_base_analysis_bytes(*building);
                if (!repository_->update_canonical_build_bytes(
                        selected_key, resident_bytes, last_cache_error_)) {
                    error = last_cache_error_.message;
                    return false;
                }
                if (!repository_->publish_canonical<StreamBaseAnalysis>(
                        selected_key, kStreamBaseTypeTag,
                        std::static_pointer_cast<const StreamBaseAnalysis>(
                            building),
                        resident_bytes, last_cache_error_)) {
                    error = last_cache_error_.message;
                    return false;
                }
                base = repository_->peek_canonical<StreamBaseAnalysis>(
                    selected_key, kStreamBaseTypeTag);
            } catch (const std::bad_alloc&) {
                repository_->fail_canonical_bad_alloc(
                    selected_key, last_cache_error_);
                error = last_cache_error_.message;
                return false;
            }
        } else {
            error = last_cache_error_.message;
            return false;
        }
    }
    if (!base) {
        error = "stream analysis cache entry is unavailable after build";
        return false;
    }
    StreamQueryView view(*base, config, options);
    return view.materialize(analysis, error);
}

#ifdef XDEBUG_STREAM_DIFFERENTIAL_TEST_BUILD
bool StreamAnalyzer::analyze_legacy(npiFsdbFileHandle file,
                                    const StreamConfig& config,
                                    const StreamQueryOptions& options,
                                    StreamAnalysis& analysis,
                                    std::string& error,
                                    bool record_probe) {
    if (record_probe) {
        analysis_probe().record(
            "miss", "stream", config.name,
            AnalysisProbeMetrics{0, 0, 0, 0, 0});
    }
    analysis = StreamAnalysis();
    analysis.requested_begin = options.begin;
    analysis.requested_end = options.end;
    ClockSampleSpec clock_sample = config.clock_sample;
    if (!normalize_clock_sample_spec(file, clock_sample, error)) return false;
    Compiled compiled;
    if (!compile(file, config, compiled, nullptr, error)) return false;
    bool has_channel_filter = !options.channel_filter.empty();
    unsigned long long channel_filter_value = 0;
    if (has_channel_filter) {
        bool ok = false;
        channel_filter_value = parse_user_u64(options.channel_filter, ok, error);
        if (!ok) {
            if (error.empty()) error = "invalid channel filter: " + options.channel_filter;
            return false;
        }
    }
    std::vector<std::string> deps = sorted_signals(compiled.deps);
    std::vector<std::string> clock_deps = sorted_signals(compiled.clock.signals());
    if (clock_deps.empty()) {
        error = "clock expression has no signal dependency";
        return false;
    }
    std::vector<ClockSampleSignal> clock_signals;
    for (const auto& sig_name : clock_deps) {
        auto path_it = compiled.dep_paths.find(sig_name);
        if (path_it == compiled.dep_paths.end()) {
            error = "clock dependency alias missing from stream signals: " + sig_name;
            return false;
        }
        npiFsdbSigHandle sig = npi_fsdb_sig_by_name(file, path_it->second.c_str(), NULL);
        if (!sig) {
            error = "signal not found for alias " + sig_name + ": " + path_it->second;
            return false;
        }
        clock_signals.push_back({sig_name, path_it->second, sig});
    }
    std::vector<ClockSampleSignal> sample_signals;
    for (const auto& sig_name : deps) {
        auto path_it = compiled.dep_paths.find(sig_name);
        if (path_it == compiled.dep_paths.end()) {
            error = "sample dependency alias missing from stream signals: " + sig_name;
            return false;
        }
        npiFsdbSigHandle sig = npi_fsdb_sig_by_name(file, path_it->second.c_str(), NULL);
        if (!sig) {
            error = "signal not found for alias " + sig_name + ": " + path_it->second;
            return false;
        }
        sample_signals.push_back({sig_name, path_it->second, sig});
    }
    std::vector<ClockSample> sampled_edges;
    ClockExpressionSampleScanner scanner(file, clock_sample.edge, clock_sample.sample_point);
    int sample_count = 0;
    bool sample_truncated = false;
    if (record_probe) {
        analysis_probe().record(
            "scan", "stream", config.name,
            AnalysisProbeMetrics{0, 0, 0, 0, 1});
    }
    if (!scanner.scan(clock_signals, sample_signals, options.begin, options.end,
        npiFsdbBinStrVal, 'b', -1,
        [&](const std::map<std::string, std::string>& raw_values,
            bool& known,
            bool& one,
            std::string& eval_error) -> bool {
            std::map<std::string, StreamValue> clock_values;
            for (const auto& sig_name : clock_deps) {
                auto it = raw_values.find(sig_name);
                if (it == raw_values.end()) {
                    eval_error = "clock dependency missing: " + sig_name;
                    return false;
                }
                std::string bits = sample_bits_from_raw(it->second);
                clock_values[sig_name] = StreamValue{bits, bits.find_first_of("xz") == std::string::npos};
            }
            StreamValue clock_value;
            std::string expr_error;
            if (!compiled.clock.evaluate(clock_values, clock_value, expr_error)) {
                eval_error = "clock evaluate failed: " + expr_error;
                return false;
            }
            known = clock_value.known;
            one = stream_value_truthy(clock_value, false);
            return true;
        },
        [&](const ClockSample& sample) -> bool {
            sampled_edges.push_back(sample);
            return true;
        }, error, sample_count, sample_truncated)) {
        if (record_probe) {
            analysis_probe().record(
                "build_failed", "stream", config.name,
                AnalysisProbeMetrics{0, 0, 0, 0, 0});
        }
        return false;
    }

    int packet_index = 0;
    StreamStallWindow current_stall;
    bool in_stall = false;
    struct PacketState {
        bool active = false;
        StreamPacket packet;
    };
    PacketState single_packet;
    std::map<std::string, PacketState> channel_packets;

    auto finish_stall = [&](npiFsdbTime end_time, int end_cycle) {
        if (!in_stall) return;
        current_stall.end_time = end_time;
        current_stall.end_cycle = end_cycle;
        analysis.stalls.push_back(current_stall);
        in_stall = false;
    };

    auto finish_packet = [&](PacketState& state, bool partial_end) {
        if (!state.active) return;
        state.packet.partial_end = partial_end;
        analysis.packet_stable_mismatch_count += static_cast<int>(state.packet.packet_stable_mismatches.size());
        if (state.packet.partial_begin || state.packet.partial_end)
            analysis.partial_packet_count++;
        else
            analysis.complete_packet_count++;
        bool retain = true;
        if (options.filter.enabled) {
            bool channel_ok = true;
            if (has_channel_filter) {
                unsigned long long got = 0;
                channel_ok = value_u64(state.packet.channel, got) &&
                             got == channel_filter_value;
            }
            ValueFilterMatch result = ValueFilterMatch::No;
            const bool missing_boundary =
                (options.filter.position == "sop" && state.packet.partial_begin) ||
                (options.filter.position == "eop" && state.packet.partial_end);
            if (channel_ok) {
                if (missing_boundary) {
                    result = ValueFilterMatch::Unresolved;
                } else {
                    const auto& fields = options.filter.position == "sop"
                        ? state.packet.first_filter_fields
                        : state.packet.last_filter_fields;
                    result = match_filter_fields(fields, options.filter);
                }
            }
            retain = result == ValueFilterMatch::Yes;
            if (result == ValueFilterMatch::Unresolved)
                analysis.unresolved_filter_count++;
            if (retain) {
                analysis.matched_packet_count++;
                if (!analysis.has_matched_packet_evidence) {
                    analysis.first_matched_packet = state.packet;
                    analysis.has_matched_packet_evidence = true;
                }
                analysis.last_matched_packet = state.packet;
            }
        }
        if (retain) {
            const int retain_limit = options.retain_limit == 0
                ? options.limit : options.retain_limit;
            if (!options.filter.enabled || retain_limit <= 0 ||
                static_cast<int>(analysis.packets.size()) < retain_limit) {
                analysis.packets.push_back(state.packet);
            } else {
                analysis.response_truncated = true;
            }
        }
        state.active = false;
        state.packet = StreamPacket();
    };

    auto start_packet = [&](PacketState& state, const StreamRow& row, bool partial_begin) {
        if (state.active) finish_packet(state, true);
        state.active = true;
        state.packet = StreamPacket();
        state.packet.packet_index = packet_index++;
        state.packet.start_cycle = row.cycle;
        state.packet.end_cycle = row.cycle;
        state.packet.start_time = row.time;
        state.packet.end_time = row.time;
        state.packet.partial_begin = partial_begin;
        state.packet.packet_stable_fields = row.packet_stable_fields;
        if (config.channel_id_valid == "sop" || config.channel_id_valid == "every_beat") {
            state.packet.channel = row.channel;
        }
    };

    auto append_packet_beat = [&](PacketState& state, StreamRow& row) {
        row.packet_index = state.packet.packet_index;
        row.beat_index = state.packet.beat_count;
        state.packet.end_cycle = row.cycle;
        state.packet.end_time = row.time;
        state.packet.beat_count++;
        if (state.packet.first_fields.empty()) state.packet.first_fields = row.fields;
        state.packet.last_fields = row.fields;
        const auto fields = filter_view(row);
        if (state.packet.first_filter_fields.empty())
            state.packet.first_filter_fields = fields;
        state.packet.last_filter_fields = fields;
        if (config.channel_id_valid == "eop" && row.eop) state.packet.channel = row.channel;
        if (config.channel_id_valid == "every_beat" && state.packet.channel.bits.empty()) {
            state.packet.channel = row.channel;
        }
        for (const auto& kv : row.packet_stable_fields) {
            auto it = state.packet.packet_stable_fields.find(kv.first);
            if (it == state.packet.packet_stable_fields.end()) {
                state.packet.packet_stable_fields[kv.first] = kv.second;
                continue;
            }
            if (!stream_value_equal(it->second, kv.second)) {
                StreamPacketStableMismatch mismatch;
                mismatch.field = kv.first;
                mismatch.cycle = row.cycle;
                mismatch.time = row.time;
                mismatch.expected = it->second;
                mismatch.actual = kv.second;
                state.packet.packet_stable_mismatches.push_back(mismatch);
            }
        }
        StreamBeat beat;
        beat.cycle = row.cycle;
        beat.time = row.time;
        beat.beat_index = row.beat_index;
        beat.fields = row.fields;
        state.packet.beats.push_back(beat);
    };

    int cycle = 0;
    for (const auto& sample : sampled_edges) {
        npiFsdbTime t = sample.time;
        if (!analysis.has_scanned_samples) {
            analysis.scanned_begin = t;
            analysis.has_scanned_samples = true;
        }
        analysis.scanned_end = t;
        analysis.clock_edges++;
        std::map<std::string, StreamValue> values;
        for (size_t i = 0; i < deps.size(); ++i) {
            std::string raw = i < sample.values.size() ? sample.values[i] : "'bx";
            std::string bits = sample_bits_from_raw(raw);
            values[deps[i]] = StreamValue{bits, bits.find_first_of("xz") == std::string::npos};
        }

        auto eval = [&](StreamExpression& expr, const std::string& label) -> StreamValue {
            if (expr.text().empty()) return StreamValue{"0", true};
            StreamValue out;
            std::string eval_error;
            if (!expr.evaluate(values, out, eval_error)) {
                error = label + " evaluate failed: " + eval_error;
                return x_value();
            }
            return out;
        };

        StreamValue reset_v{"0", true};
        if (config.has_reset) reset_v = values[kResetDependency];
        StreamValue vld_v = eval(compiled.vld, "vld");
        if (!error.empty()) return false;
        StreamValue rdy_v = config.rdy.empty() ? StreamValue{"1", true} : eval(compiled.rdy, "rdy");
        if (!error.empty()) return false;
        StreamValue bp_v = config.bp.empty() ? StreamValue{"0", true} : eval(compiled.bp, "bp");
        if (!error.empty()) return false;
        StreamValue sop_v = config.sop.empty() ? StreamValue{"0", true} : eval(compiled.sop, "sop");
        if (!error.empty()) return false;
        StreamValue eop_v = config.eop.empty() ? StreamValue{"0", true} : eval(compiled.eop, "eop");
        if (!error.empty()) return false;

        StreamRow row;
        row.cycle = cycle;
        row.time = t;
        row.reset = config.has_reset && reset_is_active(config.reset, reset_v.bits);
        row.vld = stream_value_truthy(vld_v, false);
        row.rdy = stream_value_truthy(rdy_v, false);
        row.bp = stream_value_truthy(bp_v, true);
        row.sop = stream_value_truthy(sop_v, false);
        row.eop = stream_value_truthy(eop_v, false);
        row.control_xz_count = (stream_value_has_xz(reset_v) ? 1 : 0) +
                               (stream_value_has_xz(vld_v) ? 1 : 0) +
                               (stream_value_has_xz(rdy_v) ? 1 : 0) +
                               (stream_value_has_xz(bp_v) ? 1 : 0) +
                               (stream_value_has_xz(sop_v) ? 1 : 0) +
                               (stream_value_has_xz(eop_v) ? 1 : 0);

        bool flow = true;
        if (!config.rdy.empty()) flow = flow && row.rdy;
        if (!config.bp.empty()) flow = flow && !row.bp;
        row.transfer = row.vld && flow && !row.reset;
        if (!config.rdy.empty() && !config.bp.empty()) {
            row.stall = row.vld && (!row.rdy || row.bp);
            if (!row.rdy && row.bp) row.stall_reason = "rdy_low_and_bp_high";
            else if (!row.rdy) row.stall_reason = "rdy_low";
            else if (row.bp) row.stall_reason = "bp_high";
        } else if (!config.rdy.empty()) {
            row.stall = row.vld && !row.rdy;
            if (row.stall) row.stall_reason = "rdy_low";
        } else if (!config.bp.empty()) {
            row.stall = row.vld && row.bp;
            if (row.stall) row.stall_reason = "bp_high";
        }
        if (row.vld) analysis.vld_cycles++;
        if (row.stall) analysis.stall_cycles++;
        if (row.vld && row.rdy && row.bp && !config.rdy.empty() && !config.bp.empty())
            analysis.ready_bp_conflict_count++;
        analysis.control_xz_count += row.control_xz_count;

        if (!config.data.empty()) {
            row.fields["data"] = eval(compiled.data, "data");
            if (!error.empty()) return false;
        }
        for (auto& kv : compiled.beat_fields) {
            row.fields[kv.first] = eval(kv.second, "beat_fields." + kv.first);
            if (!error.empty()) return false;
        }
        for (auto& kv : compiled.packet_stable_fields) {
            row.packet_stable_fields[kv.first] = eval(kv.second, "packet_stable_fields." + kv.first);
            if (!error.empty()) return false;
        }
        if (!config.channel_id.empty()) {
            row.channel = eval(compiled.channel, "channel_id");
            if (!error.empty()) return false;
        }
        for (const auto& kv : row.fields) {
            if (stream_value_has_xz(kv.second)) row.data_xz_count++;
        }
        for (const auto& kv : row.packet_stable_fields) {
            if (stream_value_has_xz(kv.second)) row.data_xz_count++;
        }
        analysis.data_xz_count += row.data_xz_count;

        bool channel_ok = !has_channel_filter;
        if (has_channel_filter) {
            unsigned long long got = 0;
            channel_ok = value_u64(row.channel, got) && got == channel_filter_value;
        }

        if (row.stall) {
            if (!in_stall) {
                in_stall = true;
                current_stall = StreamStallWindow();
                current_stall.start_cycle = cycle;
                current_stall.start_time = t;
                current_stall.reason = row.stall_reason;
            }
            current_stall.cycles++;
        } else {
            finish_stall(t, cycle);
        }

        if (row.transfer) {
            analysis.transfer_count++;
            if (stream_packet_enabled(config)) {
                PacketState* state = &single_packet;
                if (config.allow_interleaving) {
                    if (row.channel.bits.empty() || stream_value_has_xz(row.channel)) {
                        error = "interleaved packet stream requires known channel_id on every transfer";
                        return false;
                    }
                    state = &channel_packets[stream_value_key(row.channel)];
                } else if (config.channel_id_valid == "every_beat" && single_packet.active &&
                           !single_packet.packet.channel.bits.empty() &&
                           !stream_value_equal(single_packet.packet.channel, row.channel)) {
                    error = "non-interleaved packet channel_id changed within a packet";
                    return false;
                }

                if (row.sop) start_packet(*state, row, false);
                else if (!state->active && row.eop) start_packet(*state, row, true);

                if (state->active) {
                    append_packet_beat(*state, row);
                    if (row.eop) finish_packet(*state, false);
                }
            }
            bool selected = channel_ok;
            if (options.filter.enabled && !stream_packet_enabled(config)) {
                const ValueFilterMatch result = channel_ok
                    ? match_filter_fields(filter_view(row), options.filter)
                    : ValueFilterMatch::No;
                if (result == ValueFilterMatch::Unresolved)
                    analysis.unresolved_filter_count++;
                selected = result == ValueFilterMatch::Yes;
                if (selected) analysis.matched_transfer_count++;
            }
            if (selected && (!options.filter.enabled || !stream_packet_enabled(config))) {
                if (!analysis.has_transfer_evidence) {
                    analysis.first_transfer = row;
                    analysis.has_transfer_evidence = true;
                }
                analysis.last_transfer = row;
                const int retain_limit = options.retain_limit == 0
                    ? options.limit : options.retain_limit;
                if (retain_limit <= 0 || static_cast<int>(analysis.transfers.size()) < retain_limit)
                    analysis.transfers.push_back(row);
                else
                    analysis.response_truncated = true;
            }
        }

        cycle++;
    }
    if (sample_truncated) analysis.analysis_complete = false;
    finish_stall(sampled_edges.empty() ? options.end : sampled_edges.back().time, cycle);
    finish_packet(single_packet, true);
    for (auto& kv : channel_packets) finish_packet(kv.second, true);
    std::sort(analysis.packets.begin(), analysis.packets.end(),
              [](const StreamPacket& a, const StreamPacket& b) {
                  if (a.start_time != b.start_time) return a.start_time < b.start_time;
                  return a.packet_index < b.packet_index;
              });
    if (record_probe) {
        analysis_probe().record(
            "build", "stream", config.name,
            AnalysisProbeMetrics{0, 0, 0,
                                 estimate_stream_analysis_bytes(analysis), 0});
    }
    return true;
}
#endif

Json stream_row_json(const StreamRow& row) {
    Json j;
    j["cycle"] = row.cycle;
    j["time"] = format_time(row.time);
    j["vld"] = row.vld;
    j["rdy"] = row.rdy;
    j["bp"] = row.bp;
    j["sop"] = row.sop;
    j["eop"] = row.eop;
    j["transfer"] = row.transfer;
    j["stall"] = row.stall;
    if (!row.stall_reason.empty()) j["stall_reason"] = row.stall_reason;
    if (row.packet_index >= 0) j["packet_index"] = row.packet_index;
    j["beat_index"] = row.beat_index;
    j["fields"] = fields_json(row.fields);
    if (!row.packet_stable_fields.empty()) j["packet_stable_fields"] = fields_json(row.packet_stable_fields);
    if (!row.channel.bits.empty()) j["channel_id"] = stream_value_json(row.channel);
    return j;
}

Json stream_stall_json(const StreamStallWindow& stall) {
    return Json{{"start_cycle", stall.start_cycle}, {"end_cycle", stall.end_cycle},
                {"start_time", format_time(stall.start_time)}, {"end_time", format_time(stall.end_time)},
                {"cycles", stall.cycles}, {"reason", stall.reason}};
}

Json stream_packet_json(const StreamPacket& packet) {
    Json j{{"packet_index", packet.packet_index},
           {"start_cycle", packet.start_cycle}, {"end_cycle", packet.end_cycle},
           {"start_time", format_time(packet.start_time)}, {"end_time", format_time(packet.end_time)},
           {"beat_count", packet.beat_count},
           {"partial_begin", packet.partial_begin}, {"partial_end", packet.partial_end},
           {"packet_stable_fields", fields_json(packet.packet_stable_fields)},
           {"packet_stable_mismatches", packet_stable_mismatches_json(packet.packet_stable_mismatches)},
           {"beat_fields_preview", beat_preview_json(packet.beats)},
           {"first_fields", fields_json(packet.first_fields)},
           {"last_fields", fields_json(packet.last_fields)}};
    if (!packet.channel.bits.empty()) j["channel_id"] = stream_value_json(packet.channel);
    return j;
}

Json stream_summary_json(const StreamConfig& config, const StreamAnalysis& analysis) {
    Json j;
    j["stream"] = config.name;
    j["sampling_mode"] = "clock_edge";
    j["clock"] = config.clock_sample.clock;
    j["edge"] = clock_edge_kind_text(config.clock_sample.edge);
    if (config.clock_sample.edge != ClockEdgeKind::Negedge)
        j["sample_point"] = clock_sample_point_text(config.clock_sample.sample_point);
    j["sample_time_semantics"] = "time is sample_time";
    j["handshake"] = stream_handshake_text(config);
    j["packet_enabled"] = stream_packet_enabled(config);
    j["clock_edges"] = analysis.clock_edges;
    j["vld_cycles"] = analysis.vld_cycles;
    j["transfer_count"] = analysis.transfer_count;
    j["stall_cycles"] = analysis.stall_cycles;
    j["stall_windows"] = analysis.stalls.size();
    j["complete_packet_count"] = analysis.complete_packet_count;
    j["partial_packet_count"] = analysis.partial_packet_count;
    if (!stream_packet_enabled(config))
        j["packet_count_status"] = "not_configured";
    else if (analysis.partial_packet_count > 0 || !analysis.analysis_complete)
        j["packet_count_status"] = "ambiguous";
    else
        j["packet_count_status"] = "exact";
    j["control_xz_count"] = analysis.control_xz_count;
    j["data_xz_count"] = analysis.data_xz_count;
    j["ready_bp_conflict_count"] = analysis.ready_bp_conflict_count;
    j["packet_stable_mismatch_count"] = analysis.packet_stable_mismatch_count;
    std::vector<std::string> truncation_scopes;
    if (!analysis.analysis_complete)
        truncation_scopes.push_back("analysis_samples");
    if (analysis.response_truncated)
        truncation_scopes.push_back("response_transfers");
    xdebug_core::set_completeness(
        j,
        analysis.analysis_complete,
        analysis.analysis_complete,
        analysis.response_truncated,
        static_cast<std::size_t>(analysis.transfer_count),
        analysis.transfers.size(),
        truncation_scopes);
    j["requested_range"] = {{"begin", format_time(analysis.requested_begin)},
                             {"end", format_time(analysis.requested_end)}};
    j["scanned_range"] = {{"begin", analysis.has_scanned_samples
        ? Json(format_time(analysis.scanned_begin)) : Json(nullptr)},
                           {"end", analysis.has_scanned_samples
        ? Json(format_time(analysis.scanned_end)) : Json(nullptr)}};
    if (analysis.has_transfer_evidence) {
        j["first_transfer_time"] = format_time(analysis.first_transfer.time);
        j["last_transfer_time"] = format_time(analysis.last_transfer.time);
    }
    if (!analysis.stalls.empty()) {
        j["first_stall_time"] = format_time(analysis.stalls.front().start_time);
        j["last_stall_time"] = format_time(analysis.stalls.back().start_time);
    }
    return j;
}

Json stream_static_validation_json(npiFsdbFileHandle file,
                                   const StreamConfig& config) {
    Json validation;
    validation["status"] = "ok";
    validation["signals"] = Json::array();
    for (const auto& item : config.signals) {
        Json signal = {{"alias", item.first}, {"requested_path", item.second}};
        npiFsdbSigHandle handle = npi_fsdb_sig_by_name(file, item.second.c_str(), nullptr);
        if (!handle) {
            signal["status"] = "signal_not_found";
            validation["status"] = "error";
        } else {
            NPI_INT32 width = 0;
            const NPI_BYTE8* full_name =
                npi_fsdb_sig_property_str(npiFsdbSigFullName, handle);
            npi_fsdb_sig_property(npiFsdbSigRangeSize, handle, &width);
            signal["resolved_path"] = full_name
                ? reinterpret_cast<const char*>(full_name) : item.second;
            signal["width"] = width > 0 ? static_cast<int>(width) : 0;
            signal["status"] = "ok";
        }
        validation["signals"].push_back(signal);
    }
    validation["sampling"] = {
        {"clock", config.clock_sample.clock},
        {"edge", clock_edge_kind_text(config.clock_sample.edge)},
        {"sample_point", config.clock_sample.edge == ClockEdgeKind::Negedge
            ? Json(nullptr)
            : Json(clock_sample_point_text(config.clock_sample.sample_point))}
    };
    validation["packet_rules"] = {
        {"packet_enabled", stream_packet_enabled(config)},
        {"channel_id_valid", config.channel_id_valid},
        {"allow_interleaving", config.allow_interleaving}
    };
    return validation;
}

} // namespace xdebug_waveform
