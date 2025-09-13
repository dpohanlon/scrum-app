import matplotlib as mpl
import matplotlib.pyplot as plt

from scipy.stats import truncnorm

import numpy as np

import h5py

import os

import json

from datetime import datetime, timedelta

import re

from PIL import Image
from matplotlib.colors import Normalize
from matplotlib.cm import ScalarMappable
from scipy.stats import gaussian_kde

from matplotlib.colors import LinearSegmentedColormap

from matplotlib import rcParams

mpl.use("Agg")

rcParams["axes.facecolor"] = "FFFFFF"
rcParams["savefig.facecolor"] = "FFFFFF"
rcParams["xtick.direction"] = "in"
rcParams["ytick.direction"] = "in"

rcParams["axes.linewidth"] = 2.0

rcParams.update({"figure.autolayout": True})

plt.rcParams["figure.figsize"] = (6, 6)

LONDON_UNDERGROUND_COLORS = {
    "Bakerloo": "#B36305",
    "Central": "#E32017",
    "Circle": "#FFD300",
    "District": "#00782A",
    "Hammersmith & City": "#F3A9BB",
    "Jubilee": "#A0A5A9",
    "Metropolitan": "#9B0056",
    "Northern": "#000000",
    "Piccadilly": "#003688",
    "Victoria": "#0098D4",
    "Waterloo & City": "#95CDBA",
    "Elizabeth": "#A0A5A9",
}

def _sanitize_station_name(s):
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")

def _round_to_half_hour(tstr):
    t = datetime.strptime(tstr, "%H:%M")
    m = (t.minute + 15) // 30 * 30
    if m == 60:
        t = (t.replace(minute=0) + timedelta(hours=1))
    else:
        t = t.replace(minute=m)
    return t.strftime("%H:%M")

def _truncnorm_row(bin_centers, mean, std):
    a = (0 - mean) / std
    b = (100 - mean) / std
    vals = truncnorm.pdf(bin_centers, a, b, loc=mean, scale=std)
    s = vals.sum()
    return vals / s if s > 0 else vals

def hex_to_colormap(hex_color, name="custom_colormap", n=256):
    """
    Creates a linear segmented colormap from a single hex color.

    Parameters:
        hex_color (str): The hex color code (e.g., '#E32017').
        name (str): The name of the colormap.
        n (int): Number of discrete colors in the colormap.

    Returns:
        LinearSegmentedColormap: A Matplotlib colormap object.
    """

    hex_color = hex_color.lstrip("#")
    rgb = tuple(int(hex_color[i : i + 2], 16) / 255.0 for i in (0, 2, 4))

    colors = [(1, 1, 1), rgb]
    cmap = LinearSegmentedColormap.from_list(name, colors, N=n)
    return cmap

def crowding_api_dummy(station):
    return 0.5

def live_relative_crowding(station, maxima_dict, crowding_api):

    # Don't use for now
    #max_crowding = maxima_dict['station']

    return crowding_api(station)

def generate_live_overlay(current_time, station, direction, hdf5_dir, maxima_json, out_png, crowding_api, bins=200, std=30, overlay_path="assets/trainsparency.png", line_key="Piccadilly"):
    tkey = _round_to_half_hour(current_time).replace(":", "")
    fn = os.path.join(hdf5_dir, f"{_sanitize_station_name(station)}.h5")
    maxima = json.load(open(maxima_json, "rb"))
    line_entrances = json.load(open("data/line_entrances.json", "rb"))
    stations_pos = dict(line_entrances[line_key][0], **line_entrances[line_key][1])
    pos_idx = 1 if direction in ("WB", "SB") else 0

    xs = np.linspace(0, 100, bins + 1)
    centers = 0.5 * (xs[:-1] + xs[1:])
    mix_total = np.zeros_like(centers, dtype=float)

    with h5py.File(fn, "r") as h5:
        routes_grp = h5[direction][tkey]["routes"]
        n_routes = len(routes_grp.keys())
        for key in sorted(routes_grp.keys(), key=lambda s: int(s[1:])):
            g = routes_grp[key]
            full_path = [s for s in g["stations"][...].astype(str)]
            pivot_idx = int(g.attrs["pivot_idx"])
            upstream = full_path[:pivot_idx + 1]

            ws = np.array([live_relative_crowding(s, maxima, crowding_api) for s in upstream], dtype=float)
            sw = ws.sum()
            ws = ws / sw if sw > 0 else np.ones(len(upstream), dtype=float) / max(1, len(upstream))

            mix_route = np.zeros_like(centers, dtype=float)
            for s, w in zip(upstream, ws):
                m = stations_pos[s][pos_idx]
                mix_route += w * _truncnorm_row(centers, m, std)

            mix_total += mix_route

    mix_total /= max(1, n_routes)

    overlay_img = Image.open(overlay_path).convert("RGBA")
    img_w, img_h = overlay_img.size
    aspect = img_w / img_h
    overlay_np = np.array(overlay_img)

    fig_h = 6
    fig_w = fig_h * aspect
    dpi = 70

    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=dpi)

    norm = Normalize(vmin=mix_total.min(), vmax=mix_total.max())
    cmap = hex_to_colormap(LONDON_UNDERGROUND_COLORS.get(line_key, "#003688"))
    colors = cmap(norm(mix_total))

    bin_w = centers[1] - centers[0]
    ax.bar(centers, np.ones_like(centers), width=bin_w, color=colors, edgecolor="none", zorder=1)

    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_xlabel("")
    ax.set_ylabel("")
    ax.set_title("")
    for sp in ax.spines.values():
        sp.set_visible(False)

    extent = [0, 100, 0, 1]
    ax.imshow(overlay_np, extent=extent, aspect="auto", zorder=10, alpha=1.0, interpolation="bilinear")

    plt.tight_layout()
    fig.savefig(out_png, dpi=dpi, bbox_inches="tight", transparent=True)

if __name__ == "__main__":

    generate_live_overlay("09:35", "South Kensington", "WB", 'data', 'data/historical_maxima.json', 'overlay.png', bins=200, std=30, overlay_path="assets/trainsparency.png", line_key="Piccadilly")
