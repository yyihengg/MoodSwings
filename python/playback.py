"""Spotify playback control utilities."""

import requests
from state import AppState


def next_track(token: str) -> None:
    requests.post(
        "https://api.spotify.com/v1/me/player/next",
        headers={"Authorization": f"Bearer {token}"},
    )


def prev_track(token: str) -> None:
    requests.post(
        "https://api.spotify.com/v1/me/player/previous",
        headers={"Authorization": f"Bearer {token}"},
    )


def resume_track(token: str) -> None:
    requests.put(
        "https://api.spotify.com/v1/me/player/play",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )


def pause_track(token: str) -> None:
    requests.put(
        "https://api.spotify.com/v1/me/player/pause",
        headers={"Authorization": f"Bearer {token}"},
    )


def shuffle_playback(token: str, device_id: str | None = None) -> None:
    url = "https://api.spotify.com/v1/me/player/shuffle?state=true"
    if device_id:
        url += f"&device_id={device_id}"
    requests.put(url, headers={"Authorization": f"Bearer {token}"})


def get_devices(token: str) -> dict:
    """Return a mapping of device type to device ID for Mobile and Computer."""
    response = requests.get(
        "https://api.spotify.com/v1/me/player/devices",
        headers={"Authorization": f"Bearer {token}"},
    )
    response.raise_for_status()

    smartphone_id = None
    computer_id = None
    for device in response.json().get("devices", []):
        if device["type"] == "Smartphone":
            smartphone_id = device["id"]
        elif device["type"] == "Computer":
            computer_id = device["id"]

    return {"Computer": computer_id, "Mobile": smartphone_id}


def playlist_play(token: str, device_id: str | None = None) -> None:
    """Play the user's most recent Spotify playlist."""
    playlists = _get_user_playlists(token)
    if not playlists:
        return

    context_uri = playlists[0]["uri"]
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    params = {"device_id": device_id} if device_id else {}
    requests.put(
        "https://api.spotify.com/v1/me/player/play",
        json={"context_uri": context_uri},
        params=params,
        headers=headers,
    )


def mood_play(state: AppState, token: str, mood: str, scale: int) -> None:
    """Play previously tagged tracks closest to the requested mood and intensity."""
    if not state.mood_tracks[mood]:
        return

    tracks_info = state.mood_tracks[mood].values()
    closest_diff = 5
    closest_scale = scale

    for track_info in tracks_info:
        diff = abs(scale - track_info["track_scale"])
        if diff <= closest_diff:
            closest_diff = diff
            closest_scale = track_info["track_scale"]

    uris = [
        t["track_uri"]
        for t in tracks_info
        if t["track_scale"] == closest_scale
    ]

    import random
    random.shuffle(uris)

    requests.put(
        "https://api.spotify.com/v1/me/player/play",
        json={"uris": uris},
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )


def current_track(token: str) -> dict | None:
    """Return metadata for the currently playing track, or None if nothing is playing."""
    response = requests.get(
        "https://api.spotify.com/v1/me/player/currently-playing",
        headers={"Authorization": f"Bearer {token}"},
    )
    if response.status_code == 204:
        return None

    response.raise_for_status()
    content = response.json()
    item = content.get("item", {})
    return {
        "track_name": item.get("name"),
        "track_uri": item.get("uri"),
        "artist_names": [a["name"] for a in item.get("artists", [])],
        "artist_ids":   [a["id"]   for a in item.get("artists", [])],
    }


def store_mood(state: AppState, user_input: dict, track_info: dict) -> None:
    """Tag a track with a mood and intensity scale and store it in app state."""
    if not track_info or not track_info.get("track_name"):
        return

    mood = user_input["recordMood"]
    track_scale = int(user_input["recordScale"])
    track_name = track_info["track_name"]

    if track_name not in state.mood_tracks[mood]:
        state.mood_tracks[mood][track_name] = {
            "artist_names": track_info["artist_names"],
            "track_uri":    track_info["track_uri"],
            "artist_ids":   track_info["artist_ids"],
            "track_scale":  track_scale,
        }


def _get_user_playlists(token: str) -> list:
    response = requests.get(
        "https://api.spotify.com/v1/me/playlists",
        headers={"Authorization": f"Bearer {token}"},
    )
    response.raise_for_status()
    return response.json().get("items", [])
