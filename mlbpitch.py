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

# Command-line argument parser
parser = argparse.ArgumentParser(description="MLB Pitch Tracker")
parser.add_argument("--date", help="Date to fetch games (MM/DD/YYYY)")
parser.add_argument("--team", help="Team name to filter games")
parser.add_argument("--output", help="Output directory for saved plots")
args = parser.parse_args()

# Global variables
baseball_diameter = 0.075  # Approximate diameter of a baseball in meters

# Function to check the game schedule for a specific date
def check_schedule(date=None):
    if date is None:
        date = datetime.now().strftime("%m/%d/%Y")
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

    # Extract game details
    try:
        home_team = game_data['gameData']['teams']['home']['teamName']
        away_team = game_data['gameData']['teams']['away']['teamName']
        
        # Handle cases where pitcher information might not be available
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
    pitches = []
    for play in plays['allPlays']:
        for event in play['playEvents']:
            if event['isPitch']:
                if 'pitchData' in event and 'coordinates' in event['pitchData']:
                    coords = event['pitchData']['coordinates']
                    if 'pX' in coords and 'pZ' in coords:
                        # Extract pitch details
                        pitch_type = event['details']['type']['description'] if 'type' in event['details'] and 'description' in event['details']['type'] else 'Unknown'
                        umpire_call = event['details']['call']['description'] if 'call' in event['details'] and 'description' in event['details']['call'] else 'Unknown'
                        sz_top = event['pitchData'].get('strikeZoneTop', None)
                        sz_bottom = event['pitchData'].get('strikeZoneBottom', None)
                        pitches.append((coords['pX'], coords['pZ'], pitch_type, umpire_call, sz_top, sz_bottom))

    if not pitches:
        logging.warning("No pitch data available.")
        return None
    
    logging.info(f"Retrieved {len(pitches)} pitches.")
    return pitches, home_team, away_team, home_pitcher, away_pitcher, umpire

def add_pitch_trace(fig, pitches, name, color):
    if pitches:
        x, y, text = zip(*[(p[0], p[1], f"{p[2]}") for p in pitches])
        fig.add_trace(go.Scatter(
            x=x, y=y,
            mode='markers',
            name=name,
            text=text,
            marker=dict(size=baseball_diameter * 100, color=color, opacity=0.5)
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
            line=dict(color='White', width=2)
        ))

def add_umpire_strike_zone(fig, called_strikes, balls):
    if called_strikes:
        strike_coords = np.array([(p[0], p[1]) for p in called_strikes])
        if len(strike_coords) >= 3:
            hull = ConvexHull(strike_coords)
            hull_points = strike_coords[hull.vertices]
            hull_points = np.append(hull_points, [hull_points[0]], axis=0)
            hull_polygon = Polygon(hull_points)

            fig.add_trace(go.Scatter(
                x=hull_points[:, 0],
                y=hull_points[:, 1],
                fill='toself',
                fillcolor='rgba(255, 0, 0, 0.2)',
                mode='lines',
                name='Umpire Strike Zone',
                line=dict(color='red', width=2)
            ))

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
        marker=dict(size=baseball_diameter * 100, color='rgba(0, 0, 255, 0.5)'),
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

def generate_plot_for_game(pitches, game_title, subtitle):
    logging.debug(f"Generating plot with {len(pitches)} pitches")
    if not pitches:
        logging.warning("No pitch data to display.")
        return go.Figure()  # Return an empty figure instead of None

    pitch_data = [(float(p[0]), float(p[1]), p[2], p[3], p[4], p[5]) for p in pitches]

    balls = [p for p in pitch_data if p[3] == 'Ball']
    called_strikes = [p for p in pitch_data if p[3] == 'Called Strike']
    swinging_strikes = [p for p in pitch_data if p[3] == 'Swinging Strike']
    fouls = [p for p in pitch_data if p[3] == 'Foul']
    in_play = [p for p in pitch_data if p[3].startswith('In play')]

    fig = go.Figure()

    # Add traces for each pitch type
    add_pitch_trace(fig, balls, 'Balls', 'rgba(0, 0, 255, 0.5)')
    add_pitch_trace(fig, called_strikes, 'Called Strikes', 'rgba(255, 0, 0, 0.5)')
    add_pitch_trace(fig, swinging_strikes, 'Swinging Strikes', 'rgba(128, 0, 128, 0.5)')
    add_pitch_trace(fig, fouls, 'Fouls', 'rgba(255, 165, 0, 0.5)')
    add_pitch_trace(fig, in_play, 'In Play', 'rgba(0, 128, 0, 0.5)')

    # Add strike zone
    add_strike_zone(fig, pitch_data)

    # Add umpire's strike zone
    add_umpire_strike_zone(fig, called_strikes, balls)

    # Add last pitch
    add_last_pitch(fig, pitch_data)

    fig.update_layout(
        title=f"{game_title}<br><sub>{subtitle}</sub>",
        xaxis=dict(range=[-3, 3], title="Horizontal Location (feet)"),
        yaxis=dict(range=[0, 6], title="Vertical Location (feet)"),
        showlegend=True,
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        font=dict(color='white')
    )

    logging.debug("Plot generated successfully")
    return fig

def generate_pitch_stats_plot(pitches):
    pitch_types = [p[2] for p in pitches]
    pitch_counts = {pt: pitch_types.count(pt) for pt in set(pitch_types)}

    fig = go.Figure(data=[go.Bar(x=list(pitch_counts.keys()), y=list(pitch_counts.values()))])
    fig.update_layout(
        title="Pitch Type Distribution",
        xaxis_title="Pitch Type",
        yaxis_title="Count",
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        font=dict(color='white')
    )
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

def main():
    logging.info("Main function started")
    date = args.date if args.date else datetime.now().strftime("%m/%d/%Y")
    games = check_schedule(date)
    
    if args.team:
        games = [game for game in games if args.team.lower() in game['away_name'].lower() or args.team.lower() in game['home_name'].lower()]
    
    if not games:
        logging.warning(f"No games found for the specified date{' and team' if args.team else ''}.")
        return

    logging.info("Initializing Dash app")
    app = dash.Dash(__name__)
    app.config.suppress_callback_exceptions = True

    app.layout = html.Div([
        dcc.Dropdown(id='game-selector', placeholder="Select a game"),
        html.Div([
            dcc.Graph(id='pitch-plot', style={'width': '50%', 'display': 'inline-block'}),
            dcc.Graph(id='pitch-stats', style={'width': '50%', 'display': 'inline-block'})
        ]),
        html.Div(id='game-info'),
        dcc.Interval(id='interval-component', interval=5*1000, n_intervals=0)
    ], style={'backgroundColor': '#111111', 'color': '#FFFFFF'})

    @app.callback(Output('game-selector', 'options'),
                  Input('interval-component', 'n_intervals'))
    def update_game_options(n):
        date = args.date if args.date else datetime.now().strftime("%m/%d/%Y")
        return get_game_statuses(date)

    @app.callback(
        [Output('pitch-plot', 'figure'),
         Output('pitch-stats', 'figure'),
         Output('game-info', 'children')],
        [Input('game-selector', 'value'),
         Input('interval-component', 'n_intervals')]
    )
    def update_graphs(selected_game_id, n):
        if not selected_game_id:
            return go.Figure(), go.Figure(), "No game selected"

        result = get_play_data(selected_game_id)
        if result is None:
            return go.Figure(), go.Figure(), "Error retrieving game data"

        pitches, home_team, away_team, home_pitcher, away_pitcher, umpire = result
        game_title = f"{away_team} @ {home_team}"
        subtitle = f"Home Pitcher: {home_pitcher}, Away Pitcher: {away_pitcher}, Umpire: {umpire}"

        pitch_plot = generate_plot_for_game(pitches, game_title, subtitle)
        stats_plot = generate_pitch_stats_plot(pitches)

        game_info = html.Div([
            html.H3(game_title),
            html.P(subtitle),
            html.P(f"Total Pitches: {len(pitches)}")
        ])

        return pitch_plot, stats_plot, game_info

    logging.info("Starting Dash server")
    print("Dash server running on http://127.0.0.1:8050/")
    app.run_server(debug=True)

if __name__ == "__main__":
    main()