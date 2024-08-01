import statsapi
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime

def get_live_game_data():
    today = datetime.now().strftime("%m/%d/%Y")
    games = statsapi.schedule(date=today)
    live_games = [game for game in games if game['status'] == 'Live']
    
    if not live_games:
        print("No live games at the moment.")
        return None
    
    game_id = live_games[0]['game_id']
    plays = statsapi.get('game_playByPlay', {'gamePk': game_id})
    
    pitches = []
    for play in plays['allPlays']:
        for event in play['playEvents']:
            if event['isPitch']:
                if 'pitchData' in event and 'coordinates' in event['pitchData']:
                    coords = event['pitchData']['coordinates']
                    if 'x' in coords and 'y' in coords:
                        pitches.append((coords['x'], coords['y']))
    
    return pitches

def plot_pitches(pitches, avg_strike_zone):
    plt.figure(figsize=(10, 10))
    plt.scatter(*zip(*pitches), alpha=0.5)
    
    rectangle = plt.Rectangle((-avg_strike_zone['width']/2, avg_strike_zone['bottom']),
                              avg_strike_zone['width'], avg_strike_zone['height'],
                              fill=False, color='r')
    plt.gca().add_patch(rectangle)
    
    plt.xlim(-3, 3)
    plt.ylim(0, 5)
    plt.xlabel('Horizontal position (ft)')
    plt.ylabel('Vertical position (ft)')
    plt.title('Pitch Locations vs Average Strike Zone')
    plt.grid(True)
    plt.show()

avg_strike_zone = {
    'width': 1.5,  # feet
    'height': 2.0,  # feet
    'bottom': 1.5  # feet (approximate height of bottom of strike zone)
}

def main():
    while True:
        pitches = get_live_game_data()
        if pitches:
            plot_pitches(pitches, avg_strike_zone)
        
        user_input = input("Press Enter to refresh or 'q' to quit: ")
        if user_input.lower() == 'q':
            break

if __name__ == "__main__":
    main()