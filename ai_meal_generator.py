#!/usr/bin/env python3
"""
AI-Powered Meal Generator
Uses AI to generate personalized meal plans from static database
"""

import logging
import csv
import json
import asyncio
import aiohttp
import os
from typing import Dict, Any, List, Optional
from pathlib import Path
from datetime import datetime

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
ALLOWED_DIET_TYPES = {
    'vegetarian', 'veg', 'non-vegetarian', 'non-veg', 'vegan', 
    'keto', 'eggitarian', 'jain', 'mixed', 'paleo', 'mediterranean', 
    'dash', 'low-carb', 'high-protein', 'balanced'
}
ALLOWED_MEAL_TYPES = {'breakfast', 'lunch', 'dinner', 'snack', 'morning snack', 'evening snack'}
MAX_MEALS_PER_REQUEST = 50
MAX_CACHE_SIZE = 1000

# AI Configuration
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')
AI_AVAILABLE = bool(OPENROUTER_API_KEY)

# Cache for performance
meal_data_cache: Dict[str, List[Dict[str, Any]]] = {}
user_meal_counter: Dict[int, int] = {}  # Track meal position for each user

def cleanup_cache(cache: Dict[str, Any]) -> None:
    """Clean up cache to prevent memory issues."""
    try:
        if len(cache) > MAX_CACHE_SIZE:
            keys_to_remove = list(cache.keys())[:len(cache) - MAX_CACHE_SIZE + 10]
            for key in keys_to_remove:
                del cache[key]
            logger.info(f"Cleaned cache, removed {len(keys_to_remove)} entries")
    except Exception as e:
        logger.error(f"Error during cache cleanup: {e}")
        try:
            cache.clear()
            logger.warning("Cache cleared due to cleanup error")
        except Exception as clear_error:
            logger.error(f"Failed to clear cache: {clear_error}")

def get_fallback_meal_data() -> List[Dict[str, Any]]:
    """Get fallback meal data when CSV/JSON loading fails."""
    return [
        {
            'name': 'Healthy Breakfast Bowl',
            'calories': 300,
            'ingredients': ['Oats', 'Banana', 'Honey', 'Nuts'],
            'meal_type': 'breakfast'
        },
        {
            'name': 'Nutritious Lunch Plate',
            'calories': 450,
            'ingredients': ['Brown Rice', 'Vegetables', 'Dal', 'Salad'],
            'meal_type': 'lunch'
        },
        {
            'name': 'Light Dinner',
            'calories': 350,
            'ingredients': ['Roti', 'Sabzi', 'Curd', 'Salad'],
            'meal_type': 'dinner'
        },
        {
            'name': 'Healthy Snack',
            'calories': 150,
            'ingredients': ['Fruits', 'Nuts', 'Seeds'],
            'meal_type': 'snack'
        }
    ]

def load_meal_data_from_csv(diet_type: str = None, meal_type: str = None, max_meals: int = MAX_MEALS_PER_REQUEST) -> List[Dict[str, Any]]:
    """Load meal data from CSV file - static version."""
    try:
        csv_path = Path("all_mealplans_merged.csv")
        if not csv_path.exists():
            logger.error("CSV file not found")
            return get_fallback_meal_data()
        
        # Check cache first
        cache_key = f"{diet_type}_{meal_type}_{max_meals}"
        if cache_key in meal_data_cache:
            return meal_data_cache[cache_key]
        
        meals = []
        meals_found = 0
        
        with open(csv_path, 'r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            
            for row in reader:
                if meals_found >= max_meals:
                    break
                
                # Simple validation
                if not row.get('Dish Combo') or not row.get('Diet Type'):
                    continue
                
                # Apply filters
                if diet_type and row.get('Diet Type', '').lower() != diet_type.lower():
                    continue
                
                if meal_type and row.get('Meal', '').lower() != meal_type.lower():
                    continue
                
                # Convert to standard format
                meal = {
                    'name': row.get('Dish Combo', 'Unknown'),
                    'calories': int(row.get('Calories (kcal)', 0)),
                    'ingredients': row.get('Ingredients (per serving)', '').split(',') if row.get('Ingredients (per serving)') else [],
                    'meal_type': row.get('Meal', 'general'),
                    'diet_type': row.get('Diet Type', 'general')
                }
                
                meals.append(meal)
                meals_found += 1
        
        # Cache results
        if meals:
            meal_data_cache[cache_key] = meals
            cleanup_cache(meal_data_cache)
        
        return meals if meals else get_fallback_meal_data()
        
    except Exception as e:
        logger.error(f"Error loading CSV data: {e}")
        return get_fallback_meal_data()

def load_meal_data_from_json(state: str) -> List[Dict[str, Any]]:
    """Load meal data from JSON files - static version."""
    try:
        if state.lower() == "karnataka":
            with open("karnataka.json", 'r', encoding='utf-8') as file:
                data = json.load(file)
                return data if isinstance(data, list) else []
        
        elif state.lower() == "andhra":
            with open("andhra_dishes.json", 'r', encoding='utf-8') as file:
                data = json.load(file)
                # Flatten the nested structure
                meals = []
                for diet_type, diet_data in data.get('DietTypes', {}).items():
                    for meal_category, meal_list in diet_data.items():
                        for meal in meal_list:
                            meals.append({
                                'name': meal.get('Food Item', 'Unknown'),
                                'calories': meal.get('Calories', 0),
                                'ingredients': meal.get('Ingredients', []),
                                'meal_type': meal_category,
                                'diet_type': diet_type
                            })
                return meals
        
        return []
        
    except Exception as e:
        logger.error(f"Error loading JSON data for {state}: {e}")
        return []

def format_meal_plan(meals: List[Dict[str, Any]], user_name: str, age: int, diet: str, state: str, user_id: int = 0) -> str:
    """Format meal plan - static version, no AI."""
    
    # Get user's meal counter for sequential selection
    if user_id not in user_meal_counter:
        user_meal_counter[user_id] = 0
    
    counter = user_meal_counter[user_id]
    
    # Simple meal categorization
    breakfast_meals = [m for m in meals if 'breakfast' in m.get('meal_type', '').lower()]
    lunch_meals = [m for m in meals if 'lunch' in m.get('meal_type', '').lower()]
    dinner_meals = [m for m in meals if 'dinner' in m.get('meal_type', '').lower()]
    snack_meals = [m for m in meals if 'snack' in m.get('meal_type', '').lower()]
    
    # Select meals serially (in order) with user-specific offset
    breakfast = breakfast_meals[counter % len(breakfast_meals)] if breakfast_meals else meals[counter % len(meals)] if meals else None
    lunch = lunch_meals[counter % len(lunch_meals)] if lunch_meals else meals[(counter + 1) % len(meals)] if len(meals) > 1 else None
    dinner = dinner_meals[counter % len(dinner_meals)] if dinner_meals else meals[(counter + 2) % len(meals)] if len(meals) > 2 else None
    snack = snack_meals[counter % len(snack_meals)] if snack_meals else meals[(counter + 3) % len(meals)] if len(meals) > 3 else None
    
    # Increment counter for next time
    user_meal_counter[user_id] = (counter + 1) % 1000  # Reset after 1000 meals
    
    # Simple age-based tone
    if age < 25:
        tone = "Hey there! 🌟"
    elif age < 40:
        tone = "Hello! 👋"
    else:
        tone = "Greetings! 🙏"
    
    # Format the response
    response = f"{tone} Here's your meal plan, {user_name}!\n\n"
    
    if breakfast:
        response += f"🌅 **BREAKFAST** (7-9 AM)\n{breakfast['name']} - {breakfast['calories']} calories\n\n"
    
    if lunch:
        response += f"☀️ **LUNCH** (12-2 PM)\n{lunch['name']} - {lunch['calories']} calories\n\n"
    
    if dinner:
        response += f"🌙 **DINNER** (7-9 PM)\n{dinner['name']} - {dinner['calories']} calories\n\n"
    
    if snack:
        response += f"🍎 **SNACK** (3-4 PM)\n{snack['name']} - {snack['calories']} calories\n\n"
    
    response += f"💡 All meals are from our {state} cuisine database based on your {diet} preferences!"
    
    return response

async def save_meal_to_firebase(user_id: int, meal_plan: str, db) -> bool:
    """Save meal plan to Firebase - static version."""
    if not db:
        return False
    
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        meal_ref = db.collection('users').document(str(user_id)).collection('meals').document(today)
        
        meal_data = {
            'generated_at': datetime.now().isoformat(),
            'meal_plan': meal_plan,
            'source': 'static_database',
            'word_count': len(meal_plan.split())
        }
        
        meal_ref.set(meal_data)
        logger.info(f"Meal plan saved to Firebase for user {user_id}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to save meal plan: {e}")
        return False

async def generate_meal_plan(profile: Dict[str, Any], user_id: int, db=None) -> Optional[str]:
    """Generate meal plan - static version, no AI."""
    
    try:
        # Extract user info
        name = profile.get('name', 'User')
        age = profile.get('age', 30)
        diet = profile.get('diet_type', profile.get('diet', 'vegetarian')).lower()
        state = profile.get('state', 'India')
        
        # Normalize diet type to match CSV values
        if diet in ['veg', 'vegetarian']:
            diet = 'Vegetarian'
        elif diet in ['non-veg', 'non-vegetarian']:
            diet = 'Non-Vegetarian'
        elif diet == 'vegan':
            diet = 'Vegan'
        elif diet == 'jain':
            diet = 'Jain'
        elif diet == 'eggitarian':
            diet = 'Eggitarian'
        elif diet == 'keto':
            diet = 'Keto'
        elif diet == 'mixed':
            diet = 'Mixed'
        
        # Load meals from static database
        if state.lower() == "maharashtra":
            meals = load_meal_data_from_csv(diet_type=diet, max_meals=20)
        else:
            meals = load_meal_data_from_json(state)
            if not meals:
                meals = load_meal_data_from_csv(diet_type=diet, max_meals=20)
        
        # Format the response (no AI, just formatting)
        meal_plan = format_meal_plan(meals, name, age, diet, state, user_id)
        
        # Save to Firebase if available
        if db:
            await save_meal_to_firebase(user_id, meal_plan, db)
        
        return meal_plan
        
    except Exception as e:
        logger.error(f"Error generating meal plan: {e}")
        return "Sorry, I couldn't generate a meal plan right now. Please try again!"

def get_fallback_meal_message() -> str:
    """Get fallback message when meal generation fails."""
    return """🌅 **BREAKFAST** (7-9 AM)
Oats with fruits and nuts - 300 calories

☀️ **LUNCH** (12-2 PM)
Brown rice with dal and vegetables - 450 calories

🌙 **DINNER** (7-9 PM)
Roti with sabzi and salad - 350 calories

🍎 **SNACK** (3-4 PM)
Mixed fruits and nuts - 150 calories

💡 These are healthy fallback meals from our database!"""

def get_regional_foods(state: str) -> List[str]:
    """Get regional food suggestions - static version."""
    regional_foods = {
        'maharashtra': ['Poha', 'Misal Pav', 'Vada Pav', 'Puran Poli'],
        'karnataka': ['Bisi Bele Bath', 'Ragi Mudde', 'Mangalore Fish Curry'],
        'andhra': ['Pesarattu', 'Gongura Pachadi', 'Andhra Chicken Curry'],
        'tamil nadu': ['Idli', 'Dosa', 'Sambar', 'Rasam'],
        'kerala': ['Appam', 'Kerala Fish Curry', 'Puttu'],
        'punjab': ['Makki Roti', 'Sarson Saag', 'Butter Chicken'],
        'bengal': ['Luchi', 'Aloo Posto', 'Fish Curry'],
        'gujarat': ['Dhokla', 'Khandvi', 'Thepla'],
        'rajasthan': ['Dal Baati', 'Gatte ki Sabzi', 'Laal Maas']
    }
    
    return regional_foods.get(state.lower(), ['Healthy Indian Food'])

def generate_ingredient_based_meal_plan(ingredients: List[str], diet_type: str, state: str) -> str:
    """Generate ingredient-based meal plan - static version."""
    
    # Load meals from database
    meals = load_meal_data_from_csv(diet_type=diet_type, max_meals=50)
    
    # Simple ingredient matching
    matching_meals = []
    for meal in meals:
        meal_ingredients = [ing.lower() for ing in meal.get('ingredients', [])]
        for ingredient in ingredients:
            if ingredient.lower() in ' '.join(meal_ingredients):
                matching_meals.append(meal)
                break
    
    if not matching_meals:
        matching_meals = meals[:4]  # Fallback to first 4 meals
    
    # Format response
    response = f"🍽️ **Meal Suggestions for your ingredients:**\n\n"
    
    for i, meal in enumerate(matching_meals[:4], 1):
        response += f"{i}. **{meal['name']}** - {meal['calories']} calories\n"
        response += f"   Ingredients: {', '.join(meal['ingredients'][:3])}...\n\n"
    
    response += f"💡 Based on your {diet_type} preferences and {state} cuisine!"
    
    return response

# Legacy function names for compatibility
async def generate_ai_meal_plan(profile: Dict[str, Any], user_id: int, db=None) -> Optional[str]:
    """Generate AI-powered meal plan using static database as context."""
    try:
        if not AI_AVAILABLE:
            logger.warning("AI not available, using static meal generation")
            return await generate_meal_plan(profile, user_id, db)
        
        # Extract user data
        name = profile.get('name', 'User')
        age = profile.get('age', 25)
        diet = profile.get('diet_type', profile.get('diet', 'vegetarian')).lower()
        state = profile.get('state', 'maharashtra').lower()
        medical = profile.get('medical', 'None')
        activity = profile.get('activity', 'Sedentary')
        
        # Normalize diet type
        if diet == 'veg':
            diet = 'vegetarian'
        elif diet == 'non-veg':
            diet = 'non-vegetarian'
        
        # Load meals from static database for context
        if state.lower() == "maharashtra":
            meals = load_meal_data_from_csv(diet_type=diet.title(), max_meals=20)
        else:
            meals = load_meal_data_from_json(state)
            if not meals:
                meals = load_meal_data_from_csv(diet_type=diet.title(), max_meals=20)
        
        # Prepare meal context for AI
        meal_context = []
        for meal in meals[:10]:  # Use first 10 meals as context
            meal_context.append({
                'name': meal.get('Food Item', meal.get('name', 'Unknown')),
                'calories': meal.get('approx_calories', 200),
                'ingredients': meal.get('Ingredients', []),
                'category': meal.get('Category', 'General')
            })
        
        # Build AI prompt
        prompt = f"""You are a nutrition expert creating personalized meal plans. 

User Profile:
- Name: {name}
- Age: {age}
- Diet: {diet.title()}
- Region: {state.title()}
- Medical: {medical}
- Activity: {activity}

Available meals from {state.title()} cuisine ({diet} diet):
{json.dumps(meal_context, indent=2)}

Create a personalized daily meal plan with 4 meals (Breakfast, Lunch, Dinner, Snack) using the available meals above. 

Requirements:
1. Use only meals from the provided list
2. Ensure variety and balance
3. Consider the user's age, diet, and activity level
4. Format response cleanly without excessive emojis
5. Include calories for each meal
6. Make it personal and engaging

Format the response as:
**Daily Meal Plan**

**Profile:** [Name]
**Region:** [State]
**Diet:** [Diet Type]
**Medical:** [Medical Condition]
**Activity:** [Activity Level]

────────────────────────────────────────

**Breakfast**
[Meal Name]
Calories: [Number]
[Brief description if needed]

**Lunch**
[Meal Name]
Calories: [Number]

**Dinner**
[Meal Name]
Calories: [Number]

**Snack**
[Meal Name]
Calories: [Number]

────────────────────────────────────────
**Total Calories:** [Sum]

*Personalized for your health needs*"""

        # Call AI API
        async with aiohttp.ClientSession() as session:
            headers = {
                'Authorization': f'Bearer {OPENROUTER_API_KEY}',
                'Content-Type': 'application/json',
                'HTTP-Referer': 'https://nutriobot.com',
                'X-Title': 'NutrioBot'
            }
            
            data = {
                'model': 'openai/gpt-3.5-turbo',
                'messages': [
                    {'role': 'system', 'content': 'You are a helpful nutrition expert.'},
                    {'role': 'user', 'content': prompt}
                ],
                'max_tokens': 1000,
                'temperature': 0.7
            }
            
            async with session.post('https://openrouter.ai/api/v1/chat/completions', 
                                  headers=headers, json=data) as response:
                if response.status == 200:
                    result = await response.json()
                    ai_response = result['choices'][0]['message']['content']
                    
                    # Save to Firebase if available
                    if db:
                        await save_meal_to_firebase(user_id, ai_response, db)
                    
                    return ai_response
                else:
                    logger.error(f"AI API error: {response.status}")
                    # Fallback to static generation
                    return await generate_meal_plan(profile, user_id, db)
        
    except Exception as e:
        logger.error(f"Error in AI meal generation: {e}")
        # Fallback to static generation
        return await generate_meal_plan(profile, user_id, db)

async def save_ai_meal_to_firebase(user_id: int, meal_plan: str, db) -> bool:
    """Save AI-generated meal plan to Firebase."""
    return await save_meal_to_firebase(user_id, meal_plan, db) 