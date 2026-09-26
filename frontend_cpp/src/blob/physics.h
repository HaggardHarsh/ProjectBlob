#pragma once
#include <vector>
#include <cmath>
#include "common/types.h"

/**
 * BlobPhysics — spring-mass system arranged as a dome (half-ellipse)
 * to mimic the Rimuru-style slime shape.
 */
class BlobPhysics {
public:
    BlobPhysics();
    void update(float dt);
    std::vector<Vec2> getVertices() const;
    Vec2 getCenter() const;
    float getRadiusX() const { return radiusX_; }
    float getRadiusY() const { return topRadiusY_; }
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
    float gravity_       = 15.0f;
    float radiusX_       = 85.0f;
    float topRadiusY_    = 58.0f;
    float bottomRadiusY_ = 10.0f;
    float centerX_, centerY_;
    int windowW_, windowH_;
};
