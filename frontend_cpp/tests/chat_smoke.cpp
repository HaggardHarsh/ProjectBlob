#include "ui/chat.h"
#include "ipc/grpc_client.h"
#include <SDL2/SDL.h>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <atomic>
#include <chrono>
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
        blob::FrontendEvent request;
        while (stream->Read(&request)) {
            if (!request.has_user_message()) continue;
            const auto& message = request.user_message();
            valid = message.text() == "Explain page 1: caf" && message.attachments_size() == 1 && !message.request_id().empty();
            blob::BackendEvent response;
            response.mutable_chat_reply()->set_request_id(message.request_id());
            response.mutable_chat_reply()->set_text("lesson.pdf, page 1: Voltage equals current times resistance.\n\nFor example, 2 amps through a 10 ohm resistor gives 20 volts.");
            if (!stream->Write(response)) break;
        }
        return grpc::Status::OK;
    }
    int port = 0;
    std::atomic<bool> valid{false};
private:
    std::unique_ptr<grpc::Server> server;
};

int main() {
    if (SDL_Init(SDL_INIT_VIDEO | SDL_INIT_EVENTS) != 0) return 1;
    int result = 0;
    try {
        TestBackend backend;
        GrpcClient client("127.0.0.1:" + std::to_string(backend.port));
        client.start();
        auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
        while (!client.isConnected() && std::chrono::steady_clock::now() < deadline)
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        if (!client.isConnected()) throw std::runtime_error("Test client couldn't connect");
        ChatPanel chat(client);
        chat.show();
        if (!chat.isVisible() || !chat.windowId()) throw std::runtime_error("Chat didn't open");
        std::filesystem::path path = std::filesystem::temp_directory_path() / "blob_chat_smoke.pdf";
        { std::ofstream file(path); file << "%PDF-test"; }
        chat.addAttachment(path.string());
        chat.addAttachment(path.string());
        if (chat.attachments().size() != 1) throw std::runtime_error("Attachment duplicate");
        SDL_Event event{};
        event.type = SDL_TEXTINPUT; event.text.windowID = chat.windowId();
        SDL_strlcpy(event.text.text, "Explain page 1: café", sizeof(event.text.text));
        if (!chat.processEvent(event)) throw std::runtime_error("Input wasn't handled");
        event.type = SDL_KEYDOWN; event.key.windowID = chat.windowId();
        event.key.keysym.sym = SDLK_BACKSPACE; chat.processEvent(event);
        event.key.keysym.sym = SDLK_RETURN; chat.processEvent(event);
        if (!chat.isPending()) throw std::runtime_error("Submission wasn't sent");
        chat.receiveReply("other-request", "Unrelated reply");
        if (!chat.isPending()) throw std::runtime_error("Unrelated reply finished the submission");
        while (chat.isPending() && std::chrono::steady_clock::now() < deadline) {
            auto reply = client.pollEvent();
            if (reply && reply->has_chat_reply())
                chat.receiveReply(reply->chat_reply().request_id(), reply->chat_reply().text());
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }
        if (chat.isPending() || !backend.valid) throw std::runtime_error("Attachment/reply round trip failed");
        chat.render();
        if (const char* preview = std::getenv("BLOB_CHAT_PREVIEW")) {
            SDL_Window* window = SDL_GetWindowFromID(chat.windowId());
            SDL_Surface* surface = SDL_CreateRGBSurfaceWithFormat(0, 560, 680, 32, SDL_PIXELFORMAT_RGBA32);
            SDL_RenderReadPixels(SDL_GetRenderer(window), nullptr, surface->format->format, surface->pixels, surface->pitch);
            SDL_SaveBMP(surface, preview); SDL_FreeSurface(surface);
        }
        chat.addNotice("A long answer with page references.\nPDF page 1: a² + b² = c²\n" + std::string(5000, 'x'));
        chat.render();
        event.type = SDL_MOUSEBUTTONDOWN; event.button.windowID = chat.windowId();
        event.button.button = SDL_BUTTON_LEFT; event.button.x = 42; event.button.y = 650;
        chat.processEvent(event); chat.render();  // Exercise the file browser.
        event.type = SDL_WINDOWEVENT; event.window.windowID = chat.windowId();
        event.window.event = SDL_WINDOWEVENT_CLOSE; chat.processEvent(event);
        if (chat.isVisible()) throw std::runtime_error("Chat didn't hide");
        chat.show(); chat.render(); chat.close();
        client.stop();
        std::filesystem::remove(path);
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; result = 1; }
    SDL_Quit();
    return result;
}
