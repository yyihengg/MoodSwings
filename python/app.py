import json
import base64
import hashlib
import secrets
import string
import webbrowser

import requests
from flask import Flask, jsonify, request, render_template, url_for, redirect
from dotenv import dotenv_values
from livereload import Server

from state import AppState
from playback import (
    next_track,
    prev_track,
    resume_track,
    pause_track,
    get_devices,
    playlist_play,
    mood_play,
    shuffle_playback,
    store_mood,
    current_track,
)
from playlists import create_playlist, add_tracks, reorder_playlist
from recommendations import recommended_play, get_artists_data

# Configuration

config = dotenv_values(".env")

app = Flask(
    __name__,
    template_folder="../templates",
    static_folder="../static",
)

CLIENT_ID    = config["SPOTIFY_CLIENT_ID"]
REDIRECT_URI = config.get("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:5000/callback")
SCOPE        = config.get(
    "SPOTIFY_SCOPE",
    "playlist-read-private user-modify-playback-state user-library-modify "
    "user-read-currently-playing user-read-playback-state playlist-modify-private",
)

state = AppState()

# PKCE helpers

def _generate_code_verifier() -> str:
    return secrets.token_urlsafe(32)


def _generate_code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _generate_random_state() -> str:
    chars = string.ascii_letters + string.digits
    return "".join(secrets.choice(chars) for _ in range(16))


_code_verifier  = _generate_code_verifier()
_code_challenge = _generate_code_challenge(_code_verifier)
_random_state   = _generate_random_state()

# Auth routes

@app.route("/")
def index():
    auth_url = (
        "https://accounts.spotify.com/authorize"
        f"?client_id={CLIENT_ID}"
        f"&response_type=code"
        f"&redirect_uri={REDIRECT_URI}"
        f"&state={_random_state}"
        f"&scope={SCOPE}"
        f"&code_challenge_method=S256"
        f"&code_challenge={_code_challenge}"
    )
    return redirect(auth_url)


@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return "Authorisation failed — no code returned by Spotify.", 400

    response = requests.post(
        "https://accounts.spotify.com/api/token",
        data={
            "grant_type":    "authorization_code",
            "code":          code,
            "redirect_uri":  REDIRECT_URI,
            "client_id":     CLIENT_ID,
            "code_verifier": _code_verifier,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    if response.status_code != 200:
        return f"Token exchange failed: {response.text}", 500

    access_token = response.json().get("access_token")
    return redirect(url_for("music", access_token=access_token))


# UI route

@app.route("/music")
def music():
    # Serve the React SPA. Stores the initial token from the redirect query param
    token = request.args.get("access_token")
    if token:
        state.token = token
    return render_template("index.html")


# API helpers

def _ok(data: dict | None = None) -> tuple:
    return jsonify({"ok": True, **(data or {})}), 200


def _err(message: str, status: int = 400) -> tuple:
    return jsonify({"ok": False, "error": message}), status


def _require_token():
    if not state.token:
        return _err("Not authenticated — please restart and log in via Spotify.", 401)


# API routes

@app.post("/api/device")
def api_device():
    if (e := _require_token()):
        return e
    device_type = request.json.get("device")  # "Mobile" | "Computer"
    if device_type not in ("Mobile", "Computer"):
        return _err("device must be 'Mobile' or 'Computer'")

    devices = get_devices(state.token)
    device_id = devices.get(device_type)
    shuffle_playback(state.token, device_id)
    playlist_play(state.token, device_id)
    return _ok({"device_id": device_id})


@app.post("/api/transport")
def api_transport():
    if (e := _require_token()):
        return e
    action = request.json.get("action")  # "next" | "prev" | "pause" | "resume"
    if action == "next":
        next_track(state.token)
    elif action == "prev":
        prev_track(state.token)
    elif action == "pause":
        pause_track(state.token)
    elif action == "resume":
        resume_track(state.token)
    else:
        return _err("action must be one of: next, prev, pause, resume")
    return _ok()


@app.post("/api/record")
def api_record():
    # Tag the currently playing track with a mood and intensity scale
    if (e := _require_token()):
        return e
    body = request.json or {}
    mood  = body.get("mood")
    scale = body.get("scale")

    if mood not in ("happiness", "sadness", "anger"):
        return _err("mood must be one of: happiness, sadness, anger")
    if not isinstance(scale, int) or not (1 <= scale <= 5):
        return _err("scale must be an integer between 1 and 5")

    track_info = current_track(state.token)
    if not track_info:
        return _err("No track currently playing.")

    store_mood(state, {"recordMood": mood, "recordScale": scale}, track_info)
    get_artists_data(state.token, track_info["artist_ids"])
    print(f"Tagged: {track_info['track_name']} → {mood} @ {scale}")
    print(state.mood_tracks)
    return _ok({"track": track_info["track_name"]})


@app.post("/api/play")
def api_play():
    # Replay tagged tracks closest to the requested mood and intensity
    if (e := _require_token()):
        return e
    body  = request.json or {}
    mood  = body.get("mood")
    scale = body.get("scale")

    if mood not in ("happiness", "sadness", "anger"):
        return _err("mood must be one of: happiness, sadness, anger")
    if not isinstance(scale, int) or not (1 <= scale <= 5):
        return _err("scale must be an integer between 1 and 5")

    if not state.mood_tracks[mood]:
        return _err(f"No tracks tagged for mood '{mood}' yet.")

    mood_play(state, state.token, mood, scale)
    return _ok()


@app.post("/api/explore")
def api_explore():
    # Discover and play new tracks via the genre-weighted recommendation engine
    if (e := _require_token()):
        return e
    body  = request.json or {}
    mood  = body.get("mood")
    scale = body.get("scale")

    if mood not in ("happiness", "sadness", "anger"):
        return _err("mood must be one of: happiness, sadness, anger")
    if not isinstance(scale, int) or not (1 <= scale <= 5):
        return _err("scale must be an integer between 1 and 5")

    state.explore_tracks["mood"]  = mood
    state.explore_tracks["scale"] = scale
    state.explore_tracks["tracks"] = recommended_play(state, state.token, mood, scale)
    return _ok()


@app.post("/api/playlist")
def api_playlist():
    # Create (or update) the playlist for a given mood with all tagged tracks
    if (e := _require_token()):
        return e
    mood = (request.json or {}).get("mood")

    if mood not in ("happiness", "sadness", "anger"):
        return _err("mood must be one of: happiness, sadness, anger")

    create_playlist(state, state.token, mood)
    add_tracks(state, state.token, mood, add_current=False)
    return _ok({"playlist_id": state.playlists[mood]["playlist_id"]})


@app.post("/api/playlist/sort")
def api_playlist_sort():
    # Reorder a mood playlist by intensity (ascending or descending)
    if (e := _require_token()):
        return e
    body    = request.json or {}
    mood    = body.get("mood")
    reverse = body.get("reverse", False)

    if mood not in ("happiness", "sadness", "anger"):
        return _err("mood must be one of: happiness, sadness, anger")
    if mood not in state.playlists or "playlist_id" not in state.playlists[mood]:
        return _err(f"No playlist found for mood '{mood}'. Create it first.")

    reorder_playlist(state, state.token, mood, reverse)
    return _ok()


@app.post("/api/playlist/add")
def api_playlist_add():
    # Add the currently playing track to its corresponding mood playlist
    if (e := _require_token()):
        return e

    track_info = current_track(state.token)
    if not track_info:
        return _err("No track currently playing.")

    track_name = track_info["track_name"]
    track_uri  = track_info["track_uri"]

    # Check if the track was manually tagged
    track_mood = None
    for mood, tracks in state.mood_tracks.items():
        if track_name in tracks:
            track_mood = mood
            break

    if track_mood:
        scale = state.mood_tracks[track_mood][track_name]["track_scale"]
        track_uris = state.playlists[track_mood].setdefault(scale, [])
        if track_uri in track_uris:
            return _err("Track is already in the playlist.")
        state.playlists[track_mood][scale].append(track_uri)
        add_tracks(state, state.token, track_mood, add_current=True)
        return _ok({"mood": track_mood})

    # Check if the track came from an explore session
    explore_tracks = state.explore_tracks.get("tracks", set())
    if track_uri in explore_tracks:
        mood  = state.explore_tracks["mood"]
        scale = state.explore_tracks["scale"]
        track_uris = state.playlists[mood].setdefault(scale, [])
        if track_uri in track_uris:
            return _err("Track is already in the playlist.")
        state.playlists[mood][scale].append(track_uri)
        store_mood(state, {"recordMood": mood, "recordScale": scale}, track_info)
        add_tracks(state, state.token, mood, add_current=True)
        return _ok({"mood": mood})

    return _err("Track is not tagged and was not part of an explore session. Tag it first.")



if __name__ == "__main__":
    auth_url = (
        "https://accounts.spotify.com/authorize"
        f"?client_id={CLIENT_ID}"
        f"&response_type=code"
        f"&redirect_uri={REDIRECT_URI}"
        f"&state={_random_state}"
        f"&scope={SCOPE}"
        f"&code_challenge_method=S256"
        f"&code_challenge={_code_challenge}"
    )
    webbrowser.open(auth_url)

    server = Server(app.wsgi_app)
    server.watch("templates/*.html")
    server.watch("static/**/*.js")
    server.serve(port=5000, debug=True)
