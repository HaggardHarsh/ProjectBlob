#pragma once

#include <chrono>
#include <string>

// Keep terminal startup asynchronous and coalesce clicks while it is pending.
class ChatLauncher {
public:
    explicit ChatLauncher(std::string python = {});
    ~ChatLauncher();
    bool launch(bool conversation = false);
    void poll();

private:
    std::string python_;
    int process_ = -1;
    std::chrono::steady_clock::time_point nextLaunch_{};
};
