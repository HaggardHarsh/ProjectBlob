#include "blob/physics.h"
#include <cstdlib>
#include <algorithm>

// Window for the blob pet is 200x200.  Centre the blob in the middle.
static constexpr int WIN_W = 200;
static constexpr int WIN_H = 200;

BlobPhysics::BlobPhysics()
    : baseRadius_(40.0f),
      centerX_(WIN_W / 2.0f),
      centerY_(WIN_H / 2.0f),
      windowW_(WIN_W),
      windowH_(WIN_H)
{
    int numPoints = 16;
    float radius = baseRadius_;

    // Centre mass point (index 0)
    points.push_back({{centerX_, centerY_}, {centerX_, centerY_}, {0, 0}, 2.0f});

    // Perimeter points
    for (int i = 0; i < numPoints; ++i) {
        float angle = (float)i * 2.0f * (float)M_PI / (float)numPoints;
        Vec2 p = {centerX_ + std::cos(angle) * radius,
                  centerY_ + std::sin(angle) * radius};
        points.push_back({p, p, {0, 0}, 1.0f});

        // Spring to centre
        springs.push_back({0, i + 1, radius, 12.0f, 1.0f});

        // Spring to previous perimeter neighbour
        if (i > 0) {
            float dist = radius * 2.0f * std::sin((float)M_PI / numPoints);
            springs.push_back({i, i + 1, dist, 18.0f, 1.0f});
        }
    }
    // Close the perimeter loop
    float dist = radius * 2.0f * std::sin((float)M_PI / numPoints);
    springs.push_back({numPoints, 1, dist, 18.0f, 1.0f});
}

void BlobPhysics::update(float dt) {
    // Cap dt to prevent explosion on lag spikes
    dt = std::min(dt, 0.033f);

    // Verlet integration
    for (auto& p : points) {
        Vec2 temp = p.pos;
        Vec2 vel = (p.pos - p.oldPos) * 0.97f; // damping
        p.pos = p.pos + vel + p.accel * (dt * dt);
        p.oldPos = temp;
        p.accel = {0, gravity_};
    }

    // Spring constraint solving (several iterations for stability)
    for (int iter = 0; iter < 4; ++iter) {
        for (const auto& s : springs) {
            Point& p1 = points[s.p1];
            Point& p2 = points[s.p2];

            Vec2 delta = p2.pos - p1.pos;
            float dist = std::sqrt(delta.x * delta.x + delta.y * delta.y);
            if (dist < 0.001f) continue;

            float diff = (dist - s.restLength) / dist * 0.5f;
            Vec2 offset = delta * diff;

            float totalMass = p1.mass + p2.mass;
            p1.pos = p1.pos + offset * (p1.mass / totalMass) * 1.2f;
            p2.pos = p2.pos - offset * (p2.mass / totalMass) * 1.2f;
        }
    }

    // Floor / ceiling / wall collision (keep blob inside the 200x200 window)
    float floorY = (float)windowH_ - 8.0f;
    float ceilY  = 8.0f;
    float wallL  = 8.0f;
    float wallR  = (float)windowW_ - 8.0f;

    for (auto& p : points) {
        if (p.pos.y > floorY) {
            p.pos.y = floorY;
            p.pos.x = p.oldPos.x + (p.pos.x - p.oldPos.x) * 0.85f; // friction
        }
        if (p.pos.y < ceilY)  p.pos.y = ceilY;
        if (p.pos.x < wallL)  p.pos.x = wallL;
        if (p.pos.x > wallR)  p.pos.x = wallR;
    }
}

std::vector<Vec2> BlobPhysics::getVertices() const {
    std::vector<Vec2> v;
    for (size_t i = 1; i < points.size(); ++i) {
        v.push_back(points[i].pos);
    }
    return v;
}

Vec2 BlobPhysics::getCenter() const {
    return points[0].pos;
}

void BlobPhysics::applyForce(Vec2 force) {
    for (auto& p : points) p.accel = p.accel + force;
}

void BlobPhysics::jiggle() {
    for (size_t i = 1; i < points.size(); ++i) {
        float jx = (float)(std::rand() % 100 - 50) * 8.0f;
        float jy = (float)(std::rand() % 100 - 50) * 8.0f;
        points[i].accel = points[i].accel + Vec2{jx, jy};
    }
}

void BlobPhysics::squash(float amount) {
    for (size_t i = 1; i < points.size(); ++i) {
        points[i].pos.y += (points[i].pos.y - points[0].pos.y) * amount;
        points[i].pos.x -= (points[i].pos.x - points[0].pos.x) * amount * 0.5f;
    }
}
