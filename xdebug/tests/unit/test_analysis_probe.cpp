#include "waveform/cache/analysis_probe.h"
#include "test_temp_path.h"

#include "json.hpp"

#include <cassert>
#include <cstdio>
#include <fstream>
#include <string>
#include <sys/stat.h>
#include <unistd.h>
#include <vector>

using xdebug_waveform::AnalysisProbe;
using xdebug_waveform::AnalysisProbeMetrics;
using Json = nlohmann::ordered_json;

int main() {
    std::vector<char> marker_storage =
        test_temp_template("xdebug-analysis-probe-root.XXXXXX");
    char* marker = mkdtemp(marker_storage.data());
    assert(marker != nullptr);
    const std::string marker_path(marker);
    const std::string allowed_path = marker_path + "/probe.jsonl";

    unsetenv("XVERIF_TEST_TMPDIR");
    setenv("XDEBUG_TEST_ANALYSIS_PROBE_PATH", allowed_path.c_str(), 1);
    assert(xdebug_waveform::analysis_probe_path_from_environment().empty());
    setenv("XVERIF_TEST_TMPDIR", marker_path.c_str(), 1);
    assert(xdebug_waveform::analysis_probe_path_from_environment() ==
           allowed_path);
    setenv("XDEBUG_TEST_ANALYSIS_PROBE_PATH", marker_path.c_str(), 1);
    assert(xdebug_waveform::analysis_probe_path_from_environment().empty());
    const std::string escaped_path = marker_path + "/../escaped.jsonl";
    setenv("XDEBUG_TEST_ANALYSIS_PROBE_PATH", escaped_path.c_str(), 1);
    assert(xdebug_waveform::analysis_probe_path_from_environment().empty());
    const std::string missing_parent = marker_path + "/missing/probe.jsonl";
    setenv("XDEBUG_TEST_ANALYSIS_PROBE_PATH", missing_parent.c_str(), 1);
    assert(xdebug_waveform::analysis_probe_path_from_environment().empty());
    const std::string outside_template = marker_path + "-outside.XXXXXX";
    std::vector<char> outside_storage(
        outside_template.begin(), outside_template.end());
    outside_storage.push_back('\0');
    const int outside_fd = mkstemp(outside_storage.data());
    assert(outside_fd >= 0);
    close(outside_fd);
    const std::string symlink_path = marker_path + "/escaped-link.jsonl";
    assert(symlink(outside_storage.data(), symlink_path.c_str()) == 0);
    setenv("XDEBUG_TEST_ANALYSIS_PROBE_PATH", symlink_path.c_str(), 1);
    assert(xdebug_waveform::analysis_probe_path_from_environment().empty());
    assert(unlink(symlink_path.c_str()) == 0);
    assert(unlink(outside_storage.data()) == 0);
    unsetenv("XDEBUG_TEST_ANALYSIS_PROBE_PATH");
    assert(xdebug_waveform::analysis_probe_path_from_environment().empty());
    assert(rmdir(marker_path.c_str()) == 0);

    std::vector<char> path_storage = test_temp_template("xdebug-analysis-probe.XXXXXX");
    char* path = path_storage.data();
    const int fd = mkstemp(path);
    assert(fd >= 0);
    assert(fchmod(fd, 0644) == 0);
    close(fd);

    AnalysisProbe probe(path);
    assert(probe.enabled());
    probe.record("miss", "stream", "config-a",
                 AnalysisProbeMetrics{0, 0, 0, 0, 0});
    probe.record("scan", "stream", "config-a",
                 AnalysisProbeMetrics{0, 0, 0, 4096, 1});
    probe.record("build", "stream", "config-a",
                 AnalysisProbeMetrics{1, 0, 2048, 4096, 0});
    probe.record("hit", "stream", "config-a",
                 AnalysisProbeMetrics{1, 0, 2048, 0, 0});

    std::ifstream input(path);
    std::vector<Json> rows;
    std::string line;
    while (std::getline(input, line)) rows.push_back(Json::parse(line));
    assert(rows.size() == 4);
    assert(rows[0]["schema"] == "xdebug.analysis-probe.v1");
    assert(rows[0]["event"] == "miss");
    assert(rows[0]["misses"] == 1);
    assert(rows[1]["scanner_invocations"] == 1);
    assert(rows[2]["entry_count"] == 1);
    assert(rows[2]["resident_bytes"] == 2048);
    assert(rows[3]["hits"] == 1);
    assert(rows[3]["access_sequence"] == 4);
    assert(rows[0]["key_summary"] == rows[3]["key_summary"]);
    assert(rows[0]["key_summary"] != "config-a");

    struct stat info {};
    assert(stat(path, &info) == 0);
    assert((info.st_mode & 0777) == 0600);
    std::remove(path);
    return 0;
}
