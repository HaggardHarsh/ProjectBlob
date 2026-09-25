#pragma once
#include <string>

class NotificationManager {
public:
    NotificationManager();
    void show(const std::string& text);
    void update(float dt);
    void render();
};
