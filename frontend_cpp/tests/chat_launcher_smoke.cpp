#include "app/chat_launcher.h"

#include <chrono>
#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <sys/stat.h>
#include <unistd.h>

static void require(bool value, const char* message) {
    if (!value) throw std::runtime_error(message);
}

int main() {
    char directory[] = "/tmp/blob-chat-launch-XXXXXX";
    require(mkdtemp(directory), "Could not create test directory");
    const std::string helper = std::string(directory) + "/python";
    {
        std::ofstream script(helper);
        script << "#!/bin/sh\nprintf '%s\\n' \"$@\" >> \"$0.calls\"\n"
                  "while [ ! -e \"$0.release\" ]; do sleep 0.01; done\n";
    }
    require(chmod(helper.c_str(), 0700) == 0, "Could not prepare launcher");
    {
        ChatLauncher launcher(helper);
        const auto started = std::chrono::steady_clock::now();
        require(launcher.launch(), "First double-click must launch immediately");
        require(std::chrono::steady_clock::now() - started < std::chrono::seconds(2),
                "Terminal startup blocked the overlay");
        for (int click = 0; click < 10; ++click)
            require(!launcher.launch(), "Repeated clicks created duplicate terminals during startup");
        // A slow terminal must not block rendering or permit another launch.
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
        launcher.poll();
        require(!launcher.launch(true), "A second activation bypassed the pending launch");
        std::ofstream(helper + ".release").put('\n');
        bool relaunched = false;
        for (int attempt = 0; attempt < 500 && !relaunched; ++attempt) {
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
            relaunched = launcher.launch(true);
        }
        require(relaunched, "Chat could not reopen after the launcher finished");
        require(!launcher.launch(), "Rapid activation created another terminal");
        // Reap the completed helper before checking its arguments.
        for (int attempt = 0; attempt < 100; ++attempt) {
            launcher.poll();
            std::ifstream calls(helper + ".calls");
            const std::string text((std::istreambuf_iterator<char>(calls)), {});
            if (text == "-m\nblob.desktop\n-m\nblob.desktop\n--conversation\n") break;
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }
        std::ifstream calls(helper + ".calls");
        const std::string text((std::istreambuf_iterator<char>(calls)), {});
        require(text == "-m\nblob.desktop\n-m\nblob.desktop\n--conversation\n",
                "Launch count or conversation arguments changed");
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
        launcher.poll();
    }
    std::filesystem::remove_all(directory);
}
