import random
import requests
from state import AppState
from playlists import playlist_tracks


# Public interface

def recommended_play(state: AppState, token: str, mood: str, scale: int) -> set:
    # Discover and play tracks matching a mood and intensity using genre-weighted sampling.

    # Algorithm overview:
    #   1. Filter tagged tracks to those within ±1 intensity of the target scale.
    #   2. Score each track by proximity: score = max(0.1, 3 - variance).
    #   3. Distribute each track's score across its artists' genres proportionally.
    #   4. Normalise genre scores into a probability distribution.
    #   5. Sample 5 genres using weighted random choice, then query Spotify Search
    #      with "<mood_synonym> <genre>" to find matching playlists.
    #   6. Randomly select tracks from those playlists and play them.

    # Falls back to generic mood-based queries when insufficient tagged data exists.
    
    tracks_info = state.mood_tracks[mood].values()
    artists_genre: dict  = {}
    genre_chances: dict  = {}
    tracks_data:   list  = []
    all_artist_ids: set  = set()
    recommended_tracks: set = set()
    total_genre_score = 0
    genre_freq: dict = {}

    mood_synonyms = {
        "happiness": ["Happy", "Upbeat"],
        "sadness":   ["Sad", "Heartbreak"],
        "anger":     ["Angry", "Rage", "Aggressive"],
    }

    for track_info in tracks_info:
        track_scale = track_info["track_scale"]
        variance = abs(track_scale - scale)
        if variance > 1:
            continue
        track_score = max(0.1, 3 - variance)
        artist_ids = track_info["artist_ids"]
        all_artist_ids.update(artist_ids)
        tracks_data.append((artist_ids, track_score))

    for artist_id in all_artist_ids:
        response = requests.get(
            f"https://api.spotify.com/v1/artists/{artist_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        artist = response.json()
        artists_genre[artist["id"]] = artist.get("genres", [])

    for artist_ids, track_score in tracks_data:
        genres = set()
        for artist_id in artist_ids:
            genres.update(artists_genre.get(artist_id, []))

        if not genres:
            continue
        per_genre_score = track_score / len(genres)
        for genre in genres:
            genre_chances[genre] = genre_chances.get(genre, 0) + per_genre_score
            total_genre_score += per_genre_score

    # Fallback: not enough data
    if not genre_chances:
        for _ in range(3):
            selected_mood = random.choice(mood_synonyms[mood])
            tracks = _search_playlist_tracks(token, selected_mood, 1)
            if tracks:
                recommended_tracks.update(tracks)
        _play_uris(token, list(recommended_tracks))
        return recommended_tracks

    for genre in genre_chances:
        genre_chances[genre] /= total_genre_score

    print(genre_chances)

    genres_list   = list(genre_chances.keys())
    genres_weight = list(genre_chances.values())
    genre_choice  = random.choices(genres_list, weights=genres_weight, k=5)

    for genre in genre_choice:
        genre_freq[genre] = genre_freq.get(genre, 0) + 1

    for genre, count in genre_freq.items():
        selected_mood = random.choice(mood_synonyms[mood])
        query = f"{selected_mood} {genre}"
        print(query)
        tracks = _search_playlist_tracks(token, query, count)
        if tracks:
            recommended_tracks.update(tracks)

    _play_uris(token, list(recommended_tracks))
    return recommended_tracks


def get_artists_data(token: str, artist_ids: list) -> dict:
    response = requests.get(
        "https://api.spotify.com/v1/artists",
        params={"ids": ",".join(artist_ids)},
        headers={"Authorization": f"Bearer {token}"},
    )
    response.raise_for_status()
    return response.json()


# Internal helpers

def _search_playlist_tracks(token: str, query: str, count: int) -> list:
    response = requests.get(
        "https://api.spotify.com/v1/search",
        params={"q": query, "type": ["playlist"], "limit": 10},
        headers={"Authorization": f"Bearer {token}"},
    )
    content = response.json().get("playlists", {})
    playlists = [p for p in content.get("items", []) if p is not None]

    if not playlists:
        return []

    selected_playlist = random.choice(playlists)
    print(f"playlist name: {selected_playlist['name']}")
    tracks = playlist_tracks(token, selected_playlist["id"])["tracks"]["items"]
    random.shuffle(tracks)
    return [t["track"]["uri"] for t in tracks[:count]]


def _play_uris(token: str, uris: list) -> None:
    requests.put(
        "https://api.spotify.com/v1/me/player/play",
        json={"uris": uris},
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
