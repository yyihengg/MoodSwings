class AppState:
    """Holds shared in-memory state for the MoodSwings application.

    Note: This is a module-level singleton, meaning all users share the same
    state. This is intentional for a single-user local app but would need
    a session-based approach for multi-user deployment.
    """

    def __init__(self):
        # Tracks categorised by mood and intensity
        self.mood_tracks: dict = {"happiness": {}, "sadness": {}, "anger": {}}
        # Temporary storage for exploration mode tracks
        self.explore_tracks: dict = {}
        # Created playlists metadata storage
        self.playlists: dict = {}
        # Spotify access token
        self.token: str | None = None
