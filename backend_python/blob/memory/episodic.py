class EpisodicMemory:
    def __init__(self):
        self.buffer = []
        
    def add_episode(self, user_msg, blob_msg, timestamp, context):
        self.buffer.append({
            "user": user_msg,
            "blob": blob_msg,
            "ts": timestamp,
            "context": context
        })
