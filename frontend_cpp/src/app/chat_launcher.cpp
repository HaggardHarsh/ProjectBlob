#include "app/chat_launcher.h"

#include <cerrno>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <utility>
#ifdef __linux__
#include <spawn.h>
#include <sys/wait.h>
#include <unistd.h>
extern char** environ;
#endif

ChatLauncher::ChatLauncher(std::string python) : python_(std::move(python)) {
#ifdef __linux__
    if (python_.empty()) {
        const char* configured = std::getenv("BLOB_CHAT_PYTHON");
        python_ = configured ? configured : access("venv/bin/python", X_OK) == 0 ? "venv/bin/python" : "python3";
    }
#endif
}

ChatLauncher::~ChatLauncher() { poll(); }

void ChatLauncher::poll() {
#ifdef __linux__
    if (process_ <= 0) return;
    int status = 0;
    const pid_t result = waitpid(process_, &status, WNOHANG);
    if (result == process_ || (result < 0 && errno == ECHILD)) {
        process_ = -1;
        // Cover the window manager presenting a newly launched terminal.
        nextLaunch_ = std::chrono::steady_clock::now() + std::chrono::milliseconds(750);
        if (result > 0 && (!WIFEXITED(status) || WEXITSTATUS(status) != 0))
            std::cerr << "Could not open Blob Chat. Check the terminal launcher.\n";
    }
#endif
}

bool ChatLauncher::launch(bool conversation) {
#ifdef __linux__
    poll();
    if (process_ > 0 || std::chrono::steady_clock::now() < nextLaunch_) return false;
    char* args[] = {python_.data(), const_cast<char*>("-m"), const_cast<char*>("blob.desktop"),
                    conversation ? const_cast<char*>("--conversation") : nullptr, nullptr};
    pid_t process;
    // fork()/waitpid() can block the SDL thread on gRPC's fork handlers.
    const int error = posix_spawnp(&process, python_.c_str(), nullptr, nullptr, args, environ);
    if (error) {
        std::cerr << "Could not start Blob Chat: " << std::strerror(error) << '\n';
        return false;
    }
    process_ = process;
    return true;
#else
    return false;
#endif
}
