#!/usr/bin/env python3
"""A small web widget that shows the forecast for the configured places.

It reads the database the service writes to, so the widget can be running
while new data comes in.

    ecmwf-widget                     # serve on http://localhost:8765
    ecmwf-widget --port 9000
    ecmwf-widget --open              # also open a browser
    ecmwf-widget --text              # print the text version and exit

The page refreshes itself, so a new forecast run appears without a reload.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import models, paths
from .config import load_config
from .forecast import ForecastReader, render_text
from .store import ForecastStore

__all__ = ["WidgetServer", "main", "manifest"]


def icon_dir() -> str:
    """The directory the weather icons are read from."""
    return str(paths.icon_dir())


def manifest() -> dict:
    """The web app manifest, so the page can be installed on a phone."""
    return {
        "name": "ECMWF forecast",
        "short_name": "ECMWF",
        "description": "Point forecasts from ECMWF's free and open 0.1° data",
        "start_url": "./",
        "scope": "./",
        "display": "standalone",
        "orientation": "any",
        "background_color": "#12161c",
        "theme_color": "#1d6fb8",
        "icons": [
            {"src": "app-icon-192.png", "sizes": "192x192", "type": "image/png"},
            {
                "src": "app-icon-512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable",
            },
        ],
    }

PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ECMWF forecast</title>
<link rel="manifest" href="manifest.webmanifest">
<meta name="theme-color" content="#1d6fb8">
<meta name="description" content="Point forecasts from ECMWF's free and open 0.1° data">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="ECMWF">
<link rel="apple-touch-icon" href="app-icon-192.png">
<link rel="icon" href="app-icon-192.png">
<style>
  :root {
    --bg: #f4f6f8;
    --card: #ffffff;
    --fg: #1c2430;
    --muted: #6b7785;
    --line: #e3e8ee;
    --accent: #1d6fb8;
    --rain: #0aa6ff;
    --sun: #e8a33d;
    --shadow: 0 1px 2px rgba(16,24,40,.06), 0 8px 24px rgba(16,24,40,.06);
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg: #12161c;
      --card: #1a1f27;
      --fg: #e7ecf2;
      --muted: #8d99a8;
      --line: #2a313b;
      --accent: #5aa9e6;
      --rain: #38b9ff;
      --sun: #f0b95c;
      --shadow: 0 1px 2px rgba(0,0,0,.3), 0 8px 24px rgba(0,0,0,.28);
    }
  }
  :root[data-theme="dark"] {
    --bg: #12161c;
    --card: #1a1f27;
    --fg: #e7ecf2;
    --muted: #8d99a8;
    --line: #2a313b;
    --accent: #5aa9e6;
    --rain: #38b9ff;
    --sun: #f0b95c;
    --shadow: 0 1px 2px rgba(0,0,0,.3), 0 8px 24px rgba(0,0,0,.28);
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 24px 20px 56px;
    background: var(--bg); color: var(--fg);
    font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    -webkit-font-smoothing: antialiased;
  }
  .wrap { max-width: 1240px; margin: 0 auto; }
  header.top {
    display: flex; flex-wrap: wrap; align-items: center; gap: 10px 12px;
    margin-bottom: 20px;
  }
  header.top h1 { font-size: 20px; font-weight: 650; margin: 0; letter-spacing: -.01em; }
  .meta { color: var(--muted); font-size: 13.5px; }
  .meta b { color: var(--fg); font-weight: 550; }
  .grow { flex: 1; }
  select, button, input {
    font: inherit; font-size: 13.5px; padding: 6px 10px; color: var(--fg);
    background: var(--card); border: 1px solid var(--line); border-radius: 8px;
    max-width: 100%;
  }
  button { cursor: pointer; }
  button:hover, select:hover, input:hover { border-color: var(--accent); }
  button.on { border-color: var(--accent); color: var(--accent); }

  /* Place picker ------------------------------------------------------- */
  .picker { position: relative; min-width: 250px; }
  .picker input { width: 100%; padding-left: 30px; }
  .picker .flag { position: absolute; left: 10px; top: 50%; transform: translateY(-50%);
                  font-size: 14px; pointer-events: none; }
  .picker ul {
    position: absolute; z-index: 30; top: calc(100% + 4px); left: 0; right: 0;
    margin: 0; padding: 4px; list-style: none; max-height: 320px; overflow-y: auto;
    background: var(--card); border: 1px solid var(--line); border-radius: 10px;
    box-shadow: var(--shadow); display: none;
  }
  .picker.open ul { display: block; }
  .picker li { padding: 7px 9px; border-radius: 7px; cursor: pointer; font-size: 13.5px; }
  .picker li:hover, .picker li.active { background: color-mix(in srgb, var(--accent) 12%, transparent); }
  .picker li .c { color: var(--muted); font-size: 12px; margin-left: 6px; }
  .picker li .k { color: var(--muted); font-size: 11px; margin-left: 6px; }

  /* Parameter panel ---------------------------------------------------- */
  .tools { position: relative; display: flex; flex-wrap: wrap; align-items: center; gap: 10px 12px; }
  .panel {
    position: absolute; z-index: 40; right: 0; top: calc(100% + 8px);
    width: 520px; max-height: calc(100vh - 110px);
    overflow-y: auto; background: var(--card); border: 1px solid var(--line);
    border-radius: 12px; box-shadow: var(--shadow); padding: 14px; display: none;
  }
  .panel.open { display: block; }
  .panel h3 { margin: 0 0 4px; font-size: 14px; font-weight: 600; }
  .panel p { margin: 0 0 12px; color: var(--muted); font-size: 12px; }
  .panel .group { margin-bottom: 12px; }
  .panel .items { display: grid; grid-template-columns: 1fr 1fr; gap: 0 20px; align-items: start; }
  .panel .group-items { display: block; }
  .panel .search { width: 100%; margin: 0 0 10px; padding: 5px 9px; font-size: 13px; }
  .panel .group > h4 {
    margin: 0 0 6px; font-size: 11px; text-transform: uppercase; letter-spacing: .05em;
    color: var(--muted); font-weight: 600;
  }
  .panel label {
    display: flex; align-items: center; gap: 8px; padding: 4px 0; cursor: pointer;
    font-size: 13.5px; min-width: 0;
  }
  .panel label > span:not(.swatch) { overflow: hidden; text-overflow: ellipsis; }
  .panel label:hover { color: var(--accent); }
  .panel label.off { opacity: .38; }
  .panel label.off:hover { color: var(--muted); }
  .panel p.note { margin: 12px 0 0; font-size: 11.5px; line-height: 1.45; }
  .panel input[type=checkbox] { accent-color: var(--accent); width: 15px; height: 15px; margin: 0; }
  .panel .swatch { width: 11px; height: 11px; border-radius: 3px; flex: none; }
  .panel .unit { color: var(--muted); font-size: 11.5px; margin-left: auto;
                 white-space: nowrap; flex: none; padding-left: 4px; }

  /* Cards -------------------------------------------------------------- */
  .place {
    background: var(--card); border: 1px solid var(--line); border-radius: 14px;
    box-shadow: var(--shadow); padding: 20px 22px 22px; margin-bottom: 20px;
    position: relative;
  }
  .place-head { display: flex; align-items: center; gap: 20px; }
  .place-head > div:first-child { flex: 1; min-width: 0; }
  .place-head h2 {
    font-size: 19px; font-weight: 640; margin: 0; letter-spacing: -.01em;
    display: flex; align-items: center; gap: 7px;
  }
  .place-head h2 svg, .place-head h2 img.icon { flex: none; }
  .sub { color: var(--muted); font-size: 12.5px; margin-top: 4px; }
  .condition { text-align: center; flex: none; }
  .condition svg, .condition img.icon { display: block; margin: 0 auto 2px; }
  .condition .label { font-size: 12px; color: var(--muted); }
  .banner {
    display: flex; align-items: center; gap: 8px; margin: 16px 0 -4px;
    font-size: 13px; color: var(--accent);
    background: color-mix(in srgb, var(--accent) 9%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent) 28%, transparent);
    border-radius: 9px; padding: 6px 8px 6px 11px; width: fit-content;
  }
  .banner button {
    margin-left: 6px; padding: 3px 9px; font-size: 12.5px;
    background: transparent; color: var(--accent);
    border-color: color-mix(in srgb, var(--accent) 38%, transparent);
  }
  /* The time sits on the right of the place, vertically centred. */
  .when { flex: none; text-align: right; }
  .stamp {
    font-size: 25px; font-weight: 600; letter-spacing: -.015em;
    color: var(--fg); line-height: 1.2; white-space: nowrap;
  }
  .now {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 10px; margin: 0 0 20px;
  }
  .stat {
    background: var(--bg); border: 1px solid var(--line); border-radius: 11px;
    padding: 10px 12px; min-width: 0;
  }
  .stat .k {
    color: var(--muted); font-size: 10.5px; text-transform: uppercase;
    letter-spacing: .03em; line-height: 1.25; overflow-wrap: normal;
    display: flex; align-items: center; gap: 4px; min-width: 0;
  }
  .stat .k span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .stat .k svg, .stat .k img.icon { flex: none; opacity: .8; }
  .stat .v { font-size: 19px; font-weight: 600; margin-top: 3px; letter-spacing: -.02em; }
  .stat .v small { font-size: 12.5px; font-weight: 500; color: var(--muted); margin-left: 2px; }
  .stat.big .v { font-size: 30px; }
  .stat.more { display: flex; align-items: center; justify-content: center;
                color: var(--muted); font-size: 12.5px; }

  /* Chart -------------------------------------------------------------- */
  .chart { margin: 2px 0 22px; overflow-x: auto; scrollbar-width: thin; position: relative; }
  .chart svg { width: 100%; height: auto; display: block; overflow: visible; min-width: 560px; }
  .legend { display: flex; flex-wrap: wrap; gap: 6px 14px; margin: 0 0 10px; font-size: 12.5px; }
  .legend span { display: inline-flex; align-items: center; gap: 6px; color: var(--muted); }
  .legend i { width: 11px; height: 3px; border-radius: 2px; display: inline-block; }
  .legend b { color: var(--fg); font-weight: 600; font-variant-numeric: tabular-nums; }
  .tip {
    position: fixed; z-index: 60; pointer-events: none; opacity: 0; transition: opacity .1s;
    background: var(--card); border: 1px solid var(--line); border-radius: 10px;
    box-shadow: var(--shadow); padding: 9px 11px; font-size: 12.5px; min-width: 150px;
  }
  .tip { visibility: hidden; }
  .tip.on { opacity: 1; visibility: visible; }
  .tip .t { color: var(--muted); margin-bottom: 5px; font-size: 11.5px; }
  .tip .r { display: flex; align-items: center; gap: 7px; }
  .tip .r i { width: 9px; height: 9px; border-radius: 2px; flex: none; }
  .tip .r b { margin-left: auto; font-variant-numeric: tabular-nums; }

  /* Table -------------------------------------------------------------- */
  .grid { overflow-x: auto; scrollbar-width: thin; }
  .inner { min-width: 100%; }
  /* Fixed columns, so the chart can be drawn on exactly the same grid. */
  table { border-collapse: collapse; width: 100%; min-width: 640px; table-layout: fixed; }
  thead th:first-child, tbody th { width: 190px; min-width: 190px; }
  th, td { padding: 7px 6px; text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
  thead th {
    color: var(--muted); font-weight: 500; position: sticky; background: var(--card);
  }
  thead tr.days th {
    font-size: 12px; font-weight: 650; text-transform: uppercase; letter-spacing: .05em;
    color: var(--muted); padding-bottom: 3px; text-align: center;
  }
  /* A rule between the days, so it is clear where one day ends. */
  .day-start { border-left: 1px solid var(--line); }
  thead tr.days th.day-start { border-left: 1px solid var(--line); }
  tbody tr.summary td {
    font-size: 12.5px; color: var(--muted); text-align: center;
    padding-top: 5px; padding-bottom: 5px; white-space: nowrap;
  }
  tbody tr.summary th {
    font-size: 11px; text-transform: uppercase; letter-spacing: .05em;
    color: var(--muted);
  }
  tbody tr.summary td:first-of-type { border-left: none; }
  thead tr.days th.now-col { color: var(--accent); }
  thead tr.times th {
    font-size: 13.5px; font-weight: 500; padding-top: 1px; padding-bottom: 7px;
    border-bottom: 1px solid var(--line);
  }
  thead tr.times th.now-col { color: var(--accent); font-weight: 700; }
  thead tr.times th.clickable { cursor: pointer; }
  thead tr.times th.clickable:hover { color: var(--accent); }
  thead tr.times th.clickable::after { content: ""; }
  thead tr.times th.now-col { background: color-mix(in srgb, var(--accent) 7%, transparent); }
  tbody th {
    text-align: left; font-weight: 500; font-size: 14.5px; color: var(--muted);
    position: sticky; left: 0; background: var(--card); padding-right: 16px;
    max-width: 190px; overflow: hidden;
  }
  tbody th .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  tbody th svg, tbody th img.icon { vertical-align: -3px; margin-right: 6px; opacity: .85; }
  tbody th i { width: 9px; height: 9px; border-radius: 3px; display: inline-block; margin-right: 7px; }
  tbody td { border-top: 1px solid var(--line); font-size: 14.5px; }
  tbody td.clickable { cursor: pointer; }
  tbody td.clickable:hover { color: var(--accent); }
  tbody td.now-col { background: color-mix(in srgb, var(--accent) 7%, transparent); font-weight: 600; }
  tbody tr:hover td { background: color-mix(in srgb, var(--accent) 4%, transparent); }
  /* Precipitation is drawn as a small column chart, so the column keeps the
     same width as every other one. */
  td.precip { padding: 4px 7px; }
  .pp { display: inline-flex; align-items: flex-end; gap: 6px; }
  .pp .num { font-variant-numeric: tabular-nums; line-height: 20px; }
  .pp .gauge {
    width: 12px; height: 20px; border-radius: 3px;
    background: var(--line); opacity: .55;
    display: flex; align-items: flex-end; overflow: hidden;
    flex: none;
  }
  /* The bar must keep the height it is given, so it is not allowed to
     shrink inside the gauge. */
  .pp .gauge i {
    display: block; width: 100%; background: var(--rain);
    border-radius: 3px; flex: none;
  }
  .foot { color: var(--muted); font-size: 12px; text-align: center; margin-top: 26px; }
  .empty { color: var(--muted); padding: 40px; text-align: center; }
  .dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: var(--accent); margin-right: 7px; vertical-align: 1px; }
  .conds td { padding-top: 8px; padding-bottom: 8px; }
  .conds svg, .conds img.icon { vertical-align: middle; }
  @media (max-width: 620px) {
    body { padding: 16px 12px 40px; }
    .place { padding: 16px 14px 18px; border-radius: 12px; }
    .place-head { flex-wrap: wrap; gap: 10px 14px; }
    .place-head > div:first-child { flex: 1 1 100%; }
    .when { flex: 1; text-align: left; order: 3; }
    .stamp { font-size: 21px; white-space: normal; }
    .condition { order: 2; margin-left: auto; text-align: right; }
    .panel { right: 8px; left: 8px; width: auto; }
  }
</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <h1>ECMWF forecast</h1>
    <div class="meta" id="meta"></div>
    <div class="grow"></div>
    <div class="tools">
      <select id="model" title="Forecast model"></select>
      <div class="picker" id="picker">
        <span class="flag" id="pickerFlag"></span>
        <input id="placeInput" placeholder="Choose a place" autocomplete="off" spellcheck="false">
        <ul id="placeList"></ul>
      </div>
      <select id="run" title="Forecast run"></select>
      <button id="clock" title="Show the times in the local time or in UTC">Local</button>
      <button id="params" title="Choose the parameters to show">Parameters</button>
      <button id="tooltips" aria-pressed="false">Tooltips: off</button>
      <button id="theme" title="Switch between light and dark">Auto</button>

      <div class="panel" id="panel">
        <h3>Parameters</h3>
        <p>Pick what to show in the chart and the table. The choice is kept in the address.</p>
        <div id="panelBody"></div>
      </div>
    </div>
  </header>

  <div id="content"><div class="empty">Loading&hellip;</div></div>
  <p class="foot">
    <span class="dot"></span>Generated using ECMWF free and open data (CC-BY-4.0)<span id="refresh"> &middot; refreshed every 60&nbsp;s</span>
  </p>
</div>
<div class="tip" id="tip"></div>
<script>
const REFRESH_MS = 60000;

// --------------------------------------------------------------------------- //
// Icons
// --------------------------------------------------------------------------- //
const ICONS = {
  sun: `<circle cx="12" cy="12" r="4.2"/>
    <g stroke-linecap="round"><path d="M12 2.6v2.1M12 19.3v2.1M2.6 12h2.1M19.3 12h2.1M5.4 5.4l1.5 1.5M17.1 17.1l1.5 1.5M18.6 5.4l-1.5 1.5M6.9 17.1l-1.5 1.5"/></g>`,
  partly: `<circle cx="8" cy="8" r="3.1"/>
    <g stroke-linecap="round"><path d="M8 2.2v1.5M8 12.3v1.5M2.2 8h1.5M12.3 8h1.5M3.9 3.9l1 1M11.1 11.1l1 1M12.1 3.9l-1 1M4.9 11.1l-1 1"/></g>
    <path d="M10 20h7.6a3.4 3.4 0 0 0 .2-6.8A5.2 5.2 0 0 0 7.9 14.6 2.9 2.9 0 0 0 10 20z"/>`,
  cloud: `<path d="M7 19h9.6a4 4 0 0 0 .3-8A6 6 0 0 0 5.4 9.6 3.5 3.5 0 0 0 7 19z"/>`,
  rain: `<path d="M7 15.5h9.6a4 4 0 0 0 .3-8A6 6 0 0 0 5.4 6.1 3.5 3.5 0 0 0 7 15.5z"/>
    <g stroke-linecap="round"><path d="M8.6 18.2l-.9 2.6M12 18.2l-.9 2.6M15.4 18.2l-.9 2.6"/></g>`,
  snow: `<path d="M7 15.5h9.6a4 4 0 0 0 .3-8A6 6 0 0 0 5.4 6.1 3.5 3.5 0 0 0 7 15.5z"/>
    <g stroke-linecap="round"><path d="M8.6 18.4v2.4M7.8 19l1.6 1.2M9.4 19l-1.6 1.2"/>
    <path d="M14.2 18.4v2.4M13.4 19l1.6 1.2M15 19l-1.6 1.2"/></g>`,
  sleet: `<path d="M7 15.5h9.6a4 4 0 0 0 .3-8A6 6 0 0 0 5.4 6.1 3.5 3.5 0 0 0 7 15.5z"/>
    <g stroke-linecap="round"><path d="M8.6 18.2l-.9 2.6M15.4 18.2l-.9 2.6"/></g>
    <path d="M12 18.2v2.6M11.2 18.8l1.6 1.2M12.8 18.8l-1.6 1.2"/>`,
  storm: `<path d="M7 14.5h9.6a4 4 0 0 0 .3-8A6 6 0 0 0 5.4 5.1 3.5 3.5 0 0 0 7 14.5z"/>
    <path d="M13 15.5l-3.2 4.2h2.6l-1.1 3.4" stroke-linejoin="round" stroke-linecap="round"/>`,
  wind: `<g stroke-linecap="round"><path d="M2.8 8.5h9.4a2.6 2.6 0 1 0-2.6-2.6"/>
    <path d="M2.8 12.5h13a2.6 2.6 0 1 1-2.6 2.6"/><path d="M2.8 16.5h6.4"/></g>`,
  thermo: `<path d="M10 4.2a2 2 0 0 1 2 2v5.9a4 4 0 1 1-4 0V6.2a2 2 0 0 1 2-2z"/>
    <circle cx="10" cy="16.3" r="1.7" stroke="none"/>`,
  drop: `<path d="M12 3.2s6 6.3 6 10a6 6 0 0 1-12 0c0-3.7 6-10 6-10z"/>`,
  gauge: `<path d="M4 17.5a8 8 0 1 1 16 0" stroke-linecap="round"/>
    <path d="M12 17.5l4.2-4.6" stroke-linecap="round"/><circle cx="12" cy="17.5" r="1.3" stroke="none"/>`,
  clock: `<circle cx="12" cy="12" r="8.2"/><path d="M12 7.2V12l3.2 2" stroke-linecap="round"/>`,
};

const PARAM_ICON = {
  "2t": "thermo", "temperature_adjusted": "thermo", "apparent_temperature": "feels",
  "2d": "drop", "wind_speed": "wind", "wind_dir": "wind", "gust": "gust",
  "10fg": "gust", "10u": "wind", "10v": "wind", "msl": "gauge",
  "tp": "rain-drop", "precip_increment": "rain-drop", "tcc": "cloud-cover",
};

const SVG_FALLBACK = {
  sun: "sun", partly: "partly", cloud: "cloud", rain: "rain", snow: "snow",
  sleet: "sleet", storm: "storm", wind: "wind", thermo: "thermo", drop: "drop",
  gauge: "gauge", clock: "clock", feels: "thermo", gust: "wind",
  "rain-drop": "drop", "cloud-cover": "cloud",
};

// A colour per parameter, so the chart and the table agree.
const PARAM_COLOUR = {
  "2t": "#e4572e", "temperature_adjusted": "#b8332a", "apparent_temperature": "#d9739a",
  "2d": "#17a2a2", "wind_speed": "#1d6fb8", "wind_dir": "#6c5ce7", "gust": "#0e9aa7",
  "10fg": "#0e9aa7", "10u": "#6c8ebf", "10v": "#8fa8d8", "msl": "#7d5ba6",
  "tp": "#0b9af8", "precip_increment": "#0b9af8", "tcc": "#7b8794",
};
const PALETTE = ["#e4572e", "#1d6fb8", "#17a2a2", "#7d5ba6", "#c98a1b", "#2e8b57", "#b8332a", "#6c5ce7"];

const SVG_NS = "http://www.w3.org/2000/svg";
function svg(markup, size, cls) {
  const node = document.createElementNS(SVG_NS, "svg");
  node.setAttribute("viewBox", "0 0 24 24");
  node.setAttribute("width", size || 16);
  node.setAttribute("height", size || 16);
  node.setAttribute("fill", "none");
  node.setAttribute("stroke", "currentColor");
  node.setAttribute("stroke-width", "1.7");
  node.setAttribute("stroke-linecap", "round");
  if (cls) node.setAttribute("class", cls);
  node.innerHTML = markup;
  return node;
}

// Icons live next to the page, which is not always at the root of the site.
const ICON_BASE = new URL("icons/", window.location.href).href;

// A few symbols are drawn instead of generated, because they are simpler
// as a line drawing than as a picture.
const DRAWN_ONLY = new Set(["pin", "clock"]);

function icon(name, size, cls) {
  const fallback = SVG_FALLBACK[name] || "cloud";
  if (DRAWN_ONLY.has(name)) return svg(ICONS[fallback] || ICONS.cloud, size, cls);
  const picture = document.createElement("img");
  picture.src = ICON_BASE + name + ".png";
  picture.width = size || 16;
  picture.height = size || 16;
  picture.alt = "";
  picture.className = "icon" + (cls ? " " + cls : "");
  picture.decoding = "async";
  picture.onerror = () => {
    picture.replaceWith(svg(ICONS[fallback] || ICONS.cloud, size || 16, cls));
  };
  return picture;
}

const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
};

// --------------------------------------------------------------------------- //
// Weather condition from the forecast itself
// --------------------------------------------------------------------------- //
const SNOW_TYPES = [2, 4, 10, 11, 12, 14];
const SLEET_TYPES = [3, 6];

function conditionFor(series, index) {
  const get = (key) => {
    const s = series[key];
    return s && s.values[index] !== null && s.values[index] !== undefined ? s.values[index] : null;
  };
  const cloud = get("tcc");
  const rain = get("precip_increment");
  const ptype = get("ptype");
  const cape = get("mucape");

  if (rain !== null && rain > 0.05) {
    if (ptype !== null && SLEET_TYPES.includes(Math.round(ptype))) return { key: "sleet", label: "Sleet" };
    if (ptype !== null && SNOW_TYPES.includes(Math.round(ptype))) return { key: "snow", label: "Snow" };
    if (cape !== null && cape > 1200) return { key: "storm", label: "Thunder" };
    return { key: "rain", label: "Rain" };
  }
  if (cloud === null) return { key: "cloud", label: "" };
  if (cloud >= 80) return { key: "cloud", label: "Overcast" };
  if (cloud >= 25) return { key: "partly", label: "Partly cloudy" };
  return { key: "sun", label: "Clear" };
}

function format(series, value) {
  if (value === null || value === undefined) return "–";
  switch (series.param) {
    case "wind_dir": return Math.round(value) + "°";
    case "wind_speed": case "gust": return Math.round(value) + " " + series.unit;
    case "tp": case "precip_increment": return value.toFixed(1) + " " + series.unit;
    case "tcc": case "hcc": case "mcc": case "lcc": return Math.round(value) + "%";
    case "ptype": return String(Math.round(value));
    case "msl": return Math.round(value) + " " + series.unit;
    default:
      if (series.unit === "degC") return value.toFixed(1) + "°";
      return value.toFixed(1) + " " + series.unit;
  }
}

// The colours of the wind arrow, by the Beaufort force.
const BEAUFORT_LIMITS = [0.5, 1.5, 3.3, 5.5, 7.9, 10.7, 13.8, 17.1, 20.7, 24.4];
const BEAUFORT_COLOURS = [
  [3, "#4caf50"], [5, "#c8c000"], [7, "#e8850c"],
  [9, "#d0342c"], [11, "#8e44ad"], [99, "#7d4b28"],
];

function beaufortForce(metresPerSecond) {
  let force = 0;
  for (const limit of BEAUFORT_LIMITS) {
    if (metresPerSecond < limit) break;
    force += 1;
  }
  return force;
}

function beaufortColour(kmh) {
  const force = beaufortForce(kmh / 3.6);
  for (const [limit, colour] of BEAUFORT_COLOURS) {
    if (force <= limit) return colour;
  }
  return "#7d4b28";
}

// An arrow built from the two wind components: it points the way the wind
// blows and its length grows with the speed.
function windVector(u, v, maxSpeed) {
  const size = 26;
  const node = svg("", size);
  node.setAttribute("viewBox", "-13 -13 26 26");
  node.setAttribute("class", "vector");

  const speed = Math.hypot(u, v);
  const length = maxSpeed ? Math.max(5, (speed / maxSpeed) * 11) : 9;
  const angle = Math.atan2(-v, -u);

  const shaft = document.createElementNS(SVG_NS, "line");
  shaft.setAttribute("x1", 0);
  shaft.setAttribute("y1", 0);
  shaft.setAttribute("x2", (length * Math.cos(angle)).toFixed(2));
  shaft.setAttribute("y2", (-length * Math.sin(angle)).toFixed(2));
  shaft.setAttribute("stroke", "currentColor");
  shaft.setAttribute("stroke-width", "2");
  shaft.setAttribute("stroke-linecap", "round");
  node.appendChild(shaft);

  const head = document.createElementNS(SVG_NS, "path");
  const tipX = length * Math.cos(angle);
  const tipY = -length * Math.sin(angle);
  head.setAttribute("d",
    `M${tipX.toFixed(2)},${tipY.toFixed(2)} `
    + `L${(tipX - 4 * Math.cos(angle - 0.5)).toFixed(2)},${(-tipY + 4 * Math.sin(angle - 0.5)).toFixed(2)} `
    + `L${(tipX - 4 * Math.cos(angle + 0.5)).toFixed(2)},${(-tipY + 4 * Math.sin(angle + 0.5)).toFixed(2)} Z`);
  head.setAttribute("fill", "currentColor");
  node.appendChild(head);

  return node;
}

function arrow(degrees, speed) {
  const node = svg(
    `<path d="M12 2.5 L12 21.5 M12 2.5 L7.5 8 M12 2.5 L16.5 8" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>`,
    16,
    "arrow"
  );
  node.style.transform = `rotate(${degrees + 180}deg)`;
  if (speed !== undefined) node.style.color = beaufortColour(speed);
  return node;
}

// --------------------------------------------------------------------------- //
// State
// --------------------------------------------------------------------------- //
const modelSelect = document.getElementById("model");
const runSelect = document.getElementById("run");

const state = {
  model: null,
  run: null,
  place: null,
  visible: new Set(),
  data: null,
  catalogue: [],
  // The step the user picked, or null to follow the current hour.
  selected: null,
  // "local" or "utc".
  clock: "local",
  tooltips: false,
  selectionLoaded: false,
};

function colourFor(key, index) {
  if (PARAM_COLOUR[key]) return PARAM_COLOUR[key];
  return PALETTE[index % PALETTE.length];
}

function saveState() {
  try {
    localStorage.setItem("ecmwf-visible", JSON.stringify([...state.visible]));
  } catch (e) { /* private mode */ }
}
function loadState() {
  try {
    const raw = localStorage.getItem("ecmwf-visible");
    if (raw) { state.visible = new Set(JSON.parse(raw)); state.selectionLoaded = true; }
  } catch (e) { /* private mode */ }
}
loadState();

function syncUrl() {
  const params = new URLSearchParams(location.search);
  const set = (key, value) => {
    if (value) params.set(key, value); else params.delete(key);
  };
  set("model", state.model);
  set("run", state.run);
  set("place", state.place);
  set("theme", document.documentElement.getAttribute("data-theme"));
  if (state.visible.size) params.set("params", [...state.visible].join(","));
  else params.delete("params");
  history.replaceState(null, "", location.pathname + "?" + params.toString());
}

// --------------------------------------------------------------------------- //
// The chart
// --------------------------------------------------------------------------- //
function drawChart(place, series, keys, selected, select, box, labelWidth) {
  const drawn = keys
    .map((key) => series[key])
    .filter((entry) => entry && entry.values.some((v) => v !== null));
  if (!drawn.length) return null;

  // The chart is drawn in the same pixels as the table, so the columns of
  // the two line up exactly.
  const W = Math.max(640, box.clientWidth || 1000);
  const padL = labelWidth;
  const padR = 0;
  const padT = 8, padB = 26;
  const bandHeight = 52, gap = 10;
  const n = place.steps.length;
  const H = padT + drawn.length * (bandHeight + gap) + padB;

  // The points sit in the middle of the columns, like the table does.
  const column = (W - padL - padR) / n;
  const x = (i) => padL + (i + 0.5) * column;

  const root = svg("", 1);
  root.setAttribute("viewBox", `0 0 ${W} ${H}`);
  root.setAttribute("width", "100%");
  root.setAttribute("height", "auto");
  root.setAttribute("preserveAspectRatio", "xMidYMid meet");
  root.removeAttribute("stroke-width");
  root.setAttribute("stroke", "none");

  const add = (tag, attrs, parent) => {
    const node = document.createElementNS(SVG_NS, tag);
    Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, v));
    (parent || root).appendChild(node);
    return node;
  };

  const style = getComputedStyle(document.documentElement);
  const lineColour = (style.getPropertyValue("--line") || "#e3e8ee").trim();
  const mutedColour = (style.getPropertyValue("--muted") || "#6b7785").trim();

  drawn.forEach((entry, band) => {
    const top = padT + band * (bandHeight + gap);
    const bottom = top + bandHeight;
    const points = entry.values.map((v, i) => ({ i, v })).filter(p => p.v !== null);
    if (points.length < 2) return;

    const values = points.map(p => p.v);
    let lo = Math.min(...values), hi = Math.max(...values);
    if (hi - lo < 1e-6) { hi = lo + 1; lo -= 1; }
    const pad = (hi - lo) * 0.18;
    lo -= pad; hi += pad;
    const y = (v) => bottom - (v - lo) / (hi - lo) * (bandHeight - 6) - 3;

    const colour = colourFor(entry.param, band);

    // Band background and border.
    add("rect", { x: padL, y: top, width: W - padL - padR, height: bandHeight, fill: lineColour, opacity: 0.35, rx: 4 });

    // Scale labels.
    const hiText = add("text", { x: padL - 8, y: top + 11, "text-anchor": "end", fill: mutedColour, "font-size": 11, "font-family": "inherit" });
    hiText.textContent = format(entry, hi + pad);
    const loText = add("text", { x: padL - 8, y: bottom - 1, "text-anchor": "end", fill: mutedColour, "font-size": 11, "font-family": "inherit" });
    loText.textContent = format(entry, lo + pad);

    const nameText = add("text", { x: 4, y: top + bandHeight / 2 + 4, fill: colour, "font-size": 12.5, "font-weight": "600", "font-family": "inherit" });
    nameText.textContent = entry.label;

    // The line.
    const path = points.map((p, k) => `${k ? "L" : "M"}${x(p.i).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ");
    add("path", { d: path, fill: "none", stroke: colour, "stroke-width": 2.2, "stroke-linecap": "round", "stroke-linejoin": "round" });
    points.forEach(p => {
      add("circle", { cx: x(p.i), cy: y(p.v), r: 2.6, fill: colour, stroke: "none" });
    });

  });

  // The marker for the selected step. It moves with the mouse while
  // hovering and stays where it was clicked.
  const marker = add("line", {
    x1: x(selected), x2: x(selected), y1: padT - 4, y2: H - padB + 4,
    stroke: (style.getPropertyValue("--accent") || "#1d6fb8").trim(),
    "stroke-width": 1.5, "stroke-dasharray": "3 3"
  });

  // Time labels. The day is shown whenever it changes, so the times are
  // never ambiguous.
  const every = Math.max(1, Math.ceil(n / 12));
  const shown = [];
  for (let i = 0; i < n; i += every) shown.push(i);
  if (shown[shown.length - 1] !== n - 1) {
    // The last column gets a label too, but not on top of the one before it.
    if (n - 1 - shown[shown.length - 1] < every) shown.pop();
    shown.push(n - 1);
  }
  let lastDay = "";
  shown.forEach((i) => {
    const parts = displayTimes(place)[i].split(" ");
    const day = parts[0];
    const hour = parts.slice(1).join(" ");
    const showDay = day !== lastDay;
    lastDay = day;
    const text = add("text", {
      x: x(i), y: H - 8, "text-anchor": "middle",
      fill: mutedColour, "font-size": 11.5, "font-family": "inherit",
    });
    text.textContent = showDay ? day + " " + hour : hour;
  });

  // Where the mouse is, so the tooltip can follow.
  const overlay = add("rect", { x: padL, y: 0, width: W - padL - padR, height: H, fill: "transparent", style: "cursor:crosshair" });
  let hovered = -1;

  const nearest = (clientX) => {
    const box = root.getBoundingClientRect();
    const px = ((clientX - box.left) / box.width) * W;
    let best = 0, bestDistance = Infinity;
    for (let i = 0; i < n; i++) {
      const distance = Math.abs(x(i) - px);
      if (distance < bestDistance) { bestDistance = distance; best = i; }
    }
    return best;
  };

  overlay.addEventListener("mousemove", (event) => {
    const best = nearest(event.clientX);
    hovered = best;
    // The marker follows the mouse, and the cards show that hour.
    marker.setAttribute("x1", x(best));
    marker.setAttribute("x2", x(best));
    updateSummary(place, series, best);
    showTip(place, series, keys, best, event);
  });
  overlay.addEventListener("mouseleave", () => {
    hovered = -1;
    marker.setAttribute("x1", x(selected));
    marker.setAttribute("x2", x(selected));
    updateSummary(place, series, selected);
    hideTip();
  });
  overlay.addEventListener("click", (event) => {
    const best = hovered >= 0 ? hovered : nearest(event.clientX);
    select(best);
  });

  return root;
}

const tip = document.getElementById("tip");

// How many parameters the tooltip lists before it says "and N more".
const TIP_LIMIT = 14;

function showTip(place, series, keys, index, event) {
  if (!state.tooltips || !event) { hideTip(); return; }
  tip.innerHTML = "";
  const head = el("div", "t", displayTimes(place)[index] || "");
  tip.appendChild(head);
  keys.slice(0, TIP_LIMIT).forEach((key, i) => {
    const entry = series[key];
    if (!entry) return;
    const value = entry.values[index];
    const row = el("div", "r");
    const swatch = el("i");
    swatch.style.background = colourFor(entry.param, i);
    row.appendChild(swatch);
    row.appendChild(el("span", null, entry.label));
    const strong = el("b", null, value === null || value === undefined ? "–" : format(entry, value));
    row.appendChild(strong);
    tip.appendChild(row);
  });
  if (keys.length > TIP_LIMIT) {
    tip.appendChild(el("div", "t", "and " + (keys.length - TIP_LIMIT) + " more"));
  }
  tip.classList.add("on");
  const pad = 14;
  let left = event.clientX + pad;
  let top = event.clientY + pad;
  if (left + tip.offsetWidth > window.innerWidth - 8) left = event.clientX - tip.offsetWidth - pad;
  if (top + tip.offsetHeight > window.innerHeight - 8) top = event.clientY - tip.offsetHeight - pad;
  tip.style.left = left + "px";
  tip.style.top = top + "px";
}
function hideTip() { tip.classList.remove("on"); }

// --------------------------------------------------------------------------- //
// Rendering
// --------------------------------------------------------------------------- //
const HIDDEN = new Set(["z", "model_elevation"]);

// The times that are shown, in the zone the reader picked.
function displayTimes(place) {
  return state.clock === "utc" && place.times_utc ? place.times_utc : place.times;
}

// The columns grouped into days.
function dayGroups(place, times) {
  const groups = [];
  let at = 0;
  while (at < times.length) {
    const day = times[at].split(" ")[0];
    let end = at;
    while (end + 1 < times.length && times[end + 1].split(" ")[0] === day) end++;
    groups.push({ day, from: at, to: end });
    at = end + 1;
  }
  return groups;
}

// The temperature range and the rain of one day.
function daySummary(series, from, to) {
  const range = (key) => {
    const entry = series[key];
    if (!entry) return null;
    const values = entry.values.slice(from, to + 1).filter((v) => v !== null && v !== undefined);
    return values.length ? values : null;
  };
  const temps = range("2t");
  const rain = series.precip_increment ? series.precip_increment.values.slice(from, to + 1) : null;
  const parts = [];
  if (temps) {
    parts.push(Math.round(Math.min(...temps)) + "–" + Math.round(Math.max(...temps)) + "°");
  }
  if (rain && rain.some(v => v === null || v === undefined)) {
    parts.push("Rain incomplete");
  } else if (rain) {
    const total = rain.reduce((sum, v) => sum + v, 0);
    if (total > 0.05) parts.push(total.toFixed(1) + " mm");
  }
  return parts.join("  ·  ");
}

function renderPlace(place, nowStep, order) {
  const card = el("section", "place");
  const series = place.series;
  const steps = place.steps;
  const index = steps.indexOf(nowStep);
  const nowIndex = index >= 0 ? index : 0;
  const current = state.selected !== null && state.selected < steps.length ? state.selected : nowIndex;

  const chosen = state.visible;
  // The catalogue gives the order things are shown in.
  const rank = (key) => {
    const index = order.findIndex((item) => item.key === key);
    return index === -1 ? 999 : (order[index].rank === undefined ? 999 : order[index].rank);
  };
  const visible = [...chosen].filter((key) => series[key]).sort((a, b) => rank(a) - rank(b));
  // The times that are shown, in the zone the reader picked.
  const times = displayTimes(place);

  // Head.
  const head = el("div", "place-head");
  const title = el("div");
  const h2 = el("h2");
  h2.appendChild(icon("pin", 22));
  h2.appendChild(document.createTextNode(place.name));
  if (place.flag) h2.appendChild(el("span", null, place.flag));
  title.appendChild(h2);
  const bits = [place.latitude.toFixed(4) + ", " + place.longitude.toFixed(4)];
  if (place.country) bits.push(place.country);
  if (place.elevation !== null && place.elevation !== undefined) bits.push(place.elevation + " m");
  if (place.model_height !== null && place.model_height !== undefined) {
    bits.push("model height " + Math.round(place.model_height) + " m");
  }
  if (place.note) bits.push(place.note);
  title.appendChild(el("div", "sub", bits.join("  ·  ")));
  head.appendChild(title);

  // The time the values below belong to, big and clear, on the right.
  const when = el("div", "when");
  const stamp = el("div", "stamp");
  stamp.appendChild(el("span", null, bigStamp(place, current)));
  when.appendChild(stamp);
  head.appendChild(when);

  const condition = conditionFor(series, current);
  const conditionBox = el("div", "condition");
  conditionBox.dataset.role = "condition";
  conditionBox.appendChild(icon(condition.key, 68));
  conditionBox.appendChild(el("div", "label", condition.label));
  head.appendChild(conditionBox);
  card.appendChild(head);

  // Nothing of the chosen parameters exists at this place.
  if (!visible.length) {
    const empty = el("div", "empty");
    empty.appendChild(el("p", null, "None of the chosen parameters are available for " + place.name + "."));
    const button = el("button", null, "Use the default set");
    button.addEventListener("click", () => {
      state.visible = defaultSelection(state.data);
      state.selectionLoaded = true;
      saveState();
      syncUrl();
      renderPanel(state.data.catalogue || state.data.params);
      render();
    });
    empty.appendChild(button);
    card.appendChild(empty);
    return { card, table: null, plots: [], place, series, current };
  }

  // A banner when the user has picked a step.
  if (state.selected !== null) {
    const banner = el("div", "banner");
    banner.appendChild(icon("clock", 16));
    banner.appendChild(el("span", null, "Showing " + times[state.selected]));
    const back = el("button", null, "Back to now");
    back.addEventListener("click", (event) => {
      event.stopPropagation();
      state.selected = null;
      render();
    });
    banner.appendChild(back);
    card.appendChild(banner);
  }

  // The cards show the parameters that are switched on, the same ones the
  // chart and the table show.
  const get = (key) => {
    const s = series[key];
    return s && s.values[current] !== null && s.values[current] !== undefined ? s.values[current] : null;
  };
  const now = el("div", "now");

  // The two wind components are one thing in the table, so they are one
  // card here as well.
  const cardKeys = visible.slice();
  let windVectorCard = false;
  if (cardKeys.includes("10u") && cardKeys.includes("10v")) {
    const at = cardKeys.indexOf("10u");
    cardKeys.splice(at, 2);
    windVectorCard = true;
  }

  const shown = cardKeys.slice(0, 12);
  shown.forEach((key) => {
    const entry = series[key];
    const value = get(key);
    if (!entry || value === null) return;
    const big = key === "2t" || key === "temperature_adjusted";
    const unit = key === "wind_dir" ? "" : displayUnit(entry.unit);
    const text = key === "wind_dir" ? Math.round(value) + "°" : formatValue(entry, value);
    now.appendChild(stat(entry.short || entry.label, text, unit, PARAM_ICON[key] || "cloud", big, key));
  });

  if (windVectorCard) {
    const speed = get("wind_speed");
    const u = get("10u");
    const v = get("10v");
    const magnitude = u !== null && v !== null ? Math.hypot(u, v) * 3.6 : null;
    const value = speed !== null ? speed : magnitude;
    if (value !== null) {
      now.appendChild(stat("Wind (u, v)", Math.round(value), "km/h", "wind", false, "wind_vector"));
    }
  }

  if (cardKeys.length > shown.length + (windVectorCard ? 1 : 0)) {
    const extra = cardKeys.length - shown.length - (windVectorCard ? 1 : 0);
    now.appendChild(el("div", "stat more", "and " + extra + " more"));
  }
  if (now.children.length) card.appendChild(now);

  // The table and its plots share one scroll container, so they always have
  // the same width and the columns line up.
  const wrap = el("div", "grid");
  const inner = el("div", "inner");
  wrap.appendChild(inner);

  // Table.
  const table = el("table");
  const thead = el("thead");
  // The days are one row, the times of the day below them, the way yr.no
  // and the Met Office lay it out.
  const dayStart = {};
  dayGroups(place, times).forEach((group) => { dayStart[group.from] = true; });
  const dayRow = el("tr", "days");
  const timeRow = el("tr", "times");
  const corner = el("th", null, "");
  corner.rowSpan = 2;
  dayRow.appendChild(corner);
  let at = 0;
  while (at < times.length) {
    const day = times[at].split(" ")[0];
    let end = at;
    while (end + 1 < times.length && times[end + 1].split(" ")[0] === day) end++;
    const spans = end - at + 1;
    const head = el("th", null, day);
    if (spans > 1) head.colSpan = spans;
    head.classList.add("clickable");
    head.title = "Click to show this day";
    head.addEventListener("click", () => {
      state.selected = state.selected === at ? null : at;
      render();
    });
    dayRow.appendChild(head);
    for (let i = at; i <= end; i++) {
      const cell = el("th", (i === current ? "now-col" : null) + (dayStart[i] ? " day-start" : ""),
                      times[i].split(" ")[1]);
      cell.dataset.col = i;
      cell.classList.add("clickable");
      cell.title = "Click to show this hour";
      cell.addEventListener("click", () => {
        state.selected = state.selected === i ? null : i;
        render();
      });
      timeRow.appendChild(cell);
    }
    at = end + 1;
  }
  thead.appendChild(dayRow);
  thead.appendChild(timeRow);
  table.appendChild(thead);

  const tbody = el("tbody");
  const plots = [];

  // One cell per day, with the range and the rain of that day.
  const summaryRow = el("tr", "summary");
  summaryRow.appendChild(el("th", null, "Day"));
  const groups = dayGroups(place, times);
  groups.forEach((group) => {
    const cell = el("td", group.from > 0 ? "day-start" : null,
                    daySummary(series, group.from, group.to));
    cell.colSpan = group.to - group.from + 1;
    summaryRow.appendChild(cell);
  });
  tbody.appendChild(summaryRow);

  const condRow = el("tr", "conds");
  const condHead = el("th");
  condHead.appendChild(icon("clock", 18));
  condHead.appendChild(document.createTextNode("Condition"));
  condRow.appendChild(condHead);
  steps.forEach((_, i) => {
    const cell = el("td", (i === current ? "now-col" : null) + (dayStart[i] ? " day-start" : ""), null);
    cell.dataset.col = i;
    cell.classList.add("clickable");
    cell.title = "Click to show this hour";
    cell.addEventListener("click", () => {
      state.selected = state.selected === i ? null : i;
      render();
    });
    cell.appendChild(icon(conditionFor(series, i).key, 34));
    condRow.appendChild(cell);
  });
  tbody.appendChild(condRow);

  const keys = visible;
  let windMax = 1;

  // The two wind components are shown as one row of arrows, which is what
  // they are for, rather than as two rows of numbers.
  if (keys.includes("10u") && keys.includes("10v")) {
    const at = keys.indexOf("10u");
    keys.splice(at, 2, "wind_vector");
    const u = series["10u"].values;
    const v = series["10v"].values;
    windMax = Math.max(0.1, ...u.map((value, i) => {
      if (value === null || value === undefined || v[i] === null || v[i] === undefined) return 0;
      return Math.hypot(value, v[i]);
    }));
    // A stand in for the row; the values come from the two components.
    series.wind_vector = {
      param: "wind_vector",
      label: "Wind (u, v)",
      short: "Wind (u, v)",
      unit: "m s-1",
      values: u.map((value) => (value === null || value === undefined ? null : 1)),
    };
  }

  // Each precipitation row is scaled to its own largest value, so the bars
  // show the shape of that row rather than being comparable across rows.
  const rainScale = {};
  for (const key of ["tp", "precip_increment"]) {
    const values = series[key] ? series[key].values.map(v => v || 0) : [];
    rainScale[key] = Math.max(0.001, ...values);
  }

  keys.forEach((key, index) => {
    const s = series[key];
    if (!s) return;
    const row = el("tr");
    const label = el("th");
    label.appendChild(icon(PARAM_ICON[key] || "cloud", 21));
    const text = el("span", "name", key === "wind_vector" ? "Wind (u, v)" : (s.short || s.label));
    text.title = key === "wind_vector"
      ? "The two wind components, as arrows. The arrow points the way the wind blows."
      : s.label;
    label.appendChild(text);
    row.appendChild(label);
    s.values.forEach((value, i) => {
      const cell = el("td", (i === current ? "now-col" : null) + (dayStart[i] ? " day-start" : ""), null);
      cell.dataset.col = i;
      cell.classList.add("clickable");
      cell.title = "Click to show this hour";
      cell.addEventListener("click", () => {
        state.selected = state.selected === i ? null : i;
        render();
      });
      if (key === "wind_vector") {
        const u = series["10u"].values[i];
        const v = series["10v"].values[i];
        if (u === null || u === undefined || v === null || v === undefined) {
          cell.textContent = "–";
        } else {
          const picture = windVector(u, v, windMax);
          picture.style.color = beaufortColour(Math.hypot(u, v) * 3.6);
          cell.appendChild(picture);
        }
      } else if (value === null || value === undefined) {
        cell.textContent = "–";
      } else if (["2t", "temperature_adjusted", "apparent_temperature"].includes(s.param)) {
        cell.textContent = value.toFixed(1) + "°";
      } else if (s.param === "wind_dir") {
        // The arrow carries the direction; the number under it is the
        // direction in degrees, and the colour follows this column's speed.
        const speed = series["wind_speed"] ? series["wind_speed"].values[i] : null;
        cell.appendChild(arrow(value, speed));
        const text = el("span", "wind");
        text.textContent = Math.round(value) + "°";
        cell.appendChild(text);
      } else if (s.param === "precip_increment" || s.param === "tp") {
        cell.classList.add("precip");
        const inner = el("span", "pp");
        inner.appendChild(el("span", "num", value.toFixed(1)));
        const gauge = el("span", "gauge");
        const fill = el("i");
        fill.style.height = (value > 0 ? Math.max(3, value / rainScale[s.param] * 20) : 0) + "px";
        gauge.appendChild(fill);
        inner.appendChild(gauge);
        cell.appendChild(inner);
      } else {
        cell.textContent = format(s, value);
      }
      row.appendChild(cell);
    });
    tbody.appendChild(row);

    // And a plot of the same parameter, right under the numbers. It needs
    // a cell of its own for the label column, or it would be one column
    // short and the plot would not reach the end.
    if (key === "wind_vector") {
      tbody.appendChild(row);
      return;
    }
    const plotRow = el("tr", "plot");
    plotRow.appendChild(el("th"));
    const plotCell = el("td");
    plotCell.colSpan = steps.length;
    plotRow.appendChild(plotCell);
    tbody.appendChild(plotRow);
    plots.push({ cell: plotCell, entry: s });
  });
  table.appendChild(tbody);
  inner.appendChild(table);
  card.appendChild(wrap);
  return { card, table, wrap, inner, place, series, plots, current, keys: visible };
}

function stat(label, value, unit, iconName, big, paramKey) {
  const box = el("div", "stat" + (big ? " big" : ""));
  if (paramKey) box.dataset.param = paramKey;
  const key = el("div", "k");
  if (iconName) key.appendChild(icon(iconName, 17));
  key.appendChild(document.createTextNode(label));
  box.appendChild(key);
  const v = el("div", "v");
  const num = el("span", "num", value);
  v.appendChild(num);
  if (unit) v.appendChild(el("small", null, unit));
  box.appendChild(v);
  return box;
}

// A small plot of one parameter, sitting under its row of numbers.
function sparkline(entry, column, n) {
  const W = column * n, H = 32;
  const values = entry.values;
  const valid = values.filter((v) => v !== null && v !== undefined);
  const root = svg("", 1);
  root.setAttribute("viewBox", `0 0 ${W} ${H}`);
  root.setAttribute("width", "100%");
  root.setAttribute("height", H);
  root.setAttribute("preserveAspectRatio", "none");
  root.removeAttribute("stroke-width");
  root.setAttribute("stroke", "none");
  if (valid.length < 2) return root;

  let lo = Math.min(...valid), hi = Math.max(...valid);
  if (hi - lo < 1e-9) { hi = lo + 1; lo -= 1; }
  const pad = (hi - lo) * 0.12;
  lo -= pad; hi += pad;

  const x = (i) => (i + 0.5) * column;
  const y = (v) => H - 4 - ((v - lo) / (hi - lo)) * (H - 9);
  const colour = colourFor(entry.param, 0);

  const points = values
    .map((v, i) => ({ i, v }))
    .filter((p) => p.v !== null && p.v !== undefined);
  const line = points
    .map((p, k) => `${k ? "L" : "M"}${x(p.i).toFixed(1)},${y(p.v).toFixed(1)}`)
    .join(" ");

  const area = `${line} L${x(points[points.length - 1].i).toFixed(1)},${H - 1} L${x(points[0].i).toFixed(1)},${H - 1} Z`;

  const base = document.createElementNS(SVG_NS, "path");
  base.setAttribute("d", area);
  base.setAttribute("fill", colour);
  base.setAttribute("opacity", "0.13");
  root.appendChild(base);

  const stroke = document.createElementNS(SVG_NS, "path");
  stroke.setAttribute("d", line);
  stroke.setAttribute("fill", "none");
  stroke.setAttribute("stroke", colour);
  stroke.setAttribute("stroke-width", "1.6");
  stroke.setAttribute("vector-effect", "non-scaling-stroke");
  root.appendChild(stroke);

  // The marker that follows the mouse.
  const marker = document.createElementNS(SVG_NS, "line");
  marker.setAttribute("x1", 0);
  marker.setAttribute("x2", 0);
  marker.setAttribute("y1", 0);
  marker.setAttribute("y2", H);
  marker.setAttribute("stroke", "currentColor");
  marker.setAttribute("stroke-width", "1");
  marker.setAttribute("stroke-dasharray", "2 2");
  marker.setAttribute("opacity", "0.5");
  root.appendChild(marker);
  marker.dataset.width = String(column);

  return root;
}

// The markers in the plots, which follow the mouse.
let sparkMarkers = [];

// What the table is showing at the moment: the selected step, or the one
// under the mouse.
let hoverState = { index: -1 };

function moveSparkMarkers(index) {
  sparkMarkers.forEach((marker) => {
    const column = Number(marker.dataset.width || 0);
    const x = (index + 0.5) * column;
    marker.setAttribute("x1", x);
    marker.setAttribute("x2", x);
  });
}

// The title of the card: the time in the chosen zone, with the other one
// in brackets.
function bigStamp(place, index) {
  const local = localStamp(place.run, place.steps[index], place.timezone);
  const utc = localStamp(place.run, place.steps[index], "UTC");
  const shortUtc = utc.split(" at ")[1] || utc;
  const shortLocal = local.split(" at ")[1] || local;
  if (state.clock === "utc") {
    return utc + " UTC (" + shortLocal + " local)";
  }
  return local + " (" + shortUtc + " UTC)";
}

// The local date and time of a forecast step.
function localStamp(run, step, timezone) {
  if (!run) return "";
  const base = new Date(Date.UTC(
    Number(run.slice(0, 4)), Number(run.slice(4, 6)) - 1,
    Number(run.slice(6, 8)), Number(run.slice(8, 10))
  ));
  base.setUTCHours(base.getUTCHours() + step);
  try {
    return new Intl.DateTimeFormat("en-GB", {
      timeZone: timezone || "UTC",
      weekday: "long", day: "numeric", month: "long", year: "numeric",
      hour: "2-digit", minute: "2-digit",
    }).format(base);
  } catch (e) {
    return base.toISOString().slice(0, 16).replace("T", " ");
  }
}

// The unit shown in the cards. The data uses the GRIB spelling for degrees
// Celsius, which is not what a person expects to read next to a number.
function displayUnit(unit) {
  return unit === "degC" ? "°C" : unit;
}

// The value of a parameter without its unit, the way the cards show it.
function formatValue(entry, value) {
  if (value === null || value === undefined) return "\u2013";
  if (["2t", "temperature_adjusted", "apparent_temperature", "2d", "tp", "precip_increment"].includes(entry.param)) {
    return value.toFixed(1);
  }
  return String(Math.round(value));
}

// Update everything that shows a single hour: the cards, the time, the
// weather icon and the highlighted column.
function updateSummary(place, series, index) {
  document.querySelectorAll(".stat[data-param]").forEach((card) => {
    const entry = series[card.dataset.param];
    if (!entry) return;
    const target = card.querySelector(".v .num");
    if (target) target.textContent = formatValue(entry, entry.values[index]);
  });
  const stamp = document.querySelector(".stamp span");
  if (stamp) stamp.textContent = bigStamp(place, index);

  // The big icon shows the weather of that hour.
  const box = document.querySelector('[data-role="condition"]');
  if (box) {
    const state = conditionFor(series, index);
    box.innerHTML = "";
    box.appendChild(icon(state.key, 68));
    box.appendChild(el("div", "label", state.label));
  }

  // And the column of that hour is the highlighted one.
  document.querySelectorAll("[data-col]").forEach((cell) => {
    cell.classList.toggle("now-col", Number(cell.dataset.col) === index);
  });
  moveSparkMarkers(index);
}

// --------------------------------------------------------------------------- //
// The parameter panel
// --------------------------------------------------------------------------- //
function renderPanel(catalogue) {
  const body = document.getElementById("panelBody");
  body.innerHTML = "";
  if (!catalogue.length) {
    body.appendChild(el("p", null, "No parameters yet."));
    return;
  }

  const search = el("input", "search");
  search.placeholder = "Search the parameters";
  body.appendChild(search);

  const list = el("div", "items");
  body.appendChild(list);

  const draw = (needle) => {
    list.innerHTML = "";
    const groups = {};
    catalogue
      .filter((item) => !needle || (item.label + " " + item.key).toLowerCase().includes(needle))
      .forEach((item) => {
        const group = item.group || "other";
        (groups[group] = groups[group] || []).push(item);
      });

    Object.keys(groups).sort().forEach((group) => {
    const box = el("div", "group");
    box.appendChild(el("h4", null, group));
    const items = el("div", "group-items");
    groups[group].forEach((item) => {
      const label = el("label", item.downloaded ? "" : "off");
      if (!item.downloaded) label.title = "Not downloaded. Add it to the parameters list in places.yml.";
      const check = document.createElement("input");
      check.type = "checkbox";
      check.disabled = !item.downloaded;
      const keys = item.series.length ? item.series : [item.key];
      check.checked = keys.some((key) => state.visible.has(key));
      check.addEventListener("change", () => {
        keys.forEach((key) => {
          if (check.checked) state.visible.add(key);
          else state.visible.delete(key);
        });
        saveState();
        syncUrl();
        render();
      });
      label.appendChild(check);
      const swatch = el("span", "swatch");
      swatch.style.background = colourFor(item.key, 0);
      label.appendChild(swatch);
      label.appendChild(document.createTextNode(item.label));
      if (item.levtype === "pl") {
        const levels = item.levels || [];
        label.appendChild(el("span", "unit", levels.length + " levels"));
        label.title = "On " + levels.join(", ") + " hPa";
      } else {
        label.appendChild(el("span", "unit", item.unit));
      }
      items.appendChild(label);
    });
    box.appendChild(items);
    list.appendChild(box);
    });
  };

  draw("");
  search.addEventListener("input", () => draw(search.value.trim().toLowerCase()));

  const missing = catalogue.filter((item) => !item.downloaded).length;
  if (missing) {
    body.appendChild(el("p", "note",
      missing + " of these are not downloaded. Add them to the parameters "
      + "list in places.yml and the service will fetch them."));
  }
}

// --------------------------------------------------------------------------- //
// The place picker
// --------------------------------------------------------------------------- //
const picker = document.getElementById("picker");
const placeInput = document.getElementById("placeInput");
const placeList = document.getElementById("placeList");
const pickerFlag = document.getElementById("pickerFlag");
let highlighted = -1;

function fillPlaceList(filter) {
  placeList.innerHTML = "";
  const needle = (filter || "").toLowerCase();
  let shown = 0;
  state.catalogue.forEach((item, index) => {
    if (shown >= 60) return;
    const hay = (item.name + " " + item.country + " " + item.id).toLowerCase();
    if (needle && !hay.includes(needle)) return;
    const entry = el("li");
    entry.dataset.place = item.id;
    entry.appendChild(document.createTextNode((item.flag || "") + " " + item.name));
    if (item.country) entry.appendChild(el("span", "c", item.country));
    if (item.kind) entry.appendChild(el("span", "k", item.kind));
    entry.addEventListener("mousedown", (event) => {
      event.preventDefault();
      choosePlace(item.id);
    });
    placeList.appendChild(entry);
    shown += 1;
  });
  if (!shown) placeList.appendChild(el("li", null, "Nothing found"));
  highlighted = -1;
}

function choosePlace(id) {
  state.place = id;
  state.selected = null;
  picker.classList.remove("open");
  const item = state.catalogue.find(p => p.id === id);
  if (item) {
    placeInput.value = item.name;
    pickerFlag.textContent = item.flag || "";
  }
  syncUrl();
  load(state.run, id).catch(showError);
}

placeInput.addEventListener("focus", () => {
  // Select the current name, so the first keystroke replaces it.
  placeInput.select();
  picker.classList.add("open");
  fillPlaceList("");
});
placeInput.addEventListener("input", () => {
  picker.classList.add("open");
  fillPlaceList(placeInput.value);
});
placeInput.addEventListener("blur", () => {
  const item = state.catalogue.find((place) => place.id === state.place);
  if (item) placeInput.value = item.name;
});
placeInput.addEventListener("keydown", (event) => {
  const items = [...placeList.querySelectorAll("li")];
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    highlighted += event.key === "ArrowDown" ? 1 : -1;
    highlighted = Math.max(0, Math.min(items.length - 1, highlighted));
    items.forEach((node, i) => node.classList.toggle("active", i === highlighted));
    if (items[highlighted]) items[highlighted].scrollIntoView({ block: "nearest" });
  } else if (event.key === "Enter") {
    event.preventDefault();
    if (items[highlighted]) items[highlighted].dispatchEvent(new MouseEvent("mousedown"));
    else if (items.length && items[0].dataset.place) choosePlace(items[0].dataset.place);
  } else if (event.key === "Escape") {
    picker.classList.remove("open");
  }
});
document.addEventListener("click", (event) => {
  if (!picker.contains(event.target)) picker.classList.remove("open");
});

// --------------------------------------------------------------------------- //
// Loading
// --------------------------------------------------------------------------- //
function render() {
  const data = state.data;
  if (!data) return;
  hideTip();
  hoverState.index = -1;
  const content = document.getElementById("content");
  content.innerHTML = "";
  if (!data.places.length) {
    content.appendChild(el("div", "empty", "Nothing to show for this place yet."));
    return;
  }
  const order = data.catalogue || data.params;
  data.places.forEach((item) => {
    const built = renderPlace(item, data.now_step, order);
    content.appendChild(built.card);
    if (!built.table) return;
    // Now that the card has a width, the plots can be drawn on exactly the
    // same columns as the table.
    const labelWidth = built.table.querySelector("tbody th")
      ? built.table.querySelector("tbody th").getBoundingClientRect().width
      : 190;
    // Every column needs room for a value like "1024 hPa".
    const column = Math.max(70, (built.inner.clientWidth - labelWidth) / built.place.steps.length);
    built.inner.style.minWidth = Math.ceil(labelWidth + column * built.place.steps.length) + "px";

    sparkMarkers = [];
    built.plots.forEach((plot) => {
      const picture = sparkline(plot.entry, column, built.place.steps.length);
      const marker = picture.querySelector("line");
      if (marker) sparkMarkers.push(marker);
      plot.cell.appendChild(picture);
    });
    moveSparkMarkers(built.current);

    // Moving the mouse over the table shows that hour: the numbers are
    // highlighted, the marker moves and a box with the values appears.
    const n = built.place.steps.length;
    const visible = built.series;
    const keys = built.keys;
    const cellWidth = column;

    built.table.addEventListener("mousemove", (event) => {
      const left = built.table.getBoundingClientRect().left + labelWidth;
      let index = Math.floor((event.clientX - left) / cellWidth);
      index = Math.max(0, Math.min(n - 1, index));

      hoverState.index = index;
      updateSummary(built.place, visible, index);
      showTip(built.place, visible, keys, index, event);
    });
    built.table.addEventListener("mouseleave", () => {
      hoverState.index = -1;
      updateSummary(built.place, visible, built.current);
      hideTip();
    });
  });
}

// The static build embeds the forecast instead of fetching it.
const EMBEDDED = window.FORECAST_DATA || null;
if (EMBEDDED) {
  // A static page has no endpoint to refresh from, so it is a snapshot.
  const refresh = document.getElementById("refresh");
  if (refresh) refresh.textContent = " \u00b7 static snapshot";
}

// What is shown when nothing has been picked.
const DEFAULT_PARAMS = ["2t", "wind_speed", "msl", "tp"];

function defaultSelection(data) {
  const set = new Set();
  DEFAULT_PARAMS.forEach((key) => {
    if (data && data.params.some(p => p.key === key)) set.add(key);
  });
  return set;
}

let loadSequence = 0;
async function load(run, place) {
  const sequence = ++loadSequence;
  let data;
  if (EMBEDDED) {
    const keys = Object.keys(EMBEDDED);
    if (!state.model && keys.length) state.model = keys[0];
    const key = state.model && EMBEDDED[state.model] ? state.model : keys[0];
    const runs = (window.FORECAST_RUNS || {})[key] || {};
    const payload = run && runs[run] ? runs[run] : EMBEDDED[key];
    data = JSON.parse(JSON.stringify(payload));
    if (place) data.places = data.places.filter(p => p.id === place);
  } else {
    const params = new URLSearchParams();
    if (run) params.set("run", run);
    if (place) params.set("place", place);
    if (state.model) params.set("model", state.model);
    const query = params.toString();
    const response = await fetch("/api/forecast" + (query ? "?" + query : ""), { cache: "no-store" });
    if (!response.ok) throw new Error("HTTP " + response.status);
    data = await response.json();
  }
  if (sequence !== loadSequence) return;
  state.model = data.model;
  state.run = data.run;
  state.data = data;
  syncUrl();

  const meta = document.getElementById("meta");
  meta.innerHTML = "";
  if (!data.run) {
    document.getElementById("content").innerHTML =
      '<div class="empty">No forecast yet.<br>Run <code>ecmwf-service once</code> to fetch the latest run.</div>';
    return;
  }
  meta.appendChild(el("span", null, "Run "));
  meta.appendChild(el("b", null, data.cycle_utc));
  if (data.places.length && (data.places[0].until_utc || data.places[0].until)) {
    const until = data.places[0].until_utc || data.places[0].until;
    meta.appendChild(el("span", null, "· until " + until + (data.places[0].until_utc ? " UTC" : "")));
  }

  if (data.models.length) {
    modelSelect.innerHTML = "";
    data.models.forEach(info => {
      const option = el("option", null, info.label);
      option.value = info.key;
      modelSelect.appendChild(option);
    });
    modelSelect.dataset.filled = "yes";
  }
  if (state.model) modelSelect.value = state.model;

  // The runs of the chosen model, with how far each one reaches.
  const wanted = state.model || (data.models[0] && data.models[0].key);
  runSelect.innerHTML = "";
  data.runs.filter(item => item.model === wanted).forEach((item) => {
    const option = el("option", null, item.cycle + (item.until ? "  →  " + item.until : ""));
    option.value = item.run;
    runSelect.appendChild(option);
  });
  runSelect.value = data.run;

  if (JSON.stringify(state.catalogue) !== JSON.stringify(data.place_list)) {
    state.catalogue = data.place_list;
    fillPlaceList("");
  }
  const current = state.catalogue.find(item => item.id === state.place);
  if (current) {
    placeInput.value = current.name;
    pickerFlag.textContent = current.flag || "";
  }
  if (!state.place && data.place_list.length) {
    choosePlace(data.place_list[0].id);
    return;
  }
  if (!state.place && data.places.length) {
    state.place = data.places[0].id;
    syncUrl();
  }

  // Default to the first few parameters of the display order that are there.
  if (!state.selectionLoaded) {
    // The accumulation of the rain since the run is left out: the per step
    // amount and the total for the day in the summary row say more.
    const order = ["2t", "temperature_adjusted", "apparent_temperature",
                   "precip_increment", "wind_speed", "wind_dir", "gust",
                   "tcc", "2d", "msl", "tp"];
    const available = new Set();
    data.places.forEach((place) => {
      Object.keys(place.series).forEach((key) => available.add(key));
    });
    order.filter((key) => available.has(key)).slice(0, 6).forEach((key) => state.visible.add(key));
    state.selectionLoaded = true;
    saveState();
  }
  renderPanel(data.catalogue || data.params);
  render();
}

function showError(error) {
  const content = document.getElementById("content");
  content.replaceChildren(el("div", "empty", "Could not load the forecast: " + error.message));
}

modelSelect.addEventListener("change", (event) => {
  state.model = event.target.value;
  state.selected = null;
  // Each model has a run that reaches furthest, use that one.
  const model = state.data.models.find(item => item.key === state.model);
  state.run = model ? model.run : null;
  syncUrl();
  load(state.run, state.place).catch(showError);
});
document.getElementById("run").addEventListener("change", (event) => {
  state.run = event.target.value || null;
  state.selected = null;
  syncUrl();
  load(state.run, state.place).catch(showError);
});
document.getElementById("params").addEventListener("click", () => {
  document.getElementById("panel").classList.toggle("open");
});
document.addEventListener("click", (event) => {
  const panel = document.getElementById("panel");
  if (!panel.contains(event.target) && !event.target.closest("#params")) panel.classList.remove("open");
});

// The times: the local time of the place, or UTC.
const clockButton = document.getElementById("clock");
function applyClock(mode) {
  state.clock = mode === "utc" ? "utc" : "local";
  clockButton.textContent = state.clock === "utc" ? "UTC" : "Local";
  clockButton.classList.toggle("on", state.clock === "utc");
  try { localStorage.setItem("ecmwf-clock", state.clock); } catch (e) { /* private mode */ }
}
applyClock((() => {
  try { return localStorage.getItem("ecmwf-clock") || "local"; } catch (e) { return "local"; }
})());
clockButton.addEventListener("click", () => {
  applyClock(state.clock === "utc" ? "local" : "utc");
  syncUrl();
  render();
});

// Forecast tooltips are opt-in; hovering still updates the hour and summary.
const tooltipButton = document.getElementById("tooltips");
function applyTooltips(enabled) {
  state.tooltips = enabled;
  tooltipButton.textContent = "Tooltips: " + (enabled ? "on" : "off");
  tooltipButton.setAttribute("aria-pressed", String(enabled));
  tooltipButton.classList.toggle("on", enabled);
  if (!enabled) hideTip();
  try { localStorage.setItem("ecmwf-tooltips", String(enabled)); } catch (e) { /* private mode */ }
}
let tooltipsEnabled = false;
try { tooltipsEnabled = localStorage.getItem("ecmwf-tooltips") === "true"; } catch (e) { /* private mode */ }
applyTooltips(tooltipsEnabled);
tooltipButton.addEventListener("click", () => applyTooltips(!state.tooltips));

// Theme: auto, light or dark, remembered between visits.
const THEMES = ["auto", "light", "dark"];
const themeButton = document.getElementById("theme");
function applyTheme(theme) {
  if (theme === "auto") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", theme);
  themeButton.textContent = theme.charAt(0).toUpperCase() + theme.slice(1);
  try { localStorage.setItem("ecmwf-theme", theme); } catch (e) { /* private mode */ }
}
let theme = "auto";
try { theme = localStorage.getItem("ecmwf-theme") || "auto"; } catch (e) { /* private mode */ }
const query = new URLSearchParams(location.search);
if (query.get("theme") && THEMES.includes(query.get("theme"))) theme = query.get("theme");
applyTheme(theme);
themeButton.addEventListener("click", () => {
  theme = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
  applyTheme(theme);
  syncUrl();
});

state.model = query.get("model");
state.run = query.get("run");
state.place = query.get("place");
if (query.get("params")) {
  state.visible = new Set(query.get("params").split(",").filter(Boolean));
  state.selectionLoaded = true;
}
load(state.run, state.place).catch(showError);
if (!EMBEDDED) {
  setInterval(() => load(state.run, state.place).catch(() => {}), REFRESH_MS);
}
</script>
</body>
</html>
"""




class WidgetServer(ThreadingHTTPServer):
    """HTTP server that knows how to build the forecast payload."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, reader: ForecastReader):
        super().__init__(address, handler)
        self.reader = reader


class Handler(BaseHTTPRequestHandler):
    """Serves the page and the forecast API."""

    server_version = "EcmwfWidget/1.0"

    def log_message(self, format: str, *args) -> None:
        if os.environ.get("WIDGET_VERBOSE"):
            super().log_message(format, *args)

    def _send(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        query = self.path.split("?")[1] if "?" in self.path else ""
        from urllib.parse import parse_qsl

        params = dict(parse_qsl(query))

        if path in ("/", "/index.html"):
            self._send(PAGE.encode("utf-8"), "text/html; charset=utf-8")
            return

        if path.startswith("/icons/"):
            self._send_icon(path[len("/icons/") :])
            return

        if path == "/manifest.webmanifest":
            body = json.dumps(manifest(), indent=2, sort_keys=True).encode("utf-8")
            self._send(body, "application/manifest+json")
            return

        if path.startswith("/app-icon-"):
            self._send_asset(path)
            return

        try:
            self._send_json(self._payload(path, params))
        except KeyError as exc:
            self._send_json({"error": str(exc)}, status=404)
        except Exception as exc:  # noqa: BLE001 - never drop the connection
            self._send_json({"error": f"{type(exc).__name__}: {exc}"}, status=500)

    def _payload(self, path: str, params: dict) -> object:
        """Build the response body for an API route."""
        if path == "/api/forecast":
            run = params.get("run") or None
            place = params.get("place") or None
            model = params.get("model") or None
            if model is not None and model not in models.MODELS:
                raise KeyError(f"unknown model {model!r}")
            if run is not None and run not in self.server.reader.store.known_runs(model):
                raise KeyError(f"unknown run {run!r}")
            if place is not None and not self.server.reader.known_place(place):
                raise KeyError(f"unknown place {place!r}")
            return self.server.reader.widget_payload(run, place, model)

        if path == "/api/places":
            return [
                {
                    "id": place.id,
                    "name": place.name,
                    "latitude": place.latitude,
                    "longitude": place.longitude,
                    "elevation": place.elevation,
                    "timezone": place.timezone,
                }
                for place in self.server.reader.places()
            ]

        raise KeyError("not found")

    def _send_asset(self, name: str) -> None:
        """Serve an app icon from the assets of the package."""
        name = name.lstrip("/")
        if not re.fullmatch(r"[a-zA-Z0-9_.-]+", name):
            self._send(b"not found", "text/plain; charset=utf-8", status=404)
            return
        path = paths.ASSETS_DIR / name
        if not path.is_file():
            self._send(b"not found", "text/plain; charset=utf-8", status=404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        self.wfile.write(body)

    def _send_icon(self, name: str) -> None:
        """Serve a generated icon."""
        if not re.fullmatch(r"[a-z0-9_-]+\.png", name):
            self._send(b"not found", "text/plain; charset=utf-8", status=404)
            return
        path = os.path.join(icon_dir(), name)
        if not os.path.isfile(path):
            self._send(b"not found", "text/plain; charset=utf-8", status=404)
            return
        with open(path, "rb") as handle:
            body = handle.read()
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload, allow_nan=False).encode("utf-8")
        self._send(body, "application/json", status=status)


def _free_port(preferred: int, attempts: int = 12) -> int:
    """Find a free port, preferring the one asked for.

    A previous instance may still be releasing the port when the widget is
    restarted, so give it a moment before falling back to a random one.
    """
    for _attempt in range(attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("127.0.0.1", preferred))
                return preferred
            except OSError:
                pass
        time.sleep(0.5)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ecmwf-widget", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=None, help="configuration file")
    parser.add_argument("--database", help="override the database path")
    parser.add_argument("--host", default="127.0.0.1", help="address to bind")
    parser.add_argument("--port", type=int, default=8765, help="port to listen on")
    parser.add_argument("--open", action="store_true", help="open a browser")
    parser.add_argument("--text", action="store_true", help="print the text version and exit")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    if args.database:
        config.database = args.database

    store = ForecastStore(config.database)
    reader = ForecastReader(
        store,
        lapse_rate=config.lapse_rate,
        catalogue=config.all_places,
    )

    if args.text:
        for place in reader.places():
            print(render_text(reader.place_forecast(place.id)))
            print()
        return 0

    port = _free_port(args.port) if args.host in ("127.0.0.1", "localhost") else args.port
    server = WidgetServer((args.host, port), Handler, reader)
    url = f"http://{args.host}:{port}/"

    print(f"Serving the forecast widget on {url}")
    print("Press Ctrl+C to stop.")

    if args.open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
