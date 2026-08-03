#include "waveform/common/clock_sampling_response.h"
#include "waveform/common/xdebug_waveform_paths.h"
#include "waveform/event/event_manager.h"
#include "waveform/service/action_support.h"
#include "test_temp_path.h"

#include <cassert>
#include <cstdlib>
#include <fstream>
#include <string>
#include <unistd.h>
#include <vector>

using namespace xdebug_waveform;

namespace {

Json event_config_input(bool include_sample_point) {
    Json input = {
        {"clock", "top.clk"},
        {"edge", "negedge"},
        {"signals", {{"valid", "top.valid"}}}
    };
    if (include_sample_point) input["sample_point"] = "after";
    return input;
}

StoreJson read_json(const std::string& path) {
    std::ifstream input(path.c_str());
    assert(input.good());
    StoreJson value;
    input >> value;
    return value;
}

void require_protocol_configs_stay_strict() {
    const Json input = {
        {"clock", "top.clk"},
        {"edge", "negedge"},
        {"sample_point", "after"},
        {"reset", {
            {"signal", "top.rst_n"},
            {"polarity", "active_low"}
        }}
    };
    std::string error;
    ApbConfig apb;
    assert(!parse_apb_config(input, apb, error));
    assert(error.find("only valid with edge:posedge or edge:dual") !=
           std::string::npos);
    error.clear();
    AxiConfig axi;
    assert(!parse_axi_config(input, axi, error));
    assert(error.find("only valid with edge:posedge or edge:dual") !=
           std::string::npos);

    Json unknown_apb = input;
    unknown_apb["ignored"] = true;
    error.clear();
    assert(!parse_apb_config(unknown_apb, apb, error));
    assert(error.find("unknown field") != std::string::npos);

    Json unknown_axi = input;
    unknown_axi["ignored"] = true;
    error.clear();
    assert(!parse_axi_config(unknown_axi, axi, error));
    assert(error.find("unknown field") != std::string::npos);
}

void require_event_config_documents_stay_closed() {
    EventConfig parsed;
    std::string error;

    Json unknown = event_config_input(false);
    unknown["ignored"] = true;
    assert(!parse_event_config(unknown, parsed, error));
    assert(error.find("unknown field") != std::string::npos);

    Json empty_alias = event_config_input(false);
    empty_alias["signals"] = {{"", "top.valid"}};
    error.clear();
    assert(!parse_event_config(empty_alias, parsed, error));
    assert(error.find("non-empty strings") != std::string::npos);

    Json empty_path = event_config_input(false);
    empty_path["signals"] = {{"valid", ""}};
    error.clear();
    assert(!parse_event_config(empty_path, parsed, error));
    assert(error.find("non-empty strings") != std::string::npos);

    Json unknown_field_member = event_config_input(false);
    unknown_field_member["fields"] = {
        {"opcode", {
            {"signal", "valid"},
            {"left", 0},
            {"right", 0},
            {"ignored", true},
        }}
    };
    error.clear();
    assert(!parse_event_config(unknown_field_member, parsed, error));
    assert(error.find("unknown field") != std::string::npos);
}

} // namespace

int main() {
    require_protocol_configs_stay_strict();
    require_event_config_documents_stay_closed();

    std::vector<char> root_storage =
        test_temp_template("xdebug-event-sampling.XXXXXX");
    char* root = root_storage.data();
    assert(mkdtemp(root) != nullptr);
    setenv("HOME", root, 1);

    EventConfig explicit_sample_point;
    std::string error;
    assert(parse_event_config(
        event_config_input(true), explicit_sample_point, error));
    explicit_sample_point.name = "explicit_after";
    assert(explicit_sample_point.clock_sample.edge ==
           ClockEdgeKind::Negedge);
    assert(explicit_sample_point.clock_sample.has_sample_point);
    assert(explicit_sample_point.clock_sample.sample_point ==
           ClockSamplePointKind::After);

    const Json exposed = event_config_json(explicit_sample_point);
    assert(exposed["sample_point"] == "after");
    const ClockSamplingJson sampling =
        clock_sampling_contract_json(
            explicit_sample_point.clock_sample);
    assert(sampling["requested"]["sample_point"] == "after");
    assert(sampling["effective"]["sample_point"].is_null());
    assert(sampling["sample_point_applied"] == false);
    assert(sampling["sample_point_ignored_for_negedge"] == true);
    assert(sampling["sample_point_not_applied_reason"].is_string());

    const std::string session = "EventSampling";
    const std::string fsdb = "fixtures/design.fsdb";
    EventManager manager;
    assert(manager.create_event(
        session, fsdb, explicit_sample_point).ok());
    EventConfig loaded;
    assert(manager.get_event(
        session, fsdb, explicit_sample_point.name, loaded).ok());
    assert(loaded.clock_sample.has_sample_point);
    assert(loaded.clock_sample.sample_point ==
           ClockSamplePointKind::After);

    EventConfig implicit_sample_point;
    error.clear();
    assert(parse_event_config(
        event_config_input(false), implicit_sample_point, error));
    implicit_sample_point.name = "implicit_default";
    assert(!implicit_sample_point.clock_sample.has_sample_point);
    assert(!event_config_json(implicit_sample_point).contains(
        "sample_point"));
    assert(manager.create_event(
        session, fsdb, implicit_sample_point).ok());
    loaded = EventConfig{};
    assert(manager.get_event(
        session, fsdb, implicit_sample_point.name, loaded).ok());
    assert(!loaded.clock_sample.has_sample_point);

    const StoreJson persisted =
        read_json(xdebug_waveform_events_path(session));
    assert(persisted["version"] == 1);
    assert(persisted["events"].size() == 2);
    bool found_explicit = false;
    bool found_implicit = false;
    for (const auto& item : persisted["events"]) {
        if (item["name"] == explicit_sample_point.name) {
            found_explicit = true;
            assert(item["sample_point"] == "after");
        }
        if (item["name"] == implicit_sample_point.name) {
            found_implicit = true;
            assert(!item.contains("sample_point"));
        }
    }
    assert(found_explicit && found_implicit);

    xdebug_waveform_remove_session_dir(session);
    return 0;
}
