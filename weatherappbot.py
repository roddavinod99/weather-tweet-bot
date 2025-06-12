"""
This script runs a Flask web application that periodically posts weather updates
for a specified city to Twitter, including a dynamically generated image widget.
"""
# 1. Standard Library Imports
import logging
import os
import tempfile
from datetime import datetime, timezone

# 2. Third-Party Imports
import imgkit
import pytz
import requests
import tweepy
from flask import Flask, render_template_string
from flask_caching import Cache

# --- Configuration ---
logging.basicConfig(level=logging.INFO)

# --- Flask App Initialization ---
app = Flask(__name__)
# We keep the Cache object in case you want to use it elsewhere, but we won't use it on get_weather.
cache = Cache(app, config={'CACHE_TYPE': 'simple'}) 

# --- Constants ---
TWITTER_MAX_CHARS = 280
CITY_TO_MONITOR = "Gachibowli"
POST_TO_TWITTER_ENABLED = os.environ.get(
    "POST_TO_TWITTER_ENABLED", "true"
).lower() == "true"

# Configuration for imgkit on Windows
if os.name == 'nt':
    try:
        path_wkhtmltoimage = r'C:\Program Files\wkhtmltopdf\bin\wkhtmltoimage.exe'
        config = imgkit.config(wkhtmltoimage=path_wkhtmltoimage)
    except Exception:
        logging.warning("Could not configure wkhtmltoimage path for Windows.")
        config = None
else:
    config = None

if not POST_TO_TWITTER_ENABLED:
    logging.warning("Twitter interactions are DISABLED (Test Mode).")
else:
    logging.info("Twitter interactions ARE ENABLED.")


# --- Helper Functions and Template Filters ---
def get_env_variable(var_name, critical=True):
    """Retrieves an environment variable."""
    value = os.environ.get(var_name)
    if value is None and critical:
        raise EnvironmentError(f"Critical env var '{var_name}' not found.")
    return value

def degrees_to_cardinal(d):
    """Converts wind direction in degrees to a cardinal direction."""
    dirs = [
        'N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
        'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'
    ]
    ix = int((d + 11.25) / 22.5)
    return dirs[ix % 16]

@app.template_filter('format_unix_timestamp')
def format_unix_timestamp_filter(unix_ts, offset_seconds):
    """Jinja2 filter to format a Unix timestamp."""
    utc_time = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
    local_time = utc_time.astimezone(pytz.FixedOffset(offset_seconds // 60))
    hour_format = '%#I' if os.name == 'nt' else '%-I'
    return local_time.strftime(f"{hour_format}:%M %p, %b %d, %Y")

@app.template_filter('format_unix_timestamp_time')
def format_unix_timestamp_time_filter(unix_ts, offset_seconds):
    """Jinja2 filter to format a Unix timestamp into just time."""
    utc_time = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
    local_time = utc_time.astimezone(pytz.FixedOffset(offset_seconds // 60))
    hour_format = '%#I' if os.name == 'nt' else '%-I'
    return local_time.strftime(f"{hour_format}:%M %p")

@app.template_filter('weather_icon')
def weather_icon_filter(weather_main):
    """Jinja2 filter to return an HTML emoji entity for a weather condition."""
    condition = weather_main.lower()
    if 'clear' in condition: return '&#9728;'
    if 'rain' in condition or 'drizzle' in condition: return '&#127783;'
    if 'snow' in condition: return '&#10052;'
    if 'thunderstorm' in condition: return '&#9741;'
    if 'clouds' in condition: return '&#9729;'
    return '&#9729;'

# --- Twitter API Client Initialization ---
try:
    CONSUMER_KEY = get_env_variable("TWITTER_API_KEY")
    CONSUMER_SECRET = get_env_variable("TWITTER_API_SECRET")
    ACCESS_TOKEN = get_env_variable("TWITTER_ACCESS_TOKEN")
    ACCESS_TOKEN_SECRET = get_env_variable("TWITTER_ACCESS_TOKEN_SECRET")
    auth = tweepy.OAuth1UserHandler(
        CONSUMER_KEY, CONSUMER_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET
    )
    api_v1 = tweepy.API(auth)
    logging.info("Twitter v1.1 client initialized successfully.")
except (EnvironmentError, Exception) as e:
    logging.critical("Error initializing Twitter client: %s", e)
    api_v1 = None

# --- Core Functions ---
# ##################################################################
# ## CACHING DECORATOR REMOVED FROM THIS FUNCTION                 ##
# ##################################################################
def get_weather(city):
    """Fetches current weather data for a city."""
    try:
        weather_api_key = get_env_variable("WEATHER_API_KEY")
    except EnvironmentError:
        logging.error("WEATHER_API_KEY not found. Cannot fetch weather.")
        return None
    url = (
        f'https://api.openweathermap.org/data/2.5/weather?q={city},IN'
        f'&appid={weather_api_key}&units=metric'
    )
    try:
        weather_response = requests.get(url, timeout=10)
        weather_response.raise_for_status()
        logging.info("Successfully fetched fresh weather data.")
        return weather_response.json()
    except requests.exceptions.RequestException as err:
        logging.error("Error fetching weather data for %s: %s", city, err)
        return None

def generate_dynamic_hashtags(weather_data, current_day):
    """Generates a list of hashtags based on weather conditions."""
    hashtags = {'#Gachibowli', '#Hyderabad', '#weatherupdate'}
    main_conditions = weather_data.get('main', {})
    weather_main_info = weather_data.get('weather', [{}])[0]
    wind_conditions = weather_data.get('wind', {})
    rain_info_api = weather_data.get('rain', {})

    temp_celsius = main_conditions.get('temp', 0)
    sky_description = weather_main_info.get('description', "").lower()
    wind_speed_kmh = wind_conditions.get('speed', 0) * 3.6
    rain_1h = rain_info_api.get('1h', 0)

    if rain_1h > 0:
        hashtags.add('#HyderabadRains')
        hashtags.add('#rain')
    if temp_celsius > 35:
        hashtags.add('#Heatwave')
    if 'clear' in sky_description:
        hashtags.add('#SunnyDay')
    if wind_speed_kmh > 25:
        hashtags.add('#windy')
    if current_day in ['Saturday', 'Sunday']:
        hashtags.add('#WeekendWeather')
    return list(hashtags)

def create_weather_tweet_content(city, weather_data):
    """Creates the tweet body and a list of dynamic hashtags."""
    if not weather_data:
        return (["Could not generate weather report: Data missing."], ["#error"])
    weather_main_info = weather_data.get('weather', [{}])[0]
    main_conditions = weather_data.get('main', {})
    wind_conditions = weather_data.get('wind', {})
    rain_info_api = weather_data.get('rain', {})
    now = datetime.now(pytz.timezone('Asia/Kolkata'))
    current_day = now.strftime('%A')
    sky_description = weather_main_info.get('description', "N/A").title()
    temp_celsius = main_conditions.get('temp', 0)
    feels_like_celsius = main_conditions.get('feels_like', 0)
    humidity = main_conditions.get('humidity', 0)
    wind_speed_kmh = wind_conditions.get('speed', 0) * 3.6
    wind_dir = degrees_to_cardinal(wind_conditions.get('deg', 0))
    rain_1h = rain_info_api.get('1h', 0)
    rain_forecast = f"☔ Rain: {rain_1h:.2f} mm/hr" if rain_1h > 0 else "☔ No Rain"
    if rain_1h > 0.5: closing_message = "Stay dry out there! 🌧️"
    elif temp_celsius > 35: closing_message = "It's a hot one! Stay cool & hydrated. ☀️"
    elif temp_celsius < 18: closing_message = "Brr, it's cool! Consider a light jacket. 🧣"
    else: closing_message = "Enjoy your day! 😊"
    time_str = now.strftime("%I:%M %p")
    date_str = f"{now.day} {now.strftime('%B')}"
    greeting_line = (f"Hello, {city}!👋, {current_day} weather at {date_str}, {time_str}:")
    tweet_lines = [greeting_line, f"☁️ Sky: {sky_description}", f"🌡️ Temp: {temp_celsius:.0f}°C (feels: {feels_like_celsius:.0f}°C)", f"💧 Humidity: {humidity:.0f}%", f"💨 Wind: {wind_speed_kmh:.0f} km/h from the {wind_dir}", rain_forecast, "", closing_message]
    
    hashtags = generate_dynamic_hashtags(weather_data, current_day)
    return tweet_lines, hashtags

def create_weather_image(weather_data):
    """Generates a weather widget image from the weather data."""
    if not weather_data:
        logging.error("No weather data provided to create image.")
        return None
    try:
        with open('templates/weather_widget.html', 'r', encoding='utf-8') as f:
            html_template = f.read()
    except FileNotFoundError:
        logging.error("HTML template not found.")
        return None
    rendered_html = render_template_string(
        html_template,
        weather=weather_data,
        degrees_to_cardinal=degrees_to_cardinal
    )
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_file:
            output_image_path = temp_file.name
        
        options = {
            'format': 'png', 'width': 600,
            'enable-local-file-access': None,
            '--load-error-handling': 'ignore',
            'quiet': ''
        }

        imgkit.from_string(
            rendered_html,
            output_image_path,
            options=options,
            config=config
        )
        logging.info("Weather widget image created at %s", output_image_path)
        return output_image_path
    except Exception as e:
        logging.error("ERROR: Failed to create image with imgkit: %s", e)
        return None

def tweet_post(tweet_lines, hashtags, image_path):
    """Assembles and posts a tweet with an image."""
    if not all([tweet_lines, hashtags, api_v1, POST_TO_TWITTER_ENABLED]):
        if not POST_TO_TWITTER_ENABLED:
            logging.info("[TEST MODE] Skipping post. Content:\n%s\n%s", "\n".join(tweet_lines), " ".join(hashtags))
            return True
        logging.error("Tweet posting prerequisites not met. Aborting.")
        return False
    body = "\n".join(tweet_lines)
    while hashtags:
        hashtag_str = " ".join(hashtags)
        full_tweet = f"{body}\n{hashtag_str}"
        if len(full_tweet) <= TWITTER_MAX_CHARS: break
        hashtags.pop()
    else:
        full_tweet = body
    tweet_text = full_tweet
    try:
        media = api_v1.media_upload(filename=image_path)
        client = tweepy.Client(consumer_key=CONSUMER_KEY, consumer_secret=CONSUMER_SECRET, access_token=ACCESS_TOKEN, access_token_secret=ACCESS_TOKEN_SECRET)
        client.create_tweet(text=tweet_text, media_ids=[media.media_id])
        logging.info("Tweet posted successfully to Twitter with image!")
        logging.info("Final Tweet (%d chars): \n%s", len(tweet_text), tweet_text)
        return True
    except tweepy.errors.TooManyRequests:
        logging.warning("Rate limit exceeded. Will not retry.")
        return False
    except tweepy.errors.TweepyException as err:
        logging.error("Error posting tweet: %s", err)
        return False
    finally:
        if image_path and os.path.exists(image_path):
            os.remove(image_path)
            logging.info("Cleaned up temporary image file: %s", image_path)

def perform_scheduled_tweet_task():
    """Main task to fetch weather, create tweet, and post it."""
    logging.info("--- Running weather tweet job for %s ---", CITY_TO_MONITOR)
    weather_data = get_weather(CITY_TO_MONITOR)
    if not weather_data:
        logging.warning("Could not retrieve weather for %s. Aborting.", CITY_TO_MONITOR)
        return False
    image_path = create_weather_image(weather_data)
    if not image_path:
        logging.warning("Failed to create weather image. Aborting tweet.")
        return False
    tweet_lines, hashtags = create_weather_tweet_content(CITY_TO_MONITOR, weather_data)
    success = tweet_post(tweet_lines, hashtags, image_path)
    if success:
        logging.info("Tweet task for %s completed successfully.", CITY_TO_MONITOR)
    else:
        logging.warning("Tweet task for %s did not complete successfully.", CITY_TO_MONITOR)
    return success

# --- Flask Routes ---
@app.route('/')
def home():
    """A simple endpoint to check if the service is alive."""
    mode = "LIVE MODE" if POST_TO_TWITTER_ENABLED else "TEST MODE"
    return f"Weather Tweet Bot is alive! Current mode: {mode}", 200

@app.route('/run-tweet-task', methods=['POST', 'GET'])
def run_tweet_task_endpoint():
    """Main endpoint for a scheduler to call."""
    logging.info("'/run-tweet-task' endpoint triggered by a request.")
    success = perform_scheduled_tweet_task()
    if success:
        return "Tweet task executed successfully.", 200
    return "Tweet task execution failed or was skipped.", 500

# --- Main Execution Block ---
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))