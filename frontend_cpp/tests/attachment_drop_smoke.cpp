#include "ipc/grpc_client.h"
#include "overlay/input.h"
#include <atomic>
#include <chrono>
#include <iostream>
#include <stdexcept>
#include <thread>

class TestBackend : public blob::BlobService::Service {
public:
    TestBackend() {
        grpc::ServerBuilder builder;
        builder.AddListeningPort("127.0.0.1:0", grpc::InsecureServerCredentials(), &port);
        builder.RegisterService(this);
        server = builder.BuildAndStart();
        if (!server || !port) throw std::runtime_error("Test backend couldn't listen");
    }
    ~TestBackend() { server->Shutdown(); server->Wait(); }
    grpc::Status EventStream(grpc::ServerContext*, grpc::ServerReaderWriter<blob::BackendEvent, blob::FrontendEvent>* stream) override {
        blob::FrontendEvent event;
        while (stream->Read(&event)) {
            if (!event.has_attachment_drop()) continue;
            const auto& files = event.attachment_drop().file_paths();
            valid = files.size() == 2 && files[0] == "/tmp/lesson.pdf" && files[1] == "/tmp/diagram.png";
            blob::BackendEvent response;
            response.mutable_notification()->set_text("Files received for terminal analysis.");
            if (!stream->Write(response)) break;
        }
        return grpc::Status::OK;
    }
    int port = 0;
    std::atomic<bool> valid{false};
private:
    std::unique_ptr<grpc::Server> server;
};

InputEvent drop(InputHandler& input, const char* path) {
    SDL_Event event{};
    event.type = SDL_DROPFILE;
    event.drop.file = SDL_strdup(path);
    return input.processEvent(event);
}

int main() {
    try {
        InputHandler input;
        SDL_Event event{};
        event.type = SDL_DROPBEGIN;
        input.processEvent(event);
        if (drop(input, "/tmp/lesson.pdf").type != InputEvent::NONE)
            throw std::runtime_error("A multi-file drop was sent before completion");
        auto skill = drop(input, "/tmp/example.skill.yaml");
        if (skill.type != InputEvent::DRAG_DROP || skill.filepath != "/tmp/example.skill.yaml")
            throw std::runtime_error("Skill installation wasn't preserved");
        drop(input, "/tmp/diagram.png");
        event.type = SDL_DROPCOMPLETE;
        auto files = input.processEvent(event);
        if (files.type != InputEvent::ATTACHMENT_DROP || files.attachments.size() != 2)
            throw std::runtime_error("The file batch wasn't collected");
        auto single = drop(input, "/tmp/one.pdf");
        if (single.type != InputEvent::ATTACHMENT_DROP || single.attachments.size() != 1)
            throw std::runtime_error("A standalone file drop wasn't handled");

        TestBackend backend;
        GrpcClient client("127.0.0.1:" + std::to_string(backend.port));
        client.start();
        auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
        while (!client.isConnected() && std::chrono::steady_clock::now() < deadline)
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        if (!client.isConnected() || client.attachFiles({}) || !client.attachFiles(files.attachments))
            throw std::runtime_error("Couldn't send the dropped files");
        bool received = false;
        while (std::chrono::steady_clock::now() < deadline) {
            auto reply = client.pollEvent();
            if (reply && reply->has_notification()) { received = true; break; }
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }
        client.stop();
        if (!received || !backend.valid) throw std::runtime_error("The dropped files didn't reach the backend");
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
    return 0;
}
