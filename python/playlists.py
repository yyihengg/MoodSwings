"""Spotify playlist creation, population, and reordering utilities."""

import requests
from state import AppState
from playback import current_track


# ---------------------------------------------------------------------------
# Playlist CRUD
# ---------------------------------------------------------------------------

def get_playlists(token: str) -> list:
    """Return the current user's playlists."""
    response = requests.get(
        "https://api.spotify.com/v1/me/playlists",
        headers={"Authorization": f"Bearer {token}"},
    )
    response.raise_for_status()
    return response.json().get("items", [])


def create_playlist(state: AppState, token: str, mood: str) -> None:
    """Create a new private playlist for the given mood if one doesn't exist yet."""
    if mood in state.playlists and "playlist_id" in state.playlists[mood]:
        return  # Already created — nothing to do

    response = requests.post(
        "https://api.spotify.com/v1/me/playlists",
        json={"name": f"{mood} vibes", "public": False},
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    response.raise_for_status()

    state.playlists.setdefault(mood, {})
    state.playlists[mood]["playlist_id"] = response.json()["id"]


def reorder_playlist(state: AppState, token: str, mood: str, reverse: bool) -> None:
    """Reorder playlist tracks by intensity scale (ascending or descending)."""
    playlist_id = state.playlists[mood]["playlist_id"]
    scale_range = range(5, 0, -1) if reverse else range(1, 6)

    uris = []
    for scale in scale_range:
        if scale in state.playlists[mood]:
            uris += state.playlists[mood][scale]

    requests.put(
        f"https://api.spotify.com/v1/playlists/{playlist_id}/items",
        json={"uris": uris},
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )


# ---------------------------------------------------------------------------
# Adding tracks
# ---------------------------------------------------------------------------

def add_tracks(state: AppState, token: str, mood: str, add_current: bool) -> None:
    """Add tracks to the mood playlist.

    If add_current is True, adds the currently playing track only.
    Otherwise, syncs all tagged tracks for the mood that haven't been added yet.
    """
    playlist_id = state.playlists[mood]["playlist_id"]
    uris = []

    if add_current:
        track_info = current_track(token)
        if track_info:
            uris.append(track_info["track_uri"])
    else:
        for track_values in state.mood_tracks[mood].values():
            track_uri  = track_values["track_uri"]
            track_scale = track_values["track_scale"]
            track_uris = state.playlists[mood].setdefault(track_scale, [])
            if track_uri not in track_uris:
                state.playlists[mood][track_scale].append(track_uri)
                uris.append(track_uri)

    if uris:
        requests.post(
            f"https://api.spotify.com/v1/playlists/{playlist_id}/items",
            json={"uris": uris},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )


# ---------------------------------------------------------------------------
# Reading playlist tracks
# ---------------------------------------------------------------------------

def playlist_tracks(token: str, playlist_id: str) -> dict:
    """Fetch up to 100 tracks from a playlist and return them in a normalised format."""
    response = requests.get(
        f"https://api.spotify.com/v1/playlists/{playlist_id}/items",
        headers={"Authorization": f"Bearer {token}"},
        params={"fields": "items(item(uri))", "limit": 100},
    )
    response.raise_for_status()
    items = response.json().get("items", [])

    return {
        "tracks": {
            "items": [
                {"track": item.get("item", {})}
                for item in items
                if item.get("item") is not None
            ]
        }
    }
