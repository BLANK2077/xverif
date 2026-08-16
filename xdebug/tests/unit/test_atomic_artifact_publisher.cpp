#include "waveform/common/atomic_artifact_publisher.h"

#include <cassert>
#include <dirent.h>
#include <fstream>
#include <ios>
#include <string>
#include <sys/wait.h>
#include <unistd.h>
#include <vector>

using xdebug_waveform::AtomicArtifact;
using xdebug_waveform::publish_atomic_artifact_set;

namespace {

std::string make_temp_dir() {
    std::string pattern = "xdebug-artifact-publisher-XXXXXX";
    std::vector<char> buffer(pattern.begin(), pattern.end());
    buffer.push_back('\0');
    char* path = mkdtemp(buffer.data());
    assert(path != nullptr);
    return path;
}

bool exists(const std::string& path) {
    return access(path.c_str(), F_OK) == 0;
}

std::string read_text(const std::string& path) {
    std::ifstream input(path.c_str(), std::ios::binary);
    return std::string(
        (std::istreambuf_iterator<char>(input)),
        std::istreambuf_iterator<char>());
}

void write_text(const std::string& path, const std::string& value) {
    std::ofstream output(path.c_str(), std::ios::binary | std::ios::trunc);
    output << value;
    output.close();
    assert(output.good());
}

std::size_t temporary_count(const std::string& directory) {
    DIR* stream = opendir(directory.c_str());
    assert(stream != nullptr);
    std::size_t count = 0;
    while (dirent* entry = readdir(stream)) {
        if (std::string(entry->d_name).find(".tmp.") != std::string::npos)
            ++count;
    }
    closedir(stream);
    return count;
}

std::vector<AtomicArtifact> artifact_set(const std::string& directory,
                                         const std::string& value) {
    std::vector<AtomicArtifact> artifacts;
    artifacts.emplace_back(directory + "/data.tsv",
                           [value](std::ostream& out, std::string&) {
                               out << value;
                               return true;
                           });
    artifacts.emplace_back(directory + "/meta.json",
                           [](std::ostream& out, std::string&) {
                               out << "{}\n";
                               return true;
                           });
    return artifacts;
}

void remove_artifact_set(const std::string& directory) {
    unlink((directory + "/data.tsv").c_str());
    unlink((directory + "/meta.json").c_str());
}

}  // namespace

int main() {
    const std::string directory = make_temp_dir();
    std::string error;

    auto success = artifact_set(directory, "row\n");
    assert(publish_atomic_artifact_set(success, error));
    assert(read_text(directory + "/data.tsv") == "row\n");
    assert(read_text(directory + "/meta.json") == "{}\n");
    assert(success[0].bytes == 4);
    assert(success[1].bytes == 3);
    assert(temporary_count(directory) == 0);

    auto collision = artifact_set(directory, "replacement\n");
    error.clear();
    assert(!publish_atomic_artifact_set(collision, error));
    assert(error.find("already exists") != std::string::npos);
    assert(read_text(directory + "/data.tsv") == "row\n");
    assert(read_text(directory + "/meta.json") == "{}\n");
    assert(temporary_count(directory) == 0);
    remove_artifact_set(directory);

    std::vector<AtomicArtifact> writer_failure;
    writer_failure.emplace_back(directory + "/data.tsv",
                                [](std::ostream& out, std::string&) {
                                    out << "partial";
                                    return true;
                                });
    writer_failure.emplace_back(directory + "/meta.json",
                                [](std::ostream& out, std::string&) {
                                    out << "partial";
                                    out.setstate(std::ios::badbit);
                                    return true;
                                });
    error.clear();
    assert(!publish_atomic_artifact_set(writer_failure, error));
    assert(!exists(directory + "/data.tsv"));
    assert(!exists(directory + "/meta.json"));
    assert(temporary_count(directory) == 0);

    write_text(directory + "/meta.json", "preserve\n");
    auto late_collision = artifact_set(directory, "new\n");
    error.clear();
    assert(!publish_atomic_artifact_set(late_collision, error));
    assert(!exists(directory + "/data.tsv"));
    assert(read_text(directory + "/meta.json") == "preserve\n");
    unlink((directory + "/meta.json").c_str());

    int start_pipe[2];
    assert(pipe(start_pipe) == 0);
    pid_t children[2];
    for (int index = 0; index < 2; ++index) {
        children[index] = fork();
        assert(children[index] >= 0);
        if (children[index] == 0) {
            close(start_pipe[1]);
            char token = 0;
            assert(read(start_pipe[0], &token, 1) == 1);
            auto concurrent = artifact_set(
                directory, index == 0 ? "writer-zero\n" : "writer-one\n");
            std::string child_error;
            _exit(publish_atomic_artifact_set(concurrent, child_error) ? 0 : 1);
        }
    }
    close(start_pipe[0]);
    assert(write(start_pipe[1], "xx", 2) == 2);
    close(start_pipe[1]);
    int successes = 0;
    for (pid_t child : children) {
        int status = 0;
        assert(waitpid(child, &status, 0) == child);
        assert(WIFEXITED(status));
        if (WEXITSTATUS(status) == 0) ++successes;
    }
    assert(successes == 1);
    const std::string concurrent_data = read_text(directory + "/data.tsv");
    assert(concurrent_data == "writer-zero\n" ||
           concurrent_data == "writer-one\n");
    assert(read_text(directory + "/meta.json") == "{}\n");
    assert(temporary_count(directory) == 0);
    remove_artifact_set(directory);

    std::vector<AtomicArtifact> duplicate;
    duplicate.emplace_back(directory + "/same", [](std::ostream&, std::string&) {
        return true;
    });
    duplicate.emplace_back(directory + "/same", [](std::ostream&, std::string&) {
        return true;
    });
    error.clear();
    assert(!publish_atomic_artifact_set(duplicate, error));
    assert(error.find("duplicate") != std::string::npos);

    assert(rmdir(directory.c_str()) == 0);
    return 0;
}
