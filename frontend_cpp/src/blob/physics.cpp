#include "blob/physics.h"
#include <cstdlib>
#include <algorithm>

static constexpr int WIN_W = 250;
static constexpr int WIN_H = 180;

BlobPhysics::BlobPhysics()
    : radiusX_(85.0f),
      topRadiusY_(58.0f),
      bottomRadiusY_(10.0f),
      centerX_(WIN_W / 2.0f),
      centerY_(WIN_H / 2.0f + 20.0f),   // push centre down so dome sits low
      windowW_(WIN_W),
      windowH_(WIN_H)
{
    int numPoints = 24;

    // Centre mass point (index 0)
    points.push_back({{centerX_, centerY_}, {centerX_, centerY_}, {0, 0}, 3.0f});

    // Perimeter points — dome shape via variable Y-radius
    for (int i = 0; i < numPoints; ++i) {
        float angle = (float)i * 2.0f * (float)M_PI / (float)numPoints;

        // Smoothly interpolate Y-radius between top (large) and bottom (small)
        // sin(angle) > 0 → bottom half (screen coords)
        float t = (std::sin(angle) + 1.0f) / 2.0f;   // 0 at top, 1 at bottom
        float ry = topRadiusY_ + (bottomRadiusY_ - topRadiusY_) * t;

        Vec2 p = {centerX_ + std::cos(angle) * radiusX_,
                  centerY_ + std::sin(angle) * ry};
        points.push_back({p, p, {0, 0}, 1.0f});

        // Spring to centre — stiffer to maintain dome
        float restLen = (p - Vec2{centerX_, centerY_}).length();
        springs.push_back({0, i + 1, restLen, 22.0f, 1.0f});

        // Spring to previous neighbour
        if (i > 0) {
            Vec2 prev = points[i].pos;  // previous perimeter point
            float dist = (p - prev).length();
            springs.push_back({i, i + 1, dist, 28.0f, 1.0f});
        }
    }
    // Close perimeter loop
    Vec2 first = points[1].pos;
    Vec2 last  = points[numPoints].pos;
    float dist = (first - last).length();
    springs.push_back({numPoints, 1, dist, 28.0f, 1.0f});

    // Cross-bracing springs for extra rigidity (connect opposite points)
    for (int i = 1; i <= numPoints / 2; ++i) {
        int opp = i + numPoints / 2;
        if (opp > numPoints) opp -= numPoints;
        float d = (points[i].pos - points[opp].pos).length();
        springs.push_back({i, opp, d, 8.0f, 1.0f});
    }
}

void BlobPhysics::update(float dt) {
    dt = std::min(dt, 0.033f);

    // Verlet integration
    for (auto& p : points) {
        Vec2 temp = p.pos;
        Vec2 vel = (p.pos - p.oldPos) * 0.96f;   // damping
        p.pos = p.pos + vel + p.accel * (dt * dt);
        p.oldPos = temp;
        p.accel = {0, gravity_};
    }

    // Spring constraint solving — multiple iterations for stability
    for (int iter = 0; iter < 5; ++iter) {
        for (const auto& s : springs) {
            Point& p1 = points[s.p1];
            Point& p2 = points[s.p2];

            Vec2 delta = p2.pos - p1.pos;
            float d = std::sqrt(delta.x * delta.x + delta.y * delta.y);
            if (d < 0.001f) continue;

            float diff = (d - s.restLength) / d * 0.5f;
            Vec2 offset = delta * diff;

            float totalMass = p1.mass + p2.mass;
            p1.pos = p1.pos + offset * (p1.mass / totalMass);
            p2.pos = p2.pos - offset * (p2.mass / totalMass);
        }
    }

    // Floor & wall constraints
    float floorY = (float)windowH_ - 6.0f;
    float wallL  = 6.0f;
    float wallR  = (float)windowW_ - 6.0f;

    for (auto& p : points) {
        if (p.pos.y > floorY) {
            p.pos.y = floorY;
            p.pos.x = p.oldPos.x + (p.pos.x - p.oldPos.x) * 0.88f;
        }
        if (p.pos.y < 4.0f)   p.pos.y = 4.0f;
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
        float jx = (float)(std::rand() % 100 - 50) * 4.0f;
        float jy = (float)(std::rand() % 100 - 50) * 3.0f;
        points[i].accel = points[i].accel + Vec2{jx, jy};
    }
}

void BlobPhysics::squash(float amount) {
    for (size_t i = 1; i < points.size(); ++i) {
        points[i].pos.y += (points[i].pos.y - points[0].pos.y) * amount;
        points[i].pos.x -= (points[i].pos.x - points[0].pos.x) * amount * 0.4f;
    }
}
