from flask import Flask, request, render_template, jsonify, url_for

import json

import hashlib

from datetime import datetime

from crowding import _live_crowding, live_crowding, best_station_match

from occupancy import generate_live_overlay

app = Flask(__name__)

def current_time_str():
    """Return current local time as 'HH:MM' string (24-hour clock)."""
    return datetime.now().strftime("%H:%M")

def md5_of_string(s):
    """Return the hex MD5 digest of a string."""
    return hashlib.md5(s.encode("utf-8")).hexdigest()

def get_stations():

    lines = json.load(open("data/london_underground_lines.json", "rb"))

    piccadilly = list(set([x for sublist in lines['Piccadilly'] for x in sublist]))

    return piccadilly

def get_crowding(station, direction):

    crowding_data = _live_crowding(best_station_match(station)[0])

    img_path = get_graphic(station, direction)

    if crowding_data['dataAvailable'] == True:
        data = str(crowding_data['percentageOfBaseline'])
    else:
        data = str(1.)

    return jsonify({
        "crowding": data,
        "image_url": url_for("static", filename=img_path)
    })

def get_graphic(station, direction):

    current_time = current_time_str()

    file_name = f"{md5_of_string(station + direction + str(current_time))}.png"

    generate_live_overlay(current_time, station, direction, 'data', 'data/historical_maxima.json', f"static/{file_name}", live_crowding, bins=200, std=30, overlay_path="assets/trainsparency.png", line_key="Piccadilly")

    return file_name

@app.get("/")
def index():
    stations = get_stations()
    return render_template("index.html", stations=stations, page_title="Train Car Crowding")

@app.get("/crowding")
def crowding():
    station = request.args.get("station")
    direction = request.args.get("direction", "WB")
    return get_crowding(station, direction)

@app.get("/healthz")
def healthz():
    return "ok"
