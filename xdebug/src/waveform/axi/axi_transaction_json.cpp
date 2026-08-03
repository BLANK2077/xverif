#include "axi_transaction_json.h"
#include "core/npi/time_contract.h"
#include "core/value/logic_value.h"

namespace xdebug_waveform {

namespace {

std::string rendered(const std::string& raw, int width) {
    return xdebug_core::render_logic_value(
        xdebug_core::logic_value_from_fsdb_raw(raw, 'h', width));
}

} // namespace

AxiJson axi_transaction_to_json(npiFsdbFileHandle file,
                                const AxiTransaction& txn,
                                bool include_data,
                                bool include_first_beat) {
    AxiJson out;
    out["direction"] = txn.is_write ? "write" : "read";
    if (txn.is_write) out["phase_order"] = txn.phase_order;
    out["latency"] = xdebug_core::format_duration(
        file, txn.resp_time >= txn.addr_time ? txn.resp_time - txn.addr_time : 0);
    out["response_dependency_violation"] = txn.response_dependency_violation;

    AxiJson address;
    address["channel"] = txn.is_write ? "aw" : "ar";
    if (txn.has_addr_valid_begin_time)
        address["valid_begin_time"] = xdebug_core::format_time(file, txn.addr_valid_begin_time);
    address["handshake_time"] = xdebug_core::format_time(file, txn.addr_time);
    address["addr"] = rendered(txn.addr, txn.addr_width);
    address["id"] = rendered(txn.id, txn.id_width);
    address["len"] = rendered(txn.len, txn.len_width);
    address["size"] = rendered(txn.size, txn.size_width);
    address["burst"] = rendered(txn.burst, txn.burst_width);
    out["address"] = std::move(address);

    if (!txn.data_handshake_times.empty() || !txn.data.empty()) {
        AxiJson data;
        data["channel"] = txn.is_write ? "w" : "r";
        if (txn.has_first_data_valid_begin_time)
            data["valid_begin_time"] = xdebug_core::format_time(
                file, txn.first_data_valid_begin_time);
        data["first_handshake_time"] = xdebug_core::format_time(file, txn.first_data_time);
        data["last_handshake_time"] = xdebug_core::format_time(file, txn.last_data_time);
        data["beat_count"] = txn.data.size();
        data["expected_beat_count"] = txn.expected_beat_count;
        const auto beat_json = [&](size_t i) {
            AxiJson beat = {
                {"index", i + 1},
                {"handshake_time", xdebug_core::format_time(
                    file, i < txn.data_handshake_times.size()
                        ? txn.data_handshake_times[i]
                        : txn.first_data_time)},
                {"data", rendered(txn.data[i], txn.data_width)},
            };
            if (txn.is_write && i < txn.wstrb.size())
                beat["wstrb"] = rendered(
                    txn.wstrb[i], txn.wstrb_width);
            if (!txn.is_write && i < txn.data_resp.size())
                beat["resp"] = rendered(
                    txn.data_resp[i], txn.resp_width);
            beat["last"] = i < txn.data_last.size()
                ? txn.data_last[i]
                : i + 1 == txn.data.size();
            return beat;
        };
        if (include_data) {
            AxiJson beats = AxiJson::array();
            for (size_t i = 0; i < txn.data.size(); ++i) {
                beats.push_back(beat_json(i));
            }
            data["beats"] = std::move(beats);
        } else if (include_first_beat && !txn.data.empty()) {
            data["first_beat"] = beat_json(0);
        }
        out["data"] = std::move(data);
    }

    out["response"] = {
        {"channel", txn.is_write ? "b" : "r"},
        {"handshake_time", xdebug_core::format_time(file, txn.resp_time)},
        {"resp", rendered(txn.resp, txn.resp_width)},
    };
    return out;
}

} // namespace xdebug_waveform
