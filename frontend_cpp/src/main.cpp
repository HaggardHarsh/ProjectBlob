#include <iostream>
#include <cstdlib>
#include <ctime>
#include <string>
#include <SDL2/SDL.h>
#include "overlay/window.h"
#include "overlay/renderer.h"
#include "overlay/input.h"
#include "ipc/grpc_client.h"
#include "blob/state_machine.h"
#include "blob/physics.h"
#include "blob/animation.h"
#include "ui/tray.h"

static bool running = true;

static BlobExpression expressionFor(blob::EmoteCommand::Emote emote) {
    switch (emote) {
        case blob::EmoteCommand::HAPPY: return BlobExpression::HAPPY;
        case blob::EmoteCommand::EXCITED: return BlobExpression::EXCITED;
        case blob::EmoteCommand::CELEBRATE: return BlobExpression::CELEBRATE;
        case blob::EmoteCommand::THINKING: return BlobExpression::THINKING;
        case blob::EmoteCommand::WORRIED: return BlobExpression::WORRIED;
        case blob::EmoteCommand::SAD: return BlobExpression::SAD;
        case blob::EmoteCommand::ANGRY: return BlobExpression::ANGRY;
        case blob::EmoteCommand::CONFUSED: return BlobExpression::CONFUSED;
        case blob::EmoteCommand::SHY: return BlobExpression::SHY;
        case blob::EmoteCommand::SLEEPING: return BlobExpression::SLEEPING;
        case blob::EmoteCommand::TIRED: return BlobExpression::TIRED;
        case blob::EmoteCommand::EATING: return BlobExpression::EATING;
        case blob::EmoteCommand::PROUD: return BlobExpression::PROUD;
        case blob::EmoteCommand::PLAYFUL: return BlobExpression::PLAYFUL;
        default: return BlobExpression::IDLE;
    }
}

int main(int argc, char* argv[]) {
    std::srand((unsigned)std::time(nullptr));

    int width  = 180;
    int height = 150;
    std::string ipc_address = "localhost:50051";

    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--width"       && i + 1 < argc) width  = std::stoi(argv[++i]);
        else if (arg == "--height" && i + 1 < argc) height = std::stoi(argv[++i]);
        else if (arg == "--ipc-address" && i + 1 < argc) ipc_address = argv[++i];
    }

    // On Linux systems with Wayland/XWayland, SDL2 defaults to the native Wayland
    // driver which prohibits desktop overlay positioning (SDL_SetWindowPosition is a no-op
    // and SDL_GetGlobalMouseState returns 0,0). Prefer X11/XWayland when DISPLAY is present.
    if (!std::getenv("SDL_VIDEODRIVER") && std::getenv("DISPLAY")) {
        setenv("SDL_VIDEODRIVER", "x11", 1);
    }

    if (SDL_Init(SDL_INIT_VIDEO | SDL_INIT_EVENTS | SDL_INIT_TIMER) < 0) {
        std::cerr << "Failed to initialize SDL2: " << SDL_GetError() << std::endl;
        return -1;
    }

    OverlayWindow window(width, height);
    Renderer renderer(window.getSDLWindow(), width, height);
    InputHandler input;
    GrpcClient grpc_client(ipc_address);
    BlobStateMachine state_machine;
    BlobPhysics physics(width, height);
    AnimationController animation;
    SystemTray tray;

    grpc_client.start();

    Uint32 lastTime = SDL_GetTicks();
    const int FPS = 60;
    const int frameDelay = 1000 / FPS;

    // Idle jiggle timer
    float jiggleTimer = 0.0f;
    float nextJiggle  = 3.0f + (std::rand() % 400) / 100.0f;
    bool privacyActive = false;
    BlobExpression expression = BlobExpression::IDLE;
    Uint32 expressionUntil = 0;

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
            else if (event.type == SDL_WINDOWEVENT &&
                     event.window.event == SDL_WINDOWEVENT_CLOSE &&
                     event.window.windowID == SDL_GetWindowID(window.getSDLWindow())) {
                running = false;
            }
            else if (event.type == SDL_MOUSEBUTTONDOWN &&
                     event.button.windowID == SDL_GetWindowID(window.getSDLWindow()) &&
                     event.button.button == SDL_BUTTON_RIGHT) {
                physics.jiggle();
            }
            else if (event.type == SDL_MOUSEBUTTONDOWN &&
                     event.button.windowID == SDL_GetWindowID(window.getSDLWindow()) &&
                     event.button.button == SDL_BUTTON_LEFT && event.button.clicks >= 2) {
                physics.jiggle();
            }
            else if (event.type == SDL_MOUSEBUTTONDOWN &&
                     event.button.windowID == SDL_GetWindowID(window.getSDLWindow()) &&
                     event.button.button == SDL_BUTTON_LEFT) {
                int gx, gy;
                SDL_GetGlobalMouseState(&gx, &gy);
                window.startDrag(gx, gy);
                physics.jiggle();   // poke reaction
            }
            else if (event.type == SDL_MOUSEMOTION &&
                     event.motion.windowID == SDL_GetWindowID(window.getSDLWindow())) {
                if (window.isDragging()) {
                    int gx, gy;
                    SDL_GetGlobalMouseState(&gx, &gy);
                    if (gx != 0 || gy != 0) {
                        window.updateDrag(gx, gy);
                    } else {
                        // Fallback to relative motion delta if global mouse state query is restricted
                        window.updateDragRelative(event.motion.xrel, event.motion.yrel);
                    }
                }
            }
            else if (event.type == SDL_MOUSEBUTTONUP &&
                     event.button.windowID == SDL_GetWindowID(window.getSDLWindow()) &&
                     event.button.button == SDL_BUTTON_LEFT) {
                window.stopDrag();
            }
            else if (event.type == SDL_KEYDOWN &&
                     event.key.windowID == SDL_GetWindowID(window.getSDLWindow()) &&
                     event.key.keysym.sym == SDLK_ESCAPE) {
                running = false;
            }

            if (event.type == SDL_DROPFILE) {
                auto input_event = input.processEvent(event);
                const std::string& path = input_event.filepath;
                if (path.size() >= 11 && path.substr(path.size() - 11) == ".skill.yaml") {
                    std::cout << (grpc_client.installSkill(path) ? "Installing skill pill...\n" :
                                  "Could not queue skill installation. Start the backend and try again.\n");
                } else {
                    std::cout << "Drop a .skill.yaml file to install a skill.\n";
                }
            }
        }

        tray.poll();
        if (tray.takeActivated()) physics.jiggle();
        while (auto event = grpc_client.pollEvent()) {
            if (event->has_skill_ack()) {
                const auto& ack = event->skill_ack();
                if (ack.success()) physics.jiggle();
            } else if (event->has_emote()) {
                const auto emote = event->emote().emote();
                expression = expressionFor(emote);
                expressionUntil = expression == BlobExpression::THINKING ? 0 :
                    SDL_GetTicks() + (event->emote().duration_ms() ? event->emote().duration_ms() : 3500);
                if (privacyActive) state_machine.changeState(BlobState::BLINDFOLDED);
                else if (emote == blob::EmoteCommand::THINKING) state_machine.changeState(BlobState::THINKING);
                else if (emote == blob::EmoteCommand::EATING) state_machine.changeState(BlobState::EATING);
                else state_machine.changeState(BlobState::IDLE);
                if (emote == blob::EmoteCommand::HAPPY || emote == blob::EmoteCommand::EXCITED ||
                    emote == blob::EmoteCommand::CELEBRATE) physics.jiggle();
            } else if (event->has_privacy()) {
                privacyActive = event->privacy().activated();
                state_machine.changeState(privacyActive ? BlobState::BLINDFOLDED : BlobState::IDLE);
            }
        }
        if (expressionUntil && SDL_TICKS_PASSED(SDL_GetTicks(), expressionUntil)) {
            expression = BlobExpression::IDLE;
            expressionUntil = 0;
            if (!privacyActive) state_machine.changeState(BlobState::IDLE);
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
            nextJiggle = 3.0f + (std::rand() % 400) / 100.0f;
        }

        // ── Render (layered, back to front) ──
        renderer.clear();

        auto vertices = physics.getVertices();
        Vec2 center   = physics.getCenter();
        float rx      = physics.getRadiusX();
        float ry      = physics.getRadiusY();
        float time    = (float)SDL_GetTicks() / 1000.0f;

        // 1) Translucent rounded body
        renderer.drawOuterBody(vertices);

        // 2) Thin blue outline
        renderer.drawOutline(vertices);

        // 3) Soft interior depth
        renderer.drawInnerBody(center.x, center.y, rx, ry, time);

        // 4) White specular highlights
        renderer.drawHighlights(center.x, center.y, rx, ry);

        // 5) The expression sent by the backend
        renderer.drawFace(center.x, center.y, rx, ry, time,
                          state_machine.getCurrentState(), expression);

        renderer.present();

        // ── Transparency mask ──
        renderer.stampShape(vertices, center.x, center.y);
        window.updateShape(renderer.getShapeSurface());

        // ── Frame-rate cap ──
        Uint32 frameTime = SDL_GetTicks() - frameStart;
        if (frameDelay > (int)frameTime) {
            SDL_Delay(frameDelay - frameTime);
        }
    }

    grpc_client.stop();
    SDL_Quit();
    return 0;
}
