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

# Conversation states
NAME, AGE, GENDER, STATE, DIET_TYPE, MEDICAL_CONDITION, ACTIVITY_LEVEL, MEAL_PLAN, WEEK_PLAN, GROCERY_LIST, RATING, GROCERY_MANAGE, CART, PROFILE = range(14)

# In-memory cache for performance (with size limits)
MAX_CACHE_SIZE = 1000
user_data_cache: Dict[int, Dict[str, Any]] = {}
grocery_lists_cache: Dict[int, List[str]] = {}
user_cart_cache: Dict[int, set] = {}
user_streaks_cache: Dict[int, Dict[str, Any]] = {}

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
    """Clean up cache if it exceeds maximum size."""
    if len(cache) > max_size:
        # Remove oldest entries (simple FIFO)
        keys_to_remove = list(cache.keys())[:len(cache) - max_size]
        for key in keys_to_remove:
            del cache[key]
        logger.info(f"Cleaned up cache, removed {len(keys_to_remove)} entries")

# Firebase helper functions with proper error handling
async def save_user_profile(user_id: int, profile_data: Dict[str, Any]) -> bool:
    """Save user profile to Firebase with proper error handling."""
    # Sanitize profile data
    sanitized_profile = {}
    for key, value in profile_data.items():
        if isinstance(value, str):
            sanitized_profile[key] = sanitize_input(value)
        else:
            sanitized_profile[key] = value
    
    # Update cache
    user_data_cache[user_id] = sanitized_profile.copy()
    cleanup_cache(user_data_cache)
    
    # Save to Firebase if available
    if FIREBASE_AVAILABLE and db:
        try:
            doc_ref = db.collection('users').document(str(user_id))
            doc_ref.set({
                'profile': sanitized_profile,
                'created_at': firestore.SERVER_TIMESTAMP,
                'updated_at': firestore.SERVER_TIMESTAMP
            }, merge=True)
            logger.info(f"Profile saved to Firebase for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error saving user profile to Firebase: {e}")
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

def load_meal_data_from_json(state: str) -> List[Dict[str, Any]]:
    """Load meal data from JSON file for the given state with fallback."""
    try:
        # Handle the specific filename for Maharashtra
        if state.lower() == "maharashtra":
            filename = "maharastra.json"
        elif state.lower() == "andhra":
            filename = "andhra_dishes.json"
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
        
        # Handle existing simple format (Karnataka, Maharashtra)
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
    """Check if user has exceeded rate limit."""
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
    
    # Check current requests
    current_requests = [req for req in user_limit['requests'] 
                       if (now - req).total_seconds() <= RATE_LIMIT_WINDOW]
    
    if len(current_requests) >= MAX_REQUESTS_PER_WINDOW:
        return False
    
    # Add current request
    user_limit['requests'].append(now)
    return True

def filter_meals_by_preferences(meals: List[Dict[str, Any]], diet_type: str, medical_condition: str) -> List[Dict[str, Any]]:
    """Filter meals based on user preferences."""
    filtered_meals = []
    
    for meal in meals:
        if not isinstance(meal, dict) or "Food Item" not in meal:
            continue
            
        # Check diet compatibility
        if diet_type.lower() == "jain":
            # Check for onion, garlic, potato, eggs, meat, fish in ingredients
            if any(item in str(meal.get("Ingredients", [])).lower() for item in ["onion", "garlic", "potato", "egg", "chicken", "fish", "meat", "prawn"]):
                continue
            # Also check SpecialNote for Andhra Pradesh dishes
            if meal.get("SpecialNote", "").lower() == "no onion, garlic":
                continue
        elif diet_type.lower() == "vegan":
            # Check for non-vegan ingredients
            if any(item in str(meal.get("Ingredients", [])).lower() for item in ["milk", "ghee", "curd", "egg", "meat", "fish", "chicken"]):
                continue
            # Also check SpecialNote for Andhra Pradesh dishes
            if meal.get("SpecialNote", "").lower() == "vegan":
                continue
        elif diet_type.lower() == "non-veg":
            # For non-vegetarian, prefer meals with meat/fish
            if any(item in str(meal.get("Ingredients", [])).lower() for item in ["chicken", "fish", "meat", "prawn", "egg"]):
                filtered_meals.append(meal)
                continue
        elif diet_type.lower() == "veg":
            # For vegetarian, avoid meat/fish/eggs
            if any(item in str(meal.get("Ingredients", [])).lower() for item in ["chicken", "fish", "meat", "prawn", "egg"]):
                continue
        elif diet_type.lower() == "eggitarian":
            # For eggitarian, allow eggs but avoid meat/fish
            if any(item in str(meal.get("Ingredients", [])).lower() for item in ["chicken", "fish", "meat", "prawn"]):
                continue
            # Prefer meals with eggs
            if "egg" in str(meal.get("Ingredients", [])).lower():
                filtered_meals.append(meal)
                continue
            
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
        [InlineKeyboardButton("🌱 Vegan", callback_data="diet_vegan")]
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
        [InlineKeyboardButton("👤 View Profile", callback_data="view_profile")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        completion_message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    return PROFILE

async def get_meal_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Generate and display personalized meal plan from JSON data."""
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
    
    # Load meals from JSON
    meals = load_meal_data_from_json(user_data['state'])
    if not meals:
        await query.edit_message_text(
            f"❌ No meal data available for {user_data['state'].title()}.\n\n"
            "Please try again later or contact support.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 Try Again", callback_data="get_meal_plan")
            ]])
        )
        return ConversationHandler.END
    
    # Filter meals based on preferences
    filtered_meals = filter_meals_by_preferences(meals, user_data['diet'], user_data['medical'])
    
    if len(filtered_meals) < 4:
        # If not enough filtered meals, use all meals
        filtered_meals = meals[:4]
    
    # Select 4 meals for the day
    selected_meals = random.sample(filtered_meals, min(4, len(filtered_meals)))
    
    # Calculate total calories
    total_calories = sum(meal.get('approx_calories', 200) for meal in selected_meals)
    
    # Format meal plan message
    meal_message = f"🍽️ **Your Daily Meal Plan - Custom Made!**\n\n"
    meal_message += f"👤 **Made for:** {user_data.get('name', 'Your')} profile\n"
    meal_message += f"🏛️ **Region:** {user_data['state'].title()}\n"
    meal_message += f"🥬 **Diet:** {user_data['diet'].title()}\n"
    meal_message += f"🏥 **Medical:** {user_data['medical'].title()}\n"
    meal_message += f"🏃 **Activity:** {user_data['activity'].title()}\n"
    meal_message += f"🔥 **Streak:** {streak_data['streak_count']} days | 🎯 **Points:** {streak_data['streak_points_total']}"
    if points_earned > 0:
        meal_message += f" (+{points_earned} today!)"
    meal_message += "\n\n"
    
    meal_types = ["🌅 Breakfast", "🌞 Lunch", "🌙 Dinner", "🍎 Snack"]
    for i, meal in enumerate(selected_meals):
        meal_type = meal_types[i] if i < len(meal_types) else "🍽️ Meal"
        meal_name = meal.get('Food Item', 'Unknown')
        calories = meal.get('approx_calories', 200)
        health_impact = meal.get('Health Impact', '')
        ingredients = meal.get('Ingredients', [])
        calorie_level = meal.get('Calorie Level', '')
        
        meal_message += f"**{meal_type}:** {meal_name}\n"
        meal_message += f"🔥 Calories: ~{calories}\n"
        if calorie_level:
            meal_message += f"📊 Calorie Level: {calorie_level.title()}\n"
        if ingredients:
            ingredients_text = ", ".join(ingredients)
            meal_message += f"🥘 Ingredients: {ingredients_text}\n"
        if health_impact:
            meal_message += f"💡 Health Impact: {health_impact}\n"
        meal_message += "\n"
    
    meal_message += f"**Total Calories:** ~{total_calories}\n\n"
    meal_message += "💡 *All meals are picked just for you based on your vibe and health needs*"
    
    # Create action buttons with ratings
    keyboard = [
        [InlineKeyboardButton("👍 Like", callback_data=f"rate_like_{selected_meals[0].get('Food Item', '')}")],
        [InlineKeyboardButton("👎 Dislike", callback_data=f"rate_dislike_{selected_meals[0].get('Food Item', '')}")],
        [InlineKeyboardButton("🛒 Grocery List", callback_data="grocery_list")],
        [InlineKeyboardButton("🚚 Order on Zepto", callback_data="order_zepto")],
        [InlineKeyboardButton("🔄 New Plan", callback_data="get_meal_plan")],
        [InlineKeyboardButton("⬅️ Go Back", callback_data="go_back")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        meal_message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    return MEAL_PLAN

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
    
    # Load and filter meals
    meals = load_meal_data_from_json(user_data['state'])
    if not meals:
        await query.edit_message_text(
            f"❌ No meal data available for {user_data['state'].title()}.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Start Over", callback_data="start_over")
            ]])
        )
        return ConversationHandler.END
    
    filtered_meals = filter_meals_by_preferences(meals, user_data['diet'], user_data['medical'])
    
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
    
    if len(rating_data) < 3:
        return MEAL_PLAN
    
    rating_type = rating_data[1]  # like or dislike
    meal_name = "_".join(rating_data[2:])  # meal name might contain underscores
    
    rating_value = 1 if rating_type == "like" else 0
    
    # Save rating to Firebase
    rating_saved = await save_meal_rating(user_id, meal_name, rating_value)
    
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
    
    # Load meals from JSON
    meals = load_meal_data_from_json(user_data['state'])
    if not meals:
        await query.edit_message_text(
            f"❌ No meal data available for {user_data['state'].title()}.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Start Over", callback_data="start_over")
            ]])
        )
        return ConversationHandler.END
    
    # Filter meals based on preferences
    filtered_meals = filter_meals_by_preferences(meals, user_data['diet'], user_data['medical'])
    
    if len(filtered_meals) < 4:
        filtered_meals = meals[:4]
    
    # Extract ingredients from selected meals
    all_ingredients = set()
    for meal in filtered_meals[:4]:  # Take first 4 meals
        ingredients = meal.get('Ingredients', [])
        if isinstance(ingredients, list):
            all_ingredients.update(ingredients)
    
    # Convert to list and sort
    ingredients_list = sorted(list(all_ingredients))
    
    # Add common ingredients if list is too short
    if len(ingredients_list) < 5:
        common_ingredients = ["Rice", "Oil", "Salt", "Spices", "Vegetables", "Onions", "Tomatoes", "Potatoes", "Carrots", "Capsicum"]
        ingredients_list.extend([item for item in common_ingredients if item not in ingredients_list])
    
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
        meals = load_meal_data_from_json(user_data['state'])
        if meals:
            filtered_meals = filter_meals_by_preferences(meals, user_data['diet'], user_data['medical'])
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
    user_data = user_data_store.get(user_id)
    if not user_data:
        user_data = await get_user_profile(user_id)
    
    suggested_ingredients = []
    if user_data:
        meals = load_meal_data_from_json(user_data['state'])
        if meals:
            filtered_meals = filter_meals_by_preferences(meals, user_data['diet'], user_data['medical'])
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
    user_grocery_list = grocery_lists.get(user_id, [])
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
    user_grocery_list = grocery_lists.get(user_id, [])
    
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
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👤 View Profile", callback_data="view_profile")],
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
    """Generate Zepto search link for grocery items from JSON data."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    # Get user profile
    user_data = user_data_store.get(user_id)
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
    
    # Load meals from JSON
    meals = load_meal_data_from_json(user_data['state'])
    if not meals:
        await query.edit_message_text(
            f"❌ No meal data available for {user_data['state'].title()}.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Start Over", callback_data="start_over")
            ]])
        )
        return ConversationHandler.END
    
    # Filter meals based on preferences
    filtered_meals = filter_meals_by_preferences(meals, user_data['diet'], user_data['medical'])
    
    if len(filtered_meals) < 4:
        filtered_meals = meals[:4]
    
    # Extract ingredients from selected meals
    all_ingredients = set()
    for meal in filtered_meals[:4]:  # Take first 4 meals
        ingredients = meal.get('Ingredients', [])
        if isinstance(ingredients, list):
            all_ingredients.update(ingredients)
    
    # Convert to list and sort
    ingredients_list = sorted(list(all_ingredients))
    
    # Add common ingredients if list is too short
    if len(ingredients_list) < 5:
        common_ingredients = ["Rice", "Oil", "Salt", "Spices", "Vegetables"]
        ingredients_list.extend([item for item in common_ingredients if item not in ingredients_list])
    
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
    elif query.data == "week_plan":
        return await handle_weekly_plan(update, context)
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
        return await handle_meal_rating(update, context)
    
    # Navigation
    elif query.data == "go_back":
        return await go_back(update, context)
    elif query.data == "start_over":
        return await start_over(update, context)
    
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the conversation."""
    user_id = update.effective_user.id
    if user_id in user_data_cache:
        del user_data_cache[user_id]
    
    await update.message.reply_text(
        "👋 Alright, we're done here! Hit me up with /start when you're ready to try again! ✌️"
    )
    
    return ConversationHandler.END

def main() -> None:
    """Start the bot."""
    
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
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    
    application.add_handler(conv_handler)
    
    # Run the bot until the user presses Ctrl-C
    print("🤖 Nutrio Bot is starting...")
    print("📝 Replace 'YOUR_BOT_TOKEN' with your actual Telegram bot token")
    print("🚀 Run the bot with: python main.py")
    print("📁 Make sure karnataka.json and maharastra.json are in the same folder")
    print("🔥 Firebase integration available" if FIREBASE_AVAILABLE else "⚠️ Firebase not available - install firebase-admin")
    
    # Test Firebase connection if available
    if FIREBASE_AVAILABLE:
        print("🧪 Testing Firebase connection...")
        try:
            # Create test data for demonstration
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            test_data_result = loop.run_until_complete(create_test_data())
            if test_data_result:
                print("✅ Test data created! Check Firebase Console now!")
            else:
                print("❌ Failed to create test data")
            
            loop.close()
        except Exception as e:
            print(f"❌ Firebase test error: {e}")
    
    # Uncomment the line below when you have your bot token
    application.run_polling()

if __name__ == '__main__':
    main() 
