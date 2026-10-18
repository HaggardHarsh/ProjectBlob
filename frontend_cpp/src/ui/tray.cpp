#include "tray.h"

#ifdef BLOB_HAVE_X11
#include <X11/Xlib.h>
#include <X11/Xatom.h>
#include <SDL2/SDL.h>
#include <cstdio>
#include <cstring>

void SystemTray::tryDock() {
    if (!display_ || icon_) return;
    const int screen = DefaultScreen(display_);
    char selectionName[48];
    std::snprintf(selectionName, sizeof(selectionName), "_NET_SYSTEM_TRAY_S%d", screen);
    const Atom selection = XInternAtom(display_, selectionName, False);
    const Window manager = XGetSelectionOwner(display_, selection);
    if (!manager) return;

    icon_ = XCreateSimpleWindow(display_, RootWindow(display_, screen), 0, 0, 24, 24,
                                0, BlackPixel(display_, screen), BlackPixel(display_, screen));
    XSelectInput(display_, icon_, ExposureMask | ButtonPressMask | StructureNotifyMask);
    const Atom xembed = XInternAtom(display_, "_XEMBED_INFO", False);
    unsigned long info[2] = {0, 1};
    XChangeProperty(display_, icon_, xembed, xembed, 32, PropModeReplace,
                    reinterpret_cast<unsigned char*>(info), 2);
    XMapWindow(display_, icon_);

    XEvent event{};
    event.xclient.type = ClientMessage;
    event.xclient.window = manager;
    event.xclient.message_type = XInternAtom(display_, "_NET_SYSTEM_TRAY_OPCODE", False);
    event.xclient.format = 32;
    event.xclient.data.l[0] = CurrentTime;
    event.xclient.data.l[1] = 0; // SYSTEM_TRAY_REQUEST_DOCK
    event.xclient.data.l[2] = static_cast<long>(icon_);
    XSendEvent(display_, manager, False, NoEventMask, &event);
    XFlush(display_);
}

void SystemTray::drawIcon() {
    if (!display_ || !icon_) return;
    const int screen = DefaultScreen(display_);
    GC gc = XCreateGC(display_, icon_, 0, nullptr);
    XSetForeground(display_, gc, BlackPixel(display_, screen));
    XFillRectangle(display_, icon_, gc, 0, 0, 24, 24);
    XSetForeground(display_, gc, 0x55c8eb);
    XFillArc(display_, icon_, gc, 2, 2, 20, 20, 0, 360 * 64);
    XSetForeground(display_, gc, WhitePixel(display_, screen));
    XFillArc(display_, icon_, gc, 8, 8, 3, 3, 0, 360 * 64);
    XFillArc(display_, icon_, gc, 15, 8, 3, 3, 0, 360 * 64);
    XFreeGC(display_, gc);
    XFlush(display_);
}
#endif

SystemTray::SystemTray() {
#ifdef BLOB_HAVE_X11
    display_ = XOpenDisplay(nullptr);
    tryDock();
#endif
}

SystemTray::~SystemTray() {
#ifdef BLOB_HAVE_X11
    if (display_) {
        if (icon_) XDestroyWindow(display_, icon_);
        XCloseDisplay(display_);
    }
#endif
}

void SystemTray::poll() {
#ifdef BLOB_HAVE_X11
    if (!display_) return;
    while (XPending(display_)) {
        XEvent event{};
        XNextEvent(display_, &event);
        if (event.type == Expose && event.xexpose.window == icon_) drawIcon();
        if (event.type == ButtonPress && event.xbutton.window == icon_) {
            if (event.xbutton.button == Button3) privacyToggle_ = true;
            else activated_ = true;
        }
        if (event.type == DestroyNotify && event.xdestroywindow.window == icon_) icon_ = 0;
    }
    const unsigned long now = SDL_GetTicks();
    if (!icon_ && now - lastDockAttempt_ > 5000) {
        lastDockAttempt_ = now;
        tryDock();
    }
#endif
}

bool SystemTray::takeActivated() {
    const bool value = activated_;
    activated_ = false;
    return value;
}

bool SystemTray::takePrivacyToggle() {
    const bool value = privacyToggle_;
    privacyToggle_ = false;
    return value;
}

bool SystemTray::isAvailable() const {
#ifdef BLOB_HAVE_X11
    return icon_ != 0;
#else
    return false;
#endif
}
