#!/usr/bin/env python3
"""
AI-Powered Meal Plan Generator for Nutriomeal Bot
Uses CSV data to generate personalized meal plans with AI-like personalization
"""

import json
import logging
import re
import os
import csv
from typing import Dict, Any, Optional, List
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Security configuration - Updated to include all diet types used in the app
ALLOWED_DIET_TYPES = {
    'vegetarian', 'veg', 'non-vegetarian', 'non-veg', 'vegan', 
    'keto', 'eggitarian', 'jain', 'mixed', 'paleo', 'mediterranean', 
    'dash', 'low-carb', 'high-protein', 'balanced'
}
ALLOWED_MEAL_TYPES = {'breakfast', 'lunch', 'dinner', 'snack', 'morning snack', 'evening snack'}
MAX_MEALS_PER_REQUEST = 50
MAX_FILE_SIZE_MB = 10

# In-memory cache for performance
meal_data_cache: Dict[str, List[Dict[str, Any]]] = {}
MAX_CACHE_SIZE = 100

# Region-specific food templates (for AI-like personalization)
REGIONAL_FOODS = {
    "maharashtra": [
        "Poha", "Varan Bhaat", "Misal Pav", "Puran Poli", "Bharli Vangi", 
        "Sabudana Khichdi", "Kothimbir Vadi", "Modak", "Shrikhand", "Batata Vada"
    ],
    "karnataka": [
        "Bisi Bele Bath", "Ragi Mudde", "Neer Dosa", "Mangalore Fish Curry", 
        "Mangalore Chicken Curry", "Karnataka Sambar", "Ragi Roti", "Akki Roti", 
        "Mangalore Cucumber Curry", "Karnataka Style Rasam"
    ],
    "tamil nadu": [
        "Upma", "Rasam", "Sambar", "Idli", "Dosa", "Pongal", "Kootu", 
        "Avial", "Thayir Sadam", "Poriyal"
    ],
    "andhra pradesh": [
        "Pesarattu", "Gongura Pachadi", "Andhra Chicken Curry", "Andhra Fish Curry", 
        "Pulihora", "Gutti Vankaya", "Andhra Sambar", "Andhra Rasam", 
        "Andhra Style Biryani", "Andhra Pickles"
    ],
    "kerala": [
        "Appam", "Puttu", "Kerala Fish Curry", "Kerala Chicken Curry", 
        "Avial", "Thoran", "Kerala Sambar", "Kerala Rasam", "Malabar Biryani", 
        "Kerala Style Beef Curry"
    ],
    "punjab": [
        "Sarson da Saag", "Makki di Roti", "Butter Chicken", "Punjabi Chole", 
        "Punjabi Kadhi", "Punjabi Rajma", "Punjabi Dal", "Punjabi Aloo Paratha", 
        "Punjabi Lassi", "Punjabi Paneer"
    ],
    "bengal": [
        "Machher Jhol", "Aloo Posto", "Bengali Fish Curry", "Bengali Chicken Curry", 
        "Bengali Dal", "Bengali Aloo Bhaja", "Bengali Chutney", "Bengali Rasam", 
        "Bengali Biryani", "Bengali Sweets"
    ],
    "gujarat": [
        "Dhokla", "Khandvi", "Gujarati Kadhi", "Gujarati Dal", "Gujarati Roti", 
        "Gujarati Sabzi", "Gujarati Khichdi", "Gujarati Farsan", "Gujarati Sweets", 
        "Gujarati Pickles"
    ],
    "rajasthan": [
        "Dal Baati Churma", "Gatte ki Sabzi", "Rajasthani Kadhi", "Rajasthani Dal", 
        "Rajasthani Roti", "Rajasthani Sabzi", "Rajasthani Khichdi", "Rajasthani Sweets", 
        "Rajasthani Pickles", "Rajasthani Chutney"
    ]
}

def load_meal_data_from_csv(diet_type: str = None, meal_type: str = None, max_meals: int = MAX_MEALS_PER_REQUEST) -> List[Dict[str, Any]]:
    """
    Load meal data from CSV file with security measures and filtering.
    
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
            return get_fallback_meal_data()
        
        file_size_mb = csv_path.stat().st_size / (1024 * 1024)
        if file_size_mb > MAX_FILE_SIZE_MB:
            logger.error(f"CSV file too large: {file_size_mb:.2f}MB (max: {MAX_FILE_SIZE_MB}MB)")
            return get_fallback_meal_data()
        
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
        
        with open(csv_path, 'r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            
            for row in reader:
                # Security: Limit number of meals processed
                if meals_found >= max_meals:
                    break
                
                # Security: Validate row data
                if not validate_csv_row(row):
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
        
        # Cache the results
        if len(meals) > 0:
            meal_data_cache[cache_key] = meals
            # Clean cache if too large
            if len(meal_data_cache) > MAX_CACHE_SIZE:
                cleanup_cache(meal_data_cache)
        
        logger.info(f"Loaded {len(meals)} meals from CSV (diet: {diet_type}, meal: {meal_type})")
        return meals if meals else get_fallback_meal_data()
        
    except Exception as e:
        logger.error(f"Error loading meal data from CSV: {e}")
        return get_fallback_meal_data()

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

def cleanup_cache(cache: Dict[str, Any]) -> None:
    """Clean up cache to prevent memory issues with improved error handling."""
    try:
        if len(cache) > MAX_CACHE_SIZE:
            # Remove oldest entries
            keys_to_remove = list(cache.keys())[:len(cache) - MAX_CACHE_SIZE + 10]
            for key in keys_to_remove:
                del cache[key]
            logger.info(f"Cleaned cache, removed {len(keys_to_remove)} entries")
    except Exception as e:
        logger.error(f"Error during cache cleanup: {e}")
        # Fallback: clear cache if cleanup fails
        try:
            cache.clear()
            logger.warning("Cache cleared due to cleanup error")
        except Exception as clear_error:
            logger.error(f"Failed to clear cache: {clear_error}")

def get_fallback_meal_data() -> List[Dict[str, Any]]:
    """Provide fallback meal data when CSV is unavailable."""
    logger.info("Using fallback meal data")
    
    fallback_meals = [
        {
            "Food Item": "Vegetable Pulao",
            "Ingredients": ["Rice", "Mixed Vegetables", "Oil", "Spices"],
            "approx_calories": 350,
            "Health Impact": "Good source of fiber and vitamins",
            "Calorie Level": "medium",
            "Category": "Lunch",
            "Region": "India",
            "SpecialNote": "Vegetarian option"
        },
        {
            "Food Item": "Dal Khichdi",
            "Ingredients": ["Rice", "Lentils", "Ghee", "Spices"],
            "approx_calories": 400,
            "Health Impact": "Complete protein and easy to digest",
            "Calorie Level": "medium",
            "Category": "Dinner",
            "Region": "India",
            "SpecialNote": "Comfort food"
        },
        {
            "Food Item": "Fruit Bowl",
            "Ingredients": ["Apple", "Banana", "Orange", "Grapes"],
            "approx_calories": 150,
            "Health Impact": "Rich in vitamins and antioxidants",
            "Calorie Level": "low",
            "Category": "Snack",
            "Region": "India",
            "SpecialNote": "Healthy snack option"
        }
    ]
    
    return fallback_meals

def get_age_based_tone(age: int) -> Dict[str, str]:
    """
    Get tone and style based on user's age.
    
    Args:
        age: User's age
        
    Returns:
        Dict with tone description and emoji style
    """
    if age < 25:
        return {
            "tone": "conversational, chill, Gen-Z tone",
            "emoji_style": "lots of emojis and casual language",
            "greeting": "Hey there! 😊",
            "closing": "Hope you love this plan! ✨"
        }
    elif 25 <= age <= 40:
        return {
            "tone": "calm, balanced, practical tone",
            "emoji_style": "moderate emojis, professional yet friendly",
            "greeting": "Hello! 👋",
            "closing": "Enjoy your healthy meals! 🌟"
        }
    else:
        return {
            "tone": "respectful, slightly formal, health-conscious tone",
            "emoji_style": "minimal emojis, respectful and informative",
            "greeting": "Good day! 🌸",
            "closing": "Wishing you good health! 🙏"
        }

def get_regional_foods(state: str) -> List[str]:
    """
    Get regional food suggestions based on state.
    
    Args:
        state: User's state (lowercase)
        
    Returns:
        List of regional food items
    """
    state_lower = state.lower().strip()
    return REGIONAL_FOODS.get(state_lower, [])

def build_prompt_from_profile(profile: Dict[str, Any]) -> str:
    """
    Build AI-like prompt from user profile for CSV-based meal selection.
    
    Args:
        profile: User profile dictionary
        
    Returns:
        Formatted prompt string for meal selection
    """
    name = profile.get('name', 'User')
    age = profile.get('age', 30)
    gender = profile.get('gender', 'Not specified')
    diet = profile.get('diet', 'Mixed')
    state = profile.get('state', 'India')
    activity = profile.get('activity', 'Moderate')
    medical = profile.get('medical', 'None')
    
    # Get age-based tone
    tone_info = get_age_based_tone(age)
    
    # Get regional foods
    regional_foods = get_regional_foods(state)
    regional_food_text = ""
    if regional_foods:
        regional_food_text = f" Include regional dishes like {', '.join(regional_foods[:3])}."
    
    # Build concise prompt for CSV-based selection
    prompt = f"""Create a {diet.lower()} Indian meal plan for {name} ({age} years, {gender}, {state.title()}, {activity} activity).

**Health Focus:**
- ONLY healthy, whole foods
- NO pav, bread, fried items, sweets, or processed foods
- Consider: {medical}

**Format (PLAIN TEXT, under 300 words, EXACT STRUCTURE):**
{name}'s Daily Meal Plan

🌅 BREAKFAST (7-9 AM)
[Meal name] - [Calories]

☀️ LUNCH (12-2 PM)  
[Meal name] - [Calories]

🌙 DINNER (7-9 PM)
[Meal name] - [Calories]

🍎 SNACK (3-4 PM)
[Snack name] - [Calories]

**Style:** {tone_info['tone']} {regional_food_text}
**Opening:** {tone_info['greeting']}
**Closing:** {tone_info['closing']}

IMPORTANT: Use EXACTLY this format with emojis and dashes for easy parsing."""
    
    return prompt

def format_telegram_message(response: str) -> str:
    """
    Format AI-like response for plain text (no Markdown).
    
    Args:
        response: Raw response
        
    Returns:
        Clean plain text string
    """
    if not response:
        return ""
    
    # Remove any potentially problematic characters
    formatted = response.strip()
    
    # Clean up any backslashes from response
    formatted = re.sub(r'\\', '', formatted)
    
    # Remove any remaining special characters that might cause issues
    # Keep only letters, numbers, spaces, basic punctuation, and emojis
    formatted = re.sub(r'[^\w\s\.,!?():;\-@#$%&+=<>\[\]{}|~`"\'/\\]', '', formatted)
    
    # Ensure it's not too long for Telegram
    if len(formatted) > 4000:
        formatted = formatted[:4000] + "...\n\nMessage truncated due to length"
    
    return formatted

async def save_ai_meal_to_firebase(user_id: int, meal_plan: str, db) -> bool:
    """
    Save AI-like meal plan to Firebase with retry mechanism.
    
    Args:
        user_id: Telegram user ID
        meal_plan: Generated meal plan text
        db: Firebase database instance
        
    Returns:
        True if saved successfully, False otherwise
    """
    if not db:
        return False
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            meal_ref = db.collection('users').document(str(user_id)).collection('meals').document(today)
            
            meal_data = {
                'generated_at': datetime.now().isoformat(),
                'meal_plan': meal_plan,
                'source': 'csv_ai_like',
                'word_count': len(meal_plan.split())
            }
            
            meal_ref.set(meal_data)
            logger.info(f"✅ AI-like meal plan saved to Firebase for user {user_id} (attempt {attempt + 1})")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to save AI-like meal plan to Firebase (attempt {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(1)  # Wait before retry
            else:
                logger.error(f"Failed to save meal plan after {max_retries} attempts")
                return False
    
    return False

async def generate_ai_meal_plan(profile: Dict[str, Any], user_id: int, db=None) -> Optional[str]:
    """
    Generate AI-like meal plan using CSV data with personalization.
    
    Args:
        profile: User profile dictionary
        user_id: Telegram user ID
        db: Firebase database instance (optional)
        
    Returns:
        Formatted meal plan string or None if failed
    """
    try:
        name = profile.get('name', 'User')
        age = profile.get('age', 30)
        diet = profile.get('diet_type', profile.get('diet', 'vegetarian')).lower()
        
        # Normalize diet type for consistent handling
        if diet in ['veg', 'vegetarian']:
            diet = 'vegetarian'
        elif diet in ['non-veg', 'non-vegetarian']:
            diet = 'non-vegetarian'
        
        state = profile.get('state', 'India')
        medical = profile.get('medical', 'None')
        activity = profile.get('activity', 'Moderate')
        
        # Get age-based tone
        tone_info = get_age_based_tone(age)
        
        # Get regional foods for personalization
        regional_foods = get_regional_foods(state)
        
        # Load meals from CSV based on diet
        meals = load_meal_data_from_csv(diet_type=diet, max_meals=50)
        if not meals:
            logger.warning(f"⚠️ No meals found for diet: {diet}")
            return None
        
        # Filter meals by medical conditions if any
        if medical and medical.lower() != 'none':
            filtered_meals = filter_meals_by_medical_condition(meals, medical)
        else:
            filtered_meals = meals
        
        # Prioritize regional foods if available
        if regional_foods:
            regional_meals = [m for m in filtered_meals if any(food.lower() in m.get('Food Item', '').lower() for food in regional_foods)]
            if regional_meals:
                filtered_meals = regional_meals + [m for m in filtered_meals if m not in regional_meals]
        
        # Select meals for different times of day
        breakfast_meals = [m for m in filtered_meals if m.get('Category', '').lower() in ['breakfast', 'morning snack']]
        lunch_meals = [m for m in filtered_meals if m.get('Category', '').lower() in ['lunch']]
        dinner_meals = [m for m in filtered_meals if m.get('Category', '').lower() in ['dinner']]
        snack_meals = [m for m in filtered_meals if m.get('Category', '').lower() in ['snack', 'evening snack']]
        
        # Select random meals for each category
        import random
        selected_meals = {
            'breakfast': random.choice(breakfast_meals) if breakfast_meals else random.choice(filtered_meals[:10]),
            'lunch': random.choice(lunch_meals) if lunch_meals else random.choice(filtered_meals[10:20]),
            'dinner': random.choice(dinner_meals) if dinner_meals else random.choice(filtered_meals[20:30]),
            'snack': random.choice(snack_meals) if snack_meals else random.choice(filtered_meals[30:40])
        }
        
        # Calculate total calories
        total_calories = sum(meal.get('approx_calories', 200) for meal in selected_meals.values())
        
        # Build AI-like meal plan message
        meal_message = f"{tone_info['greeting']}\n\n"
        meal_message += f"{name}'s Daily Meal Plan\n\n"
        
        meal_types = [
            ("🌅 BREAKFAST (7-9 AM)", selected_meals['breakfast']),
            ("☀️ LUNCH (12-2 PM)", selected_meals['lunch']),
            ("🌙 DINNER (7-9 PM)", selected_meals['dinner']),
            ("🍎 SNACK (3-4 PM)", selected_meals['snack'])
        ]
        
        for meal_type, meal in meal_types:
            if meal:
                meal_name = meal.get('Food Item', 'Unknown')
                calories = meal.get('approx_calories', 200)
                
                meal_message += f"{meal_type}\n{meal_name} - {int(calories)}\n\n"
        
        meal_message += f"**Total Calories:** ~{total_calories}\n\n"
        meal_message += f"{tone_info['closing']}\n\n"
        meal_message += "*💡 All meals are carefully selected from our healthy database based on your preferences!*"
        
        # Format for Telegram
        formatted_response = format_telegram_message(meal_message)
        if not formatted_response:
            logger.warning(f"⚠️ Meal plan formatting failed for user {user_id}")
            return None
        
        # Save to Firebase if available
        if db:
            await save_ai_meal_to_firebase(user_id, formatted_response, db)
        
        logger.info(f"✅ AI-like meal plan generated successfully for user {user_id}")
        return formatted_response
        
    except Exception as e:
        logger.error(f"❌ Error generating AI-like meal plan: {e}")
        return None

def filter_meals_by_medical_condition(meals: List[Dict[str, Any]], medical_condition: str) -> List[Dict[str, Any]]:
    """
    Filter meals based on medical conditions.
    
    Args:
        meals: List of meal dictionaries
        medical_condition: Medical condition to filter by
        
    Returns:
        Filtered list of meals
    """
    condition_lower = medical_condition.lower()
    
    # Define condition-specific filters
    filters = {
        'diabetes': ['low-carb', 'diabetic-friendly', 'sugar-free'],
        'heart': ['low-fat', 'heart-healthy', 'low-sodium'],
        'blood pressure': ['low-sodium', 'heart-healthy'],
        'weight loss': ['low-calorie', 'high-protein'],
        'pregnancy': ['nutrient-rich', 'pregnancy-safe'],
        'lactose intolerant': ['dairy-free', 'lactose-free'],
        'gluten free': ['gluten-free'],
        'vegetarian': ['vegetarian'],
        'vegan': ['vegan']
    }
    
    # Find matching filter
    matching_filter = None
    for condition, keywords in filters.items():
        if condition in condition_lower:
            matching_filter = keywords
            break
    
    if not matching_filter:
        return meals  # Return all meals if no specific condition found
    
    # Filter meals based on health impact
    filtered_meals = []
    for meal in meals:
        health_impact = meal.get('Health Impact', '').lower()
        if any(keyword in health_impact for keyword in matching_filter):
            filtered_meals.append(meal)
    
    return filtered_meals if filtered_meals else meals

async def generate_ingredient_based_meal_plan(profile: Dict[str, Any], ingredients: str, user_id: int, db=None, meal_type: str = "meal") -> Optional[str]:
    """
    Generate ingredient-based meal plan using CSV data.
    
    Args:
        profile: User profile dictionary
        ingredients: Available ingredients (comma-separated)
        user_id: User ID for logging
        db: Firebase database reference (optional)
        meal_type: Type of meal (breakfast, lunch, dinner, snack)
        
    Returns:
        Formatted meal plan string or None if failed
    """
    try:
        logger.info(f"🔧 Generating {meal_type} using ingredients: {ingredients}")
        
        name = profile.get('name', 'User')
        age = profile.get('age', 30)
        diet = profile.get('diet_type', profile.get('diet', 'vegetarian')).lower()
        
        # Get age-based tone
        tone_info = get_age_based_tone(age)
        
        # Load meals from CSV
        meals = load_meal_data_from_csv(diet_type=diet, meal_type=meal_type, max_meals=30)
        if not meals:
            return None
        
        # Filter meals by available ingredients
        ingredient_list = [ing.strip().lower() for ing in ingredients.split(',')]
        matching_meals = []
        
        for meal in meals:
            meal_ingredients = [ing.lower() for ing in meal.get('Ingredients', [])]
            # Check if any ingredient matches
            if any(ing in ' '.join(meal_ingredients) for ing in ingredient_list):
                matching_meals.append(meal)
        
        if not matching_meals:
            # Fallback to any meal if no ingredient matches
            matching_meals = meals[:5]
        
        # Select best matching meal
        import random
        selected_meal = random.choice(matching_meals)
        
        # Build meal suggestion
        meal_name = selected_meal.get('Food Item', 'Unknown')
        calories = selected_meal.get('approx_calories', 200)
        health_impact = selected_meal.get('Health Impact', '')
        
        meal_message = f"{tone_info['greeting']}\n\n"
        meal_message += f"{name}'s {meal_type.title()} with Available Ingredients\n\n"
        meal_message += f"🍽️ {meal_type.upper()} SUGGESTION\n{meal_name} - {int(calories)}\n"
        if health_impact:
            meal_message += f"{health_impact}\n"
        meal_message += f"\n{tone_info['closing']}\n\n"
        meal_message += "Keep it simple and use only the provided ingredients."
        
        # Format for Telegram
        formatted_response = format_telegram_message(meal_message)
        
        # Save to Firebase if available
        if db:
            await save_ai_meal_to_firebase(user_id, formatted_response, db)
        
        logger.info(f"✅ Ingredient-based meal plan generated successfully for user {user_id}")
        return formatted_response
        
    except Exception as e:
        logger.error(f"❌ Error generating ingredient-based meal plan: {e}")
        return None

def get_fallback_meal_message(profile: Dict[str, Any], streak_data: Dict[str, Any]) -> str:
    """
    Generate fallback meal message when CSV data is unavailable.
    
    Args:
        profile: User profile dictionary
        streak_data: User streak information
        
    Returns:
        Fallback meal message
    """
    name = profile.get('name', 'User')
    diet = profile.get('diet_type', profile.get('diet', 'vegetarian')).title()
    medical = profile.get('medical', 'None')
    activity = profile.get('activity', 'Moderate')
    
    return f"""🍽️ **Your Daily Meal Plan - Custom Made!** (Fallback)

👤 **Made for:** {name}'s profile
🥬 **Diet:** {diet}
🏥 **Medical:** {medical.title()}
🏃 **Activity:** {activity.title()}
🔥 **Streak:** {streak_data.get('streak_count', 0)} days | 🎯 **Points:** {streak_data.get('streak_points_total', 0)}

*Note: Using our curated meal database. Your personalized meal plan is ready!* 🌟"""

# Legacy function for backward compatibility
async def generate_csv_based_meal_plan(profile: Dict[str, Any], user_id: int, db=None) -> Optional[str]:
    """
    Legacy function that now uses AI-like meal generation.
    
    Args:
        profile: User profile dictionary
        user_id: Telegram user ID
        db: Firebase database instance (optional)
        
    Returns:
        Formatted meal plan string or None if failed
    """
    logger.info(f"🔄 Using AI-like meal generation for user {user_id}")
    return await generate_ai_meal_plan(profile, user_id, db) 