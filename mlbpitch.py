import statsapi
from datetime import datetime, timedelta
import time
import plotly.graph_objs as go
import plotly.io as pio
from plotly.subplots import make_subplots
import numpy as np
from scipy.spatial import ConvexHull
from shapely.geometry import Polygon, Point

# Set the default renderer for Plotly
pio.renderers.default = 'browser'

# Function to check the game schedule for a specific date
def check_schedule(date=None):
    if date is None:
        date = datetime.now().strftime("%m/%d/%Y")
    print(f"Fetching schedule for: {date}")
    games = statsapi.schedule(date=date)
    print(f"Number of games: {len(games)}")
    for game in games:
        print(f"Game ID: {game['game_id']}, Status: {game['status']}")
    return games

# Function to fetch play-by-play data for a specific game
def get_game_data(game_id):
    print(f"Fetching play-by-play data for game ID: {game_id}")
    try:
        plays = statsapi.get('game_playByPlay', {'gamePk': game_id})
    except Exception as e:
        return None, f"Error retrieving game data: {e}"
    
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
        return None, "No pitch data available."
    
    print(f"Retrieved {len(pitches)} pitches.")
    return pitches, None

# Function to generate a plot for a single game
def generate_plot_for_game(fig, pitches, subplot_position):
    if not pitches:
        print("No pitch data to display.")
        return

    # Convert pitch data to a list of tuples with required attributes
    pitch_data = [(float(p[0]), float(p[1]), p[2], p[3], p[4], p[5]) for p in pitches]

    # Categorize pitches based on umpire's call
    balls = [p for p in pitch_data if p[3] == 'Ball']
    called_strikes = [p for p in pitch_data if p[3] == 'Called Strike']
    swinging_strikes = [p for p in pitch_data if p[3] == 'Swinging Strike']
    fouls = [p for p in pitch_data if p[3] == 'Foul']
    in_play = [p for p in pitch_data if p[3].startswith('In play')]

    # Define baseball diameter
    baseball_diameter = 0.241667  # Baseball diameter in feet (approximate)

    # Function to add pitch traces to the plot with realistic size and reduced opacity
    def add_pitch_trace(pitches, name, color):
        if pitches:
            x, y, text = zip(*[(p[0], p[1], f"{p[2]}") for p in pitches])
            fig.add_trace(go.Scatter(
                x=x, y=y,
                mode='markers',
                name=name,
                text=text,
                marker=dict(size=baseball_diameter * 100, color=color, opacity=0.5)
            ), row=subplot_position[0], col=subplot_position[1])

    # Add different types of pitches to the plot
    add_pitch_trace(balls, 'Balls', 'rgba(0, 0, 255, 0.5)')
    add_pitch_trace(called_strikes, 'Called Strikes', 'rgba(255, 0, 0, 0.5)')
    add_pitch_trace(swinging_strikes, 'Swinging Strikes', 'rgba(128, 0, 128, 0.5)')
    add_pitch_trace(fouls, 'Fouls', 'rgba(255, 165, 0, 0.5)')
    add_pitch_trace(in_play, 'In Play', 'rgba(0, 128, 0, 0.5)')

    # Determine average strike zone if available
    valid_sz = [(p[4], p[5]) for p in pitches if p[4] and p[5]]
    if valid_sz:
        sz_top = np.mean([sz[0] for sz in valid_sz])  # Already in feet
        sz_bottom = np.mean([sz[1] for sz in valid_sz])  # Already in feet
        sz_left = -0.708333  # Fixed value for left strike zone boundary in feet (-8.5 inches converted to feet)
        sz_right = 0.708333  # Fixed value for right strike zone boundary in feet (8.5 inches converted to feet)

        # Create the strike zone rectangle
        strike_zone = go.Scatter(
            x=[sz_left, sz_right, sz_right, sz_left, sz_left],
            y=[sz_bottom, sz_bottom, sz_top, sz_top, sz_bottom],
            mode='lines',
            name='Strike Zone',
            line=dict(color='Black', width=2)
        )
        fig.add_trace(strike_zone, row=subplot_position[0], col=subplot_position[1])

    # Generate convex hull for called strikes
    if called_strikes:
        strike_coords = np.array([(p[0], p[1]) for p in called_strikes])
        if len(strike_coords) >= 3:  # ConvexHull requires at least 3 points
            hull = ConvexHull(strike_coords)
            hull_points = strike_coords[hull.vertices]
            hull_points = np.append(hull_points, [hull_points[0]], axis=0)  # Close the polygon
            hull_polygon = Polygon(hull_points)

            # Add convex hull to plot
            fig.add_trace(go.Scatter(
                x=hull_points[:, 0],
                y=hull_points[:, 1],
                fill='toself',
                fillcolor='rgba(255, 0, 0, 0.2)',
                mode='lines',
                name='Umpire Strike Zone',
                line=dict(color='red', width=2)
            ), row=subplot_position[0], col=subplot_position[1])

            # Apply blue circles where balls exist within the hull and label them "Inconsistent"
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
                marker=dict(size=baseball_diameter * 100, color='rgba(0, 0, 255, 0.5)'),  # Size scaled appropriately
                name='Inconsistent',
                text=inconsistent_text
            ), row=subplot_position[0], col=subplot_position[1])

    # Highlight the last pitch with a black circle
    last_pitch = pitch_data[-1]
    fig.add_trace(go.Scatter(
        x=[last_pitch[0]], y=[last_pitch[1]],
        mode='markers',
        marker=dict(size=baseball_diameter * 100, color='black'),
        name='Last Pitch',
        text=[f"{last_pitch[2]}"]
    ), row=subplot_position[0], col=subplot_position[1])

    # Set consistent x and y axis ranges
    fig.update_xaxes(range=[-3, 3], row=subplot_position[0], col=subplot_position[1])
    fig.update_yaxes(range=[0, 6], row=subplot_position[0], col=subplot_position[1])

def main():
    # Fetch game schedule
    games = check_schedule()
    live_games = [game for game in games if game['status'] == 'In Progress']

    # Determine mode: Live or Recap
    if live_games:
        print(f"Found {len(live_games)} live games.")
        game_ids = [game['game_id'] for game in live_games]
    else:
        print("No live games found. Switching to recap mode.")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%m/%d/%Y")
        yesterday_games = check_schedule(yesterday)
        completed_games = [game for game in yesterday_games if game['status'] == 'Final']
        if completed_games:
            game_ids = [game['game_id'] for game in completed_games]
            print(f"Found {len(completed_games)} completed games from yesterday.")
        else:
            print("No completed games found. Exiting.")
            return

    # Define the number of rows and columns for the subplots
    num_games = len(game_ids)
    cols = 2  # Number of columns
    rows = (num_games + cols - 1) // cols  # Calculate the number of rows needed

    # Create a subplot figure
    fig = make_subplots(rows=rows, cols=cols, subplot_titles=[f"Game ID: {game_id}" for game_id in game_ids])

    # Fetch and plot pitch data for each game
    for i, game_id in enumerate(game_ids):
        pitches, error_message = get_game_data(game_id)
        if pitches:
            print(f"Sample pitch data for game {game_id}:")
            for j, pitch in enumerate(pitches[:5]):  # Print first 5 pitches
                print(f"Pitch {j+1}: x={pitch[0]}, y={pitch[1]}, type={pitch[2]}, call={pitch[3]}, sz_top={pitch[4]}, sz_bottom={pitch[5]}")
            row = (i // cols) + 1
            col = (i % cols) + 1
            generate_plot_for_game(fig, pitches, (row, col))
        else:
            print(error_message)

    # Update layout and display the figure
    fig.update_layout(
        title_text="Pitch Locations and Strike Zones",
        height=rows * 700,
        width=cols * 700,
        showlegend=True,
    )

    fig.show()

if __name__ == "__main__":
    main()