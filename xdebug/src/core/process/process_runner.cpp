#include "process_runner.h"

#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

namespace xdebug {

namespace {

void set_nonblocking(int fd) {
    int flags = fcntl(fd, F_GETFL, 0);
    if (flags >= 0) fcntl(fd, F_SETFL, flags | O_NONBLOCK);
}

void drain_fd(Fd& fd, std::string& output) {
    char buffer[8192];
    while (fd.valid()) {
        ssize_t n = read(fd.get(), buffer, sizeof(buffer));
        if (n > 0) {
            output.append(buffer, static_cast<size_t>(n));
            continue;
        }
        if (n == 0) fd.reset();
        if (n < 0 && errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)
            fd.reset();
        break;
    }
}

} // namespace

ProcessResult ProcessRunner::run(const ProcessRequest& request) const {
    ProcessResult result;

    Pipe stdin_pipe;
    Pipe stdout_pipe;
    Pipe stderr_pipe;
    if (!stdin_pipe.valid() || !stdout_pipe.valid() || !stderr_pipe.valid()) {
        result.exit_code = -1;
        result.stderr_text = std::string("failed to create pipe: ") + std::strerror(errno);
        return result;
    }

    pid_t pid = fork();
    if (pid < 0) {
        result.exit_code = -1;
        result.stderr_text = std::string("failed to fork: ") + std::strerror(errno);
        return result;
    }

    if (pid == 0) {
        // Child process
        setpgid(0, 0);
        dup2(stdin_pipe.read_end.get(), STDIN_FILENO);
        dup2(stdout_pipe.write_end.get(), STDOUT_FILENO);
        dup2(stderr_pipe.write_end.get(), STDERR_FILENO);

        // Close all pipe ends in child (dup'd ones remain as stdin/stdout)
        stdin_pipe.read_end.reset();
        stdin_pipe.write_end.reset();
        stdout_pipe.read_end.reset();
        stdout_pipe.write_end.reset();
        stderr_pipe.read_end.reset();
        stderr_pipe.write_end.reset();

        if (!request.working_dir.empty()) {
            if (chdir(request.working_dir.c_str()) != 0) {
                dprintf(STDERR_FILENO, "failed to chdir to %s: %s\n",
                        request.working_dir.c_str(), std::strerror(errno));
                _exit(126);
            }
        }

        // Build argv array
        std::vector<const char*> cargv;
        cargv.push_back(request.executable.c_str());
        for (const auto& a : request.argv) {
            cargv.push_back(a.c_str());
        }
        cargv.push_back(nullptr);

        if (request.executable.find('/') == std::string::npos) {
            execvp(request.executable.c_str(), const_cast<char* const*>(cargv.data()));
        } else {
            execv(request.executable.c_str(), const_cast<char* const*>(cargv.data()));
        }
        dprintf(STDERR_FILENO, "failed to exec %s: %s\n",
                request.executable.c_str(), std::strerror(errno));
        _exit(127);
    }

    // Parent process
    setpgid(pid, pid);
    stdin_pipe.read_end.reset();   // Close read end (child reads from it)
    stdout_pipe.write_end.reset(); // Close write end (child writes to it)
    stderr_pipe.write_end.reset();
    set_nonblocking(stdin_pipe.write_end.get());
    set_nonblocking(stdout_pipe.read_end.get());
    set_nonblocking(stderr_pipe.read_end.get());

    size_t stdin_offset = 0;
    if (request.stdin_text.empty()) stdin_pipe.write_end.reset();
    const auto start = std::chrono::steady_clock::now();
    bool child_exited = false;
    int status = 0;
    bool sent_sigterm = false;
    auto termination_time = start;

    while (!child_exited || stdout_pipe.read_end.valid() || stderr_pipe.read_end.valid()) {
        if (!child_exited) {
            pid_t waited = waitpid(pid, &status, WNOHANG);
            if (waited == pid) {
                child_exited = true;
                stdin_pipe.write_end.reset();
            }
        }

        const auto now = std::chrono::steady_clock::now();
        if (!child_exited && request.timeout_ms > 0 &&
            std::chrono::duration_cast<std::chrono::milliseconds>(now - start).count() >=
                request.timeout_ms) {
            result.timed_out = true;
            if (!sent_sigterm) {
                kill(-pid, SIGTERM);
                sent_sigterm = true;
                termination_time = now;
                stdin_pipe.write_end.reset();
            } else if (std::chrono::duration_cast<std::chrono::milliseconds>(
                           now - termination_time).count() >=
                       (request.termination_grace_ms > 0
                            ? request.termination_grace_ms
                            : 0)) {
                kill(-pid, SIGKILL);
            }
        }

        struct pollfd fds[3];
        nfds_t count = 0;
        int stdin_index = -1;
        int stdout_index = -1;
        int stderr_index = -1;
        if (stdin_pipe.write_end.valid()) {
            stdin_index = static_cast<int>(count);
            fds[count++] = {stdin_pipe.write_end.get(), POLLOUT, 0};
        }
        if (stdout_pipe.read_end.valid()) {
            stdout_index = static_cast<int>(count);
            fds[count++] = {stdout_pipe.read_end.get(), POLLIN | POLLHUP, 0};
        }
        if (stderr_pipe.read_end.valid()) {
            stderr_index = static_cast<int>(count);
            fds[count++] = {stderr_pipe.read_end.get(), POLLIN | POLLHUP, 0};
        }

        if (count > 0) {
            int rc = poll(fds, count, 50);
            if (rc < 0 && errno != EINTR) break;
        } else if (!child_exited) {
            usleep(50000);
        }

        if (stdin_index >= 0 &&
            (fds[stdin_index].revents & (POLLOUT | POLLERR | POLLHUP))) {
            size_t remaining = request.stdin_text.size() - stdin_offset;
            ssize_t n = write(stdin_pipe.write_end.get(),
                              request.stdin_text.data() + stdin_offset,
                              remaining);
            if (n > 0) stdin_offset += static_cast<size_t>(n);
            if (stdin_offset == request.stdin_text.size() ||
                (n < 0 && errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)) {
                stdin_pipe.write_end.reset();
            }
        }
        if (stdout_index >= 0 &&
            (fds[stdout_index].revents & (POLLIN | POLLHUP | POLLERR)))
            drain_fd(stdout_pipe.read_end, result.stdout_text);
        if (stderr_index >= 0 &&
            (fds[stderr_index].revents & (POLLIN | POLLHUP | POLLERR)))
            drain_fd(stderr_pipe.read_end, result.stderr_text);
    }

    if (!child_exited) {
        kill(-pid, SIGKILL);
        while (waitpid(pid, &status, 0) < 0 && errno == EINTR) {}
        child_exited = true;
    }
    drain_fd(stdout_pipe.read_end, result.stdout_text);
    drain_fd(stderr_pipe.read_end, result.stderr_text);

    if (WIFEXITED(status)) {
        result.exit_code = WEXITSTATUS(status);
    } else if (WIFSIGNALED(status)) {
        result.exit_code = -1;
        if (!result.stderr_text.empty() && result.stderr_text.back() != '\n')
            result.stderr_text.push_back('\n');
        result.stderr_text += "child killed by signal " + std::to_string(WTERMSIG(status));
    }

    return result;
}

} // namespace xdebug
