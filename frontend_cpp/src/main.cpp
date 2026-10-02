#include <iostream>
#include <cstdlib>
#include <algorithm>
#include <cmath>
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
#include "ui/chat.h"

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
        case blob::EmoteCommand::WORKING: return BlobExpression::WORKING;
        case blob::EmoteCommand::DEEP_THINKING: return BlobExpression::DEEP_THINKING;
        case blob::EmoteCommand::LISTENING: return BlobExpression::LISTENING;
        case blob::EmoteCommand::SHOCKED: return BlobExpression::SHOCKED;
        case blob::EmoteCommand::MELTING: return BlobExpression::MELTING;
        case blob::EmoteCommand::ERROR: return BlobExpression::ERROR;
        case blob::EmoteCommand::SUCCESS: return BlobExpression::SUCCESS;
        case blob::EmoteCommand::WAITING: return BlobExpression::WAITING;
        default: return BlobExpression::IDLE;
    }
}

int main(int argc, char* argv[]) {
    int width  = 132;
    int height = 116;
    std::string ipc_address = "localhost:50051";
    bool open_chat = false;

    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--width"       && i + 1 < argc) width  = std::stoi(argv[++i]);
        else if (arg == "--height" && i + 1 < argc) height = std::stoi(argv[++i]);
        else if (arg == "--ipc-address" && i + 1 < argc) ipc_address = argv[++i];
        else if (arg == "--chat") open_chat = true;
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
    ChatPanel chat(grpc_client);
    BlobStateMachine state_machine;
    BlobPhysics physics(width, height);
    AnimationController animation;
    SystemTray tray;

    grpc_client.start();
    if (open_chat) chat.show();

    Uint32 lastTime = SDL_GetTicks();
    const int FPS = 60;
    const int frameDelay = 1000 / FPS;

    bool privacyActive = false;
    BlobExpression expression = BlobExpression::IDLE;
    Uint32 expressionUntil = 0;
    Uint32 speakingUntil = 0;

    while (running) {
        Uint32 frameStart = SDL_GetTicks();
        float dt = (float)(frameStart - lastTime) / 1000.0f;
        lastTime = frameStart;

        // ── Event loop ──
        SDL_Event event;
        while (SDL_PollEvent(&event)) {
            if (event.type == SDL_DROPFILE) {
                auto input_event = input.processEvent(event);
                const std::string& path = input_event.filepath;
                if (path.size() >= 11 && path.substr(path.size() - 11) == ".skill.yaml") {
                    chat.addNotice(grpc_client.installSkill(path) ? "Installing skill..." :
                        "Could not queue skill installation. Start the backend and try again.");
                } else chat.addAttachment(path);
                continue;
            }
            if (chat.processEvent(event)) continue;
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
                chat.toggle();
            }
            else if (event.type == SDL_MOUSEBUTTONDOWN &&
                     event.button.windowID == SDL_GetWindowID(window.getSDLWindow()) &&
                     event.button.button == SDL_BUTTON_LEFT && event.button.clicks >= 2) {
                physics.jiggle();
                window.stopDrag();
                chat.show();
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

        }

        tray.poll();
        if (tray.takeActivated()) { physics.jiggle(); chat.toggle(); }
        while (auto event = grpc_client.pollEvent()) {
            if (event->has_skill_ack()) {
                const auto& ack = event->skill_ack();
                expression = ack.success() ? BlobExpression::SUCCESS : BlobExpression::ERROR;
                expressionUntil = SDL_GetTicks() + 1800;
                animation.setExpression(expression, ack.success() ? 0.5f : 0.7f);
                animation.setBlend(BlobExpression::IDLE, 0.0f);
                if (ack.success()) physics.jiggle();
                chat.addNotice(ack.success() ? ack.description() : ack.error_message());
            } else if (event->has_chat_reply()) {
                chat.receiveReply(event->chat_reply().request_id(), event->chat_reply().text());
            } else if (event->has_emote()) {
                const auto emote = event->emote().emote();
                expression = expressionFor(emote);
                animation.setExpression(expression,
                    event->emote().intensity() > 0.0f ? event->emote().intensity() : 0.55f);
                animation.setBlend(expressionFor(event->emote().secondary_emote()),
                                   event->emote().blend());
                expressionUntil = (expression == BlobExpression::THINKING ||
                                   expression == BlobExpression::DEEP_THINKING ||
                                   expression == BlobExpression::WORKING ||
                                   expression == BlobExpression::WAITING) ? 0 :
                    SDL_GetTicks() + (event->emote().duration_ms() ? event->emote().duration_ms() : 3500);
                if (privacyActive) state_machine.changeState(BlobState::BLINDFOLDED);
                else if (emote == blob::EmoteCommand::THINKING) state_machine.changeState(BlobState::THINKING);
                else if (emote == blob::EmoteCommand::EATING) state_machine.changeState(BlobState::EATING);
                else state_machine.changeState(BlobState::IDLE);
                if (emote == blob::EmoteCommand::HAPPY || emote == blob::EmoteCommand::EXCITED ||
                    emote == blob::EmoteCommand::CELEBRATE) physics.jiggle();
            } else if (event->has_notification()) {
                const size_t length = event->notification().text().size();
                speakingUntil = SDL_GetTicks() + Uint32(std::clamp<size_t>(length * 33, 650, 2400));
            } else if (event->has_privacy()) {
                privacyActive = event->privacy().activated();
                state_machine.changeState(privacyActive ? BlobState::BLINDFOLDED : BlobState::IDLE);
            }
        }
        if (expressionUntil && SDL_TICKS_PASSED(SDL_GetTicks(), expressionUntil)) {
            if (expression == BlobExpression::MELTING || expression == BlobExpression::MELTED) {
                expression = BlobExpression::RECOVERING;
                animation.setExpression(expression, 0.65f);
                expressionUntil = SDL_GetTicks() + 1000;
            } else {
                expression = BlobExpression::IDLE;
                animation.setExpression(expression);
                animation.setBlend(BlobExpression::IDLE, 0.0f);
                expressionUntil = 0;
                if (!privacyActive) state_machine.changeState(BlobState::IDLE);
            }
        }

        // ── Physics & animation ──
        state_machine.update(dt);
        animation.update(dt);
        BlobPose pose = animation.pose();
        if (speakingUntil && SDL_TICKS_PASSED(SDL_GetTicks(), speakingUntil)) speakingUntil = 0;
        if (speakingUntil) {
            pose.mouthOpen = std::max(pose.mouthOpen,
                0.22f + 0.42f * (0.5f + 0.5f * std::sin(SDL_GetTicks() * 0.015f)));
        }
        physics.setPose(pose);
        physics.update(dt);

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

        // 3) One soft highlight
        renderer.drawHighlights(center.x, center.y, rx, ry);

        renderer.drawDetails(center.x, center.y, rx, ry, time, pose);

        // 4) The expression sent by the backend
        renderer.drawFace(center.x, center.y, rx, ry, time,
                          state_machine.getCurrentState(), pose);

        renderer.present();

        // ── Transparency mask ──
        renderer.stampShape(vertices, center.x, center.y);
        window.updateShape(renderer.getShapeSurface());
        chat.render();

        // ── Frame-rate cap ──
        Uint32 frameTime = SDL_GetTicks() - frameStart;
        if (frameDelay > (int)frameTime) {
            SDL_Delay(frameDelay - frameTime);
        }
    }

    grpc_client.stop();
    chat.close();
    SDL_Quit();
    return 0;
}
