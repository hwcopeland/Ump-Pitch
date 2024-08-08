import statsapi
from datetime import datetime, timedelta
import plotly.graph_objs as go
import plotly.io as pio
from plotly.subplots import make_subplots
import numpy as np
from scipy.spatial import ConvexHull
from shapely.geometry import Polygon, Point
import argparse
import json
import os
import dash
from dash import dcc, html
from dash.dependencies import Input, Output
import threading
import time
import logging
from flask import Flask, jsonify
from flask_cors import CORS
import pytz

# Define local timezone, replace with your desired timezone
local_tz = pytz.timezone('America/Chicago')

# Set up logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# Load configuration
def load_config():
    config_path = os.path.join(os.path.dirname(__file__), 'config.json')
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            return json.load(f)
    return {}

config = load_config()

# Global variables
baseball_diameter = 0.075  # Approximate diameter of a baseball in meters

# Function to check the game schedule for a specific date
def check_schedule(date=None):
    if date is None:
        now_local = datetime.now(local_tz)
        date = now_local.strftime("%m/%d/%Y")
    logging.info(f"Fetching schedule for: {date}")
    games = statsapi.schedule(date=date)
    return games

# Function to fetch play-by-play data for a specific game
def get_play_data(game_id):
    logging.info(f"Fetching play-by-play data for game ID: {game_id}")
    try:
        plays = statsapi.get('game_playByPlay', {'gamePk': game_id})
        game_data = statsapi.get('game', {'gamePk': game_id})
    except Exception as e:
        logging.error(f"Error retrieving game data: {e}")
        return None

    # Convert game time to local timezone
    try:
        game_datetime_utc = datetime.strptime(game_data['gameData']['datetime']['dateTime'], '%Y-%m-%dT%H:%M:%SZ')
        game_datetime_local = game_datetime_utc.replace(tzinfo=pytz.utc).astimezone(local_tz)
        game_data['gameData']['datetime']['dateTime'] = game_datetime_local.strftime('%Y-%m-%d %H:%M:%S %Z')
    except KeyError as e:
        logging.error(f"Error converting game time: {e}")
        return None

    # Extract game details
    try:
        home_team = game_data['gameData']['teams']['home']['teamName']
        away_team = game_data['gameData']['teams']['away']['teamName']

        home_pitcher = "TBD"
        away_pitcher = "TBD"
        if game_data['liveData']['boxscore']['teams']['home'].get('pitchers'):
            home_pitcher_id = game_data['liveData']['boxscore']['teams']['home']['pitchers'][0]
            home_pitcher = game_data['liveData']['boxscore']['teams']['home']['players'][f'ID{home_pitcher_id}']['person']['fullName']
        if game_data['liveData']['boxscore']['teams']['away'].get('pitchers'):
            away_pitcher_id = game_data['liveData']['boxscore']['teams']['away']['pitchers'][0]
            away_pitcher = game_data['liveData']['boxscore']['teams']['away']['players'][f'ID{away_pitcher_id}']['person']['fullName']

        umpire = next((official['official']['fullName'] for official in game_data['liveData']['boxscore']['officials'] if official['officialType'] == 'Home Plate'), 'Unknown')
    except KeyError as e:
        logging.error(f"Error retrieving game details: {e}")
        return None

    # List to store pitch data
    home_pitches = []
    away_pitches = []
    for play in plays['allPlays']:
        for event in play['playEvents']:
            if event['isPitch']:
                if 'pitchData' in event and 'coordinates' in event['pitchData']:
                    coords = event['pitchData']['coordinates']
                    if 'pX' in coords and 'pZ' in coords:
                        pitch_type = event['details']['type']['description'] if 'type' in event['details'] and 'description' in event['details']['type'] else 'Unknown'
                        umpire_call = event['details']['call']['description'] if 'call' in event['details'] and 'description' in event['details']['call'] else 'Unknown'
                        sz_top = event['pitchData'].get('strikeZoneTop', None)
                        sz_bottom = event['pitchData'].get('strikeZoneBottom', None)
                        pitcher_team = play['about']['halfInning']
                        pitch_data = (coords['pX'], coords['pZ'], pitch_type, umpire_call, sz_top, sz_bottom)
                        if pitcher_team == 'top':
                            home_pitches.append(pitch_data)
                        else:
                            away_pitches.append(pitch_data)

    if not home_pitches and not away_pitches:
        logging.warning("No pitch data available.")
        return None

    logging.info(f"Retrieved {len(home_pitches)} home pitches and {len(away_pitches)} away pitches.")
    return home_pitches, away_pitches, home_team, away_team, home_pitcher, away_pitcher, umpire

def add_pitch_trace(fig, pitches, name, color, visible=True):
    if pitches:
        x, y, text = zip(*[(p[0], p[1], f"{p[2]}") for p in pitches])
        fig.add_trace(go.Scatter(
            x=x, y=y,
            mode='markers',
            name=name,
            text=text,
            marker=dict(size=baseball_diameter * 100, color=color, opacity=0.7),
            visible=visible
        ))

def add_strike_zone(fig, pitch_data):
    valid_sz = [(p[4], p[5]) for p in pitch_data if p[4] and p[5]]
    if valid_sz:
        sz_top = np.mean([sz[0] for sz in valid_sz])
        sz_bottom = np.mean([sz[1] for sz in valid_sz])
        sz_left = -0.708333
        sz_right = 0.708333

        fig.add_trace(go.Scatter(
            x=[sz_left, sz_right, sz_right, sz_left, sz_left],
            y=[sz_bottom, sz_bottom, sz_top, sz_top, sz_bottom],
            mode='lines',
            name='Strike Zone',
            line=dict(color='#e0e0e0', width=2)
        ))

def add_umpire_strike_zone(fig, called_strikes, balls):
    if called_strikes:
        strike_coords = np.array([(p[0], p[1]) for p in called_strikes])
        if len(strike_coords) >= 3:
            hull = ConvexHull(strike_coords)
            hull_points = strike_coords[hull.vertices]
            # Smooth the edges by adding more points
            smooth_points = []
            for i in range(len(hull_points)):
                p1 = hull_points[i]
                p2 = hull_points[(i + 1) % len(hull_points)]
                smooth_points.extend(np.linspace(p1, p2, num=10))
            smooth_points = np.array(smooth_points)

            fig.add_trace(go.Scatter(
                x=smooth_points[:, 0],
                y=smooth_points[:, 1],
                fill='toself',
                fillcolor='rgba(255, 0, 0, 0.2)',
                mode='lines',
                name='Umpire Strike Zone',
                line=dict(color='red', width=2, shape='spline')
            ))

            hull_polygon = Polygon(hull_points)
            add_inconsistent_calls(fig, balls, hull_polygon)

def add_inconsistent_calls(fig, balls, hull_polygon):
    inconsistent_x = []
    inconsistent_y = []
    inconsistent_text = []
    for ball in balls:
        point = Point(ball[0], ball[1])
        if hull_polygon.contains(point):
            inconsistent_x.append(ball[0])
            inconsistent_y.append(ball[1])
            inconsistent_text.append(f"{ball[2]}")
    fig.add_trace(go.Scatter(
        x=inconsistent_x, y=inconsistent_y,
        mode='markers',
        marker=dict(size=baseball_diameter * 100, color='rgba(0, 0, 255, 0.7)'),
        name='Inconsistent',
        text=inconsistent_text
    ))

def add_last_pitch(fig, pitch_data):
    last_pitch = pitch_data[-1]
    fig.add_trace(go.Scatter(
        x=[last_pitch[0]], y=[last_pitch[1]],
        mode='markers',
        marker=dict(size=baseball_diameter * 100, color='white'),
        name='Last Pitch',
        text=[f"{last_pitch[2]}"]
    ))

def generate_plot_for_game(home_pitches, away_pitches, game_title, subtitle):
    logging.debug(f"Generating plot with {len(home_pitches)} home pitches and {len(away_pitches)} away pitches")
    if not home_pitches and not away_pitches:
        logging.warning("No pitch data to display.")
        return go.Figure()

    fig = go.Figure()

    # Add home pitches
    pitch_data_home = [(float(p[0]), float(p[1]), p[2], p[3], p[4], p[5]) for p in home_pitches]
    balls_home = [p for p in pitch_data_home if p[3] == 'Ball']
    called_strikes_home = [p for p in pitch_data_home if p[3] == 'Called Strike']
    swinging_strikes_home = [p for p in pitch_data_home if p[3] == 'Swinging Strike']
    fouls_home = [p for p in pitch_data_home if p[3] == 'Foul']
    in_play_home = [p for p in pitch_data_home if p[3].startswith('In play')]

    add_pitch_trace(fig, balls_home, 'Balls (Home)', '#4287f5')
    add_pitch_trace(fig, called_strikes_home, 'Called Strikes (Home)', '#f54242')
    add_pitch_trace(fig, swinging_strikes_home, 'Swinging Strikes (Home)', '#9c42f5')
    add_pitch_trace(fig, fouls_home, 'Fouls (Home)', '#f5a442')
    add_pitch_trace(fig, in_play_home, 'In Play (Home)', '#42f54e')

    # Add away pitches
    pitch_data_away = [(float(p[0]), float(p[1]), p[2], p[3], p[4], p[5]) for p in away_pitches]
    balls_away = [p for p in pitch_data_away if p[3] == 'Ball']
    called_strikes_away = [p for p in pitch_data_away if p[3] == 'Called Strike']
    swinging_strikes_away = [p for p in pitch_data_away if p[3] == 'Swinging Strike']
    fouls_away = [p for p in pitch_data_away if p[3] == 'Foul']
    in_play_away = [p for p in pitch_data_away if p[3].startswith('In play')]

    add_pitch_trace(fig, balls_away, 'Balls (Away)', '#4287f5', visible=False)
    add_pitch_trace(fig, called_strikes_away, 'Called Strikes (Away)', '#f54242', visible=False)
    add_pitch_trace(fig, swinging_strikes_away, 'Swinging Strikes (Away)', '#9c42f5', visible=False)
    add_pitch_trace(fig, fouls_away, 'Fouls (Away)', '#f5a442', visible=False)
    add_pitch_trace(fig, in_play_away, 'In Play (Away)', '#42f54e', visible=False)

    add_strike_zone(fig, pitch_data_home + pitch_data_away)
    add_umpire_strike_zone(fig, called_strikes_home + called_strikes_away, balls_home + balls_away)

    if pitch_data_home:
        add_last_pitch(fig, pitch_data_home)
    elif pitch_data_away:
        add_last_pitch(fig, pitch_data_away)

    fig.update_xaxes(range=[-3, 3], title="Horizontal Location (feet)", gridcolor='#444444')
    fig.update_yaxes(range=[0, 6], title="Vertical Location (feet)", gridcolor='#444444')

    fig.update_layout(
        title=f"{game_title}<br><sub>{subtitle}</sub>",
        showlegend=True,
        plot_bgcolor='#2b2b2b',
        paper_bgcolor='#2b2b2b',
        font=dict(color='#e0e0e0'),
        margin=dict(l=50, r=50, t=80, b=50),
        height=600,
        width=600  # Ensure the plot is square
    )

    logging.debug("Plot generated successfully")
    return fig

def generate_pitch_stats_plot(home_pitches, away_pitches):
    home_pitch_types = [p[2] for p in home_pitches]
    away_pitch_types = [p[2] for p in away_pitches]
    
    home_pitch_counts = {pt: home_pitch_types.count(pt) for pt in set(home_pitch_types)}
    away_pitch_counts = {pt: away_pitch_types.count(pt) for pt in set(away_pitch_types)}

    fig = make_subplots(rows=1, cols=2, subplot_titles=("Home Team Pitch Types", "Away Team Pitch Types"))

    fig.add_trace(go.Bar(
        x=list(home_pitch_counts.keys()),
        y=list(home_pitch_counts.values()),
        marker_color='#4287f5',
        name='Home Team'
    ), row=1, col=1)

    fig.add_trace(go.Bar(
        x=list(away_pitch_counts.keys()),
        y=list(away_pitch_counts.values()),
        marker_color='#f54242',
        name='Away Team'
    ), row=1, col=2)

    fig.update_layout(
        title="Pitch Type Distribution",
        showlegend=True,
        plot_bgcolor='#2b2b2b',
        paper_bgcolor='#2b2b2b',
        font=dict(color='#e0e0e0'),
        margin=dict(l=50, r=50, t=80, b=50),
        height=400
    )
    fig.update_xaxes(title="Pitch Type", gridcolor='#444444')
    fig.update_yaxes(title="Count", gridcolor='#444444')
    return fig

def get_game_statuses(date):
    games = check_schedule(date)
    game_options = []
    for game in games:
        status = game['status']
        score = f"{game['away_name']} {game['away_score']} - {game['home_score']} {game['home_name']}"
        option = {'label': f"{game['away_name']} @ {game['home_name']} ({status}) - {score}", 'value': game['game_id']}
        game_options.append(option)
    return game_options

def create_app():
    app = Flask(__name__)
    CORS(app)

    @app.route('/api/games')
    def get_games():
        date = datetime.now(local_tz).strftime("%m/%d/%Y")
        games = get_game_statuses(date)
        return jsonify(games)

    @app.route('/api/game/<int:game_id>')
    def get_game_data_route(game_id):
        try:
            result = get_play_data(game_id)
            if result is None:
                logging.error("No data returned from get_play_data")
                return jsonify({"error": "Error retrieving game data"}), 404

            home_pitches, away_pitches, home_team, away_team, home_pitcher, away_pitcher, umpire = result
            game_title = f"{away_team} @ {home_team}"
            subtitle = f"Home Pitcher: {home_pitcher} ({len(home_pitches)} pitches), Away Pitcher: {away_pitcher} ({len(away_pitches)} pitches), Umpire: {umpire}"

            pitch_plot = generate_plot_for_game(home_pitches, away_pitches, game_title, subtitle)
            stats_plot = generate_pitch_stats_plot(home_pitches, away_pitches)

            return jsonify({
                "pitch_plot": pitch_plot.to_json(),
                "stats_plot": stats_plot.to_json(),
                "game_info": {
                    "title": game_title,
                    "subtitle": subtitle,
                    "home_pitches": len(home_pitches),
                    "away_pitches": len(away_pitches)
                }
            })
        except Exception as e:
            logging.exception("An error occurred while fetching game data")
            return jsonify({"error": "Internal Server Error"}), 500

    return app

if __name__ == "__main__":
    app = create_app()
    app.run(host='0.0.0.0', port=8686)