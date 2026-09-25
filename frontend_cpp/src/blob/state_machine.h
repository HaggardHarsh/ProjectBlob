#pragma once

enum class BlobState {
    IDLE, CRAWLING, SLEEPING, EATING, DIVIDING, MERGING, BLINDFOLDED, THINKING, BOUNCING
};

class BlobStateMachine {
public:
    BlobStateMachine();
    void update(float dt);
    void changeState(BlobState newState);
    BlobState getCurrentState() const { return currentState; }

private:
    BlobState currentState = BlobState::IDLE;
    float stateTime = 0.0f;
};
