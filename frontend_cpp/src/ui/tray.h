#pragma once

#ifdef BLOB_HAVE_X11
struct _XDisplay;
#endif

class SystemTray {
public:
    SystemTray();
    ~SystemTray();
    void poll();
    bool takeActivated();
    bool takePrivacyToggle();
    bool isAvailable() const;

private:
#ifdef BLOB_HAVE_X11
    void tryDock();
    void drawIcon();
    _XDisplay* display_ = nullptr;
    unsigned long icon_ = 0;
    unsigned long lastDockAttempt_ = 0;
#endif
    bool activated_ = false;
    bool privacyToggle_ = false;
};
