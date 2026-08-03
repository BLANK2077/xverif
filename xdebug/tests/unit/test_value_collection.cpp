#include "waveform/value/value_collection.h"

#include "waveform/apb/apb_config.h"
#include "waveform/axi/axi_config.h"
#include "waveform/list/signal_list.h"
#include "waveform/stream/stream_config.h"

#include <cassert>
#include <memory>
#include <string>
#include <vector>

using namespace xdebug_waveform;

namespace {

std::vector<std::string> keys(
    const ValueCollectionProvider& provider) {
    std::vector<std::string> result;
    for (const ValueCollectionEntry& entry : provider.entries()) {
        result.push_back(entry.key);
    }
    return result;
}
}  // namespace

int main() {
    std::unique_ptr<ValueCollectionProvider> signal =
        make_signal_value_collection("top.u.valid");
    assert(signal->kind() == "signal");
    assert(signal->name() == "top.u.valid");
    assert(keys(*signal) == std::vector<std::string>({"top.u.valid"}));

    SignalList list;
    list.name = "ctrl";
    list.signals = {"top.u.valid", "top.u.ready"};
    std::unique_ptr<ValueCollectionProvider> list_provider =
        make_list_value_collection(list);
    assert(
        keys(*list_provider) ==
        std::vector<std::string>(
            {"top.u.valid", "top.u.ready"}));

    ApbConfig apb;
    apb.name = "apb0";
    apb.clock_sample.clock = "top.pclk";
    apb.reset.signal = "top.presetn";
    apb.paddr = "top.paddr";
    apb.psel = "top.psel";
    apb.penable = "top.penable";
    apb.pwrite = "top.pwrite";
    apb.pwdata = "top.pwdata";
    apb.prdata = "top.prdata";
    apb.pready = "top.pready";
    std::unique_ptr<ValueCollectionProvider> apb_provider =
        make_apb_value_collection(apb);
    assert(
        keys(*apb_provider) ==
        std::vector<std::string>({
            "clock", "reset", "paddr", "psel", "penable",
            "pwrite", "pwdata", "prdata", "pready",
        }));

    AxiConfig axi;
    axi.name = "axi0";
    axi.clock_sample.clock = "top.aclk";
    axi.reset.signal = "top.aresetn";
    axi.awaddr = "top.awaddr";
    axi.awvalid = "top.awvalid";
    axi.awready = "top.awready";
    axi.wdata = "top.wdata";
    axi.wvalid = "top.wvalid";
    axi.wready = "top.wready";
    axi.bresp = "top.bresp";
    axi.bvalid = "top.bvalid";
    axi.bready = "top.bready";
    axi.araddr = "top.araddr";
    axi.arvalid = "top.arvalid";
    axi.arready = "top.arready";
    axi.rdata = "top.rdata";
    axi.rresp = "top.rresp";
    axi.rvalid = "top.rvalid";
    axi.rready = "top.rready";
    std::unique_ptr<ValueCollectionProvider> axi_provider =
        make_axi_value_collection(axi);
    const std::vector<std::string> axi_keys = keys(*axi_provider);
    assert(axi_keys.front() == "clock");
    assert(axi_keys[1] == "reset");
    assert(axi_keys[2] == "aw.addr");
    assert(axi_keys.back() == "r.ready");

    StreamConfig stream;
    stream.name = "stream0";
    stream.signals = {
        {"clk", "top.clk"},
        {"payload", "top.payload"},
        {"ready", "top.ready"},
        {"valid", "top.valid"},
    };
    stream.clock_sample.clock = "clk";
    stream.has_reset = true;
    stream.reset.signal = "top.rst_n";
    stream.vld = "valid";
    stream.rdy = "ready";
    stream.data = "payload";
    stream.beat_fields["opcode"] = "payload[7:0]";
    std::string error;
    std::unique_ptr<ValueCollectionProvider> stream_provider =
        make_stream_value_collection(stream, error);
    assert(stream_provider);
    assert(error.empty());
    const std::vector<std::string> stream_keys = keys(*stream_provider);
    assert(stream_keys[0] == "semantic.clock");
    assert(stream_keys[1] == "semantic.reset");
    assert(stream_keys[2] == "semantic.vld");
    assert(stream_keys[3] == "semantic.rdy");
    assert(stream_keys[4] == "semantic.data");
    assert(stream_keys[5] == "beat_fields.opcode");
    assert(stream_keys[6] == "signals.clk");
    assert(stream_keys.back() == "signals.valid");
    assert(
        stream_provider->entries()[4].kind ==
        ValueCollectionEntryKind::Expression);
    assert(
        stream_provider->entries()[4].dependencies[0].alias ==
        "payload");
    return 0;
}
