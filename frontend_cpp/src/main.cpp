#include <iostream>
#include <cstdlib>
#include <ctime>
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

static bool running = true;

int main(int argc, char* argv[]) {
    std::srand((unsigned)std::time(nullptr));

    int width  = 200;
    int height = 200;
    std::string ipc_address = "localhost:50051";

    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--width"       && i + 1 < argc) width  = std::stoi(argv[++i]);
        else if (arg == "--height" && i + 1 < argc) height = std::stoi(argv[++i]);
        else if (arg == "--ipc-address" && i + 1 < argc) ipc_address = argv[++i];
    }

    if (SDL_Init(SDL_INIT_VIDEO | SDL_INIT_EVENTS | SDL_INIT_TIMER) < 0) {
        std::cerr << "Failed to initialize SDL2: " << SDL_GetError() << std::endl;
        return -1;
    }

    // ── Create window & renderer ──
    OverlayWindow window(width, height);
    Renderer renderer(window.getSDLWindow(), width, height);
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
    const int FPS = 60;
    const int frameDelay = 1000 / FPS;

    // Idle jiggle timer
    float jiggleTimer = 0.0f;
    float nextJiggle  = 2.0f + (std::rand() % 300) / 100.0f;

    while (running) {
        Uint32 frameStart = SDL_GetTicks();
        float dt = (float)(frameStart - lastTime) / 1000.0f;
        lastTime = frameStart;

        // ── Event loop ──
        SDL_Event event;
        while (SDL_PollEvent(&event)) {
            if (event.type == SDL_QUIT) {
                running = false;
            }
            else if (event.type == SDL_MOUSEBUTTONDOWN && event.button.button == SDL_BUTTON_LEFT) {
                int gx, gy;
                SDL_GetGlobalMouseState(&gx, &gy);
                window.startDrag(gx, gy);
                // Give the blob a little poke jiggle
                physics.jiggle();
            }
            else if (event.type == SDL_MOUSEMOTION) {
                if (window.isDragging()) {
                    int gx, gy;
                    SDL_GetGlobalMouseState(&gx, &gy);
                    window.updateDrag(gx, gy);
                }
            }
            else if (event.type == SDL_MOUSEBUTTONUP && event.button.button == SDL_BUTTON_LEFT) {
                window.stopDrag();
            }
            else if (event.type == SDL_KEYDOWN && event.key.keysym.sym == SDLK_ESCAPE) {
                running = false;
            }

            // Process other input events (drag-drop, etc.)
            auto input_event = input.processEvent(event);
            (void)input_event; // will be wired to IPC later
        }

        // ── Physics & animation ──
        physics.update(dt);
        state_machine.update(dt);
        animation.update(dt);

        // Periodic idle jiggle
        jiggleTimer += dt;
        if (jiggleTimer >= nextJiggle) {
            physics.jiggle();
            jiggleTimer = 0.0f;
            nextJiggle = 2.0f + (std::rand() % 300) / 100.0f;
        }

        // ── Render ──
        renderer.clear();

        auto vertices = physics.getVertices();
        Vec2 center   = physics.getCenter();
        float radius  = physics.getRadius();

        // Cute slime-green body
        renderer.drawBlobMesh(vertices, {60, 210, 90, 255});

        // Face
        float time = (float)SDL_GetTicks() / 1000.0f;
        renderer.drawEyes(center.x, center.y, radius, time);
        renderer.drawMouth(center.x, center.y, radius, time);

        renderer.present();

        // ── Update window shape (transparency mask) ──
        window.updateShape(renderer.getShapeSurface());

        // ── Frame-rate limiter ──
        Uint32 frameTime = SDL_GetTicks() - frameStart;
        if (frameDelay > (int)frameTime) {
            SDL_Delay(frameDelay - frameTime);
        }
    }

    grpc_client.stop();
    SDL_Quit();
    return 0;
}
