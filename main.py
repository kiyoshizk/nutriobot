#!/usr/bin/env python3
"""
Nutrition Assistant Telegram Bot
A comprehensive nutrition assistant for Indian users in Maharashtra and Karnataka
Built with python-telegram-bot v20+ and Firebase integration
"""

import logging
import asyncio
import json
import random
import os
import re
import csv
from typing import Dict, Any, Optional, List
from urllib.parse import quote
from pathlib import Path
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, 
    CommandHandler, 
    CallbackQueryHandler, 
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters
)

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Firebase imports (you'll need to install firebase-admin)
try:
    import firebase_admin
    from firebase_admin import credentials, firestore
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False
    print("\u26A0\uFE0F Firebase not available - install with: pip install firebase-admin")

# Static Meal Generator imports
try:
    from ai_meal_generator import generate_ai_meal_plan, get_fallback_meal_message
    MEAL_GENERATOR_AVAILABLE = True
except ImportError:
    MEAL_GENERATOR_AVAILABLE = False
    print("\u26A0\uFE0F Meal generator not available - check ai_meal_generator.py")

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
BOT_TOKEN = os.getenv('BOT_TOKEN')
FIREBASE_CREDENTIALS_PATH = os.getenv('FIREBASE_CREDENTIALS_PATH', 'firebase-credentials.json')
FIREBASE_CREDENTIALS_JSON = os.getenv('FIREBASE_CREDENTIALS_JSON')

# Timeout configuration
CSV_PROCESSING_TIMEOUT = 30  # seconds
FIREBASE_TIMEOUT = 10  # seconds

# Security configuration - Updated to include all diet types used in the app
ALLOWED_DIET_TYPES = {
    'vegetarian', 'veg', 'non-vegetarian', 'non-veg', 'vegan', 
    'keto', 'eggitarian', 'jain', 'mixed', 'paleo', 'mediterranean', 
    'dash', 'low-carb', 'high-protein', 'balanced'
}
ALLOWED_MEAL_TYPES = {'breakfast', 'lunch', 'dinner', 'snack', 'morning snack', 'evening snack'}
MAX_MEALS_PER_REQUEST = 50
MAX_FILE_SIZE_MB = 10

# Conversation states
NAME, AGE, GENDER, STATE, DIET_TYPE, MEDICAL_CONDITION, ACTIVITY_LEVEL, MEAL_PLAN, WEEK_PLAN, GROCERY_LIST, RATING, GROCERY_MANAGE, CART, PROFILE, INGREDIENTS, MEAL_TYPE, LOG_MEAL_FOLLOWED, LOG_MEAL_SKIPPED, LOG_MEAL_EXTRA, LOG_MEAL_CUSTOM = range(20)

# In-memory cache for performance (with size limits)
MAX_CACHE_SIZE = 1000
user_data_cache: Dict[int, Dict[str, Any]] = {}
grocery_lists_cache: Dict[int, List[str]] = {}
user_cart_cache: Dict[int, set] = {}
user_streaks_cache: Dict[int, Dict[str, Any]] = {}
meal_data_cache: Dict[str, List[Dict[str, Any]]] = {}

# Rate limiting data
user_rate_limits: Dict[int, Dict[str, Any]] = {}
RATE_LIMIT_WINDOW = 60  # 1 minute
MAX_REQUESTS_PER_WINDOW = 30  # 30 requests per minute

# Firebase setup
if FIREBASE_AVAILABLE:
    try:
        # Try to load credentials from JSON string in environment variable first
        if FIREBASE_CREDENTIALS_JSON:
            cred = credentials.Certificate(json.loads(FIREBASE_CREDENTIALS_JSON))
            firebase_admin.initialize_app(cred)
            db = firestore.client()
            logger.info("✅ Firebase connected successfully with credentials from environment variable")
            
        # Fallback to credentials file
        elif os.path.exists(FIREBASE_CREDENTIALS_PATH):
            cred = credentials.Certificate(FIREBASE_CREDENTIALS_PATH)
            firebase_admin.initialize_app(cred)
            db = firestore.client()
            logger.info("✅ Firebase connected successfully with credentials file")
        else:
            db = firestore.client()
            logger.info("✅ Firebase connected successfully (no credentials)")
    except Exception as e:
        logger.error(f"❌ Firebase connection failed: {e}")
        FIREBASE_AVAILABLE = False
        db = None
else:
    db = None

# Missing function fixes
def get_firebase_db():
    """Get Firebase database instance."""
    return db if FIREBASE_AVAILABLE else None

async def create_test_data():
    """Create test data for Firebase demonstration."""
    try:
        if FIREBASE_AVAILABLE and db:
            # Create test user data
            test_user_id = "test_user_123"
            test_data = {
                "name": "Test User",
                "age": 25,
                "diet": "vegetarian",
                "state": "maharashtra",
                "gender": "male",
                "medical": "none",
                "activity": "active"
            }
            await save_user_profile(int(test_user_id), test_data)
            logger.info("✅ Test data created successfully")
            return True
        else:
            logger.warning("⚠️ Firebase not available for test data creation")
            return False
    except Exception as e:
        logger.error(f"❌ Error creating test data: {e}")
        return False

# Input validation functions
def sanitize_input(text: str, max_length: int = 200) -> str:
    """Sanitize user input to prevent injection attacks."""
    if not text:
        return ""
    
    # Remove potentially dangerous characters
    sanitized = re.sub(r'[<>"\']', '', text.strip())
    
    # Limit length
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length]
    
    return sanitized

def validate_name(name: str) -> bool:
    """Validate user name input."""
    if not name or len(name) < 2 or len(name) > 50:
        return False
    
    # Check for valid characters (letters, numbers, spaces, common punctuation)
    if not re.match(r'^[a-zA-Z0-9\s\.\-\']+$', name):
        return False
    
    return True

def validate_age(age_text: str) -> Optional[int]:
    """Validate age input."""
    try:
        # Remove non-numeric characters
        clean_age = re.sub(r'[^\d]', '', age_text)
        if not clean_age:
            return None
        
        age = int(clean_age)
        if age < 1 or age > 120:
            return None
        
        return age
    except ValueError:
        return None

# Cache management functions
def cleanup_cache(cache: Dict, max_size: int = MAX_CACHE_SIZE):
    """Clean up cache if it exceeds maximum size with improved performance."""
    try:
        if len(cache) > max_size:
            # Remove oldest entries (simple FIFO)
            keys_to_remove = list(cache.keys())[:len(cache) - max_size + 10]  # Keep some buffer
            for key in keys_to_remove:
                del cache[key]
            logger.info(f"Cleaned up cache, removed {len(keys_to_remove)} entries")
    except Exception as e:
        logger.error(f"Error during cache cleanup: {e}")
        # Fallback: clear cache if cleanup fails
        try:
            cache.clear()
            logger.warning("Cache cleared due to cleanup error")
        except Exception as clear_error:
            logger.error(f"Failed to clear cache: {clear_error}")

# Firebase helper functions with proper error handling
async def save_user_profile(user_id: int, profile_data: Dict[str, Any]) -> bool:
    """Save user profile to Firebase with proper error handling and retry mechanism."""
    # Sanitize profile data
    sanitized_profile = {}
    for key, value in profile_data.items():
        if isinstance(value, str):
            sanitized_profile[key] = sanitize_input(value)
        else:
            sanitized_profile[key] = value
    
    # Update cache immediately for better performance
    user_data_cache[user_id] = sanitized_profile.copy()
    cleanup_cache(user_data_cache)
    
    # Save to Firebase if available with retry mechanism
    if FIREBASE_AVAILABLE and db:
        max_retries = 3
        for attempt in range(max_retries):
            try:
                doc_ref = db.collection('users').document(str(user_id))
                doc_ref.set({
                    'profile': sanitized_profile,
                    'created_at': firestore.SERVER_TIMESTAMP,
                    'updated_at': firestore.SERVER_TIMESTAMP
                }, merge=True)
                logger.info(f"Profile saved to Firebase for user {user_id} (attempt {attempt + 1})")
                return True
            except Exception as e:
                logger.error(f"Error saving user profile to Firebase (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)  # Wait before retry
                else:
                    logger.error(f"Failed to save profile to Firebase after {max_retries} attempts")
                    return False
    else:
        logger.warning(f"Firebase not available - profile saved to cache only for user {user_id}")
        return False

async def get_user_profile(user_id: int) -> Optional[Dict[str, Any]]:
    """Get user profile from cache or Firebase with proper error handling."""
    # Check cache first
    if user_id in user_data_cache:
        logger.info(f"Profile found in cache for user {user_id}")
        return user_data_cache[user_id]
    
    # Try Firebase if available
    if FIREBASE_AVAILABLE and db:
        try:
            doc_ref = db.collection('users').document(str(user_id))
            doc = doc_ref.get()
            if doc.exists:
                data = doc.to_dict()
                profile_data = data.get('profile')
                if profile_data:
                    # Cache for future access
                    user_data_cache[user_id] = profile_data
                    cleanup_cache(user_data_cache)
                    logger.info(f"Profile loaded from Firebase for user {user_id}")
                    return profile_data
        except Exception as e:
            logger.error(f"Error getting user profile from Firebase: {e}")
    
    logger.info(f"No profile found for user {user_id}")
    return None

async def save_grocery_list(user_id: int, grocery_list: List[str]) -> bool:
    """Save grocery list to Firebase with proper error handling."""
    # Sanitize grocery list
    sanitized_list = [sanitize_input(item, 100) for item in grocery_list if item.strip()]
    
    # Update cache
    grocery_lists_cache[user_id] = sanitized_list
    cleanup_cache(grocery_lists_cache)
    
    # Save to Firebase if available
    if FIREBASE_AVAILABLE and db:
        try:
            doc_ref = db.collection('users').document(str(user_id))
            doc_ref.update({
                'grocery_list': sanitized_list,
                'updated_at': firestore.SERVER_TIMESTAMP
            })
            logger.info(f"Grocery list saved to Firebase for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error saving grocery list to Firebase: {e}")
            return False
    else:
        logger.warning(f"Firebase not available - grocery list saved to cache only for user {user_id}")
        return False

async def get_grocery_list(user_id: int) -> List[str]:
    """Get grocery list from cache or Firebase."""
    # Check cache first
    if user_id in grocery_lists_cache:
        return grocery_lists_cache[user_id]
    
    # Try Firebase if available
    if FIREBASE_AVAILABLE and db:
        try:
            doc_ref = db.collection('users').document(str(user_id))
            doc = doc_ref.get()
            if doc.exists:
                data = doc.to_dict()
                grocery_list = data.get('grocery_list', [])
                # Cache for future access
                grocery_lists_cache[user_id] = grocery_list
                cleanup_cache(grocery_lists_cache)
                return grocery_list
        except Exception as e:
            logger.error(f"Error getting grocery list from Firebase: {e}")
    
    return []

async def save_cart_selections(user_id: int, cart_items: set) -> bool:
    """Save cart selections to Firebase."""
    # Convert set to list for Firebase storage
    cart_list = list(cart_items)
    
    # Update cache
    user_cart_cache[user_id] = cart_items
    cleanup_cache(user_cart_cache)
    
    # Save to Firebase if available
    if FIREBASE_AVAILABLE and db:
        try:
            doc_ref = db.collection('users').document(str(user_id))
            doc_ref.update({
                'cart_selections': cart_list,
                'updated_at': firestore.SERVER_TIMESTAMP
            })
            return True
        except Exception as e:
            logger.error(f"Error saving cart selections to Firebase: {e}")
            return False
    else:
        logger.warning(f"Firebase not available - cart selections saved to cache only for user {user_id}")
        return False

async def get_cart_selections(user_id: int) -> set:
    """Get cart selections from cache or Firebase."""
    # Check cache first
    if user_id in user_cart_cache:
        return user_cart_cache[user_id]
    
    # Try Firebase if available
    if FIREBASE_AVAILABLE and db:
        try:
            doc_ref = db.collection('users').document(str(user_id))
            doc = doc_ref.get()
            if doc.exists:
                data = doc.to_dict()
                cart_list = data.get('cart_selections', [])
                cart_set = set(cart_list)
                # Cache for future access
                user_cart_cache[user_id] = cart_set
                cleanup_cache(user_cart_cache)
                return cart_set
        except Exception as e:
            logger.error(f"Error getting cart selections from Firebase: {e}")
    
    return set()

async def save_meal_rating(user_id: int, meal_name: str, rating: int, feedback: str = "") -> bool:
    """Save meal rating to Firebase with proper error handling."""
    if not FIREBASE_AVAILABLE or not db:
        logger.warning("Firebase not available - rating not saved")
        return False
    
    try:
        # Sanitize inputs
        sanitized_meal_name = sanitize_input(meal_name, 100)
        sanitized_feedback = sanitize_input(feedback, 500)
        
        doc_ref = db.collection('ratings').document()
        doc_ref.set({
            'user_id': str(user_id),
            'meal_name': sanitized_meal_name,
            'rating': rating,  # 1 for 👍, 0 for 👎
            'feedback': sanitized_feedback,
            'timestamp': firestore.SERVER_TIMESTAMP
        })
        logger.info(f"Meal rating saved to Firebase for user {user_id}")
        return True
    except Exception as e:
        logger.error(f"Error saving meal rating: {e}")
        return False

def calculate_streak_points(streak_count: int) -> int:
    """Calculate points based on streak count with exponential growth."""
    if streak_count <= 0:
        return 0
    elif streak_count == 1:
        return random.randint(2, 5)
    elif streak_count == 2:
        return random.randint(4, 8)
    elif streak_count == 3:
        return random.randint(8, 15)
    else:
        # Exponential growth: base * (multiplier ^ (days - 3))
        base_points = random.randint(8, 15)
        multiplier = 1.5
        days_over_3 = streak_count - 3
        return int(base_points * (multiplier ** days_over_3))

async def update_user_streak(user_id: int) -> Dict[str, Any]:
    """Update user streak and return streak info with proper Firebase persistence."""
    today = datetime.now().date()
    
    # Get current streak data
    streak_data = await get_user_streak(user_id)
    
    last_completed = streak_data.get('last_completed_date')
    
    # Check if user already completed today
    if last_completed and last_completed == today:
        return streak_data
    
    # Check if streak should continue or reset
    if last_completed:
        days_diff = (today - last_completed).days
        if days_diff == 1:
            # Consecutive day - continue streak
            streak_data['streak_count'] += 1
        elif days_diff > 1:
            # Gap in streak - reset
            streak_data['streak_count'] = 1
        else:
            # Same day - no change
            return streak_data
    else:
        # First time - start streak
        streak_data['streak_count'] = 1
    
    # Calculate points for this completion
    points_earned = calculate_streak_points(streak_data['streak_count'])
    streak_data['streak_points_total'] += points_earned
    streak_data['last_completed_date'] = today
    
    # Save to cache
    user_streaks_cache[user_id] = streak_data
    cleanup_cache(user_streaks_cache)
    
    # Save to Firebase if available
    if FIREBASE_AVAILABLE and db:
        try:
            doc_ref = db.collection('users').document(str(user_id))
            doc_ref.update({
                'streak_data': streak_data,
                'updated_at': firestore.SERVER_TIMESTAMP
            })
            logger.info(f"Streak data saved to Firebase for user {user_id}")
        except Exception as e:
            logger.error(f"Error saving streak data: {e}")
    
    return streak_data

async def get_user_streak(user_id: int) -> Dict[str, Any]:
    """Get user streak data from cache or Firebase."""
    # Check cache first
    if user_id in user_streaks_cache:
        return user_streaks_cache[user_id]
    
    # Try Firebase
    if FIREBASE_AVAILABLE and db:
        try:
            doc_ref = db.collection('users').document(str(user_id))
            doc = doc_ref.get()
            if doc.exists:
                data = doc.to_dict()
                streak_data = data.get('streak_data', {
                    'streak_count': 0,
                    'last_completed_date': None,
                    'streak_points_total': 0
                })
                # Cache for future access
                user_streaks_cache[user_id] = streak_data
                cleanup_cache(user_streaks_cache)
                return streak_data
        except Exception as e:
            logger.error(f"Error getting streak data: {e}")
    
    # Return default
    default_streak = {
        'streak_count': 0,
        'last_completed_date': None,
        'streak_points_total': 0
    }
    user_streaks_cache[user_id] = default_streak
    cleanup_cache(user_streaks_cache)
    return default_streak

def load_meal_data_from_csv(diet_type: str = None, meal_type: str = None, max_meals: int = MAX_MEALS_PER_REQUEST) -> List[Dict[str, Any]]:
    """
    Load meal data from CSV file with enhanced security measures and filtering.
    
    Args:
        diet_type: Filter by diet type (optional)
        meal_type: Filter by meal type (optional)
        max_meals: Maximum number of meals to return (security limit)
        
    Returns:
        List of meal dictionaries
    """
    try:
        # Security: Check file size
        csv_path = Path("all_mealplans_merged.csv")
        if not csv_path.exists():
            logger.error("CSV file not found: all_mealplans_merged.csv")
            return get_fallback_meal_data("general")
        
        file_size_mb = csv_path.stat().st_size / (1024 * 1024)
        if file_size_mb > MAX_FILE_SIZE_MB:
            logger.error(f"CSV file too large: {file_size_mb:.2f}MB (max: {MAX_FILE_SIZE_MB}MB)")
            return get_fallback_meal_data("general")
        
        # Security: Validate input parameters
        if diet_type and diet_type.lower() not in ALLOWED_DIET_TYPES:
            logger.warning(f"Invalid diet type: {diet_type}")
            diet_type = None
        
        if meal_type and meal_type.lower() not in ALLOWED_MEAL_TYPES:
            logger.warning(f"Invalid meal type: {meal_type}")
            meal_type = None
        
        if max_meals > MAX_MEALS_PER_REQUEST:
            max_meals = MAX_MEALS_PER_REQUEST
            logger.warning(f"Max meals limited to {MAX_MEALS_PER_REQUEST}")
        
        # Check cache first
        cache_key = f"{diet_type}_{meal_type}_{max_meals}"
        if cache_key in meal_data_cache:
            logger.info(f"Returning cached meal data for key: {cache_key}")
            return meal_data_cache[cache_key]
        
        meals = []
        meals_found = 0
        invalid_rows = 0
        
        try:
            with open(csv_path, 'r', encoding='utf-8') as file:
                reader = csv.DictReader(file)
                
                for row_num, row in enumerate(reader, 1):
                    # Security: Limit number of meals processed
                    if meals_found >= max_meals:
                        break
                    
                    # Memory safety: Limit total rows processed
                    if row_num > 10000:  # Safety limit
                        logger.warning("Reached safety limit of 10,000 rows, stopping processing")
                        break
                    
                    # Security: Validate row data
                    if not validate_csv_row(row):
                        invalid_rows += 1
                        if invalid_rows > 100:  # Stop if too many invalid rows
                            logger.error("Too many invalid rows in CSV, stopping processing")
                            break
                        continue
                    
                    # Apply filters
                    if diet_type and row.get('Diet Type', '').lower() != diet_type.lower():
                        continue
                    
                    if meal_type and row.get('Meal', '').lower() != meal_type.lower():
                        continue
                    
                    # Convert CSV row to standard meal format
                    meal = convert_csv_row_to_meal(row)
                    if meal:
                        meals.append(meal)
                        meals_found += 1
                        
        except UnicodeDecodeError:
            logger.error("CSV file encoding error, trying with different encoding")
            try:
                with open(csv_path, 'r', encoding='latin-1') as file:
                    reader = csv.DictReader(file)
                    # Process with latin-1 encoding
                    for row in reader:
                        if meals_found >= max_meals:
                            break
                        if validate_csv_row(row):
                            meal = convert_csv_row_to_meal(row)
                            if meal:
                                meals.append(meal)
                                meals_found += 1
            except Exception as e:
                logger.error(f"Failed to read CSV with latin-1 encoding: {e}")
        
        # Cache the results
        if len(meals) > 0:
            meal_data_cache[cache_key] = meals
            # Clean cache if too large
            if len(meal_data_cache) > MAX_CACHE_SIZE:
                cleanup_cache(meal_data_cache)
        
        logger.info(f"Loaded {len(meals)} meals from CSV (diet: {diet_type}, meal: {meal_type}, invalid rows: {invalid_rows})")
        return meals if meals else get_fallback_meal_data("general")
        
    except Exception as e:
        logger.error(f"Error loading meal data from CSV: {e}")
        return get_fallback_meal_data("general")

def validate_csv_row(row: Dict[str, str]) -> bool:
    """Validate CSV row data for security and data integrity."""
    try:
        # Check required fields
        required_fields = ['Diet Type', 'Meal', 'Dish Combo', 'Ingredients (per serving)', 'Calories (kcal)']
        for field in required_fields:
            if not row.get(field) or not row[field].strip():
                return False
        
        # Security: Check for suspicious content
        suspicious_patterns = [
            r'<script', r'javascript:', r'data:', r'vbscript:', r'onload=',
            r'<iframe', r'<object', r'<embed', r'<form', r'<input'
        ]
        
        for field, value in row.items():
            if isinstance(value, str):
                for pattern in suspicious_patterns:
                    if re.search(pattern, value, re.IGNORECASE):
                        logger.warning(f"Suspicious content found in CSV: {pattern}")
                        return False
        
        # Validate numeric fields
        try:
            calories = float(row.get('Calories (kcal)', '0'))
            if calories < 0 or calories > 2000:  # Reasonable calorie range
                return False
        except (ValueError, TypeError):
            return False
        
        # Validate string lengths
        for field, value in row.items():
            if isinstance(value, str) and len(value) > 1000:  # Max length per field
                return False
        
        return True
        
    except Exception as e:
        logger.error(f"Error validating CSV row: {e}")
        return False

def convert_csv_row_to_meal(row: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """Convert CSV row to standard meal format."""
    try:
        # Parse ingredients
        ingredients_str = row.get('Ingredients (per serving)', '')
        ingredients = [ing.strip() for ing in ingredients_str.split(',') if ing.strip()]
        
        # Parse calories
        calories = float(row.get('Calories (kcal)', '200'))
        
        # Determine calorie level
        if calories < 200:
            calorie_level = "low"
        elif calories < 500:
            calorie_level = "medium"
        else:
            calorie_level = "high"
        
        # Create meal object
        meal = {
            "Food Item": row.get('Dish Combo', '').strip(),
            "Ingredients": ingredients,
            "approx_calories": calories,
            "Health Impact": row.get('Healthy Tag', 'Good for health'),
            "Calorie Level": calorie_level,
            "Category": row.get('Meal', 'General'),
            "Region": "India",  # Default region
            "SpecialNote": f"Diet: {row.get('Diet Type', 'General')}",
            "Carbs": float(row.get('Carbs (g)', '0')),
            "Protein": float(row.get('Protein (g)', '0')),
            "Fat": float(row.get('Fat (g)', '0'))
        }
        
        return meal
        
    except Exception as e:
        logger.error(f"Error converting CSV row to meal: {e}")
        return None

def load_meal_data_from_json(state: str) -> List[Dict[str, Any]]:
    """Load meal data from JSON file for the given state with fallback."""
    try:
        # Handle the specific filename for Maharashtra - use CSV instead
        if state.lower() == "maharashtra":
            logger.info(f"Redirecting Maharashtra request to CSV-based loading")
            return load_meal_data_from_csv()
        
        # Handle other states with their JSON files
        elif state.lower() == "andhra":
            filename = "andhra_dishes.json"
        elif state.lower() == "karnataka":
            filename = "karnataka.json"
        else:
            filename = f"{state.lower()}.json"
        
        file_path = Path(filename)
        
        if not file_path.exists():
            logger.error(f"File not found: {filename}")
            # Return fallback data
            return get_fallback_meal_data(state)
        
        with open(file_path, 'r', encoding='utf-8') as file:
            data = json.load(file)
            
        meals = []
        
        # Handle Andhra Pradesh dishes format (complex nested structure)
        if state.lower() == "andhra" and isinstance(data, dict) and "DietTypes" in data:
            for diet_type, diet_data in data["DietTypes"].items():
                if isinstance(diet_data, dict):
                    for meal_category, meal_list in diet_data.items():
                        if isinstance(meal_list, list):
                            for meal in meal_list:
                                if isinstance(meal, dict) and "DishName" in meal:
                                    # Convert Andhra format to standard format
                                    converted_meal = {
                                        "Food Item": meal["DishName"],
                                        "Ingredients": meal.get("MainIngredients", []),
                                        "approx_calories": meal.get("Calories", 200),
                                        "Health Impact": meal.get("HealthBenefits", "Good for health"),
                                        "Calorie Level": "medium" if meal.get("Calories", 200) > 200 else "low",
                                        "Category": meal.get("Category", "General"),
                                        "Region": meal.get("Region", "Andhra Pradesh"),
                                        "SpecialNote": meal.get("SpecialNote", "")
                                    }
                                    meals.append(converted_meal)
        
        # Handle existing simple format (Karnataka)
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and "Items" in item:
                    meals.extend(item["Items"])
                elif isinstance(item, dict) and "Food Item" in item:
                    meals.append(item)
        
        # Validate meal data structure
        validated_meals = []
        for meal in meals:
            if validate_meal_structure(meal):
                validated_meals.append(meal)
            else:
                logger.warning(f"Invalid meal structure found: {meal.get('Food Item', 'Unknown')}")
        
        logger.info(f"Loaded {len(validated_meals)} valid meals from JSON for {state} from {filename}")
        return validated_meals if validated_meals else get_fallback_meal_data(state)
        
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error for {state}: {e}")
        return get_fallback_meal_data(state)
    except Exception as e:
        logger.error(f"Error loading meal data for {state}: {e}")
        return get_fallback_meal_data(state)

def validate_meal_structure(meal: Dict[str, Any]) -> bool:
    """Validate meal data structure."""
    required_fields = ["Food Item", "Ingredients", "approx_calories"]
    optional_fields = ["Health Impact", "Calorie Level", "Category", "Region", "SpecialNote"]
    
    # Check required fields
    for field in required_fields:
        if field not in meal:
            return False
    
    # Validate data types
    if not isinstance(meal["Food Item"], str) or len(meal["Food Item"]) < 1:
        return False
    
    if not isinstance(meal["Ingredients"], list) or len(meal["Ingredients"]) < 1:
        return False
    
    if not isinstance(meal["approx_calories"], (int, float)) or meal["approx_calories"] <= 0:
        return False
    
    return True

def get_fallback_meal_data(state: str) -> List[Dict[str, Any]]:
    """Provide fallback meal data when JSON files are unavailable."""
    logger.info(f"Using fallback meal data for {state}")
    
    fallback_meals = [
        {
            "Food Item": "Rice and Dal",
            "Ingredients": ["rice", "lentils", "spices", "onion", "tomato"],
            "approx_calories": 250,
            "Health Impact": "Balanced meal with protein and carbs",
            "Calorie Level": "medium"
        },
        {
            "Food Item": "Vegetable Curry",
            "Ingredients": ["vegetables", "spices", "onion", "tomato", "oil"],
            "approx_calories": 180,
            "Health Impact": "High in fiber and vitamins",
            "Calorie Level": "low"
        },
        {
            "Food Item": "Chapati",
            "Ingredients": ["wheat flour", "water", "salt"],
            "approx_calories": 120,
            "Health Impact": "Whole grain bread, good source of fiber",
            "Calorie Level": "low"
        },
        {
            "Food Item": "Mixed Vegetable Salad",
            "Ingredients": ["cucumber", "tomato", "onion", "lemon", "salt"],
            "approx_calories": 80,
            "Health Impact": "Low calorie, high in vitamins",
            "Calorie Level": "low"
        }
    ]
    
    return fallback_meals

def check_rate_limit(user_id: int) -> bool:
    """Check if user has exceeded rate limit with improved performance."""
    now = datetime.now()
    
    if user_id not in user_rate_limits:
        user_rate_limits[user_id] = {
            'requests': [],
            'last_reset': now
        }
    
    user_limit = user_rate_limits[user_id]
    
    # Reset window if needed
    if (now - user_limit['last_reset']).total_seconds() > RATE_LIMIT_WINDOW:
        user_limit['requests'] = []
        user_limit['last_reset'] = now
    
    # Check current requests with improved performance
    window_start = now - timedelta(seconds=RATE_LIMIT_WINDOW)
    current_requests = [req for req in user_limit['requests'] if req > window_start]
    
    if len(current_requests) >= MAX_REQUESTS_PER_WINDOW:
        return False
    
    # Add current request
    user_limit['requests'].append(now)
    
    # Clean up old requests to prevent memory buildup
    if len(user_limit['requests']) > MAX_REQUESTS_PER_WINDOW * 2:
        user_limit['requests'] = current_requests
    
    return True

def filter_meals_by_preferences(meals: List[Dict[str, Any]], diet_type: str, medical_condition: str) -> List[Dict[str, Any]]:
    """Filter meals based on user preferences with improved diet type handling."""
    filtered_meals = []
    
    # Normalize diet type for consistent handling
    diet_type_lower = diet_type.lower()
    if diet_type_lower in ['veg', 'vegetarian']:
        diet_type_lower = 'vegetarian'
    elif diet_type_lower in ['non-veg', 'non-vegetarian']:
        diet_type_lower = 'non-vegetarian'
    
    for meal in meals:
        if not isinstance(meal, dict) or "Food Item" not in meal:
            continue
            
        # Check diet compatibility
        if diet_type_lower == "jain":
            # Check for onion, garlic, potato, eggs, meat, fish in ingredients
            if any(item in str(meal.get("Ingredients", [])).lower() for item in ["onion", "garlic", "potato", "egg", "chicken", "fish", "meat", "prawn"]):
                continue
            # Also check SpecialNote for Andhra Pradesh dishes
            if meal.get("SpecialNote", "").lower() == "no onion, garlic":
                continue
        elif diet_type_lower == "vegan":
            # Check for non-vegan ingredients
            if any(item in str(meal.get("Ingredients", [])).lower() for item in ["milk", "ghee", "curd", "egg", "meat", "fish", "chicken"]):
                continue
            # Also check SpecialNote for Andhra Pradesh dishes
            if meal.get("SpecialNote", "").lower() == "vegan":
                continue
        elif diet_type_lower == "non-vegetarian":
            # For non-vegetarian, prefer meals with meat/fish
            if any(item in str(meal.get("Ingredients", [])).lower() for item in ["chicken", "fish", "meat", "prawn", "egg"]):
                filtered_meals.append(meal)
                continue
        elif diet_type_lower == "vegetarian":
            # For vegetarian, avoid meat/fish/eggs
            if any(item in str(meal.get("Ingredients", [])).lower() for item in ["chicken", "fish", "meat", "prawn", "egg"]):
                continue
        elif diet_type_lower == "eggitarian":
            # For eggitarian, allow eggs but avoid meat/fish
            if any(item in str(meal.get("Ingredients", [])).lower() for item in ["chicken", "fish", "meat", "prawn"]):
                continue
            # Prefer meals with eggs
            if "egg" in str(meal.get("Ingredients", [])).lower():
                filtered_meals.append(meal)
                continue
        elif diet_type_lower == "keto":
            # For keto, prefer low-carb, high-fat meals
            if meal.get("Carbs", 0) > 20:  # High carb meals
                continue
            # Prefer meals with healthy fats
            if meal.get("Fat", 0) > 10:
                filtered_meals.append(meal)
                continue
        elif diet_type_lower == "mixed":
            # Mixed diet accepts all meals
            pass
            
        # Check medical condition compatibility
        if medical_condition.lower() == "diabetes":
            if meal.get("Calorie Level", "").lower() in ["high", "very high"]:
                continue
            # Also check calories directly
            if meal.get("approx_calories", 0) > 300:
                continue
        elif medical_condition.lower() == "thyroid":
            # Prefer meals with good iodine content
            if "coconut" in str(meal.get("Ingredients", [])).lower():
                continue
                
        filtered_meals.append(meal)
    
    return filtered_meals

def generate_weekly_plan(meals: List[Dict[str, Any]], user_profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Generate a 7-day meal plan."""
    if len(meals) < 7:
        # Repeat meals if not enough variety
        meals = meals * (7 // len(meals) + 1)
    
    weekly_plan = []
    for day in range(7):
        day_meals = random.sample(meals, min(4, len(meals)))  # 4 meals per day
        weekly_plan.append({
            "day": day + 1,
            "breakfast": day_meals[0] if len(day_meals) > 0 else None,
            "lunch": day_meals[1] if len(day_meals) > 1 else None,
            "dinner": day_meals[2] if len(day_meals) > 2 else None,
            "snack": day_meals[3] if len(day_meals) > 3 else None
        })
    
    return weekly_plan

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the conversation and ask for name."""
    if not update.effective_user or not update.message:
        return ConversationHandler.END
        
    user_id = update.effective_user.id
    
    # Check if user already has a profile
    existing_profile = await get_user_profile(user_id)
    if existing_profile:
        # User has profile, show main menu
        keyboard = [
            [InlineKeyboardButton("🍽️ Get Daily Meal Plan", callback_data="get_meal_plan")],
            [InlineKeyboardButton("🥘 Suggest from Ingredients", callback_data="ingredient_meal")],
            [InlineKeyboardButton("📝 Log Today's Meals", callback_data="log_meal")],
            [InlineKeyboardButton("📅 Weekly Meal Plan", callback_data="week_plan")],
            [InlineKeyboardButton("🛒 Grocery List", callback_data="grocery_list")],
            [InlineKeyboardButton("👤 View Profile", callback_data="view_profile")],
            [InlineKeyboardButton("🔄 Update Profile", callback_data="update_profile")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Get streak data for welcome message
        streak_data = await get_user_streak(user_id)
        
        await update.message.reply_text(
            f"🍎 Yo! Welcome back to Nutrio! 👋\n\n"
            f"👤 Name: {existing_profile.get('name', 'Not set')}\n"
            f"🏛️ State: {existing_profile.get('state', 'Not set')}\n"
            f"🥬 Diet: {existing_profile.get('diet', 'Not set')}\n"
            f"🔥 Streak: {streak_data['streak_count']} days | 🎯 Points: {streak_data['streak_points_total']}\n\n"
            f"What's the move today? Let's get you some good eats! 😋",
            reply_markup=reply_markup
        )
        return MEAL_PLAN
    
    # Initialize user data for new user
    user_data_cache[user_id] = {}
    cleanup_cache(user_data_cache)
    
    keyboard = [
        [InlineKeyboardButton("✅ Start Profile Creation", callback_data="start_profile")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🍎 Hey there! Welcome to Nutrio - your personal nutrition wingman! 👋\n\n"
        "I'm here to hook you up with some fire meal plans that actually taste good and keep you healthy.\n\n"
        "Let's get your profile set up so I can suggest the perfect meals for your vibe! 🔥",
        reply_markup=reply_markup
    )
    
    return NAME

async def start_profile_creation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start profile creation flow."""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "👤 **Step 1/7 - Let's get to know you!**\n\n"
        "Drop your full name below 👇",
        parse_mode='Markdown'
    )
    
    return NAME

async def handle_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle name input and ask for age."""
    if not update.effective_user or not update.message:
        return ConversationHandler.END
        
    user_id = update.effective_user.id
    name = update.message.text.strip()
    
    # Enhanced input validation using new validation function
    if not validate_name(name):
        await update.message.reply_text("❌ Please enter a valid name (2-50 characters, letters, numbers, spaces, dots, hyphens, apostrophes only)! 😅")
        return NAME
    
    # Get existing user data or create new
    user_data = user_data_cache.get(user_id, {})
    user_data["name"] = name
    
    # Save to cache immediately
    user_data_cache[user_id] = user_data
    cleanup_cache(user_data_cache)
    
    await update.message.reply_text(
        f"✅ Got it! {name} it is! ✨\n\n"
        "👤 **Step 2/7 - Age check**\n\n"
        "How old are you? Drop your exact age below 👇\n\n"
        "*Just type a number like 25, 32, 45, etc.*",
        parse_mode='Markdown'
    )
    
    return AGE

async def handle_age(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle age input and ask for gender."""
    if not update.effective_user or not update.message:
        return ConversationHandler.END
        
    user_id = update.effective_user.id
    age_text = update.message.text.strip()
    
    # Enhanced age validation using new validation function
    age = validate_age(age_text)
    if age is None:
        await update.message.reply_text("❌ Please enter a valid age between 1-120! 😅")
        return AGE
    
    # Get existing user data or create new
    user_data = user_data_cache.get(user_id, {})
    user_data["age"] = age
    
    # Save to cache immediately
    user_data_cache[user_id] = user_data
    cleanup_cache(user_data_cache)
    
    keyboard = [
        [InlineKeyboardButton("👨 Male", callback_data="gender_male")],
        [InlineKeyboardButton("👩 Female", callback_data="gender_female")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"✅ Sweet! {age} years old! 🎉\n\n"
        "👤 **Step 3/7 - Gender**\n\n"
        "What's your gender? Choose below 👇",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    return GENDER

async def handle_custom_medical(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle custom medical condition input."""
    if not update.effective_user or not update.message:
        return ConversationHandler.END
        
    user_id = update.effective_user.id
    medical_condition = update.message.text.strip()
    
    # Enhanced medical condition validation
    if not medical_condition or len(medical_condition) < 3:
        await update.message.reply_text("❌ Please give me a bit more detail about your health condition! 😅")
        return MEDICAL_CONDITION
    
    if len(medical_condition) > 200:
        await update.message.reply_text("❌ That's too long! Please keep it under 200 characters! 😅")
        return MEDICAL_CONDITION
    
    # Sanitize input using new function
    sanitized_medical = sanitize_input(medical_condition, 200)
    if len(sanitized_medical) < 3:
        await update.message.reply_text("❌ Please enter a valid health condition description! 😅")
        return MEDICAL_CONDITION
    
    # Get existing user data or create new
    user_data = user_data_cache.get(user_id, {})
    user_data["medical"] = sanitized_medical
    
    # Save to cache immediately
    user_data_cache[user_id] = user_data
    cleanup_cache(user_data_cache)
    
    keyboard = [
        [InlineKeyboardButton("🛋️ Sedentary (Office work, minimal exercise)", callback_data="activity_sedentary")],
        [InlineKeyboardButton("🏃 Active (Regular exercise, physical work)", callback_data="activity_active")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"✅ Got it! {medical_condition} - noted! 📝\n\n"
        "👤 **Step 7/7 - Energy levels**\n\n"
        "How active are you? Be real with me! 💪",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    return ACTIVITY_LEVEL

async def gender_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle gender selection and ask for state."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    gender = query.data.split("_")[1]
    
    # Get existing user data or create new
    user_data = user_data_cache.get(user_id, {})
    user_data["gender"] = gender
    
    # Save to cache immediately
    user_data_cache[user_id] = user_data
    cleanup_cache(user_data_cache)
    
    keyboard = [
        [InlineKeyboardButton("🏛️ Maharashtra", callback_data="state_maharashtra")],
        [InlineKeyboardButton("🏛️ Karnataka", callback_data="state_karnataka")],
        [InlineKeyboardButton("🌶️ Andhra Pradesh", callback_data="state_andhra")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"✅ Got it! {gender.title()} it is! 💪\n\n"
        "👤 **Step 4/7 - Location**\n\n"
        "Where you at? Pick your state 👇",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    return STATE

async def state_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle state selection and ask for diet type."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    state = query.data.split("_")[1]
    
    # Get existing user data or create new
    user_data = user_data_cache.get(user_id, {})
    user_data["state"] = state
    
    # Save to cache immediately
    user_data_cache[user_id] = user_data
    cleanup_cache(user_data_cache)
    
    keyboard = [
        [InlineKeyboardButton("🥬 Vegetarian", callback_data="diet_veg")],
        [InlineKeyboardButton("🥚 Eggitarian", callback_data="diet_eggitarian")],
        [InlineKeyboardButton("🍗 Non-Vegetarian", callback_data="diet_non-veg")],
        [InlineKeyboardButton("🕉️ Jain", callback_data="diet_jain")],
        [InlineKeyboardButton("🌱 Vegan", callback_data="diet_vegan")],
        [InlineKeyboardButton("🥑 Keto", callback_data="diet_keto")],
        [InlineKeyboardButton("🍽️ Mixed (Everything)", callback_data="diet_mixed")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"✅ Nice! {state.title()} represent! 🌟\n\n"
        "👤 **Step 5/7 - Food vibes**\n\n"
        "What's your eating style? Pick your vibe 👇",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    return DIET_TYPE

async def diet_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle diet selection and ask for medical condition."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    diet = query.data.split("_")[1]
    
    # Get existing user data or create new
    user_data = user_data_cache.get(user_id, {})
    user_data["diet"] = diet
    
    # Save to cache immediately
    user_data_cache[user_id] = user_data
    cleanup_cache(user_data_cache)
    
    keyboard = [
        [InlineKeyboardButton("🩸 Diabetes", callback_data="medical_diabetes")],
        [InlineKeyboardButton("🦋 Thyroid", callback_data="medical_thyroid")],
        [InlineKeyboardButton("🏥 Other", callback_data="medical_other")],
        [InlineKeyboardButton("✅ None", callback_data="medical_none")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"✅ {diet.title()} gang! Love that for you! 🥗\n\n"
        "👤 **Step 6/7 - Health check**\n\n"
        "Any health stuff I should know about? Be honest! 👇",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    return MEDICAL_CONDITION

async def medical_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle medical condition selection and ask for activity level."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    medical = query.data.split("_")[1]
    
    if medical == "other":
        # Ask user to specify their medical condition
        await query.edit_message_text(
            "🏥 **Tell me about your health condition**\n\n"
            "What medical condition or treatment are you dealing with?\n\n"
            "*Be specific so I can suggest the best meals for you!*",
            parse_mode='Markdown'
        )
        return MEDICAL_CONDITION
    
    # Get existing user data or create new
    user_data = user_data_cache.get(user_id, {})
    user_data["medical"] = medical
    
    # Save to cache immediately
    user_data_cache[user_id] = user_data
    cleanup_cache(user_data_cache)
    
    keyboard = [
        [InlineKeyboardButton("🛋️ Sedentary (Office work, minimal exercise)", callback_data="activity_sedentary")],
        [InlineKeyboardButton("🏃 Active (Regular exercise, physical work)", callback_data="activity_active")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"✅ Got it! {medical.title()} - noted! 📝\n\n"
        "👤 **Step 7/7 - Energy levels**\n\n"
        "How active are you? Be real with me! 💪",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    return ACTIVITY_LEVEL

async def activity_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle activity level selection and complete profile."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    activity = query.data.split("_")[1]
    
    # Get existing user data or create new
    user_data = user_data_cache.get(user_id, {})
    user_data["activity"] = activity
    
    # Save to cache immediately
    user_data_cache[user_id] = user_data
    cleanup_cache(user_data_cache)
    
    # Save profile to Firebase
    profile_saved = await save_user_profile(user_id, user_data)
    
    # Update streak for completing Quick-Comm
    streak_data = await update_user_streak(user_id)
    
    # Display completion message with streak info
    completion_message = (
        f"🎉 **Profile Complete! You're all set!**\n\n"
        f"👤 **Name:** {user_data.get('name', 'Not set')}\n"
        f"👤 **Age:** {user_data.get('age', 'Not set')}\n"
        f"👤 **Gender:** {user_data['gender'].title()}\n"
        f"🏛️ **State:** {user_data['state'].title()}\n"
        f"🥬 **Diet:** {user_data['diet'].title()}\n"
        f"🏥 **Medical:** {user_data['medical'].title()}\n"
        f"🏃 **Activity:** {user_data['activity'].title()}\n\n"
        f"🔥 **Streak:** {streak_data['streak_count']} days\n"
        f"🎯 **Streak Points:** {streak_data['streak_points_total']}\n\n"
        f"{'✅ Profile saved to database' if profile_saved else '⚠️ Profile saved to cache only (Firebase not available)'}\n\n"
        f"Your profile is now ready! 🎯"
    )
    
    keyboard = [
        [InlineKeyboardButton("🍽️ Get AI Meal Plan", callback_data="get_meal_plan")],
        [InlineKeyboardButton("🥘 Suggest from Ingredients", callback_data="ingredient_meal")],
        [InlineKeyboardButton("👤 View Profile", callback_data="view_profile")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        completion_message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    # Profile completion - no automatic AI generation, wait for user instruction
    
    return PROFILE

async def handle_ingredient_meal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle ingredient-based meal plan request."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    logger.info(f"🔧 Ingredient meal requested by user {user_id}")
    
    # Get user profile
    user_data = user_data_cache.get(user_id)
    if not user_data:
        user_data = await get_user_profile(user_id)
        if not user_data:
            await query.edit_message_text(
                "❌ No profile found. Please create your profile first.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🏠 Start Over", callback_data="start_over")
                ]])
            )
            return ConversationHandler.END
    
    # Store user data in context for later use
    context.user_data['ingredient_user_data'] = user_data
    
    # Ask user for meal type first
    keyboard = [
        [InlineKeyboardButton("🌅 Breakfast", callback_data="meal_type_breakfast")],
        [InlineKeyboardButton("☀️ Lunch", callback_data="meal_type_lunch")],
        [InlineKeyboardButton("🌙 Dinner", callback_data="meal_type_dinner")],
        [InlineKeyboardButton("🍎 Snack", callback_data="meal_type_snack")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"🥘 Ingredient-Based Meal Suggestions\n\n"
        f"Hey {user_data.get('name', 'there')}! Let me suggest meals based on what you have.\n\n"
        f"First, what type of meal would you like to make?\n\n"
        f"Choose your meal type:",
        reply_markup=reply_markup
    )
    
    logger.info(f"✅ Meal type selection prompt sent to user {user_id}, returning MEAL_TYPE state")
    return MEAL_TYPE

async def handle_meal_type_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle meal type selection and ask for ingredients."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    meal_type = query.data.split("_")[2]  # meal_type_breakfast -> breakfast
    
    # Store meal type in context
    context.user_data['selected_meal_type'] = meal_type
    
    # Get user data from context
    user_data = context.user_data.get('ingredient_user_data')
    
    logger.info(f"🔧 Meal type selected by user {user_id}: {meal_type}")
    
    # Ask user for ingredients
    await query.edit_message_text(
        f"🥘 {meal_type.title()} with Your Ingredients\n\n"
        f"Hey {user_data.get('name', 'there')}! Let me suggest a {meal_type} using what you have.\n\n"
        f"Please list your available ingredients (separated by commas):\n\n"
        f"Example: rice, dal, tomatoes, onions, potatoes, eggs, milk\n\n"
        f"I'll create a healthy {meal_type} using only these ingredients!",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Go Back", callback_data="go_back")
        ]])
    )
    
    logger.info(f"✅ Ingredient prompt sent to user {user_id}, returning INGREDIENTS state")
    return INGREDIENTS

async def handle_ingredients_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle user's ingredient input and generate meal plan."""
    user_id = update.message.from_user.id
    ingredients = update.message.text.strip()
    logger.info(f"🔧 Ingredients input received from user {user_id}: {ingredients}")
    
    # Get user profile from context (set during meal type selection)
    user_data = context.user_data.get('ingredient_user_data')
    meal_type = context.user_data.get('selected_meal_type', 'meal')
    
    if not user_data:
        # Fallback to cache if not in context
        user_data = user_data_cache.get(user_id)
        if not user_data:
            user_data = await get_user_profile(user_id)
            if not user_data:
                await update.message.reply_text(
                    "❌ No profile found. Please create your profile first.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🏠 Start Over", callback_data="start_over")
                    ]])
                )
                return ConversationHandler.END
    
    # Show loading message
    loading_message = await update.message.reply_text(
        f"🤖 AI is crafting your {meal_type} using your ingredients...\n\n"
        f"Using ingredients: {ingredients}\n"
        "This will take a few seconds. Please wait! ⏳"
        )

    try:
        # Import the ingredient-based meal generation function
        from ai_meal_generator import generate_ingredient_based_meal_plan

        # Generate ingredient-based meal plan with specific meal type
        ai_meal_plan = await generate_ingredient_based_meal_plan(user_data, ingredients, user_id, db, meal_type)
        
        if ai_meal_plan:
            # Create action buttons for AI meal plan
            keyboard = [
                [InlineKeyboardButton("👍 Like", callback_data="rate_like_ai_generated")],
                [InlineKeyboardButton("👎 Dislike", callback_data="rate_dislike_ai_generated")],
                [InlineKeyboardButton("📝 Log Today's Meals", callback_data="log_meal")],
                [InlineKeyboardButton("🛒 Grocery List", callback_data="grocery_list")],
                [InlineKeyboardButton("🚚 Order on Zepto", callback_data="order_zepto")],
                [InlineKeyboardButton("🥘 New Ingredient Plan", callback_data="ingredient_meal")],
                [InlineKeyboardButton("⬅️ Go Back", callback_data="go_back")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await loading_message.edit_text(
                ai_meal_plan,
                reply_markup=reply_markup
            )
            logger.info(f"✅ Ingredient-based AI meal plan sent to user {user_id}")
        else:
            # AI failed, show fallback message
            await loading_message.edit_text(
                f"❌ Sorry, I couldn't generate a meal plan with those ingredients.\n\n"
                f"**Try:**\n"
                f"- Adding more ingredients\n"
                f"- Using common ingredients like rice, dal, vegetables\n"
                f"- Or use our regular meal plan feature",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🥘 Try Again", callback_data="ingredient_meal")],
                    [InlineKeyboardButton("🍽️ Regular Meal Plan", callback_data="get_meal_plan")],
                    [InlineKeyboardButton("⬅️ Go Back", callback_data="go_back")]
                ])
            )
            logger.warning(f"⚠️ Ingredient-based AI meal plan failed for user {user_id}")
            
    except Exception as e:
        logger.error(f"❌ Error in ingredient-based meal generation: {e}")
        await loading_message.edit_text(
            "❌ Sorry, there was an error generating your meal plan.\n\n"
            "Please try again or use our regular meal plan feature.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🥘 Try Again", callback_data="ingredient_meal")],
                [InlineKeyboardButton("🍽️ Regular Meal Plan", callback_data="get_meal_plan")],
                [InlineKeyboardButton("⬅️ Go Back", callback_data="go_back")]
            ])
        )
    
    return MEAL_PLAN

async def get_meal_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Generate and display personalized meal plan using AI or JSON fallback."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    # Check rate limit
    if not check_rate_limit(user_id):
        await query.edit_message_text(
            "⚠️ **Rate Limit Exceeded**\n\n"
            "You're making too many requests! Please wait a minute and try again. 😅\n\n"
            "*This helps keep the bot running smoothly for everyone!*",
            parse_mode='Markdown'
        )
        return MEAL_PLAN
    
    # Get user profile (from cache or Firebase)
    user_data = user_data_cache.get(user_id)
    if not user_data:
        user_data = await get_user_profile(user_id)
        if not user_data:
            await query.edit_message_text(
                "❌ No profile found. Please create your profile first.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🏠 Start Over", callback_data="start_over")
                ]])
            )
            return ConversationHandler.END
    
    # Update streak for completing Quick-Comm (getting meal plan)
    streak_data = await update_user_streak(user_id)
    
    # Check if this is a new completion today (points were earned)
    today = datetime.now().date()
    points_earned = 0
    if streak_data.get('last_completed_date') == today:
        # Calculate points that would be earned for this streak
        points_earned = calculate_streak_points(streak_data['streak_count'])
    
    # 🍽️ PRIMARY: Generate meal plan based on user's state
    try:
        # Show loading message
        await query.edit_message_text(
            "**Generating your meal plan...**\n\n"
            "Please wait a moment.",
            parse_mode='Markdown'
        )
        
        # Determine data source based on user's state
        user_state = user_data.get('state', '').lower()
        
        if user_state == 'maharashtra':
            # 🔥 MAHARASHTRA: Use CSV data ONLY (no fallback)
            logger.info(f"User {user_id} from Maharashtra - using CSV data only")
            
            # Load meals from CSV based on user's diet
            user_diet = user_data.get('diet_type', user_data.get('diet', 'vegetarian')).lower()
            
            # Normalize diet type for CSV matching
            diet_mapping = {
                'veg': 'Vegetarian',
                'vegetarian': 'Vegetarian',
                'non-veg': 'Non-Vegetarian',
                'non-vegetarian': 'Non-Vegetarian',
                'vegan': 'Vegan',
                'jain': 'Jain',
                'eggitarian': 'Eggitarian',
                'keto': 'Keto',
                'mixed': 'Mixed'
            }
            csv_diet_type = diet_mapping.get(user_diet, 'Vegetarian')
            
            meals = load_meal_data_from_csv(diet_type=csv_diet_type, max_meals=30)
            
            if not meals:
                await query.edit_message_text(
                    f"❌ No meal data available for {user_data['diet'].title()} diet in Maharashtra.\n\n"
                    "Please try again later or contact support.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔄 Try Again", callback_data="get_meal_plan")
                    ]])
                )
                return ConversationHandler.END
            
            # Filter meals by meal type to ensure we get one of each
            meal_categories = {
                'Breakfast': [],
                'Lunch': [],
                'Dinner': [],
                'Evening Snack': [],
                'Morning Snack': []
            }
            
            # Categorize meals by their meal type
            for meal in meals:
                meal_type = meal.get('Category', meal.get('Meal', '')).strip()
                if meal_type in meal_categories:
                    meal_categories[meal_type].append(meal)
                elif 'breakfast' in meal_type.lower():
                    meal_categories['Breakfast'].append(meal)
                elif 'lunch' in meal_type.lower():
                    meal_categories['Lunch'].append(meal)
                elif 'dinner' in meal_type.lower():
                    meal_categories['Dinner'].append(meal)
                elif 'snack' in meal_type.lower():
                    if 'morning' in meal_type.lower():
                        meal_categories['Morning Snack'].append(meal)
                    else:
                        meal_categories['Evening Snack'].append(meal)
            
            # Select one meal from each category
            selected_meals = []
            meal_types_order = ['Breakfast', 'Lunch', 'Dinner', 'Evening Snack']
            
            for meal_type in meal_types_order:
                available_meals = meal_categories.get(meal_type, [])
                if available_meals:
                    # Randomly select one meal from this category
                    selected_meal = random.choice(available_meals)
                    selected_meals.append(selected_meal)
                else:
                    # If no meals in this category, try to find a similar one
                    if meal_type == 'Evening Snack' and meal_categories.get('Morning Snack'):
                        selected_meal = random.choice(meal_categories['Morning Snack'])
                        selected_meals.append(selected_meal)
                    elif len(meals) > len(selected_meals):
                        # Fallback: pick any remaining meal
                        remaining_meals = [m for m in meals if m not in selected_meals]
                        if remaining_meals:
                            selected_meals.append(random.choice(remaining_meals))
            
            # If we still don't have 4 meals, add more from any category
            while len(selected_meals) < 4 and len(meals) > len(selected_meals):
                remaining_meals = [m for m in meals if m not in selected_meals]
                if remaining_meals:
                    selected_meals.append(random.choice(remaining_meals))
                else:
                    break
            
            # Calculate total calories
            total_calories = sum(meal.get('approx_calories', 200) for meal in selected_meals)
            
            # Format meal plan message with clean, readable layout
            meal_message = f"**Daily Meal Plan**\n\n"
            meal_message += f"**Profile:** {user_data.get('name', 'Your')}\n"
            meal_message += f"**Region:** {user_data['state'].title()}\n"
            meal_message += f"**Diet:** {user_data['diet'].title()}\n"
            meal_message += f"**Medical:** {user_data['medical'].title()}\n"
            meal_message += f"**Activity:** {user_data['activity'].title()}\n"
            meal_message += f"**Streak:** {streak_data['streak_count']} days | **Points:** {streak_data['streak_points_total']}"
            if points_earned > 0:
                meal_message += f" (+{points_earned} today)"
            meal_message += "\n\n"
            meal_message += "─" * 40 + "\n\n"
            
            meal_types = ["Breakfast", "Lunch", "Dinner", "Snack"]
            meal_names = []
            
            for i, meal in enumerate(selected_meals):
                meal_type = meal_types[i] if i < len(meal_types) else "Meal"
                meal_name = meal.get('Dish Combo', meal.get('Food Item', 'Unknown'))
                calories = meal.get('approx_calories', 200)
                health_impact = meal.get('Health Impact', '')
                ingredients = meal.get('Ingredients', [])
                calorie_level = meal.get('Calorie Level', '')
                
                meal_message += f"**{meal_type}**\n"
                meal_message += f"{meal_name}\n"
                meal_message += f"Calories: {calories}\n"
                if calorie_level:
                    meal_message += f"Level: {calorie_level.title()}\n"
                if ingredients:
                    ingredients_text = ", ".join(ingredients)
                    meal_message += f"Ingredients: {ingredients_text}\n"
                if health_impact:
                    meal_message += f"Health: {health_impact}\n"
                meal_message += "\n"
                
                # Store meal name for rating
                meal_names.append({'name': meal_name})
            
            meal_message += "─" * 40 + "\n"
            meal_message += f"**Total Calories:** {total_calories}\n\n"
            meal_message += "*Meals personalized for your health needs*"
            
            # Create action buttons with ratings for the first meal
            first_meal_name = meal_names[0].get('name', '') if meal_names else 'Meal Plan'
            
            # Clean meal name for callback data (remove special characters)
            clean_meal_name = re.sub(r'[^\w\s-]', '', first_meal_name).strip()
            if not clean_meal_name:
                clean_meal_name = "Meal_Plan"
            
            keyboard = [
                [
                    InlineKeyboardButton("👍 Like", callback_data=f"rate_like_{clean_meal_name}"),
                    InlineKeyboardButton("👎 Dislike", callback_data=f"rate_dislike_{clean_meal_name}")
                ],
                [InlineKeyboardButton("Log Today's Meals", callback_data="log_meal")],
                [
                    InlineKeyboardButton("Grocery List", callback_data="grocery_list"),
                    InlineKeyboardButton("Order on Zepto", callback_data="order_zepto")
                ],
                [
                    InlineKeyboardButton("New Plan", callback_data="get_meal_plan"),
                    InlineKeyboardButton("Go Back", callback_data="go_back")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Cache the suggested meals for logging
            context.user_data["last_suggested_meals"] = meal_names
            
            await query.edit_message_text(
                meal_message,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            logger.info(f"✅ CSV meal plan sent to user {user_id} from Maharashtra")
            return MEAL_PLAN
            
        else:
            # 🔄 OTHER STATES: Use AI meal generation (JSON fallback)
            if MEAL_GENERATOR_AVAILABLE:
                # Generate AI meal plan (using JSON data)
                ai_meal_plan = await generate_ai_meal_plan(user_data, user_id, db)
                logger.info(f"AI meal plan generated for user {user_id}: {len(ai_meal_plan) if ai_meal_plan else 0} characters")
                
                if ai_meal_plan and ai_meal_plan.strip():
                    # Create action buttons for AI meal plan with actual meal names
                    # Get the first meal name for rating
                    first_meal_name = "AI Generated Meal Plan"
                    if meal_names and len(meal_names) > 0:
                        first_meal_name = meal_names[0].get('name', 'AI Generated Meal Plan')
                    
                    # Clean meal name for callback data (remove special characters)
                    clean_meal_name = re.sub(r'[^\w\s-]', '', first_meal_name).strip()
                    if not clean_meal_name:
                        clean_meal_name = "AI_Generated_Meal"
                    
                    keyboard = [
                        [
                            InlineKeyboardButton("👍 Like", callback_data=f"rate_like_{clean_meal_name}"),
                            InlineKeyboardButton("👎 Dislike", callback_data=f"rate_dislike_{clean_meal_name}")
                        ],
                        [InlineKeyboardButton("Log Today's Meals", callback_data="log_meal")],
                        [
                            InlineKeyboardButton("Grocery List", callback_data="grocery_list"),
                            InlineKeyboardButton("Order on Zepto", callback_data="order_zepto")
                        ],
                        [
                            InlineKeyboardButton("New Plan", callback_data="get_meal_plan"),
                            InlineKeyboardButton("Go Back", callback_data="go_back")
                        ]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    # Cache the suggested meals for logging
                    # Enhanced meal extraction for AI responses
                    meal_names = []
                    
                    # Extract meal names using improved regex patterns
                    meal_patterns = [
                        r'🌅\s*(.*?)\s*-\s*\d+',  # Breakfast pattern
                        r'☀️\s*(.*?)\s*-\s*\d+',  # Lunch pattern  
                        r'🌙\s*(.*?)\s*-\s*\d+',  # Dinner pattern
                        r'🍎\s*(.*?)\s*-\s*\d+',  # Snack pattern
                        r'🌅\s*(.*?)(?:\n|$)',    # Breakfast without calories
                        r'☀️\s*(.*?)(?:\n|$)',    # Lunch without calories
                        r'🌙\s*(.*?)(?:\n|$)',    # Dinner without calories
                        r'🍎\s*(.*?)(?:\n|$)',    # Snack without calories
                    ]
                    
                    for pattern in meal_patterns:
                        matches = re.findall(pattern, ai_meal_plan, re.MULTILINE)
                        for match in matches:
                            meal_name = match.strip()
                            if meal_name and len(meal_name) > 2 and len(meal_name) < 50:
                                # Clean meal name
                                meal_name = re.sub(r'[^\w\s\-]', '', meal_name).strip()
                                if meal_name:
                                    meal_names.append({'name': meal_name})
                    
                    # If regex extraction fails, use enhanced line parsing
                    if not meal_names:
                        lines = ai_meal_plan.split('\n')
                        for line in lines:
                            line = line.strip()
                            if any(emoji in line for emoji in ['🌅', '☀️', '🌙', '🍎']):
                                # Remove emoji and extract meal name
                                for emoji in ['🌅', '☀️', '🌙', '🍎']:
                                    if emoji in line:
                                        # Extract text after emoji, before any dash or newline
                                        parts = line.split(emoji, 1)
                                        if len(parts) > 1:
                                            meal_text = parts[1].strip()
                                            # Remove calories and other info
                                            if ' - ' in meal_text:
                                                meal_name = meal_text.split(' - ')[0].strip()
                                            else:
                                                meal_name = meal_text.split()[0] if meal_text.split() else ''
                                            
                                            # Clean and validate meal name
                                            if meal_name and len(meal_name) > 2 and len(meal_name) < 50:
                                                meal_name = re.sub(r'[^\w\s\-]', '', meal_name).strip()
                                                if meal_name:
                                                    meal_names.append({'name': meal_name})
                                        break
                    
                    # Final fallback: create default meal names
                    if not meal_names:
                        meal_names = [
                            {'name': 'Breakfast'},
                            {'name': 'Lunch'},
                            {'name': 'Dinner'},
                            {'name': 'Snack'}
                        ]
                    
                    context.user_data["last_suggested_meals"] = meal_names
                    
                    await query.edit_message_text(
                        ai_meal_plan,
                        reply_markup=reply_markup
                    )
                    logger.info(f"✅ AI meal plan sent to user {user_id}")
                    return MEAL_PLAN
                else:
                    logger.warning(f"⚠️ AI meal plan failed for user {user_id}")
                    
            # If AI fails or not available, show error for non-Maharashtra states
            await query.edit_message_text(
                f"❌ Unable to generate meal plan for {user_data['state'].title()}.\n\n"
                "Please try again later or contact support.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔄 Try Again", callback_data="get_meal_plan")
                ]])
            )
            return ConversationHandler.END
            return ConversationHandler.END
            
    except Exception as e:
        logger.error(f"❌ Error in meal generation: {e}")
        await query.edit_message_text(
            "❌ **Error generating meal plan**\n\n"
            "Something went wrong. Please try again later.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 Try Again", callback_data="get_meal_plan")
            ]])
        )
        return ConversationHandler.END

async def handle_weekly_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle weekly meal plan request."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    # Get user profile
    user_data = user_data_cache.get(user_id)
    if not user_data:
        user_data = await get_user_profile(user_id)
        if not user_data:
            await query.edit_message_text(
                "❌ No profile found. Please create your profile first.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🏠 Start Over", callback_data="start_over")
                ]])
            )
            return ConversationHandler.END
    
    # Load and filter meals from CSV
    user_diet = user_data.get('diet_type', user_data.get('diet', 'vegetarian')).lower()
    meals = load_meal_data_from_csv(diet_type=user_diet, max_meals=50)
    if not meals:
        await query.edit_message_text(
            f"❌ No meal data available for {user_data['diet'].title()} diet.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Start Over", callback_data="start_over")
            ]])
        )
        return ConversationHandler.END
    
    # Filter meals based on preferences
    if user_data.get('medical'):
        filtered_meals = filter_meals_by_preferences(meals, user_diet, user_data['medical'])
    else:
        filtered_meals = meals[:20]  # Take first 20 meals if no medical conditions
    
    # Generate weekly plan
    weekly_plan = generate_weekly_plan(filtered_meals, user_data)
    
    # Store weekly plan in context for navigation
    context.user_data['weekly_plan'] = weekly_plan
    context.user_data['current_day'] = 0
    
    # Show first day
    return await show_weekly_day(update, context)

async def show_weekly_day(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show a specific day of the weekly plan."""
    query = update.callback_query
    await query.answer()
    
    weekly_plan = context.user_data.get('weekly_plan', [])
    current_day = context.user_data.get('current_day', 0)
    
    if not weekly_plan or current_day >= len(weekly_plan):
        await query.edit_message_text(
            "❌ Weekly plan not available.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Start Over", callback_data="start_over")
            ]])
        )
        return ConversationHandler.END
    
    day_data = weekly_plan[current_day]
    
    # Format day message
    day_message = f"📅 **Week {current_day + 1} - Day {day_data['day']}**\n\n"
    
    meal_types = [
        ("🌅 Breakfast", day_data.get('breakfast')),
        ("🌞 Lunch", day_data.get('lunch')),
        ("🌙 Dinner", day_data.get('dinner')),
        ("🍎 Snack", day_data.get('snack'))
    ]
    
    for meal_type, meal in meal_types:
        if meal:
            meal_name = meal.get('Food Item', 'Unknown')
            calories = meal.get('approx_calories', 200)
            health_impact = meal.get('Health Impact', '')
            ingredients = meal.get('Ingredients', [])
            calorie_level = meal.get('Calorie Level', '')
            
            day_message += f"**{meal_type}:** {meal_name}\n"
            day_message += f"🔥 Calories: ~{calories}\n"
            if calorie_level:
                day_message += f"📊 Calorie Level: {calorie_level.title()}\n"
            if ingredients:
                ingredients_text = ", ".join(ingredients)
                day_message += f"🥘 Ingredients: {ingredients_text}\n"
            if health_impact:
                day_message += f"💡 Health Impact: {health_impact}\n"
            day_message += "\n"
    
    # Navigation buttons
    keyboard = []
    if current_day > 0:
        keyboard.append([InlineKeyboardButton("⬅️ Previous Day", callback_data="week_prev")])
    if current_day < len(weekly_plan) - 1:
        keyboard.append([InlineKeyboardButton("➡️ Next Day", callback_data="week_next")])
    
    keyboard.extend([
        [InlineKeyboardButton("🛒 Grocery List", callback_data="grocery_list")],
        [InlineKeyboardButton("🔄 New Week", callback_data="week_plan")],
        [InlineKeyboardButton("⬅️ Back to Menu", callback_data="go_back")]
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        day_message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    return WEEK_PLAN

async def handle_meal_rating(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle meal rating (like/dislike)."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    rating_data = query.data.split("_")
    
    if len(rating_data) < 2:
        return MEAL_PLAN
    
    rating_type = rating_data[1]  # like or dislike
    
    # Handle different rating formats
    if len(rating_data) >= 3:
        # Format: rate_like_meal_name or rate_dislike_meal_name
        meal_name = "_".join(rating_data[2:])  # meal name might contain underscores
    else:
        # Format: rate_like_ai_generated or rate_dislike_ai_generated
        meal_name = "AI Generated Meal Plan"
    
    rating_value = 1 if rating_type == "like" else 0
    
    # Log the rating attempt
    logger.info(f"🔧 Rating attempt by user {user_id}: {rating_type} for meal '{meal_name}'")
    
    # Save rating to Firebase
    rating_saved = await save_meal_rating(user_id, meal_name, rating_value)
    
    # Log the result
    logger.info(f"✅ Rating saved for user {user_id}: {rating_type} for '{meal_name}' - Firebase: {rating_saved}")
    
    # Show confirmation
    emoji = "👍" if rating_type == "like" else "👎"
    message = f"{emoji} **Rating Saved!**\n\n"
    message += f"**Meal:** {meal_name}\n"
    message += f"**Rating:** {'Liked' if rating_type == 'like' else 'Disliked'}\n"
    message += f"{'✅ Saved to database' if rating_saved else '⚠️ Saved locally only'}\n\n"
    message += "Thanks for the feedback fam! This helps me get better at suggesting meals for you! 🙏"
    
    keyboard = [
        [InlineKeyboardButton("🍽️ Get New Meal Plan", callback_data="get_meal_plan")],
        [InlineKeyboardButton("🛒 Grocery List", callback_data="grocery_list")],
        [InlineKeyboardButton("⬅️ Back to Menu", callback_data="go_back")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    return MEAL_PLAN

async def show_grocery_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show grocery list with cart functionality."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    # Get user profile
    user_data = user_data_cache.get(user_id)
    if not user_data:
        user_data = await get_user_profile(user_id)
        if not user_data:
            await query.edit_message_text(
                "❌ No profile found. Please create your profile first.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🏠 Start Over", callback_data="start_over")
                ]])
            )
            return ConversationHandler.END
    
    # Load meals from CSV
    user_diet = user_data.get('diet_type', user_data.get('diet', 'vegetarian')).lower()
    meals = load_meal_data_from_csv(diet_type=user_diet, max_meals=30)
    if not meals:
        await query.edit_message_text(
            f"❌ No meal data available for {user_data['diet'].title()} diet.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Start Over", callback_data="start_over")
            ]])
        )
        return ConversationHandler.END
    
    # Filter meals based on preferences
    if user_data.get('medical'):
        filtered_meals = filter_meals_by_preferences(meals, user_diet, user_data['medical'])
    else:
        filtered_meals = meals[:10]  # Take first 10 meals if no medical conditions
    
    if len(filtered_meals) < 4:
        filtered_meals = meals[:4]
    
    # Extract ingredients from selected meals - ONLY from meal data
    all_ingredients = set()
    for meal in filtered_meals[:4]:  # Take first 4 meals
        ingredients = meal.get('Ingredients', [])
        if isinstance(ingredients, list):
            # Clean and validate each ingredient
            for ingredient in ingredients:
                if ingredient and isinstance(ingredient, str) and len(ingredient.strip()) > 0:
                    all_ingredients.add(ingredient.strip())
    
    # Convert to list and sort
    ingredients_list = sorted(list(all_ingredients))
    
    # If no ingredients found, try to get from more meals
    if len(ingredients_list) < 3:
        for meal in filtered_meals[4:8]:  # Try next 4 meals
            ingredients = meal.get('Ingredients', [])
            if isinstance(ingredients, list):
                for ingredient in ingredients:
                    if ingredient and isinstance(ingredient, str) and len(ingredient.strip()) > 0:
                        all_ingredients.add(ingredient.strip())
        ingredients_list = sorted(list(all_ingredients))
    
    # Get user's current grocery list from cache or Firebase
    user_grocery_list = await get_grocery_list(user_id)
    
    # Combine suggested ingredients with user's custom list
    combined_list = list(set(ingredients_list + user_grocery_list))
    combined_list.sort()
    
    # Get user's cart selections from cache or Firebase
    user_cart = await get_cart_selections(user_id)
    
    grocery_message = (
        f"🛒 **Your Shopping List**\n\n"
        f"👤 **For:** {user_data.get('name', 'Your')} profile\n"
        f"🏛️ **Region:** {user_data['state'].title()}\n"
        f"🥬 **Diet:** {user_data['diet'].title()}\n\n"
        f"*Select items for your cart:*\n\n"
    )
    
    # Create keyboard with toggle buttons for each item
    keyboard = []
    for ingredient in combined_list:
        if ingredient in user_cart:
            # Item is in cart - show "Added" button
            keyboard.append([InlineKeyboardButton(f"✅ {ingredient}", callback_data=f"cart_toggle_{ingredient}")])
        else:
            # Item is not in cart - show "Add to Cart" button
            keyboard.append([InlineKeyboardButton(f"➕ Add {ingredient}", callback_data=f"cart_toggle_{ingredient}")])
    
    # Add cart summary and action buttons
    cart_count = len(user_cart)
    keyboard.append([InlineKeyboardButton(f"🛍 Show Cart ({cart_count} items)", callback_data="show_cart")])
    keyboard.append([InlineKeyboardButton("👤 View Profile", callback_data="view_profile")])
    keyboard.append([InlineKeyboardButton("⬅️ Back to Meal Plan", callback_data="get_meal_plan")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        grocery_message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    return MEAL_PLAN

async def manage_grocery_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show grocery list management interface."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    # Get user's current grocery list from cache or Firebase
    user_grocery_list = await get_grocery_list(user_id)
    
    # Get suggested ingredients from meals
    user_data = user_data_cache.get(user_id)
    if not user_data:
        user_data = await get_user_profile(user_id)
    
    suggested_ingredients = []
    if user_data:
        # Load meals based on user's diet type
        user_diet = user_data.get('diet_type', user_data.get('diet', 'vegetarian')).lower()
        meals = load_meal_data_from_csv(diet_type=user_diet, max_meals=20)
        if meals:
            # Filter meals by medical conditions if any
            if user_data.get('medical'):
                filtered_meals = filter_meals_by_preferences(meals, user_diet, user_data['medical'])
            else:
                filtered_meals = meals[:4]
            
            if len(filtered_meals) < 4:
                filtered_meals = meals[:4]
            
            all_ingredients = set()
            for meal in filtered_meals[:4]:
                ingredients = meal.get('Ingredients', [])
                if isinstance(ingredients, list):
                    all_ingredients.update(ingredients)
            suggested_ingredients = sorted(list(all_ingredients))
    
    # Add common ingredients
    common_ingredients = ["Rice", "Oil", "Salt", "Spices", "Vegetables", "Onions", "Tomatoes", "Potatoes", "Carrots", "Capsicum"]
    suggested_ingredients.extend([item for item in common_ingredients if item not in suggested_ingredients])
    suggested_ingredients = list(set(suggested_ingredients))  # Remove duplicates
    suggested_ingredients.sort()
    
    # Create management message
    manage_message = (
        f"⚙️ **Manage Your Shopping List**\n\n"
        f"👤 **For:** {user_data.get('name', 'Your') if user_data else 'Your'} profile\n\n"
        f"*Current items in your list:* {len(user_grocery_list)}\n"
        f"*Suggested items:* {len(suggested_ingredients)}\n\n"
        f"*Tap 'Add Items' to add what you need, or 'Remove Items' to clean up your list!*"
    )
    
    # Create management buttons
    keyboard = [
        [InlineKeyboardButton("➕ Add Items", callback_data="add_grocery_items")],
        [InlineKeyboardButton("➖ Remove Items", callback_data="remove_grocery_items")],
        [InlineKeyboardButton("🗑️ Clear All", callback_data="clear_grocery_list")],
        [InlineKeyboardButton("👤 View Profile", callback_data="view_profile")],
        [InlineKeyboardButton("⬅️ Back to List", callback_data="grocery_list")],
        [InlineKeyboardButton("🏠 Start Over", callback_data="start_over")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        manage_message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    return GROCERY_MANAGE

async def add_grocery_items(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show interface to add grocery items."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    # Get suggested ingredients
    user_data = user_data_cache.get(user_id)
    if not user_data:
        user_data = await get_user_profile(user_id)
    
    suggested_ingredients = []
    if user_data:
        # Load meals based on user's diet type
        user_diet = user_data.get('diet_type', user_data.get('diet', 'vegetarian')).lower()
        meals = load_meal_data_from_csv(diet_type=user_diet, max_meals=20)
        if meals:
            # Filter meals by medical conditions if any
            if user_data.get('medical'):
                filtered_meals = filter_meals_by_preferences(meals, user_diet, user_data['medical'])
            else:
                filtered_meals = meals[:4]
            
            if len(filtered_meals) < 4:
                filtered_meals = meals[:4]
            
            all_ingredients = set()
            for meal in filtered_meals[:4]:
                ingredients = meal.get('Ingredients', [])
                if isinstance(ingredients, list):
                    all_ingredients.update(ingredients)
            suggested_ingredients = sorted(list(all_ingredients))
    
    # Add common ingredients
    common_ingredients = ["Rice", "Oil", "Salt", "Spices", "Vegetables", "Onions", "Tomatoes", "Potatoes", "Carrots", "Capsicum", "Milk", "Bread", "Eggs", "Chicken", "Fish"]
    suggested_ingredients.extend([item for item in common_ingredients if item not in suggested_ingredients])
    suggested_ingredients = list(set(suggested_ingredients))
    suggested_ingredients.sort()
    
    # Get user's current list to avoid duplicates
    user_grocery_list = await get_grocery_list(user_id)
    available_items = [item for item in suggested_ingredients if item not in user_grocery_list]
    
    # Create add message
    add_message = (
        f"➕ **Add Items to Your List**\n\n"
        f"*Tap the items you want to add:*\n\n"
    )
    
    # Create buttons for available items (max 10 per row)
    keyboard = []
    for i in range(0, len(available_items), 2):
        row = []
        row.append(InlineKeyboardButton(f"➕ {available_items[i]}", callback_data=f"add_item_{available_items[i]}"))
        if i + 1 < len(available_items):
            row.append(InlineKeyboardButton(f"➕ {available_items[i+1]}", callback_data=f"add_item_{available_items[i+1]}"))
        keyboard.append(row)
    
    # Add navigation buttons
    keyboard.extend([
        [InlineKeyboardButton("👤 View Profile", callback_data="view_profile")],
        [InlineKeyboardButton("⬅️ Back to Manage", callback_data="manage_grocery")],
        [InlineKeyboardButton("🛒 View List", callback_data="grocery_list")]
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        add_message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    return GROCERY_MANAGE

async def remove_grocery_items(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show interface to remove grocery items."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    # Get user's current grocery list
    user_grocery_list = await get_grocery_list(user_id)
    
    if not user_grocery_list:
        await query.edit_message_text(
            "❌ Your shopping list is empty! Add some items first.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Back to Manage", callback_data="manage_grocery")
            ]])
        )
        return GROCERY_MANAGE
    
    # Create remove message
    remove_message = (
        f"➖ **Remove Items from Your List**\n\n"
        f"*Tap the items you want to remove:*\n\n"
    )
    
    # Create buttons for current items (max 2 per row)
    keyboard = []
    for i in range(0, len(user_grocery_list), 2):
        row = []
        row.append(InlineKeyboardButton(f"➖ {user_grocery_list[i]}", callback_data=f"remove_item_{user_grocery_list[i]}"))
        if i + 1 < len(user_grocery_list):
            row.append(InlineKeyboardButton(f"➖ {user_grocery_list[i+1]}", callback_data=f"remove_item_{user_grocery_list[i+1]}"))
        keyboard.append(row)
    
    # Add navigation buttons
    keyboard.extend([
        [InlineKeyboardButton("👤 View Profile", callback_data="view_profile")],
        [InlineKeyboardButton("⬅️ Back to Manage", callback_data="manage_grocery")],
        [InlineKeyboardButton("🛒 View List", callback_data="grocery_list")]
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        remove_message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    return GROCERY_MANAGE

async def add_grocery_item(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Add a specific item to grocery list."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    item_name = query.data.split("_", 2)[2]  # Get item name from callback data
    
    # Get current grocery list
    user_grocery_list = await get_grocery_list(user_id)
    
    # Add item if not already in list
    if item_name not in user_grocery_list:
        user_grocery_list.append(item_name)
        user_grocery_list.sort()  # Keep list sorted
        
        # Save updated list
        await save_grocery_list(user_id, user_grocery_list)
    
    # Show confirmation
    await query.edit_message_text(
        f"✅ **Added to your list!**\n\n"
        f"➕ **{item_name}** has been added to your shopping list.\n\n"
        f"*Your list now has {len(user_grocery_list)} items.*",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👤 View Profile", callback_data="view_profile")],
            [InlineKeyboardButton("➕ Add More Items", callback_data="add_grocery_items")],
            [InlineKeyboardButton("🛒 View List", callback_data="grocery_list")],
            [InlineKeyboardButton("⬅️ Back to Manage", callback_data="manage_grocery")]
        ]),
        parse_mode='Markdown'
    )
    
    return GROCERY_MANAGE

async def remove_grocery_item(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Remove a specific item from grocery list."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    item_name = query.data.split("_", 2)[2]  # Get item name from callback data
    
    # Get current grocery list
    user_grocery_list = await get_grocery_list(user_id)
    
    # Remove item from list
    if item_name in user_grocery_list:
        user_grocery_list.remove(item_name)
        # Save updated list
        await save_grocery_list(user_id, user_grocery_list)
    
    # Show confirmation
    await query.edit_message_text(
        f"✅ **Removed from your list!**\n\n"
        f"➖ **{item_name}** has been removed from your shopping list.\n\n"
        f"*Your list now has {len(user_grocery_list)} items.*",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👤 View Profile", callback_data="view_profile")],
            [InlineKeyboardButton("➖ Remove More Items", callback_data="remove_grocery_items")],
            [InlineKeyboardButton("🛒 View List", callback_data="grocery_list")],
            [InlineKeyboardButton("⬅️ Back to Manage", callback_data="manage_grocery")]
        ]),
        parse_mode='Markdown'
    )
    
    return GROCERY_MANAGE

async def clear_grocery_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Clear all items from grocery list."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    # Clear the list
    await save_grocery_list(user_id, [])
    
    await query.edit_message_text(
        f"🗑️ **List Cleared!**\n\n"
        f"Your shopping list has been cleared.\n\n"
        f"*Start fresh with suggested items or add your own!*",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("👤 View Profile", callback_data="view_profile")],
            [InlineKeyboardButton("➕ Add Items", callback_data="add_grocery_items")],
            [InlineKeyboardButton("🛒 View List", callback_data="grocery_list")],
            [InlineKeyboardButton("⬅️ Back to Manage", callback_data="manage_grocery")]
        ]),
        parse_mode='Markdown'
    )
    
    return GROCERY_MANAGE

async def toggle_cart_item(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Toggle an item in the user's cart."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    item_name = query.data.split("_", 2)[2]  # Get item name from callback data
    
    # Get current cart selections
    user_cart = await get_cart_selections(user_id)
    
    # Toggle the item
    if item_name in user_cart:
        user_cart.remove(item_name)
    else:
        user_cart.add(item_name)
    
    # Save updated cart selections
    await save_cart_selections(user_id, user_cart)
    
    # Return to the grocery list to show updated state
    return await show_grocery_list(update, context)

async def show_cart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show the user's cart with selected items."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    # Get user profile
    user_data = user_data_cache.get(user_id)
    if not user_data:
        user_data = await get_user_profile(user_id)
        if not user_data:
            await query.edit_message_text(
                "❌ No profile found. Please create your profile first.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🏠 Start Over", callback_data="start_over")
                ]])
            )
            return ConversationHandler.END
    
    # Get user's cart selections from cache or Firebase
    user_cart = await get_cart_selections(user_id)
    
    if not user_cart:
        cart_message = (
            f"🛍 **Your Cart is Empty**\n\n"
            f"👤 **For:** {user_data.get('name', 'Your')} profile\n\n"
            f"*You haven't selected any items yet.*\n\n"
            f"*Go back to the shopping list to add items to your cart!*"
        )
        
        keyboard = [
            [InlineKeyboardButton("👤 View Profile", callback_data="view_profile")],
            [InlineKeyboardButton("🛒 Back to Shopping List", callback_data="grocery_list")],
            [InlineKeyboardButton("⬅️ Back to Meal Plan", callback_data="get_meal_plan")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            cart_message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return CART
    
    # Format cart message
    cart_message = (
        f"🛍 **Your Shopping Cart**\n\n"
        f"👤 **For:** {user_data.get('name', 'Your')} profile\n"
        f"🏛️ **Region:** {user_data['state'].title()}\n\n"
        f"*Selected items:*\n\n"
    )
    
    for i, item in enumerate(sorted(user_cart), 1):
        cart_message += f"{i}. {item}\n"
    
    cart_message += f"\n*Total items: {len(user_cart)}*\n\n"
    cart_message += "*Ready to order? Choose your delivery service below!*"
    
    # Create order buttons
    keyboard = [
        [InlineKeyboardButton("🛒 Order from Blinkit", url="https://www.blinkit.com")],
        [InlineKeyboardButton("🛍 Order from Zepto", url="https://www.zepto.in")],
        [InlineKeyboardButton("🛒 Back to Shopping List", callback_data="grocery_list")],
        [InlineKeyboardButton("⬅️ Back to Meal Plan", callback_data="get_meal_plan")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        cart_message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    return CART

async def order_on_zepto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle Zepto order request with dynamic ingredients from AI/JSON."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    # Get user profile
    user_data = user_data_cache.get(user_id)
    if not user_data:
        user_data = await get_user_profile(user_id)
        if not user_data:
            await query.edit_message_text(
                "❌ No profile found. Please create your profile first.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🏠 Start Over", callback_data="start_over")
                ]])
            )
            return ConversationHandler.END
    
    # Get ingredients from last suggested meals (AI or JSON)
    last_meals = context.user_data.get("last_suggested_meals", [])
    all_ingredients = set()
    
    if last_meals:
        # Extract ingredients from cached meals
        for meal in last_meals:
            if isinstance(meal, dict):
                # JSON meal format
                ingredients = meal.get('Ingredients', [])
                if isinstance(ingredients, list):
                    all_ingredients.update(ingredients)
                elif isinstance(ingredients, str):
                    # Handle string ingredients
                    all_ingredients.update([ing.strip() for ing in ingredients.split(',')])
            else:
                # AI meal format - extract from meal name
                meal_name = str(meal)
                # Common ingredients that might be in meal names
                common_ingredients = ["Rice", "Dal", "Vegetables", "Potato", "Tomato", "Onion", "Oil", "Spices"]
                for ingredient in common_ingredients:
                    if ingredient.lower() in meal_name.lower():
                        all_ingredients.add(ingredient)
    
    # If no ingredients found, fallback to CSV meals
    if not all_ingredients:
        user_diet = user_data.get('diet_type', user_data.get('diet', 'vegetarian')).lower()
        meals = load_meal_data_from_csv(diet_type=user_diet, max_meals=20)
        if meals:
            # Filter meals by medical conditions if any
            if user_data.get('medical'):
                filtered_meals = filter_meals_by_preferences(meals, user_diet, user_data['medical'])
            else:
                filtered_meals = meals[:4]
            
            if len(filtered_meals) < 4:
                filtered_meals = meals[:4]
            
            for meal in filtered_meals[:4]:
                ingredients = meal.get('Ingredients', [])
                if isinstance(ingredients, list):
                    all_ingredients.update(ingredients)
    
    # Convert to list and sort
    ingredients_list = sorted(list(all_ingredients))
    
    # Add common ingredients if list is too short
    if len(ingredients_list) < 5:
        common_ingredients = ["Rice", "Oil", "Salt", "Spices", "Vegetables", "Onion", "Tomato", "Potato"]
        ingredients_list.extend([item for item in common_ingredients if item not in ingredients_list])
    
    # Silently add ingredients to grocery list
    if ingredients_list:
        current_grocery_list = await get_grocery_list(user_id)
        new_items = [item for item in ingredients_list[:8] if item not in current_grocery_list]  # Limit to 8 items
        if new_items:
            updated_list = current_grocery_list + new_items
            await save_grocery_list(user_id, updated_list)
            logger.info(f"✅ Silently added {len(new_items)} ingredients to grocery list for user {user_id}")
    
    # Create search query for Zepto
    search_query = "+".join(ingredients_list[:5])  # Limit to first 5 items
    zepto_url = f"https://www.zepto.com/search?q={search_query}"
    
    zepto_message = (
        f"🚚 **Get Your Groceries Delivered!**\n\n"
        f"👤 **For:** {user_data.get('name', 'Your')} profile\n"
        f"🏛️ **Region:** {user_data['state'].title()}\n\n"
        f"Tap the link below to find your items on Zepto:\n\n"
        f"🔗 [Order on Zepto]({zepto_url})\n\n"
        f"*Search includes: {', '.join(ingredients_list[:5])}*\n\n"
        f"*✅ Ingredients automatically added to your grocery list!*\n\n"
        f"*You can add more stuff to your cart once you're there!*"
    )
    
    # Create action buttons
    keyboard = [
        [InlineKeyboardButton("🛒 View Grocery List", callback_data="grocery_list")],
        [InlineKeyboardButton("⬅️ Back to Meal Plan", callback_data="get_meal_plan")],
        [InlineKeyboardButton("🏠 Start Over", callback_data="start_over")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        zepto_message,
        reply_markup=reply_markup,
        parse_mode='Markdown',
        disable_web_page_preview=True
    )
    
    return MEAL_PLAN

async def show_user_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show user profile with streak information."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    # Get user profile
    user_data = user_data_cache.get(user_id)
    if not user_data:
        user_data = await get_user_profile(user_id)
        if not user_data:
            await query.edit_message_text(
                "❌ No profile found. Please create your profile first.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🏠 Start Over", callback_data="start_over")
                ]])
            )
            return ConversationHandler.END
    
    # Get streak data
    streak_data = await get_user_streak(user_id)
    
    # Format profile message
    profile_message = (
        f"👤 **Your Profile**\n\n"
        f"**Personal Info:**\n"
        f"👤 **Name:** {user_data.get('name', 'Not set')}\n"
        f"👤 **Age:** {user_data.get('age', 'Not set')}\n"
        f"👤 **Gender:** {user_data['gender'].title()}\n"
        f"🏛️ **State:** {user_data['state'].title()}\n\n"
        f"**Preferences:**\n"
        f"🥬 **Diet:** {user_data['diet'].title()}\n"
        f"🏥 **Medical:** {user_data['medical'].title()}\n"
        f"🏃 **Activity:** {user_data['activity'].title()}\n\n"
        f"**Streak Stats:**\n"
        f"🔥 **Current Streak:** {streak_data['streak_count']} days\n"
        f"🎯 **Total Streak Points:** {streak_data['streak_points_total']}\n"
    )
    
    # Add streak explanation if streak is 0
    if streak_data['streak_count'] == 0:
        profile_message += (
            f"\n💡 **How Streaks Work:**\n"
            f"• Complete your daily meal plan to build streaks\n"
            f"• Consecutive days increase your streak\n"
            f"• Missing a day resets your streak to 0\n"
            f"• Higher streaks earn more points!\n"
        )
    else:
        profile_message += (
            f"\n💡 **Keep it up!** Complete your meal plan today to continue your streak! 🔥\n"
        )
    
    # Create action buttons
    keyboard = [
        [InlineKeyboardButton("🍽️ Get Daily Meal Plan", callback_data="get_meal_plan")],
        [InlineKeyboardButton("📅 Weekly Meal Plan", callback_data="week_plan")],
        [InlineKeyboardButton("🛒 Grocery List", callback_data="grocery_list")],
        [InlineKeyboardButton("🔥 Streak Help", callback_data="streak_help")],
        [InlineKeyboardButton("🔄 Update Profile", callback_data="update_profile")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        profile_message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    return PROFILE

async def show_streak_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show detailed streak system explanation."""
    query = update.callback_query
    await query.answer()
    
    help_message = (
        f"🔥 **Streak System Guide**\n\n"
        f"**How it works:**\n"
        f"• Complete your daily meal plan to build streaks\n"
        f"• Each consecutive day increases your streak\n"
        f"• Missing a day resets your streak to 0\n"
        f"• Higher streaks earn exponentially more points!\n\n"
        f"**Points System:**\n"
        f"• Day 1: 2-5 points\n"
        f"• Day 2: 4-8 points\n"
        f"• Day 3: 8-15 points\n"
        f"• Day 4+: Exponential growth (1.5x multiplier)\n\n"
        f"**Tips:**\n"
        f"• Get your meal plan daily to maintain streaks\n"
        f"• The longer your streak, the more points you earn\n"
        f"• Points compound with each successful day\n"
        f"• Don't break the chain! 🔥\n\n"
        f"*Your streak resets at midnight if you miss a day*"
    )
    
    keyboard = [
        [InlineKeyboardButton("👤 Back to Profile", callback_data="view_profile")],
        [InlineKeyboardButton("🍽️ Get Meal Plan", callback_data="get_meal_plan")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        help_message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    return PROFILE

async def go_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Go back to the main menu."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    # Get user profile
    user_data = user_data_cache.get(user_id)
    if not user_data:
        user_data = await get_user_profile(user_id)
    
    if user_data:
        # User has profile - show main menu
        keyboard = [
            [InlineKeyboardButton("🍽️ Get Daily Meal Plan", callback_data="get_meal_plan")],
            [InlineKeyboardButton("🥘 Suggest from Ingredients", callback_data="ingredient_meal")],
            [InlineKeyboardButton("📝 Log Today's Meals", callback_data="log_meal")],
            [InlineKeyboardButton("📅 Weekly Meal Plan", callback_data="week_plan")],
            [InlineKeyboardButton("🛒 Grocery List", callback_data="grocery_list")],
            [InlineKeyboardButton("👤 View Profile", callback_data="view_profile")],
            [InlineKeyboardButton("🔄 Update Profile", callback_data="update_profile")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Get streak data for welcome message
        streak_data = await get_user_streak(user_id)
        
        await query.edit_message_text(
            f"🍎 Yo! Welcome back to Nutrio! 👋\n\n"
            f"👤 Name: {user_data.get('name', 'Not set')}\n"
            f"🏛️ State: {user_data.get('state', 'Not set')}\n"
            f"🥬 Diet: {user_data.get('diet', 'Not set')}\n"
            f"🔥 Streak: {streak_data['streak_count']} days | 🎯 Points: {streak_data['streak_points_total']}\n\n"
            f"What's the move today? Let's get you some good eats! 😋",
            reply_markup=reply_markup
        )
        return MEAL_PLAN
    else:
        # No profile - start profile creation
        keyboard = [
            [InlineKeyboardButton("✅ Start Profile Creation", callback_data="start_profile")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "🍎 Hey there! Welcome to Nutrio - your personal nutrition wingman! 👋\n\n"
            "I'm here to hook you up with some fire meal plans that actually taste good and keep you healthy.\n\n"
            "Let's get your profile set up so I can suggest the perfect meals for your vibe! 🔥",
            reply_markup=reply_markup
        )
        return NAME

async def start_over(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start over the conversation."""
    query = update.callback_query
    await query.answer()
    
    # Clear user data from cache
    user_id = query.from_user.id
    if user_id in user_data_cache:
        del user_data_cache[user_id]
    
    # Restart the conversation
    keyboard = [
        [InlineKeyboardButton("👨 Male", callback_data="gender_male")],
        [InlineKeyboardButton("👩 Female", callback_data="gender_female")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "🍎 Hey! Welcome to Nutrio - your nutrition wingman! 👋\n\n"
        "Let's get you set up with some fire meal plans. First, what's your gender?",
        reply_markup=reply_markup
    )
    
    return GENDER

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle all button callbacks."""
    query = update.callback_query
    
    # Profile creation flow
    if query.data == "start_profile":
        return await start_profile_creation(update, context)
    elif query.data.startswith("gender_"):
        return await gender_selection(update, context)
    elif query.data.startswith("state_"):
        return await state_selection(update, context)
    elif query.data.startswith("diet_"):
        return await diet_selection(update, context)
    elif query.data.startswith("medical_"):
        return await medical_selection(update, context)
    elif query.data.startswith("activity_"):
        return await activity_selection(update, context)
    
    # Main menu options
    elif query.data == "get_meal_plan":
        return await get_meal_plan(update, context)
    elif query.data == "ingredient_meal":
        return await handle_ingredient_meal(update, context)
    elif query.data.startswith("meal_type_"):
        return await handle_meal_type_selection(update, context)
    elif query.data == "log_meal":
        return await log_meal_command(update, context)
    elif query.data.startswith("follow_meal_") or query.data == "log_followed_done":
        return await handle_log_meal_followed(update, context)
    elif query.data.startswith("skip_meal_") or query.data == "log_skipped_done":
        return await handle_log_meal_skipped(update, context)
    elif query.data.startswith("extra_") or query.data == "log_extra_done" or query.data == "add_custom_extra":
        return await handle_log_meal_extra(update, context)
    elif query.data == "week_plan":
        return await handle_weekly_plan(update, context)
    elif query.data == "go_back":
        return await go_back(update, context)
    elif query.data == "grocery_list":
        return await show_grocery_list(update, context)
    elif query.data == "order_zepto":
        return await order_on_zepto(update, context)
    elif query.data == "update_profile":
        return await start_profile_creation(update, context)
    
    # Grocery management
    elif query.data == "manage_grocery":
        return await manage_grocery_list(update, context)
    elif query.data == "add_grocery_items":
        return await add_grocery_items(update, context)
    elif query.data == "remove_grocery_items":
        return await remove_grocery_items(update, context)
    elif query.data == "clear_grocery_list":
        return await clear_grocery_list(update, context)
    elif query.data.startswith("add_item_"):
        return await add_grocery_item(update, context)
    elif query.data.startswith("remove_item_"):
        return await remove_grocery_item(update, context)
    
    # Cart management
    elif query.data.startswith("cart_toggle_"):
        return await toggle_cart_item(update, context)
    elif query.data == "show_cart":
        return await show_cart(update, context)
    
    # Profile management
    elif query.data == "view_profile":
        return await show_user_profile(update, context)
    elif query.data == "streak_help":
        return await show_streak_help(update, context)
    
    # Weekly plan navigation
    elif query.data == "week_prev":
        context.user_data['current_day'] = max(0, context.user_data.get('current_day', 0) - 1)
        return await show_weekly_day(update, context)
    elif query.data == "week_next":
        context.user_data['current_day'] = min(len(context.user_data.get('weekly_plan', [])) - 1, 
                                              context.user_data.get('current_day', 0) + 1)
        return await show_weekly_day(update, context)
    
    # Rating system
    elif query.data.startswith("rate_"):
        logger.info(f"🔧 Rating button clicked: {query.data}")
        return await handle_meal_rating(update, context)
    
    # Navigation
    elif query.data == "start_over":
        return await start_over(update, context)
    
    return ConversationHandler.END

async def log_meal_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the log meal flow."""
    # Handle both command and button callbacks
    if update.callback_query:
        query = update.callback_query
        user_id = query.from_user.id
        message = query.message
    else:
        user_id = update.effective_user.id
        message = update.message
    
    # Get user profile
    user_data = user_data_cache.get(user_id)
    if not user_data:
        user_data = await get_user_profile(user_id)
        if not user_data:
            if update.callback_query:
                await query.edit_message_text(
                    "❌ No profile found. Please create your profile first.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🏠 Start Over", callback_data="start_over")
                    ]])
                )
            else:
                await update.message.reply_text(
                    "❌ No profile found. Please create your profile first.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🏠 Start Over", callback_data="start_over")
                    ]])
                )
            return ConversationHandler.END
    
    # Get last suggested meals from context
    last_meals = context.user_data.get("last_suggested_meals", [])
    
    if not last_meals:
        if update.callback_query:
            await query.edit_message_text(
                "❌ No meal suggestions found for today.\n\n"
                "Please get a meal plan first, then log your meals!",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🍽️ Get Meal Plan", callback_data="get_meal_plan")
                ]])
            )
        else:
            await update.message.reply_text(
                "❌ No meal suggestions found for today.\n\n"
                "Please get a meal plan first, then log your meals!",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🍽️ Get Meal Plan", callback_data="get_meal_plan")
                ]])
            )
        return ConversationHandler.END
    
    # Initialize meal log in context
    context.user_data["meal_log"] = {
        "followed_meals": [],
        "skipped_meals": [],
        "extra_items": []
    }
    
    # Create buttons for followed meals with better error handling
    keyboard = []
    for i, meal in enumerate(last_meals):
        # Handle both AI format (with 'name' key) and JSON format (with 'Food Item' key)
        if isinstance(meal, dict):
            meal_name = meal.get('name') or meal.get('Food Item', f'Meal {i+1}')
        else:
            meal_name = str(meal) if str(meal).strip() else f'Meal {i+1}'
        
        # Ensure meal name is not too long for button
        if len(meal_name) > 30:
            meal_name = meal_name[:27] + "..."
        
        keyboard.append([InlineKeyboardButton(f"✅ {meal_name}", callback_data=f"follow_meal_{meal_name}")])
    
    keyboard.append([InlineKeyboardButton("✅ Done", callback_data="log_followed_done")])
    keyboard.append([InlineKeyboardButton("⬅️ Go Back", callback_data="go_back")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await query.edit_message_text(
            "📝 **Step 1/4: Which meals did you follow today?**\n\n"
            "Click the meals you actually ate today. They'll turn ✅ when selected.\n\n"
            "Click ✅ Done when finished.",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            "📝 **Step 1/4: Which meals did you follow today?**\n\n"
            "Click the meals you actually ate today. They'll turn ✅ when selected.\n\n"
            "Click ✅ Done when finished.",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    return LOG_MEAL_FOLLOWED

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the conversation."""
    user_id = update.effective_user.id
    if user_id in user_data_cache:
        del user_data_cache[user_id]
    
    await update.message.reply_text(
        "👋 Alright, we're done here! Hit me up with /start when you're ready to try again! ✌️"
    )
    
    return ConversationHandler.END

async def handle_log_meal_followed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle followed meal selection."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "log_followed_done":
        # Move to step 2: skipped meals
        last_meals = context.user_data.get("last_suggested_meals", [])
        
        keyboard = []
        for i, meal in enumerate(last_meals):
            # Handle both AI format (with 'name' key) and JSON format (with 'Food Item' key)
            if isinstance(meal, dict):
                meal_name = meal.get('name') or meal.get('Food Item', f'Meal {i+1}')
            else:
                meal_name = str(meal) if str(meal).strip() else f'Meal {i+1}'
            
            # Ensure meal name is not too long for button
            if len(meal_name) > 30:
                meal_name = meal_name[:27] + "..."
            
            keyboard.append([InlineKeyboardButton(f"⛔ {meal_name}", callback_data=f"skip_meal_{meal_name}")])
        
        keyboard.append([InlineKeyboardButton("✅ Done", callback_data="log_skipped_done")])
        keyboard.append([InlineKeyboardButton("⬅️ Go Back", callback_data="go_back")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "📝 **Step 2/4: Which meals did you skip today?**\n\n"
            "Click the meals you didn't eat today. They'll turn ✅ when selected.\n\n"
            "Click ✅ Done when finished.",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
        return LOG_MEAL_SKIPPED
    
    elif query.data.startswith("follow_meal_"):
        # Toggle meal selection
        meal_name = query.data.replace("follow_meal_", "")
        meal_log = context.user_data.get("meal_log", {})
        followed_meals = meal_log.get("followed_meals", [])
        
        if meal_name in followed_meals:
            followed_meals.remove(meal_name)
            button_text = f"⛔ {meal_name}"
        else:
            followed_meals.append(meal_name)
            button_text = f"✅ {meal_name}"
        
        meal_log["followed_meals"] = followed_meals
        context.user_data["meal_log"] = meal_log
        
        # Rebuild the keyboard with updated button states
        last_meals = context.user_data.get("last_suggested_meals", [])
        keyboard = []
        for i, meal in enumerate(last_meals):
            if isinstance(meal, dict):
                meal_name = meal.get('name') or meal.get('Food Item', f'Meal {i+1}')
            else:
                meal_name = str(meal) if str(meal).strip() else f'Meal {i+1}'
            
            if len(meal_name) > 30:
                meal_name = meal_name[:27] + "..."
            
            if meal_name in followed_meals:
                keyboard.append([InlineKeyboardButton(f"✅ {meal_name}", callback_data=f"follow_meal_{meal_name}")])
            else:
                keyboard.append([InlineKeyboardButton(f"⛔ {meal_name}", callback_data=f"follow_meal_{meal_name}")])
        
        keyboard.append([InlineKeyboardButton("✅ Done", callback_data="log_followed_done")])
        keyboard.append([InlineKeyboardButton("⬅️ Go Back", callback_data="go_back")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_reply_markup(reply_markup=reply_markup)
        
        return LOG_MEAL_FOLLOWED

async def handle_log_meal_skipped(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle skipped meal selection."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "log_skipped_done":
        # Move to step 3: extra items
        keyboard = [
            [InlineKeyboardButton("🍔 Vada Pav", callback_data="extra_vada_pav")],
            [InlineKeyboardButton("🍦 Ice Cream", callback_data="extra_ice_cream")],
            [InlineKeyboardButton("🥨 Chips", callback_data="extra_chips")],
            [InlineKeyboardButton("🍕 Pizza", callback_data="extra_pizza")],
            [InlineKeyboardButton("🍰 Cake", callback_data="extra_cake")],
            [InlineKeyboardButton("🍫 Chocolate", callback_data="extra_chocolate")],
            [InlineKeyboardButton("➕ Add Custom", callback_data="add_custom_extra")],
            [InlineKeyboardButton("✅ Done", callback_data="log_extra_done")],
            [InlineKeyboardButton("⬅️ Go Back", callback_data="go_back")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "📝 **Step 3/4: What extra items did you eat?**\n\n"
            "Click the extra items you ate today. They'll turn ✅ when selected.\n\n"
            "Click ✅ Done when finished.",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
        return LOG_MEAL_EXTRA
    
    elif query.data.startswith("skip_meal_"):
        # Toggle meal selection
        meal_name = query.data.replace("skip_meal_", "")
        meal_log = context.user_data.get("meal_log", {})
        skipped_meals = meal_log.get("skipped_meals", [])
        
        if meal_name in skipped_meals:
            skipped_meals.remove(meal_name)
            button_text = f"⛔ {meal_name}"
        else:
            skipped_meals.append(meal_name)
            button_text = f"✅ {meal_name}"
        
        meal_log["skipped_meals"] = skipped_meals
        context.user_data["meal_log"] = meal_log
        
        # Rebuild the keyboard with updated button states
        last_meals = context.user_data.get("last_suggested_meals", [])
        keyboard = []
        for i, meal in enumerate(last_meals):
            if isinstance(meal, dict):
                meal_name = meal.get('name') or meal.get('Food Item', f'Meal {i+1}')
            else:
                meal_name = str(meal) if str(meal).strip() else f'Meal {i+1}'
            
            if len(meal_name) > 30:
                meal_name = meal_name[:27] + "..."
            
            if meal_name in skipped_meals:
                keyboard.append([InlineKeyboardButton(f"✅ {meal_name}", callback_data=f"skip_meal_{meal_name}")])
            else:
                keyboard.append([InlineKeyboardButton(f"⛔ {meal_name}", callback_data=f"skip_meal_{meal_name}")])
        
        keyboard.append([InlineKeyboardButton("✅ Done", callback_data="log_skipped_done")])
        keyboard.append([InlineKeyboardButton("⬅️ Go Back", callback_data="go_back")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_reply_markup(reply_markup=reply_markup)
        
        return LOG_MEAL_SKIPPED

async def handle_log_meal_extra(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle extra item selection."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "log_extra_done":
        # Save meal log and show confirmation
        await save_meal_log_and_show_confirmation(update, context)
        return ConversationHandler.END
    
    elif query.data == "add_custom_extra":
        # Ask for custom extra item
        await query.edit_message_text(
            "📝 **Add Custom Extra Item**\n\n"
            "Type the name of the extra item you ate:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Go Back", callback_data="go_back")
            ]])
        )
        return LOG_MEAL_CUSTOM
    
    elif query.data.startswith("extra_"):
        # Toggle extra item selection
        item_name = query.data.replace("extra_", "").replace("_", " ").title()
        meal_log = context.user_data.get("meal_log", {})
        extra_items = meal_log.get("extra_items", [])
        
        if item_name in extra_items:
            extra_items.remove(item_name)
        else:
            extra_items.append(item_name)
        
        meal_log["extra_items"] = extra_items
        context.user_data["meal_log"] = meal_log
        
        # Rebuild the keyboard with updated button states
        keyboard = []
        extra_items_list = [
            ("🍔 Vada Pav", "extra_vada_pav"),
            ("🍦 Ice Cream", "extra_ice_cream"),
            ("🥨 Chips", "extra_chips"),
            ("🍕 Pizza", "extra_pizza"),
            ("🍰 Cake", "extra_cake"),
            ("🍫 Chocolate", "extra_chocolate")
        ]
        
        for item_text, item_data in extra_items_list:
            item_name = item_data.replace("extra_", "").replace("_", " ").title()
            if item_name in extra_items:
                keyboard.append([InlineKeyboardButton(f"✅ {item_text}", callback_data=item_data)])
            else:
                keyboard.append([InlineKeyboardButton(f"⛔ {item_text}", callback_data=item_data)])
        
        keyboard.append([InlineKeyboardButton("➕ Add Custom", callback_data="add_custom_extra")])
        keyboard.append([InlineKeyboardButton("✅ Done", callback_data="log_extra_done")])
        keyboard.append([InlineKeyboardButton("⬅️ Go Back", callback_data="go_back")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_reply_markup(reply_markup=reply_markup)
        
        return LOG_MEAL_EXTRA

async def handle_log_meal_custom(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle custom extra item input."""
    user_id = update.message.from_user.id
    custom_item = update.message.text.strip()
    
    if not custom_item:
        await update.message.reply_text(
            "❌ Please enter a valid item name.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Go Back", callback_data="go_back")
            ]])
        )
        return LOG_MEAL_CUSTOM
    
    # Add custom item to meal log
    meal_log = context.user_data.get("meal_log", {})
    extra_items = meal_log.get("extra_items", [])
    extra_items.append(custom_item)
    meal_log["extra_items"] = extra_items
    context.user_data["meal_log"] = meal_log
    
    # Go back to extra items selection
    keyboard = [
        [InlineKeyboardButton("🍔 Vada Pav", callback_data="extra_vada_pav")],
        [InlineKeyboardButton("🍦 Ice Cream", callback_data="extra_ice_cream")],
        [InlineKeyboardButton("🥨 Chips", callback_data="extra_chips")],
        [InlineKeyboardButton("🍕 Pizza", callback_data="extra_pizza")],
        [InlineKeyboardButton("🍰 Cake", callback_data="extra_cake")],
        [InlineKeyboardButton("🍫 Chocolate", callback_data="extra_chocolate")],
        [InlineKeyboardButton("➕ Add Custom", callback_data="add_custom_extra")],
        [InlineKeyboardButton("✅ Done", callback_data="log_extra_done")],
        [InlineKeyboardButton("⬅️ Go Back", callback_data="go_back")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"✅ Added '{custom_item}' to your extra items!\n\n"
        "📝 **Step 3/4: What extra items did you eat?**\n\n"
        "Click the extra items you ate today. They'll turn ✅ when selected.\n\n"
        "Click ✅ Done when finished.",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    return LOG_MEAL_EXTRA

async def save_meal_log_and_show_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Save meal log to Firebase and show confirmation."""
    query = update.callback_query
    user_id = query.from_user.id
    
    # Get meal log data
    meal_log = context.user_data.get("meal_log", {})
    
    # Generate random points (3-8)
    import random
    points_earned = random.randint(3, 8)
    
    # Add timestamp
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    timestamp = datetime.now().isoformat()
    
    # Prepare log data
    log_data = {
        "followed_meals": meal_log.get("followed_meals", []),
        "skipped_meals": meal_log.get("skipped_meals", []),
        "extra_items": meal_log.get("extra_items", []),
        "points_earned": points_earned,
        "timestamp": timestamp
    }
    
    # Save to Firebase
    if FIREBASE_AVAILABLE and db:
        try:
            # Save meal log
            await db.collection('users').document(str(user_id)).collection('meal_logs').document(today).set(log_data)
            
            # Update total points
            user_ref = db.collection('users').document(str(user_id))
            user_doc = await user_ref.get()
            
            if user_doc.exists:
                current_points = user_doc.to_dict().get('total_points', 0)
                new_total = current_points + points_earned
                await user_ref.update({'total_points': new_total})
            else:
                await user_ref.set({'total_points': points_earned})
            
            logger.info(f"✅ Meal log saved for user {user_id}, earned {points_earned} points")
        except Exception as e:
            logger.error(f"❌ Error saving meal log: {e}")
    else:
        logger.warning(f"⚠️ Firebase not available for user {user_id}")
    
    # Show confirmation message
    await query.edit_message_text(
        f"✅ **Meal logged for today!**\n\n"
        f"You earned *{points_earned}* points 🎉\n\n"
        f"**Followed:** {', '.join(meal_log.get('followed_meals', [])) or 'None'}\n"
        f"**Skipped:** {', '.join(meal_log.get('skipped_meals', [])) or 'None'}\n"
        f"**Extra:** {', '.join(meal_log.get('extra_items', [])) or 'None'}",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🏠 Main Menu", callback_data="go_back")
        ]]),
        parse_mode='Markdown'
    )

def main() -> None:
    """Start the bot with comprehensive error handling."""
    
    try:
        # 🔑 BOT TOKEN CONFIGURATION - Load from environment variable
        if not BOT_TOKEN:
            print("❌ ERROR: BOT_TOKEN environment variable not set!")
            print("🔑 Please set your bot token in the .env file")
            print("📝 Example: BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz")
            print("📁 Copy env_example.txt to .env and add your token")
            return
        
        # Validate bot token format
        if not BOT_TOKEN.count(':') == 1 or len(BOT_TOKEN.split(':')) != 2:
            print("❌ ERROR: Invalid bot token format!")
            print("🔑 Token should be in format: 1234567890:ABCdefGHIjklMNOpqrsTUVwxyz")
            return
        
        # Create the Application and pass it your bot's token
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Add conversation handler
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", start)],
            states={
                NAME: [
                    CallbackQueryHandler(button_handler),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_name)
                ],
                AGE: [
                    CallbackQueryHandler(button_handler),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_age)
                ],
                GENDER: [CallbackQueryHandler(button_handler)],
                STATE: [CallbackQueryHandler(button_handler)],
                DIET_TYPE: [CallbackQueryHandler(button_handler)],
                MEDICAL_CONDITION: [
                    CallbackQueryHandler(button_handler),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_custom_medical)
                ],
                ACTIVITY_LEVEL: [CallbackQueryHandler(button_handler)],
                MEAL_PLAN: [CallbackQueryHandler(button_handler)],
                WEEK_PLAN: [CallbackQueryHandler(button_handler)],
                GROCERY_LIST: [CallbackQueryHandler(button_handler)],
                RATING: [CallbackQueryHandler(button_handler)],
                GROCERY_MANAGE: [CallbackQueryHandler(button_handler)],
                CART: [CallbackQueryHandler(button_handler)],
                PROFILE: [CallbackQueryHandler(button_handler)],
                INGREDIENTS: [
                    CallbackQueryHandler(button_handler),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ingredients_input)
                ],
                MEAL_TYPE: [
                    CallbackQueryHandler(button_handler)
                ],
                LOG_MEAL_FOLLOWED: [
                    CallbackQueryHandler(button_handler)
                ],
                LOG_MEAL_SKIPPED: [
                    CallbackQueryHandler(button_handler)
                ],
                LOG_MEAL_EXTRA: [
                    CallbackQueryHandler(button_handler)
                ],
                LOG_MEAL_CUSTOM: [
                    CallbackQueryHandler(button_handler),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_log_meal_custom)
                ],
            },
            fallbacks=[CommandHandler("cancel", cancel)],
            per_message=False,
        )
        
        application.add_handler(conv_handler)
        
        # Add command handlers
        application.add_handler(CommandHandler("logmeal", log_meal_command))
        
        # Run the bot until the user presses Ctrl-C
        print("🤖 Nutrio Bot is starting...")
        print("📝 Bot token configured successfully")
        print("🚀 Run the bot with: python main.py")
        print("📁 Make sure all required files are in the same folder")
        print("🔥 Firebase integration available" if FIREBASE_AVAILABLE else "⚠️ Firebase not available - install firebase-admin")
        print("🍽️ Static meal generator available" if MEAL_GENERATOR_AVAILABLE else "⚠️ Meal generator not available")
        
        # Test Firebase connection if available (commented out to prevent crashes)
        # if FIREBASE_AVAILABLE:
        #     print("🧪 Testing Firebase connection...")
        #     try:
        #         # Create test data for demonstration
        #         loop = asyncio.new_event_loop()
        #         asyncio.set_event_loop(loop)
        #         
        #         test_data_result = loop.run_until_complete(create_test_data())
        #         if test_data_result:
        #             print("✅ Test data created! Check Firebase Console now!")
        #         else:
        #             print("❌ Failed to create test data")
        #         
        #         loop.close()
        #     except Exception as e:
        #         print(f"❌ Firebase test error: {e}")
        
        # Start the bot with enhanced polling configuration
        print("🚀 Starting bot polling...")
        try:
            application.run_polling(
                drop_pending_updates=True, 
                allowed_updates=[],
                close_loop=False,
                stop_signals=None
            )
        except Exception as polling_error:
            print(f"❌ Polling error: {polling_error}")
            logger.error(f"Polling error: {polling_error}")
            raise
        
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user (Ctrl+C)")
    except Exception as e:
        print(f"❌ Critical error starting bot: {e}")
        logger.error(f"Critical error in main function: {e}")
        raise

if __name__ == '__main__':
    main() 
