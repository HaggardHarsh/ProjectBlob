#pragma once

class AnimationController {
public:
    AnimationController();
    void update(float dt);

private:
    float time = 0.0f;
};
