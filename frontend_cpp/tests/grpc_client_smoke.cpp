#include "ipc/grpc_client.h"

#include <chrono>
#include <iostream>
#include <thread>

int main(int argc, char** argv) {
    if (argc < 2 || argc > 3) {
        std::cerr << "Usage: blob_ipc_smoke <gRPC address> [skill file]\n";
        return 2;
    }
    GrpcClient client(argv[1]);
    client.start();
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(8);
    while (!client.isConnected() && std::chrono::steady_clock::now() < deadline) {
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }
    if (!client.isConnected()) {
        std::cerr << "Client did not connect\n";
        client.stop();
        return 1;
    }
    if (argc == 3) {
        const std::string mode(argv[2]);
        if (mode == "--mute" || mode == "--quiet") {
            client.proactiveControl(mode == "--quiet");
            while (client.proactiveControlPending() && std::chrono::steady_clock::now() < deadline)
                std::this_thread::sleep_for(std::chrono::milliseconds(20));
            const bool completed = !client.proactiveControlPending();
            client.stop();
            return completed ? 0 : 1;
        }
        if (!client.installSkill(argv[2])) return 1;
        bool installed = false;
        while (std::chrono::steady_clock::now() < deadline) {
            auto event = client.pollEvent();
            if (event && event->has_skill_ack()) {
                installed = event->skill_ack().success();
                break;
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(20));
        }
        if (!installed) {
            std::cerr << "Skill was not acknowledged\n";
            client.stop();
            return 1;
        }
    }
    if (!client.sendMessage("/camera list")) {
        std::cerr << "Client did not connect or queue a message\n";
        client.stop();
        return 1;
    }
    while (std::chrono::steady_clock::now() < deadline) {
        auto event = client.pollEvent();
        if (event && event->has_notification()) {
            std::cout << event->notification().text() << '\n';
            client.stop();
            return 0;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }
    client.stop();
    std::cerr << "No notification received\n";
    return 1;
}
