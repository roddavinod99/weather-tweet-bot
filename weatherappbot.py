""" 
This script runs a Flask web application that periodically posts weather updates 
for a specified city to Twitter, including a dynamically generated image widget 
with both current conditions and an hourly forecast. 

It includes a /test-preview route for local visual testing. 
""" 
# 1. Standard Library Imports 
import logging 
import os 
import sys 
import tempfile 
import base64 
from datetime import datetime, timezone 

# 2. Third-Party Imports 
import imgkit 
import pytz 
import requests 
import tweepy 
from flask import Flask, render_template_string, render_template 
from flask_caching import Cache 

# --- Configuration --- 
logging.basicConfig(level=logging.INFO) 

# --- Flask App Initialization --- 
app = Flask(__name__) 
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
    logging.warning("--- TEST MODE IS ACTIVE ---") 
    logging.warning("Tweets will NOT be sent. Use the /test-preview endpoint for visual output.") 
else: 
    logging.info("--- LIVE MODE IS ACTIVE ---") 
    logging.info("Tweets WILL be sent to Twitter.") 


# --- Helper Functions and Template Filters --- 
def get_env_variable(var_name, critical=True): 
    """Retrieves an environment variable.""" 
    value = os.environ.get(var_name) 
    if value is None and critical: 
        sys.exit(f"FATAL: Critical environment variable '{var_name}' not found. The service cannot start.") 
    return value 

def degrees_to_cardinal(d): 
    """Converts wind direction in degrees to a cardinal direction.""" 
    dirs = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'] 
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

# ################################################################## 
# ## NEW TEMPLATE FILTER FOR THE HOURLY FORECAST                  ## 
# ################################################################## 
@app.template_filter('format_forecast_time') 
def format_forecast_time_filter(unix_ts, offset_seconds): 
    """Jinja2 filter to format forecast timestamp into just a simple time (e.g., 9AM).""" 
    utc_time = datetime.fromtimestamp(unix_ts, tz=timezone.utc) 
    local_time = utc_time.astimezone(pytz.FixedOffset(offset_seconds // 60)) 
    hour_format = '%#I%p' if os.name == 'nt' else '%-I%p' # e.g., 9AM 
    return local_time.strftime(hour_format).lower() 

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

# --- Core Functions --- 
def get_weather(city): 
    """Fetches current weather data for a city.""" 
    weather_api_key = get_env_variable("WEATHER_API_KEY", critical=False) 
    if not weather_api_key: 
        logging.error("WEATHER_API_KEY not found.") 
        return None 
    url = ( 
        f'https://api.openweathermap.org/data/2.5/weather?q={city},IN' 
        f'&appid={weather_api_key}&units=metric' 
    ) 
    try: 
        weather_response = requests.get(url, timeout=10) 
        weather_response.raise_for_status() 
        logging.info("Successfully fetched fresh CURRENT weather data.") 
        return weather_response.json() 
    except requests.exceptions.RequestException as err: 
        logging.error("Error fetching current weather data for %s: %s", city, err) 
        return None 

# ################################################################## 
# ## NEW FUNCTION TO FETCH THE 5-DAY / 3-HOUR FORECAST            ## 
# ################################################################## 
def get_forecast(city): 
    """Fetches 5-day/3-hour forecast data for a city.""" 
    weather_api_key = get_env_variable("WEATHER_API_KEY", critical=False) 
    if not weather_api_key: 
        logging.error("WEATHER_API_KEY not found.") 
        return None 
    url = ( 
        f'https://api.openweathermap.org/data/2.5/forecast?q={city},IN' 
        f'&appid={weather_api_key}&units=metric' 
    ) 
    try: 
        forecast_response = requests.get(url, timeout=10) 
        forecast_response.raise_for_status() 
        logging.info("Successfully fetched fresh FORECAST data.") 
        return forecast_response.json() 
    except requests.exceptions.RequestException as err: 
        logging.error("Error fetching forecast data for %s: %s", city, err) 
        return None 

def create_weather_image(current_weather, forecast_data): 
    """Generates a weather widget image from the weather data.""" 
    if not current_weather or not forecast_data: 
        logging.error("Missing current weather or forecast data to create image.") 
        return None 
    try: 
        with open('templates/weather_widget.html', 'r', encoding='utf-8') as f: 
            html_template = f.read() 
    except FileNotFoundError: 
        logging.error("HTML template not found.") 
        return None 
        
    # Pass both current weather and forecast data to the template 
    rendered_html = render_template_string( 
        html_template, 
        weather=current_weather, 
        forecast=forecast_data, 
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
            rendered_html, output_image_path, options=options, config=config 
        ) 
        logging.info("Weather widget image created at %s", output_image_path) 
        return output_image_path 
    except Exception as e: 
        logging.error("ERROR: Failed to create image with imgkit: %s", e) 
        return None 

def create_full_tweet_text(tweet_lines, hashtags): 
    """Combines tweet lines and hashtags into the final text.""" 
    body = "\n".join(tweet_lines) 
    while hashtags: 
        hashtag_str = " ".join(hashtags) 
        full_tweet = f"{body}\n{hashtag_str}" 
        if len(full_tweet) <= TWITTER_MAX_CHARS: 
            return full_tweet 
        hashtags.pop() 
    return body 

def tweet_post(tweet_text, image_path): 
    """Assembles and posts a tweet with an image.""" 
    try: 
        consumer_key = get_env_variable("TWITTER_API_KEY") 
        consumer_secret = get_env_variable("TWITTER_API_SECRET") 
        access_token = get_env_variable("TWITTER_ACCESS_TOKEN") 
        access_token_secret = get_env_variable("TWITTER_ACCESS_TOKEN_SECRET") 
        
        client_v2 = tweepy.Client( 
            consumer_key=consumer_key, consumer_secret=consumer_secret, 
            access_token=access_token, access_token_secret=access_token_secret 
        ) 
        auth = tweepy.OAuth1UserHandler( 
            consumer_key, consumer_secret, access_token, access_token_secret 
        ) 
        api_v1 = tweepy.API(auth) 
        logging.info("Twitter clients initialized successfully for posting.") 
    except Exception as e: 
        logging.error("Failed to initialize Twitter clients: %s", e) 
        return False 

    try: 
        media = api_v1.media_upload(filename=image_path) 
        client_v2.create_tweet(text=tweet_text, media_ids=[media.media_id]) 
        logging.info("Tweet posted successfully!") 
        return True 
    except tweepy.errors.TweepyException as err: 
        logging.error("Error posting tweet with Tweepy: %s", err) 
        return False 
    finally: 
        if image_path and os.path.exists(image_path): 
            os.remove(image_path) 
            logging.info("Cleaned up temporary image file: %s", image_path) 

def generate_tweet_content(weather_data): 
    """Generates the text lines and hashtags for the tweet.""" 
    if not weather_data: 
        return None, None 
        
    now = datetime.now(pytz.timezone('Asia/Kolkata')) 
    current_day = now.strftime('%A') 
    weather_main_info = weather_data.get('weather', [{}])[0] 
    main_conditions = weather_data.get('main', {}) 
    wind_conditions = weather_data.get('wind', {}) 
    rain_info_api = weather_data.get('rain', {}) 
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
    greeting_line = (f"Hello, {CITY_TO_MONITOR}!👋, {current_day} weather at {date_str}, {time_str}:") 
    tweet_lines = [greeting_line, f"☁️ Sky: {sky_description}", f"🌡️ Temp: {temp_celsius:.0f}°C (feels: {feels_like_celsius:.0f}°C)", f"💧 Humidity: {humidity:.0f}%", f"💨 Wind: {wind_speed_kmh:.0f} km/h from the {wind_dir}", rain_forecast, "", closing_message] 
    
    hashtags = generate_dynamic_hashtags(weather_data, current_day) 
    return tweet_lines, hashtags 

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
    
# --- Flask Routes --- 
@app.route('/') 
def home(): 
    """A simple endpoint to check if the service is alive.""" 
    mode = "LIVE" if POST_TO_TWITTER_ENABLED else "TEST" 
    return f"Weather Tweet Bot is alive and running! Current mode: {mode}", 200 

@app.route('/run-tweet-task', methods=['POST']) 
def run_tweet_task_endpoint(): 
    """Main endpoint for a scheduler to call. Posts to Twitter if enabled.""" 
    logging.info("'/run-tweet-task' endpoint triggered.") 
    
    if not POST_TO_TWITTER_ENABLED: 
        msg = "Live tweet task skipped because POST_TO_TWITTER_ENABLED is false." 
        logging.warning(msg) 
        return msg, 403 

    current_weather = get_weather(CITY_TO_MONITOR) 
    forecast_data = get_forecast(CITY_TO_MONITOR) 
    if not current_weather or not forecast_data: 
        return "Failed to get weather or forecast data.", 500 
        
    image_path = create_weather_image(current_weather, forecast_data) 
    if not image_path: 
        return "Failed to create weather image.", 500 

    tweet_lines, hashtags = generate_tweet_content(current_weather) 
    final_tweet_text = create_full_tweet_text(tweet_lines, hashtags) 
    
    success = tweet_post(final_tweet_text, image_path) 
    if success: 
        return "Tweet task executed successfully.", 200 
        
    return "Tweet task execution failed.", 500 

@app.route('/test-preview') 
def test_preview_endpoint(): 
    """Generates and displays the tweet and image locally without posting.""" 
    logging.info("'/test-preview' endpoint triggered.") 
    
    current_weather = get_weather(CITY_TO_MONITOR) 
    forecast_data = get_forecast(CITY_TO_MONITOR) 
    if not current_weather or not forecast_data: 
        return "<h1>Error</h1><p>Could not get weather or forecast data. Check logs.</p>", 500 

    image_path = create_weather_image(current_weather, forecast_data) 
    if not image_path: 
        return "<h1>Error</h1><p>Could not create weather image. Check logs.</p>", 500 

    try: 
        with open(image_path, "rb") as img_file: 
            image_data_b64 = base64.b64encode(img_file.read()).decode('utf-8') 
    except Exception as e: 
        logging.error("Could not read or encode image file: %s", e) 
        return "<h1>Error</h1><p>Could not read or encode image file.</p>", 500 
    finally: 
        if os.path.exists(image_path): 
            os.remove(image_path) 
            logging.info("Cleaned up temporary preview image.") 

    tweet_lines, hashtags = generate_tweet_content(current_weather) 
    final_tweet_text = create_full_tweet_text(tweet_lines, hashtags) 

    return render_template('test_preview.html',  
                            tweet_text=final_tweet_text,  
                            image_data=image_data_b64) 

# --- Main Execution Block --- 
if __name__ == "__main__": 
    from dotenv import load_dotenv 
    load_dotenv() 
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)), debug=True)