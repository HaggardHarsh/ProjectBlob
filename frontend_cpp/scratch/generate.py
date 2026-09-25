import os

files = {
    "/home/cloud/ProjectBlob/frontend_cpp/CMakeLists.txt": """cmake_minimum_required(VERSION 3.15)
project(blob_frontend CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(SDL2 REQUIRED)
find_package(OpenGL REQUIRED)

# gRPC and Protobuf
find_package(gRPC CONFIG REQUIRED)
find_package(Protobuf REQUIRED)

# Include directories
include_directories(${SDL2_INCLUDE_DIRS} ${OPENGL_INCLUDE_DIRS})

# Proto generation
set(PROTO_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../proto")
set(PROTO_FILE "${PROTO_DIR}/blob_service.proto")
set(PROTO_SRC "${CMAKE_CURRENT_BINARY_DIR}/blob_service.pb.cc")
set(PROTO_HDR "${CMAKE_CURRENT_BINARY_DIR}/blob_service.pb.h")
set(GRPC_SRC "${CMAKE_CURRENT_BINARY_DIR}/blob_service.grpc.pb.cc")
set(GRPC_HDR "${CMAKE_CURRENT_BINARY_DIR}/blob_service.grpc.pb.h")

add_custom_command(
    OUTPUT ${PROTO_SRC} ${PROTO_HDR} ${GRPC_SRC} ${GRPC_HDR}
    COMMAND ${PROTOBUF_PROTOC_EXECUTABLE}
    ARGS --grpc_out=${CMAKE_CURRENT_BINARY_DIR}
         --cpp_out=${CMAKE_CURRENT_BINARY_DIR}
         --plugin=protoc-gen-grpc=$<TARGET_FILE:gRPC::grpc_cpp_plugin>
         -I ${PROTO_DIR}
         ${PROTO_FILE}
    DEPENDS ${PROTO_FILE}
)

include_directories(${CMAKE_CURRENT_BINARY_DIR})
include_directories(src)

file(GLOB_RECURSE SRC_FILES
    "src/*.cpp"
    "src/*.h"
)

add_executable(blob_overlay ${SRC_FILES} ${PROTO_SRC} ${GRPC_SRC})
target_link_libraries(blob_overlay
    ${SDL2_LIBRARIES}
    ${OPENGL_LIBRARIES}
    gRPC::grpc++
    gRPC::grpc
    protobuf::libprotobuf
)
""",
    "/home/cloud/ProjectBlob/frontend_cpp/src/main.cpp": """#include <iostream>
#include <SDL2/SDL.h>
#include "overlay/window.h"
#include "overlay/renderer.h"
#include "overlay/input.h"
#include "ipc/grpc_client.h"
#include "blob/state_machine.h"
#include "blob/physics.h"
#include "blob/animation.h"
#include "blob/emotes.h"
#include "ui/notification.h"
#include "ui/tray.h"
#include "ui/chat_window.h"

bool running = true;

int main(int argc, char* argv[]) {
    int width = 800;
    int height = 600;
    std::string ipc_address = "unix:///tmp/blob.sock";

    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--width" && i + 1 < argc) width = std::stoi(argv[++i]);
        else if (arg == "--height" && i + 1 < argc) height = std::stoi(argv[++i]);
        else if (arg == "--ipc-address" && i + 1 < argc) ipc_address = argv[++i];
    }

    if (SDL_Init(SDL_INIT_VIDEO | SDL_INIT_EVENTS | SDL_INIT_TIMER) < 0) {
        std::cerr << "Failed to initialize SDL2: " << SDL_GetError() << std::endl;
        return -1;
    }

    OverlayWindow window(width, height);
    Renderer renderer;
    InputHandler input;
    GrpcClient grpc_client(ipc_address);
    BlobStateMachine state_machine;
    BlobPhysics physics;
    AnimationController animation;
    EmoteRenderer emotes;
    NotificationManager notifications;
    SystemTray tray;
    ChatWindow chat_window;

    grpc_client.start();

    Uint32 lastTime = SDL_GetTicks();
    const int FPS = 30;
    const int frameDelay = 1000 / FPS;

    while (running) {
        Uint32 frameStart = SDL_GetTicks();
        float dt = (frameStart - lastTime) / 1000.0f;
        lastTime = frameStart;

        SDL_Event event;
        while (SDL_PollEvent(&event)) {
            if (event.type == SDL_QUIT) running = false;
            auto input_event = input.processEvent(event);
            if (input_event.type != InputEvent::NONE) {
                // pass to state machine or IPC
            }
        }
        
        physics.update(dt);
        state_machine.update(dt);
        animation.update(dt);
        
        renderer.clear();
        physics.getVertices();
        renderer.drawBlobMesh({}, {255, 255, 255, 255});
        renderer.present();

        Uint32 frameTime = SDL_GetTicks() - frameStart;
        if (frameDelay > frameTime) {
            SDL_Delay(frameDelay - frameTime);
        }
    }

    grpc_client.stop();
    SDL_Quit();
    return 0;
}
""",
    "/home/cloud/ProjectBlob/frontend_cpp/src/overlay/window.h": """#pragma once
#include <SDL2/SDL.h>
#include <string>

class OverlayWindow {
public:
    OverlayWindow(int width, int height);
    ~OverlayWindow();

    void makeClickThrough(bool clickThrough);
    SDL_Window* getSDLWindow() const { return window; }
    int getWidth() const { return width; }
    int getHeight() const { return height; }

private:
    SDL_Window* window = nullptr;
    SDL_GLContext glContext;
    int width, height;
};
""",
    "/home/cloud/ProjectBlob/frontend_cpp/src/overlay/window.cpp": """#include "window.h"
#include <iostream>

OverlayWindow::OverlayWindow(int w, int h) : width(w), height(h) {
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_MAJOR_VERSION, 3);
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_MINOR_VERSION, 3);
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_PROFILE_MASK, SDL_GL_CONTEXT_PROFILE_CORE);

    window = SDL_CreateWindow("Blob Overlay",
                              SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED,
                              width, height,
                              SDL_WINDOW_OPENGL | SDL_WINDOW_BORDERLESS | SDL_WINDOW_ALWAYS_ON_TOP | SDL_WINDOW_ALLOW_HIGHDPI);
    
    if (!window) {
        std::cerr << "Window creation failed: " << SDL_GetError() << std::endl;
        return;
    }

    glContext = SDL_GL_CreateContext(window);
    if (!glContext) {
        std::cerr << "GL context creation failed: " << SDL_GetError() << std::endl;
        return;
    }
    
    SDL_EventState(SDL_DROPFILE, SDL_ENABLE);
    makeClickThrough(true);
}

OverlayWindow::~OverlayWindow() {
    if (glContext) SDL_GL_DeleteContext(glContext);
    if (window) SDL_DestroyWindow(window);
}

void OverlayWindow::makeClickThrough(bool clickThrough) {
#ifdef _WIN32
    // Windows specific clickthrough
#elif defined(__linux__)
    // Linux X11/Wayland clickthrough logic
#endif
}
""",
    "/home/cloud/ProjectBlob/frontend_cpp/src/overlay/renderer.h": """#pragma once
#include <vector>
#include <string>

struct Color { unsigned char r, g, b, a; };
struct Vec2 { float x, y; };

class Renderer {
public:
    Renderer();
    ~Renderer();

    void clear();
    void present();

    void drawQuad(float x, float y, float w, float h, Color color);
    void drawCircle(float x, float y, float radius, Color color, int segments);
    void drawBlobMesh(const std::vector<Vec2>& vertices, Color color);
    void drawText(float x, float y, const std::string& text, Color color);
};
""",
    "/home/cloud/ProjectBlob/frontend_cpp/src/overlay/renderer.cpp": """#include "renderer.h"

Renderer::Renderer() {
    // Initialize GL
}

Renderer::~Renderer() {}

void Renderer::clear() {
    // glClear(GL_COLOR_BUFFER_BIT);
}

void Renderer::present() {
    // SDL_GL_SwapWindow
}

void Renderer::drawQuad(float x, float y, float w, float h, Color color) {}
void Renderer::drawCircle(float x, float y, float radius, Color color, int segments) {}
void Renderer::drawBlobMesh(const std::vector<Vec2>& vertices, Color color) {}
void Renderer::drawText(float x, float y, const std::string& text, Color color) {}
""",
    "/home/cloud/ProjectBlob/frontend_cpp/src/overlay/input.h": """#pragma once
#include <SDL2/SDL.h>
#include <string>

struct InputEvent {
    enum Type { NONE, CLICK, DOUBLE_CLICK, PET, POKE, RIGHT_CLICK, DRAG_DROP } type;
    int x, y;
    float velocity;
    std::string filepath;
};

class InputHandler {
public:
    InputHandler();
    InputEvent processEvent(const SDL_Event& event);

private:
    Uint32 lastClickTime = 0;
    bool isDragging = false;
    int dragStartX, dragStartY;
};
""",
    "/home/cloud/ProjectBlob/frontend_cpp/src/overlay/input.cpp": """#include "input.h"

InputHandler::InputHandler() {}

InputEvent InputHandler::processEvent(const SDL_Event& event) {
    InputEvent result = {InputEvent::NONE, 0, 0, 0.0f, ""};
    if (event.type == SDL_MOUSEBUTTONDOWN) {
        result.type = InputEvent::CLICK;
        result.x = event.button.x;
        result.y = event.button.y;
    } else if (event.type == SDL_DROPFILE) {
        result.type = InputEvent::DRAG_DROP;
        result.filepath = event.drop.file;
        SDL_free(event.drop.file);
    }
    return result;
}
""",
    "/home/cloud/ProjectBlob/frontend_cpp/src/blob/state_machine.h": """#pragma once

enum class BlobState {
    IDLE, CRAWLING, SLEEPING, EATING, DIVIDING, MERGING, BLINDFOLDED, THINKING, BOUNCING
};

class BlobStateMachine {
public:
    BlobStateMachine();
    void update(float dt);
    void changeState(BlobState newState);
    BlobState getCurrentState() const { return currentState; }

private:
    BlobState currentState = BlobState::IDLE;
    float stateTime = 0.0f;
};
""",
    "/home/cloud/ProjectBlob/frontend_cpp/src/blob/state_machine.cpp": """#include "state_machine.h"

BlobStateMachine::BlobStateMachine() {}

void BlobStateMachine::update(float dt) {
    stateTime += dt;
}

void BlobStateMachine::changeState(BlobState newState) {
    currentState = newState;
    stateTime = 0.0f;
}
""",
    "/home/cloud/ProjectBlob/frontend_cpp/src/blob/physics.h": """#pragma once
#include <vector>
#include "../overlay/renderer.h"

class BlobPhysics {
public:
    BlobPhysics();
    void update(float dt);
    std::vector<Vec2> getVertices() const;
    void applyForce(Vec2 force);
    void jiggle();
    void squash(float amount);

private:
    std::vector<Vec2> vertices;
};
""",
    "/home/cloud/ProjectBlob/frontend_cpp/src/blob/physics.cpp": """#include "physics.h"

BlobPhysics::BlobPhysics() {}

void BlobPhysics::update(float dt) {}
std::vector<Vec2> BlobPhysics::getVertices() const { return vertices; }
void BlobPhysics::applyForce(Vec2 force) {}
void BlobPhysics::jiggle() {}
void BlobPhysics::squash(float amount) {}
""",
    "/home/cloud/ProjectBlob/frontend_cpp/src/blob/animation.h": """#pragma once

class AnimationController {
public:
    AnimationController();
    void update(float dt);

private:
    float time = 0.0f;
};
""",
    "/home/cloud/ProjectBlob/frontend_cpp/src/blob/animation.cpp": """#include "animation.h"

AnimationController::AnimationController() {}
void AnimationController::update(float dt) { time += dt; }
""",
    "/home/cloud/ProjectBlob/frontend_cpp/src/blob/emotes.h": """#pragma once

class EmoteRenderer {
public:
    EmoteRenderer();
    void render();
};
""",
    "/home/cloud/ProjectBlob/frontend_cpp/src/blob/emotes.cpp": """#include "emotes.h"

EmoteRenderer::EmoteRenderer() {}
void EmoteRenderer::render() {}
""",
    "/home/cloud/ProjectBlob/frontend_cpp/src/ipc/grpc_client.h": """#pragma once
#include <string>

class GrpcClient {
public:
    GrpcClient(const std::string& address);
    ~GrpcClient();
    void start();
    void stop();

private:
    std::string address;
};
""",
    "/home/cloud/ProjectBlob/frontend_cpp/src/ipc/grpc_client.cpp": """#include "grpc_client.h"

GrpcClient::GrpcClient(const std::string& addr) : address(addr) {}
GrpcClient::~GrpcClient() {}
void GrpcClient::start() {}
void GrpcClient::stop() {}
""",
    "/home/cloud/ProjectBlob/frontend_cpp/src/ipc/event_queue.h": """#pragma once
#include <mutex>
#include <queue>
#include <optional>
#include <vector>

template <typename T>
class EventQueue {
public:
    void push(T event) {
        std::lock_guard<std::mutex> lock(mtx);
        q.push(event);
    }
    
    std::optional<T> tryPop() {
        std::lock_guard<std::mutex> lock(mtx);
        if (q.empty()) return std::nullopt;
        T val = q.front();
        q.pop();
        return val;
    }
    
    std::vector<T> popAll() {
        std::lock_guard<std::mutex> lock(mtx);
        std::vector<T> res;
        while (!q.empty()) {
            res.push_back(q.front());
            q.pop();
        }
        return res;
    }

private:
    std::queue<T> q;
    std::mutex mtx;
};
""",
    "/home/cloud/ProjectBlob/frontend_cpp/src/ipc/event_queue.cpp": """#include "event_queue.h"
// Template class, fully implemented in header.
""",
    "/home/cloud/ProjectBlob/frontend_cpp/src/ui/notification.h": """#pragma once
#include <string>

class NotificationManager {
public:
    NotificationManager();
    void show(const std::string& text);
    void update(float dt);
    void render();
};
""",
    "/home/cloud/ProjectBlob/frontend_cpp/src/ui/notification.cpp": """#include "notification.h"

NotificationManager::NotificationManager() {}
void NotificationManager::show(const std::string& text) {}
void NotificationManager::update(float dt) {}
void NotificationManager::render() {}
""",
    "/home/cloud/ProjectBlob/frontend_cpp/src/ui/tray.h": """#pragma once

class SystemTray {
public:
    SystemTray();
    ~SystemTray();
};
""",
    "/home/cloud/ProjectBlob/frontend_cpp/src/ui/tray.cpp": """#include "tray.h"

SystemTray::SystemTray() {}
SystemTray::~SystemTray() {}
""",
    "/home/cloud/ProjectBlob/frontend_cpp/src/ui/chat_window.h": """#pragma once

class ChatWindow {
public:
    ChatWindow();
    void render();
};
""",
    "/home/cloud/ProjectBlob/frontend_cpp/src/ui/chat_window.cpp": """#include "chat_window.h"

ChatWindow::ChatWindow() {}
void ChatWindow::render() {}
"""
}

for path, content in files.items():
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
