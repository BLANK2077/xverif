#include "waveform/axi/axi_transaction_tracker.h"

#include <cassert>
#include <cstdint>
#include <iostream>
#include <random>

using namespace xdebug_waveform;

namespace {

AxiSample aw(npiFsdbTime time, const char* id = "1", const char* len = "0") {
    AxiSample s;
    s.time = time;
    s.aw_valid = true;
    s.aw_handshake = true;
    s.awid = id;
    s.awaddr = "100";
    s.awlen = len;
    s.awsize = "3";
    s.awburst = "1";
    return s;
}

AxiSample w(npiFsdbTime time, bool last = true) {
    AxiSample s;
    s.time = time;
    s.w_valid = true;
    s.w_handshake = true;
    s.wlast = last;
    s.wdata = "55";
    s.wstrb = "ff";
    return s;
}

AxiSample idle(npiFsdbTime time, bool aw_valid = false, bool w_valid = false,
               bool ar_valid = false, bool r_valid = false) {
    AxiSample s;
    s.time = time;
    s.aw_valid = aw_valid;
    s.w_valid = w_valid;
    s.ar_valid = ar_valid;
    s.r_valid = r_valid;
    return s;
}

AxiSample b(npiFsdbTime time, const char* id = "1") {
    AxiSample s;
    s.time = time;
    s.b_handshake = true;
    s.bid = id;
    s.bresp = "0";
    return s;
}

AxiSample ar(npiFsdbTime time, const char* id = "1", const char* len = "0") {
    AxiSample s;
    s.time = time;
    s.ar_valid = true;
    s.ar_handshake = true;
    s.arid = id;
    s.araddr = "200";
    s.arlen = len;
    s.arsize = "3";
    s.arburst = "1";
    return s;
}

AxiSample r(npiFsdbTime time, const char* id = "1", bool last = true) {
    AxiSample s;
    s.time = time;
    s.r_valid = true;
    s.r_handshake = true;
    s.rid = id;
    s.rdata = "aa";
    s.rresp = "0";
    s.rlast = last;
    return s;
}

void test_aw_before_w_without_later_aw() {
    AxiTransactionTracker tracker;
    tracker.consume(aw(10));
    tracker.consume(w(20));
    tracker.consume(b(30));
    AxiResult result = tracker.finish(0, 40);
    assert(result.writes.size() == 1);
    assert(result.writes[0].phase_order == "aw_before_w");
    assert(result.writes[0].addr_time == 10);
    assert(result.writes[0].addr_valid_begin_time == 10);
    assert(result.writes[0].first_data_time == 20);
    assert(result.writes[0].first_data_valid_begin_time == 20);
    assert(result.writes[0].data_handshake_times == std::vector<npiFsdbTime>({20}));
    assert(result.diagnostics.final_write_outstanding == 0);
    assert(result.diagnostics.incomplete_write_count == 0);
}

void test_valid_begin_stall_and_back_to_back() {
    AxiTransactionTracker tracker;
    tracker.consume(idle(10, true, false));
    tracker.consume(idle(20, true, false));
    tracker.consume(aw(30, "1", "1"));

    tracker.consume(idle(40, false, true));
    tracker.consume(idle(50, false, true));
    tracker.consume(w(60, false));
    tracker.consume(w(70, true));
    tracker.consume(b(80));

    AxiResult result = tracker.finish(0, 90);
    assert(result.writes.size() == 1);
    const AxiTransaction& txn = result.writes[0];
    assert(txn.has_addr_valid_begin_time);
    assert(txn.addr_valid_begin_time == 10);
    assert(txn.has_first_data_valid_begin_time);
    assert(txn.first_data_valid_begin_time == 40);
    assert(txn.data_handshake_times == std::vector<npiFsdbTime>({60, 70}));
    assert(txn.data_last == std::vector<bool>({false, true}));
}

void test_read_valid_begin_stall_and_back_to_back() {
    AxiTransactionTracker tracker;
    tracker.consume(idle(10, false, false, true));
    tracker.consume(idle(20, false, false, true));
    tracker.consume(ar(30, "1", "1"));
    tracker.consume(ar(40, "2"));

    tracker.consume(idle(50, false, false, false, true));
    tracker.consume(r(60, "1", false));
    tracker.consume(r(70, "1", true));
    tracker.consume(r(80, "2", true));

    AxiResult result = tracker.finish(0, 90);
    assert(result.reads.size() == 2);
    assert(result.reads[0].id == "1");
    assert(result.reads[0].addr_valid_begin_time == 10);
    assert(result.reads[0].first_data_valid_begin_time == 50);
    assert(result.reads[0].data_handshake_times ==
           std::vector<npiFsdbTime>({60, 70}));
    assert(result.reads[0].data_resp == std::vector<std::string>({"0", "0"}));
    assert(result.reads[0].data_last == std::vector<bool>({false, true}));
    assert(result.reads[1].id == "2");
    assert(result.reads[1].addr_valid_begin_time == 40);
    assert(result.reads[1].first_data_valid_begin_time == 80);
    assert(result.reads[1].data_handshake_times ==
           std::vector<npiFsdbTime>({80}));
    assert(result.diagnostics.final_read_outstanding == 0);
}

void test_multiple_w_bursts_before_aw() {
    AxiTransactionTracker tracker;
    tracker.consume(w(10));
    tracker.consume(w(20));
    tracker.consume(aw(30, "1"));
    tracker.consume(aw(40, "2"));
    tracker.consume(b(50, "2"));
    tracker.consume(b(60, "1"));
    AxiResult result = tracker.finish(0, 70);
    assert(result.writes.size() == 2);
    assert(result.writes[0].id == "1");
    assert(result.writes[0].first_data_time == 10);
    assert(result.writes[0].phase_order == "w_before_aw");
    assert(result.writes[1].id == "2");
    assert(result.writes[1].first_data_time == 20);
    assert(result.writes[1].phase_order == "w_before_aw");
    assert(result.diagnostics.orphan_b_count == 0);
}

void test_same_cycle_and_dependency_violation() {
    AxiTransactionTracker tracker;
    AxiSample sample = aw(10);
    sample.w_valid = true;
    sample.w_handshake = true;
    sample.wlast = true;
    sample.wdata = "aa";
    sample.wstrb = "ff";
    tracker.consume(sample);
    tracker.consume(b(20));
    AxiResult result = tracker.finish(0, 20);
    assert(result.writes.size() == 1);
    assert(result.writes[0].phase_order == "same_cycle");
    assert(!result.writes[0].response_dependency_violation);

    AxiTransactionTracker invalid;
    AxiSample all = aw(10);
    all.w_valid = true;
    all.w_handshake = true;
    all.wlast = true;
    all.wdata = "aa";
    all.wstrb = "ff";
    all.b_handshake = true;
    all.bid = "1";
    all.bresp = "0";
    invalid.consume(all);
    AxiResult invalid_result = invalid.finish(0, 10);
    assert(invalid_result.writes.size() == 1);
    assert(invalid_result.writes[0].response_dependency_violation);
    assert(invalid_result.diagnostics.response_dependency_violation_count == 1);
}

void test_multibeat_before_aw_and_pending_diagnostics() {
    AxiTransactionTracker tracker;
    tracker.consume(w(10, false));
    tracker.consume(w(20, false));
    tracker.consume(w(30, false));
    tracker.consume(w(40, true));
    tracker.consume(aw(50, "3", "3"));
    tracker.consume(b(60, "3"));
    tracker.consume(aw(70, "4"));
    tracker.consume(w(80));
    AxiResult result = tracker.finish(0, 90);
    assert(result.writes.size() == 1);
    assert(result.writes[0].data.size() == 4);
    assert(result.writes[0].last_data_time < result.writes[0].addr_time);
    assert(result.pending_writes.size() == 1);
    assert(result.pending_writes[0].id == "4");
    assert(result.diagnostics.incomplete_write_count == 1);
    assert(result.diagnostics.final_write_outstanding == 1);
}

void test_reset_and_orphans() {
    AxiTransactionTracker tracker;
    tracker.consume(aw(10));
    tracker.consume(w(20));
    AxiSample reset;
    reset.time = 30;
    reset.reset_active = true;
    tracker.consume(reset);
    tracker.consume(b(40));
    AxiSample orphan_r;
    orphan_r.time = 50;
    orphan_r.r_handshake = true;
    orphan_r.rid = "2";
    orphan_r.rlast = true;
    tracker.consume(orphan_r);
    AxiResult result = tracker.finish(0, 60);
    assert(result.diagnostics.reset_cleared_write_count == 1);
    assert(result.diagnostics.orphan_b_count == 1);
    assert(result.diagnostics.orphan_r_beat_count == 1);
}

void test_working_set_estimator_includes_pending_state() {
    AxiTransactionTracker tracker;
    const std::size_t empty_bytes = tracker.estimated_working_set_bytes();
    tracker.consume(aw(10, "pending-id", "7"));
    AxiSample beat = w(20, false);
    beat.wdata.assign(4096, 'a');
    beat.wstrb.assign(512, 'f');
    tracker.consume(beat);
    const std::size_t pending_bytes = tracker.estimated_working_set_bytes();
    assert(pending_bytes > empty_bytes + 4096);
}

void test_fixed_seed_schedules() {
    for (uint32_t seed : {7u, 19u, 73u}) {
        std::mt19937 random(seed);
        AxiTransactionTracker tracker;
        npiFsdbTime time = 10;
        size_t expected_aw_first = 0;
        size_t expected_same = 0;
        size_t expected_w_first = 0;
        for (int i = 0; i < 128; ++i) {
            const int relation = i < 3 ? i : static_cast<int>(random() % 3);
            const std::string id = std::to_string(random() % 8);
            if (relation == 0) {
                tracker.consume(aw(time, id.c_str()));
                tracker.consume(w(time + 2));
                ++expected_aw_first;
            } else if (relation == 1) {
                AxiSample both = aw(time, id.c_str());
                both.w_valid = true;
                both.w_handshake = true;
                both.wlast = true;
                both.wdata = "1";
                both.wstrb = "ff";
                tracker.consume(both);
                ++expected_same;
            } else {
                tracker.consume(w(time));
                tracker.consume(aw(time + 2, id.c_str()));
                ++expected_w_first;
            }
            tracker.consume(b(time + 4, id.c_str()));
            time += 10;
        }
        AxiResult result = tracker.finish(0, time);
        size_t aw_first = 0, same = 0, w_first = 0;
        for (const auto& txn : result.writes) {
            aw_first += txn.phase_order == "aw_before_w";
            same += txn.phase_order == "same_cycle";
            w_first += txn.phase_order == "w_before_aw";
        }
        assert(result.writes.size() == 128);
        assert(aw_first == expected_aw_first);
        assert(same == expected_same);
        assert(w_first == expected_w_first);
        assert(aw_first > 0 && same > 0 && w_first > 0);
        assert(result.diagnostics.final_write_outstanding == 0);
    }
}

void test_latency_outlier_selection_is_bounded_and_stable() {
    std::vector<AxiTransaction> transactions(6);
    const npiFsdbTime latencies[] = {10, 50, 30, 50, 20, 40};
    for (size_t index = 0; index < transactions.size(); ++index) {
        transactions[index].seq = index + 1;
        transactions[index].addr_time = 100 + index;
        transactions[index].resp_time =
            transactions[index].addr_time + latencies[index];
        transactions[index].is_write = index != 5;
    }
    AxiLatencyOutlierSelection top = select_axi_latency_outliers(
        transactions, 0, 1000, 0, false, 0, 4, 2);
    assert(top.candidate_count == 6);
    assert(top.matched_outlier_count == 4);
    assert(top.transactions.size() == 2);
    assert(top.transactions[0]->seq == 2);
    assert(top.transactions[1]->seq == 4);

    AxiLatencyOutlierSelection threshold = select_axi_latency_outliers(
        transactions, 0, 1000, 0, true, 25, 0, 3);
    assert(threshold.candidate_count == 6);
    assert(threshold.matched_outlier_count == 4);
    assert(threshold.transactions.size() == 3);
    assert(threshold.transactions[0]->seq == 2);
    assert(threshold.transactions[1]->seq == 4);
    assert(threshold.transactions[2]->seq == 6);

    AxiLatencyOutlierSelection reads = select_axi_latency_outliers(
        transactions, 0, 1000, 2, false, 0, 10, 10);
    assert(reads.candidate_count == 1);
    assert(reads.transactions.size() == 1);
    assert(reads.transactions[0]->seq == 6);

    AxiLatencyOutlierSelection ranged = select_axi_latency_outliers(
        transactions, 102, 104, 0, false, 0, 10, 10);
    assert(ranged.candidate_count == 3);
    assert(ranged.matched_outlier_count == 3);
    assert(ranged.transactions.size() == 3);
    assert(ranged.transactions[0]->seq == 4);
    assert(ranged.transactions[1]->seq == 3);
    assert(ranged.transactions[2]->seq == 5);
}

} // namespace

int main() {
    test_aw_before_w_without_later_aw();
    test_multiple_w_bursts_before_aw();
    test_valid_begin_stall_and_back_to_back();
    test_read_valid_begin_stall_and_back_to_back();
    test_same_cycle_and_dependency_violation();
    test_multibeat_before_aw_and_pending_diagnostics();
    test_reset_and_orphans();
    test_working_set_estimator_includes_pending_state();
    test_fixed_seed_schedules();
    test_latency_outlier_selection_is_bounded_and_stable();
    std::cout << "PASS: AXI transaction tracker unit tests\n";
    return 0;
}
