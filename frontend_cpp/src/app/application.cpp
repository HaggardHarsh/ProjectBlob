#include "app/application.h"
#include "app/settings.h"
#include "app/chat_launcher.h"
#include "ui/tray.h"
#include "ui/conversation_bubble.h"
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
#include <chrono>
#include <cstdlib>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>


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
struct DesktopStatus { bool connected = false, shield = true, paused = false, cloud = false; };
struct SdlRuntime {
    SdlRuntime() {
        const char* driver = nullptr;
#ifdef __linux__
        const auto environment = [](const char* name) {
            const char* value = std::getenv(name);
            return value && *value ? value : nullptr;
        };
        driver = environment("SDL_VIDEODRIVER");
        if (!driver) {
            if (environment("DISPLAY")) driver = "x11";
            else if (environment("WAYLAND_DISPLAY")) driver = "wayland";
            else throw std::runtime_error("Desktop display is not ready; waiting for DISPLAY or WAYLAND_DISPLAY. "
                                          "The desktop service will retry.");
        }
        const std::string requested(driver);
        if (requested != "x11" && requested != "wayland" && requested != "dummy" && requested != "offscreen")
            throw std::runtime_error("Unsupported SDL_VIDEODRIVER: " + requested +
                                     ". Blob requires x11 or wayland (dummy/offscreen for headless checks).");
#endif
        // The click that focuses Blob is also the first half of a double-click.
        SDL_SetHint(SDL_HINT_MOUSE_FOCUS_CLICKTHROUGH, "1");
        // An explicit driver prevents SDL from probing KMSDRM and taking control
        // of the display when the desktop session isn't ready yet.
        if (SDL_Init(SDL_INIT_EVENTS | SDL_INIT_TIMER) || SDL_VideoInit(driver)) {
            const std::string error = SDL_GetError();
            SDL_VideoQuit();
            SDL_Quit();
            throw std::runtime_error("Desktop video initialization failed (" +
                                     std::string(driver ? driver : "default") + "): " + error);
        }
        std::cerr << "Blob video driver: " << SDL_GetCurrentVideoDriver() << '\n';
    }
    ~SdlRuntime() { SDL_VideoQuit(); SDL_Quit(); }
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
    // Start each launch in the bottom-left corner, regardless of the last drag position.
    OverlayWindow window(int(width * settings.scale), int(height * settings.scale));
    Renderer renderer(window.getSDLWindow(), width, height);
    InputHandler input;
    GrpcClient client(address);
    AnimationController animation;
    BlobPhysics physics(width, height);
    SystemTray tray;
    ChatLauncher chat;
    DesktopStatus status;
    ConversationBubble bubble;
    if (!demo) client.start();
    else { status.connected = true; status.shield = false; }
    bool running = true, hovered = false, lastConnected = false;
    BlobExpression expression = BlobExpression::IDLE, secondary = BlobExpression::IDLE;
    float intensity = 0.6f, blend = 0;
    Uint32 expressionUntil = 0, speakingUntil = 0, reminderShakeUntil = 0;
    auto persist = [&]() {
        SDL_GetWindowPosition(window.getSDLWindow(), &settings.x, &settings.y); settings.positioned = true;
        if (!demo && !settings.save(settingsPath)) std::cerr << "Could not save desktop preferences.\n";
    };
    Uint64 previous = SDL_GetPerformanceCounter();
    const double frequency = double(SDL_GetPerformanceFrequency());
    int frame = 0;
    std::string lastTitle;
    const auto attend = [&](int x, int y) {
        animation.setAttention((x - window.getWidth() * 0.5f) / (window.getWidth() * 0.4f),
                               (y - window.getHeight() * 0.57f) / (window.getHeight() * 0.4f), true);
    };
    while (running) {
        const Uint64 start = SDL_GetPerformanceCounter();
        const float dt = std::clamp(float((start - previous) / frequency), 0.0f, 0.05f);
        previous = start;
        const Uint32 now = SDL_GetTicks();
        chat.poll();
        SDL_Event event{};
        while (SDL_PollEvent(&event)) {
            if (auto action = bubble.handle(event)) {
                if (*action == blob::ProactiveFeedback::QUIET_TODAY || *action == blob::ProactiveFeedback::MUTE)
                    client.proactiveControl(*action == blob::ProactiveFeedback::QUIET_TODAY);
                else client.proactiveFeedback(bubble.id(), *action);
                bubble.hide();
                if (*action == blob::ProactiveFeedback::REPLY) chat.launch(true);
                continue;
            }
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
                if (event.window.event == SDL_WINDOWEVENT_ENTER) {
                    hovered = true;
                    int x, y; SDL_GetMouseState(&x, &y); attend(x, y);
                }
                if (event.window.event == SDL_WINDOWEVENT_LEAVE) hovered = false;
            }
            if (event.type == SDL_MOUSEBUTTONDOWN && event.button.windowID == id) {
                if (event.button.button == SDL_BUTTON_RIGHT) client.togglePrivacy();
                else if (event.button.button == SDL_BUTTON_LEFT) {
                    if (event.button.clicks == 2) { window.stopDrag(); physics.setDrag(0); chat.launch(); }
                    else {
                        animation.poke();
                        int x, y; SDL_GetGlobalMouseState(&x, &y); window.startDrag(x, y); physics.jiggle();
                    }
                }
            }
            if (event.type == SDL_MOUSEMOTION && event.motion.windowID == id) {
                if (!window.isDragging()) hovered = true;
                attend(event.motion.x, event.motion.y);
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
                if (event.key.keysym.sym == SDLK_RETURN && !event.key.repeat) chat.launch();
                else if (event.key.keysym.sym == SDLK_SPACE && !event.key.repeat) { animation.poke(); physics.jiggle(); }
                else if (event.key.keysym.sym == SDLK_ESCAPE) running = false;
            }
        }
        tray.poll();
        if (tray.takeActivated()) chat.launch();
        if (tray.takePrivacyToggle()) client.togglePrivacy();
        while (auto event = client.pollEvent()) {
            if (event->has_privacy()) {
                const auto& p = event->privacy();
                if (p.controls_available()) {
                    status.paused = p.manual_pause();
                    status.cloud = p.cloud_enabled();
                }
                status.shield = p.activated();
            } else if (event->has_notification()) {
                const auto& notice = event->notification();
                if (notice.proactive()) {
                    const auto wallNow = std::chrono::duration_cast<std::chrono::milliseconds>(
                        std::chrono::system_clock::now().time_since_epoch()).count();
                    if (notice.text().empty()) bubble.hide();
                    else if (ConversationBubble::fresh(event->timestamp_ms(), wallNow) &&
                             !status.shield && !status.paused && status.cloud && !client.proactiveControlPending() &&
                             bubble.show(notice, window.getSDLWindow(), now)) {
                        client.proactiveFeedback(notice.approach_id(), blob::ProactiveFeedback::SHOWN);
                        expression = BlobExpression::CURIOUS;
                        intensity = 0.45f; expressionUntil = now + 2500;
                        speakingUntil = now + 1600;
                    }
                } else {
                    speakingUntil = now + 1600;
                    if (!notice.delivery_id().empty()) reminderShakeUntil = now + 8000;
                }
            } else if (event->has_skill_ack()) {
                expression = event->skill_ack().success() ? BlobExpression::SUCCESS : BlobExpression::ERROR;
                intensity = 0.7f; expressionUntil = now + 2200;
                std::cout << (event->skill_ack().success() ? event->skill_ack().description() :
                              "Skill installation failed: " + event->skill_ack().error_message()) << '\n';
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
        SDL_Rect desktop{};
        SDL_GetDisplayBounds(std::max(0, SDL_GetWindowDisplayIndex(window.getSDLWindow())), &desktop);
        const Uint32 flags = SDL_GetWindowFlags(window.getSDLWindow());
        const bool visible = !(flags & (SDL_WINDOW_HIDDEN | SDL_WINDOW_MINIMIZED));
        client.desktopPresence(visible, desktop.w, desktop.h);
        if (!connected || status.shield || status.paused || !status.cloud || !visible) bubble.hide();
        bubble.update(window.getSDLWindow(), now);
        if (demo) {
            constexpr std::array poses{BlobExpression::IDLE, BlobExpression::HAPPY, BlobExpression::THINKING,
                BlobExpression::SHOCKED, BlobExpression::ANGRY, BlobExpression::SAD, BlobExpression::CRYING,
                BlobExpression::SHY, BlobExpression::PLAYFUL, BlobExpression::CELEBRATE, BlobExpression::MELTING};
            expression = poses[(frame / 150) % poses.size()];
        }
        if (expressionUntil && SDL_TICKS_PASSED(now, expressionUntil)) {
            if (expression == BlobExpression::MELTING) { expression = BlobExpression::RECOVERING; expressionUntil = now + 1000; }
            else { expression = BlobExpression::IDLE; secondary = expression; blend = 0; expressionUntil = 0; }
        }
        const auto visual = !connected || (status.shield && expression == BlobExpression::IDLE)
            ? BlobExpression::SLEEPING : expression;
        animation.setReducedMotion(settings.reducedMotion); physics.setReducedMotion(settings.reducedMotion);
        animation.setExpression(visual, intensity); animation.setBlend(secondary, blend);
        if (!hovered) animation.setAttention(0, 0, false);
        animation.update(dt);
        BlobPose pose = animation.pose();
        if (!settings.reducedMotion && connected && reminderShakeUntil && !SDL_TICKS_PASSED(now, reminderShakeUntil)) {
            const float remaining = (reminderShakeUntil - now) / 1000.0f;
            // Rapid reminder shake, easing out over the final third of a second.
            pose.shake += 6.0f * std::min(1.0f, remaining / 0.35f) * std::sin((8.0f - remaining) * 75.0f);
        }
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
