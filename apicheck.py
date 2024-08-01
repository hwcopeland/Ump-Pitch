import statsapi
from datetime import datetime

# Fetch today's schedule
def check_schedule():
    today = datetime.now().strftime("%m/%d/%Y")
    print(f"Fetching schedule for today: {today}")
    games = statsapi.schedule(date=today)
    print(f"Number of games today: {len(games)}")
    for game in games:
        print(f"Game ID: {game['game_id']}, Status: {game['status']}")
    return games

# Fetch details of a specific game
def check_game_details(game_id):
    print(f"Fetching details for game ID: {game_id}")
    try:
        game_details = statsapi.get('game', {'gamePk': game_id})
        print(f"Game details: {game_details}")
    except Exception as e:
        print(f"Error retrieving game details: {e}")

# Main function to verify API calls
def main():
    games = check_schedule()
    if games:
        game_id = games[0]['game_id']
        check_game_details(game_id)
    else:
        print("No games found in the schedule.")

if __name__ == "__main__":
    main()