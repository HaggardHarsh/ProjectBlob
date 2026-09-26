#pragma once
#include <vector>
#include <cmath>
#include "common/types.h"

class BlobPhysics {
public:
    BlobPhysics();
    void update(float dt);
    std::vector<Vec2> getVertices() const;
    Vec2 getCenter() const;
    float getRadius() const { return baseRadius_; }
    void applyForce(Vec2 force);
    void jiggle();
    void squash(float amount);

private:
    struct Point {
        Vec2 pos, oldPos, accel;
        float mass = 1.0f;
    };

    struct Spring {
        int p1, p2;
        float restLength, k, damp;
    };

    std::vector<Point> points;
    std::vector<Spring> springs;
    float gravity_ = 9.81f * 10.0f;
    float baseRadius_ = 40.0f;
    float centerX_, centerY_;
    int windowW_, windowH_;
};
