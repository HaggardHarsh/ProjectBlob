#pragma once

#include <vector>

#include "common/types.h"

/** A calm slime outline with a small, quickly settling reaction to pokes. */
class BlobPhysics {
public:
    BlobPhysics(int windowWidth = 132, int windowHeight = 116);
    void update(float dt);
    std::vector<Vec2> getVertices() const;
    Vec2 getCenter() const;
    float getRadiusX() const { return radiusX_; }
    float getRadiusY() const { return topRadiusY_; }
    void applyForce(Vec2 force);
    void jiggle();
    void squash(float amount);

private:
    float radiusX_;
    float topRadiusY_;
    float bottomRadiusY_;
    float centerX_;
    float centerY_;
    float time_ = 0.0f;
    float wobble_ = 0.0f;
    float squash_ = 0.0f;
};
