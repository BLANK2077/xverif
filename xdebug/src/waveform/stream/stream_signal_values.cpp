#include "stream_expr.h"

#include "../server/fsdb_value_reader.h"

#include <cctype>

namespace xdebug_waveform {

namespace {

std::string lower_bits(std::string text) {
    std::string out;
    for (char c : text) {
        if (c == '_' || std::isspace(static_cast<unsigned char>(c))) continue;
        if (c == '0' || c == '1' || c == 'x' || c == 'X' || c == 'z' || c == 'Z') {
            out.push_back(static_cast<char>(std::tolower(static_cast<unsigned char>(c))));
        }
    }
    return out;
}

bool has_xz_bits(const std::string& bits) {
    return bits.find_first_of("xzXZ") != std::string::npos;
}

std::string strip_prefix(std::string text) {
    if (text.size() >= 2 && text[0] == '\'' &&
        (text[1] == 'b' || text[1] == 'B' || text[1] == 'h' || text[1] == 'H' ||
         text[1] == 'd' || text[1] == 'D')) {
        return text.substr(2);
    }
    return text;
}

} // namespace

bool stream_collect_signal_values(npiFsdbFileHandle file,
                                  const std::vector<std::string>& signals,
                                  npiFsdbTime time,
                                  std::map<std::string, StreamValue>& values,
                                  std::string& error) {
    values.clear();
    if (signals.empty()) return true;
    std::vector<std::string> raw;
    std::vector<bool> found;
    read_sig_vec_value_at_with_status(file, signals, time, 'b', raw, found);
    for (size_t i = 0; i < signals.size(); ++i) {
        if (!found[i]) {
            error = "signal not found: " + signals[i];
            return false;
        }
        npiFsdbSigHandle signal =
            npi_fsdb_sig_by_name(file, signals[i].c_str(), nullptr);
        xdebug_core::LogicValue logic =
            logic_value_from_fsdb_signal(signal, raw[i], 'b');
        std::string bits = logic.bits;
        if (bits.empty()) bits = lower_bits(strip_prefix(raw[i]));
        if (bits.empty()) bits = "x";
        values[signals[i]] = StreamValue{
            bits, !has_xz_bits(bits), logic.width_reliable};
    }
    return true;
}

} // namespace xdebug_waveform
