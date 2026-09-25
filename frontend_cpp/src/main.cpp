#include <iostream>
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
