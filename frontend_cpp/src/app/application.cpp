#include "app/application.h"
#include "app/settings.h"
#include "ui/tray.h"
#include "overlay/window.h"
#include "overlay/renderer.h"
#include "overlay/input.h"
#include "blob/animation.h"
#include "blob/physics.h"
#include "ipc/grpc_client.h"
#include <SDL2/SDL.h>
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdlib>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>
#ifdef __linux__
#include <unistd.h>
#include <sys/wait.h>
#endif

static void openChat() {
#ifdef __linux__
    const pid_t launcher = fork();
    if (launcher == 0) {
        const pid_t child = fork();
        if (child == 0) {
            const char* python = std::getenv("BLOB_CHAT_PYTHON");
            if (!python) python = access("venv/bin/python", X_OK) == 0 ? "venv/bin/python" : "python3";
            execlp(python, python, "-m", "blob.desktop", static_cast<char*>(nullptr));
            _exit(127);
        }
        _exit(child < 0 ? 1 : 0);
    }
    if (launcher > 0) waitpid(launcher, nullptr, 0);
#endif
}


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

namespace {
struct DesktopStatus { bool connected = false, shield = true, paused = false; };
struct SdlRuntime {
    SdlRuntime() {
        if (!std::getenv("SDL_VIDEODRIVER") && std::getenv("DISPLAY")) SDL_setenv("SDL_VIDEODRIVER", "x11", 0);
        if (SDL_Init(SDL_INIT_VIDEO | SDL_INIT_EVENTS | SDL_INIT_TIMER)) throw std::runtime_error(SDL_GetError());
    }
    ~SdlRuntime() { SDL_Quit(); }
};
int number(const std::string& text, int minimum, int maximum) {
    size_t length = 0;
    const int value = std::stoi(text, &length);
    if (length != text.size() || value < minimum || value > maximum) throw std::invalid_argument("Window or frame option is out of range");
    return value;
}
void snapshot(SDL_Renderer* renderer, const std::string& path) {
    int w = 0, h = 0; SDL_GetRendererOutputSize(renderer, &w, &h);
    SDL_Surface* surface = SDL_CreateRGBSurfaceWithFormat(0, w, h, 32, SDL_PIXELFORMAT_RGBA32);
    if (!surface) throw std::runtime_error("Could not allocate preview");
    const bool failed = SDL_RenderReadPixels(renderer, nullptr, surface->format->format, surface->pixels, surface->pitch) != 0 ||
                        SDL_SaveBMP(surface, path.c_str()) != 0;
    SDL_FreeSurface(surface);
    if (failed) throw std::runtime_error("Could not save preview");
}
}

int runDesktop(int argc, char** argv) {
    int width = 132, height = 116, frames = 0;
    bool demo = false, reduced = false;
    std::optional<float> requestedScale;
    std::string address = std::getenv("BLOB_IPC_ADDRESS") ? std::getenv("BLOB_IPC_ADDRESS") : "localhost:50051";
    std::string settingsPath = DesktopSettings::defaultPath(), screenshot;
    for (int i = 1; i < argc; ++i) {
        const std::string arg(argv[i]);
        auto value = [&]() -> std::string { if (++i >= argc) throw std::invalid_argument("Missing value for " + arg); return argv[i]; };
        if (arg == "--help") {
            std::cout << "Blob desktop companion\n--width 80..400 --height 80..400 --scale 0.75..2\n"
                "--ipc-address ADDRESS --settings FILE --reduced-motion\n"
                "--demo --frames 1..10000 --snapshot FILE.bmp\n"
                "Double-click: terminal chat. Right-click: privacy pause.\n";
            return 0;
        } else if (arg == "--width") width = number(value(), 80, 400);
        else if (arg == "--height") height = number(value(), 80, 400);
        else if (arg == "--frames") frames = number(value(), 1, 10000);
        else if (arg == "--ipc-address") address = value();
        else if (arg == "--settings") settingsPath = value();
        else if (arg == "--snapshot") screenshot = value();
        else if (arg == "--demo") demo = true;
        else if (arg == "--reduced-motion") reduced = true;
        else if (arg == "--scale") {
            const auto text = value(); size_t length = 0; float scale = std::stof(text, &length);
            if (length != text.size() || !std::isfinite(scale) || scale < 0.75f || scale > 2.0f) throw std::invalid_argument("Scale must be between 0.75 and 2");
            requestedScale = scale;
        } else throw std::invalid_argument("Unknown option: " + arg);
    }
    SdlRuntime sdl; // All SDL resources are destroyed before SDL_Quit.
    auto settings = DesktopSettings::load(settingsPath);
    if (requestedScale) settings.scale = *requestedScale;
    if (reduced) settings.reducedMotion = true;
    OverlayWindow window(int(width * settings.scale), int(height * settings.scale));
    if (settings.positioned) window.restorePosition(settings.x, settings.y);
    Renderer renderer(window.getSDLWindow(), width, height);
    InputHandler input;
    GrpcClient client(address);
    AnimationController animation;
    BlobPhysics physics(width, height);
    SystemTray tray;
    DesktopStatus status;
    if (!demo) client.start();
    else { status.connected = true; status.shield = false; }
    bool running = true, hovered = false, lastConnected = false;
    BlobExpression expression = BlobExpression::IDLE, secondary = BlobExpression::IDLE;
    float intensity = 0.6f, blend = 0;
    Uint32 expressionUntil = 0, speakingUntil = 0;
    auto persist = [&]() {
        SDL_GetWindowPosition(window.getSDLWindow(), &settings.x, &settings.y); settings.positioned = true;
        if (!demo && !settings.save(settingsPath)) std::cerr << "Could not save desktop preferences.\n";
    };
    Uint64 previous = SDL_GetPerformanceCounter();
    const double frequency = double(SDL_GetPerformanceFrequency());
    int frame = 0;
    std::string lastTitle;
    while (running) {
        const Uint64 start = SDL_GetPerformanceCounter();
        const float dt = std::clamp(float((start - previous) / frequency), 0.0f, 0.05f);
        previous = start;
        const Uint32 now = SDL_GetTicks();
        SDL_Event event{};
        while (SDL_PollEvent(&event)) {
            if (event.type == SDL_QUIT) { running = false; continue; }
            if (event.type == SDL_DROPBEGIN || event.type == SDL_DROPFILE || event.type == SDL_DROPCOMPLETE) {
                auto drop = input.processEvent(event);
                if (drop.type == InputEvent::ATTACHMENT_DROP) {
                    if (!client.attachFiles(drop.attachments)) std::cerr << "Files were not sent. Reconnect and drop them again.\n";
                    else std::cout << "Files sent for analysis. Continue in terminal chat.\n";
                } else if (drop.type == InputEvent::DRAG_DROP) {
                    if (!client.installSkill(drop.filepath)) std::cerr << "Skill was not sent. Reconnect and try again.\n";
                }
                continue;
            }
            const Uint32 id = SDL_GetWindowID(window.getSDLWindow());
            if (event.type == SDL_WINDOWEVENT && event.window.windowID == id) {
                if (event.window.event == SDL_WINDOWEVENT_CLOSE) running = false;
                if (event.window.event == SDL_WINDOWEVENT_ENTER) hovered = true;
                if (event.window.event == SDL_WINDOWEVENT_LEAVE) hovered = false;
            }
            if (event.type == SDL_MOUSEBUTTONDOWN && event.button.windowID == id) {
                if (event.button.button == SDL_BUTTON_RIGHT) client.togglePrivacy();
                else if (event.button.button == SDL_BUTTON_LEFT) {
                    if (event.button.clicks >= 2) { window.stopDrag(); physics.setDrag(0); openChat(); }
                    else { int x, y; SDL_GetGlobalMouseState(&x, &y); window.startDrag(x, y); physics.jiggle(); }
                }
            }
            if (event.type == SDL_MOUSEMOTION && event.motion.windowID == id) {
                animation.setAttention((event.motion.x / settings.scale - width / 2.0f) / (width * 0.4f),
                                       (event.motion.y / settings.scale - height / 2.0f) / (height * 0.4f), hovered);
                if (window.isDragging()) {
                    int x, y; SDL_GetGlobalMouseState(&x, &y);
                    if (x || y) window.updateDrag(x, y); else window.updateDragRelative(event.motion.xrel, event.motion.yrel);
                    physics.setDrag(event.motion.xrel / 12.0f);
                }
            }
            if (event.type == SDL_MOUSEBUTTONUP && event.button.windowID == id && event.button.button == SDL_BUTTON_LEFT) {
                if (window.isDragging()) {
                    window.stopDrag(); physics.setDrag(0); physics.jiggle();
                    int x, y; SDL_GetWindowPosition(window.getSDLWindow(), &x, &y); window.restorePosition(x, y); persist();
                }
            }
            if (event.type == SDL_KEYDOWN && event.key.windowID == id) {
                if (event.key.keysym.sym == SDLK_RETURN) openChat();
                else if (event.key.keysym.sym == SDLK_SPACE) physics.jiggle();
                else if (event.key.keysym.sym == SDLK_ESCAPE) running = false;
            }
        }
        tray.poll();
        if (tray.takeActivated()) openChat();
        if (tray.takePrivacyToggle()) client.togglePrivacy();
        while (auto event = client.pollEvent()) {
            if (event->has_privacy()) {
                const auto& p = event->privacy();
                if (p.controls_available()) {
                    status.paused = p.manual_pause();
                }
                status.shield = p.activated();
            } else if (event->has_notification()) {
                speakingUntil = now + 1600;
            } else if (event->has_skill_ack()) {
                expression = event->skill_ack().success() ? BlobExpression::SUCCESS : BlobExpression::ERROR;
                intensity = 0.7f; expressionUntil = now + 2200;
                std::cout << (event->skill_ack().success() ? "Skill installed.\n" : "Skill installation failed.\n");
            } else if (event->has_emote()) {
                expression = expressionFor(event->emote().emote());
                intensity = event->emote().intensity() > 0 ? event->emote().intensity() : 0.6f;
                secondary = expressionFor(event->emote().secondary_emote()); blend = event->emote().blend();
                const bool busy = expression == BlobExpression::THINKING || expression == BlobExpression::DEEP_THINKING ||
                                  expression == BlobExpression::WORKING || expression == BlobExpression::WAITING;
                expressionUntil = busy ? 0 : now + (event->emote().duration_ms() ? event->emote().duration_ms() : 3500);
                if (expression == BlobExpression::HAPPY || expression == BlobExpression::CELEBRATE) physics.jiggle();
            }
        }
        const bool connected = demo || client.isConnected();
        if (!connected && lastConnected) {
            std::cerr << "Backend disconnected. Check completed actions before retrying.\n";
        }
        status.connected = connected; lastConnected = connected;
        if (demo) {
            constexpr std::array poses{BlobExpression::IDLE, BlobExpression::HAPPY, BlobExpression::THINKING,
                BlobExpression::PLAYFUL, BlobExpression::CELEBRATE, BlobExpression::MELTING};
            expression = poses[(frame / 150) % poses.size()];
        }
        if (expressionUntil && SDL_TICKS_PASSED(now, expressionUntil)) {
            if (expression == BlobExpression::MELTING) { expression = BlobExpression::RECOVERING; expressionUntil = now + 1000; }
            else { expression = BlobExpression::IDLE; secondary = expression; blend = 0; expressionUntil = 0; }
        }
        const auto visual = !connected ? BlobExpression::SLEEPING : status.shield ? BlobExpression::SLEEPING : expression;
        animation.setReducedMotion(settings.reducedMotion); physics.setReducedMotion(settings.reducedMotion);
        animation.setExpression(visual, intensity); animation.setBlend(status.shield ? BlobExpression::IDLE : secondary, status.shield ? 0 : blend);
        if (!hovered) animation.setAttention(0, 0, false);
        animation.update(dt);
        BlobPose pose = animation.pose();
        if (!settings.reducedMotion && !status.paused && connected && speakingUntil && !SDL_TICKS_PASSED(now, speakingUntil))
            pose.mouthOpen = std::max(pose.mouthOpen, 0.25f + 0.30f * (0.5f + 0.5f * std::sin(now * 0.014f)));
        physics.setPose(pose); physics.update(dt);
        renderer.clear();
        const auto vertices = physics.getVertices(); const auto center = physics.getCenter();
        renderer.drawOuterBody(vertices); renderer.drawOutline(vertices);
        renderer.drawHighlights(center.x, center.y, physics.getRadiusX(), physics.getRadiusY());
        const float time = settings.reducedMotion ? 0 : now / 1000.0f;
        renderer.drawDetails(center.x, center.y, physics.getRadiusX(), physics.getRadiusY(), time, pose);
        renderer.drawFace(center.x, center.y, physics.getRadiusX(), physics.getRadiusY(), time,
                          connected && status.shield ? BlobState::BLINDFOLDED : BlobState::IDLE, pose);
        renderer.present(); renderer.stampShape(vertices, center.x, center.y); window.updateShape(renderer.getShapeSurface());
        const std::string title = !connected ? "Blob — reconnecting" : status.paused ? "Blob — privacy paused" : "Blob — double-click to chat";
        if (title != lastTitle) { SDL_SetWindowTitle(window.getSDLWindow(), title.c_str()); lastTitle = title; }
        ++frame;
        if (frames && frame >= frames) {
            if (!screenshot.empty()) snapshot(renderer.native(), screenshot);
            running = false;
        }
        const double elapsed = (SDL_GetPerformanceCounter() - start) / frequency;
        const double interval = 1.0 / (settings.reducedMotion ? 30.0 : 60.0);
        if (elapsed < interval) SDL_Delay(Uint32((interval - elapsed) * 1000));
    }
    client.stop();
    return 0;
}
