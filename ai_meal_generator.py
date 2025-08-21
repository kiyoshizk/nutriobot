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
ALLOWED_MEAL_TYPES = {'breakfast', 'lunch', 'dinner', 'snack', 'morning snack', 'evening snack', 'day total'}
MAX_MEALS_PER_REQUEST = 50
MAX_CACHE_SIZE = 1000

# AI Configuration
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')
AI_AVAILABLE = bool(OPENROUTER_API_KEY)

# Medical condition mapping for accurate meal filtering
MEDICAL_CONDITION_MAPPING = {
    'diabetes': {
        'keywords': ['diabetes', 'diabetic', 'blood sugar', 'glucose'],
        'avoid': ['high sugar', 'refined carbs', 'sweet', 'jaggery', 'honey'],
        'prefer': ['low glycemic', 'fiber rich', 'complex carbs', 'protein'],
        'max_carbs': 45,  # grams per meal
        'max_calories': 400
    },
    'thyroid': {
        'keywords': ['thyroid', 'hypothyroid', 'hyperthyroid'],
        'avoid': ['goitrogenic foods', 'raw cabbage', 'soy'],
        'prefer': ['iodine rich', 'selenium rich', 'protein rich'],
        'max_calories': 500
    },
    'heart': {
        'keywords': ['heart', 'cardiac', 'cardiovascular', 'bp', 'blood pressure'],
        'avoid': ['high sodium', 'fried', 'trans fat', 'saturated fat'],
        'prefer': ['low sodium', 'heart healthy', 'omega 3', 'fiber'],
        'max_sodium': 500,  # mg per meal
        'max_fat': 15  # grams per meal
    },
    'obesity': {
        'keywords': ['obesity', 'overweight', 'weight loss'],
        'avoid': ['high calorie', 'fried', 'sweet'],
        'prefer': ['low calorie', 'high protein', 'fiber rich'],
        'max_calories': 300
    },
    'kidney': {
        'keywords': ['kidney', 'renal', 'creatinine'],
        'avoid': ['high protein', 'high potassium', 'high sodium'],
        'prefer': ['low protein', 'low potassium', 'low sodium'],
        'max_protein': 15,  # grams per meal
        'max_calories': 350
    },
    'liver': {
        'keywords': ['liver', 'hepatic'],
        'avoid': ['high fat', 'fried', 'alcohol'],
        'prefer': ['low fat', 'protein rich', 'antioxidant'],
        'max_fat': 10,  # grams per meal
        'max_calories': 400
    }
}

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

def filter_meals_by_medical_condition(meals: List[Dict[str, Any]], medical_condition: str) -> List[Dict[str, Any]]:
    """Filter meals based on medical condition for maximum accuracy."""
    if not medical_condition or medical_condition.lower() == 'none':
        return meals
    
    medical_condition = medical_condition.lower()
    filtered_meals = []
    
    # Find matching medical condition
    condition_config = None
    for condition, config in MEDICAL_CONDITION_MAPPING.items():
        if any(keyword in medical_condition for keyword in config['keywords']):
            condition_config = config
            break
    
    if not condition_config:
        return meals  # Return all meals if no specific condition found
    
    for meal in meals:
        score = 0
        should_avoid = False
        
        # Check meal name and ingredients
        meal_name = meal.get('Food Item', meal.get('name', '')).lower()
        ingredients = meal.get('Ingredients', [])
        if isinstance(ingredients, str):
            ingredients = [ing.strip().lower() for ing in ingredients.split(',')]
        
        # Check for foods to avoid
        for avoid_item in condition_config.get('avoid', []):
            if avoid_item in meal_name:
                should_avoid = True
                break
            for ingredient in ingredients:
                if avoid_item in ingredient:
                    should_avoid = True
                    break
            if should_avoid:
                break
        
        if should_avoid:
            continue
        
        # Check for preferred foods
        for prefer_item in condition_config.get('prefer', []):
            if prefer_item in meal_name:
                score += 5
            for ingredient in ingredients:
                if prefer_item in ingredient:
                    score += 3
        
        # Check nutritional limits
        calories = meal.get('approx_calories', meal.get('Calories (kcal)', 200))
        carbs = meal.get('Carbs (g)', 0)
        protein = meal.get('Protein (g)', 0)
        fat = meal.get('Fat (g)', 0)
        
        # Apply medical condition limits
        if 'max_calories' in condition_config and calories > condition_config['max_calories']:
            continue
        if 'max_carbs' in condition_config and carbs > condition_config['max_carbs']:
            continue
        if 'max_protein' in condition_config and protein > condition_config['max_protein']:
            continue
        if 'max_fat' in condition_config and fat > condition_config['max_fat']:
            continue
        
        # Add meal with score
        meal['medical_score'] = score
        filtered_meals.append(meal)
    
    # Sort by medical score (highest first)
    filtered_meals.sort(key=lambda x: x.get('medical_score', 0), reverse=True)
    
    logger.info(f"Filtered {len(meals)} meals to {len(filtered_meals)} for {medical_condition}")
    return filtered_meals

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

def load_meal_data_from_csv(state: str = None, diet_type: str = None, meal_type: str = None, max_meals: int = MAX_MEALS_PER_REQUEST) -> List[Dict[str, Any]]:
    """Load meal data from CSV files based on state - static version."""
    try:
        # Determine which CSV file to load based on state
        if state:
            state_lower = state.lower()
            if state_lower == "maharashtra":
                csv_path = Path("maharastra.csv")
            elif state_lower == "karnataka":
                csv_path = Path("karnataka.csv")
            elif state_lower == "andhra":
                csv_path = Path("andhra.csv")
            else:
                # Default to maharashtra if state not recognized
                csv_path = Path("maharastra.csv")
                logger.warning(f"Unknown state '{state}', defaulting to maharashtra")
        else:
            # If no state specified, try to load from all CSV files
            csv_path = Path("maharastra.csv")
            logger.info("No state specified, defaulting to maharashtra.csv")
        
        logger.info(f"📁 [AI] Loading CSV from: {csv_path.absolute()}")
        
        if not csv_path.exists():
            logger.error(f"CSV file not found: {csv_path}")
            return get_fallback_meal_data()
        
        # Check cache first
        cache_key = f"{state}_{diet_type}_{meal_type}_{max_meals}"
        if cache_key in meal_data_cache:
            logger.info(f"📊 [AI] Returning cached meals for key: {cache_key}")
            return meal_data_cache[cache_key]
        
        logger.info(f"🔍 [AI] Loading meals for state: {state}, diet: {diet_type}, meal_type: {meal_type}")
        
        meals = []
        meals_found = 0
        
        with open(csv_path, 'r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            
            for row in reader:
                if meals_found >= max_meals:
                    break
                
                # Simple validation
                if not row.get('Dish Combo'):
                    continue
                
                # Apply filters with debug logging
                if diet_type and row.get('Diet Type', '').lower() != diet_type.lower():
                    logger.debug(f"❌ [AI] Diet filter: CSV={row.get('Diet Type', '')}, Requested={diet_type}")
                    continue
                
                if meal_type:
                    csv_meal = row.get('Meal', '').lower()
                    requested_meal = meal_type.lower()
                    
                    # Handle meal type mapping for CSV format
                    meal_mapping = {
                        'snack': ['morning snack', 'evening snack'],
                        'morning snack': ['morning snack'],
                        'evening snack': ['evening snack'],
                        'breakfast': ['breakfast'],
                        'lunch': ['lunch'],
                        'dinner': ['dinner'],
                        'day total': ['day total']
                    }
                    
                    # Check if the requested meal type matches the CSV meal
                    meal_passed = False
                    if requested_meal in meal_mapping:
                        if csv_meal in meal_mapping[requested_meal]:
                            meal_passed = True
                            logger.debug(f"✅ [AI] Meal passed mapping filter: CSV={csv_meal}, Requested={requested_meal}")
                    else:
                        # Direct comparison for other meal types
                        if csv_meal == requested_meal:
                            meal_passed = True
                            logger.debug(f"✅ [AI] Meal passed direct filter: CSV={csv_meal}, Requested={requested_meal}")
                    
                    if not meal_passed:
                        logger.debug(f"❌ [AI] Meal filter: CSV={csv_meal}, Requested={requested_meal}")
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
            logger.info(f"📊 [AI] Loaded {len(meals)} meals from CSV")
            logger.info(f"✅ [AI] Sample meals: {[m.get('name', 'Unknown') for m in meals[:3]]}")
        else:
            logger.warning(f"⚠️ [AI] No meals loaded for state: {state}, diet: {diet_type}, meal_type: {meal_type}")
            # Try loading without meal type filter to see if any meals exist
            all_meals = load_meal_data_from_csv(state=state, diet_type=diet_type, max_meals=10)
            logger.warning(f"🔍 [AI] Total meals without meal filter: {len(all_meals) if all_meals else 0}")
            if all_meals:
                logger.warning(f"🔍 [AI] Sample meals without filter: {[m.get('name', 'Unknown') for m in all_meals[:3]]}")
        
        return meals if meals else get_fallback_meal_data()
        
    except Exception as e:
        logger.error(f"Error loading CSV data: {e}")
        return get_fallback_meal_data()

def load_meal_data_from_json(state: str) -> List[Dict[str, Any]]:
    """Load meal data from CSV files - static version (legacy function name)."""
    try:
        # Since we've moved to CSV files, redirect all requests to CSV loading
        logger.info(f"Redirecting {state} request to CSV-based loading")
        return load_meal_data_from_csv(state=state)
        
    except Exception as e:
        logger.error(f"Error loading CSV data for {state}: {e}")
        return []

def format_meal_plan(meals: List[Dict[str, Any]], user_name: str, age: int, diet: str, state: str, user_id: int = 0) -> str:
    """Format meal plan - static version, no AI."""
    
    # Get user's meal counter for sequential selection
    if user_id not in user_meal_counter:
        user_meal_counter[user_id] = 0
    
    counter = user_meal_counter[user_id]
    
    # Meal categorization with proper CSV meal type mapping
    breakfast_meals = [m for m in meals if m.get('meal_type', '').lower() == 'breakfast']
    lunch_meals = [m for m in meals if m.get('meal_type', '').lower() == 'lunch']
    dinner_meals = [m for m in meals if m.get('meal_type', '').lower() == 'dinner']
    snack_meals = [m for m in meals if m.get('meal_type', '').lower() in ['morning snack', 'evening snack']]
    
    logger.info(f"🔍 [AI] Meal categorization: Breakfast={len(breakfast_meals)}, Lunch={len(lunch_meals)}, Dinner={len(dinner_meals)}, Snack={len(snack_meals)}")
    
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
        original_diet = diet
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
        
        logger.info(f"🔍 [AI] Diet mapping: original='{original_diet}' -> normalized='{diet}'")
        
        # Load meals from static database based on state
        meals = load_meal_data_from_csv(state=state, diet_type=diet, max_meals=20)
        if not meals:
            # Fallback to JSON for other states
            meals = load_meal_data_from_json(state)
        
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

async def generate_ingredient_based_meal_plan(user_data: Dict[str, Any], ingredients: str, user_id: int, db=None, meal_type: str = "meal") -> str:
    """Generate ingredient-based meal plan - BEAST MODE with AI fallback."""
    try:
        # Parse ingredients
        ingredient_list = [ing.strip().lower() for ing in ingredients.split(',') if ing.strip()]
        logger.info(f"Processing ingredients: {ingredient_list}")
        
        # Get user preferences
        diet_type = user_data.get('diet_type', user_data.get('diet', 'vegetarian')).lower()
        state = user_data.get('state', 'maharashtra').lower()
        name = user_data.get('name', 'User')
        
        # Normalize diet type
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
        csv_diet_type = diet_mapping.get(diet_type, 'Vegetarian')
        
        # 🔥 STEP 1: Search ALL static files for perfect matches
        all_meals = []
        
        # Load from CSV based on state
        csv_meals = load_meal_data_from_csv(state=state, diet_type=csv_diet_type, max_meals=100)
        all_meals.extend(csv_meals)
        
        # Load from JSON files (other states)
        json_meals = load_meal_data_from_json(state)
        if json_meals:
            all_meals.extend(json_meals)
        
        # Also load from other states for variety
        other_states = ['karnataka', 'andhra'] if state not in ['karnataka', 'andhra'] else []
        for other_state in other_states:
            other_meals = load_meal_data_from_json(other_state)
            if other_meals:
                all_meals.extend(other_meals)
        
        # 🔥 CRITICAL: Apply medical filtering for accuracy
        medical_condition = user_data.get('medical', 'None')
        if medical_condition and medical_condition.lower() != 'none':
            all_meals = filter_meals_by_medical_condition(all_meals, medical_condition)
            logger.info(f"Applied medical filtering for {medical_condition}: {len(all_meals)} meals remaining")
        
        logger.info(f"Loaded {len(all_meals)} total meals from all sources")
        
        # 🔥 STEP 2: Advanced ingredient matching with scoring
        matching_meals = []
        
        for meal in all_meals:
            score = 0
            meal_ingredients = []
            
            # Extract ingredients from meal
            if 'Ingredients' in meal:
                meal_ingredients = [ing.strip().lower() for ing in meal['Ingredients']]
            elif 'ingredients' in meal:
                meal_ingredients = [ing.strip().lower() for ing in meal['ingredients']]
            
            # Calculate match score
            meal_name = meal.get('Food Item', meal.get('name', '')).lower()
            
            for user_ingredient in ingredient_list:
                # Check meal name first (often contains main ingredients)
                if user_ingredient in meal_name:
                    score += 8  # Ingredient in meal name
                
                for meal_ingredient in meal_ingredients:
                    # Exact match
                    if user_ingredient == meal_ingredient:
                        score += 10
                    # Partial match (contains)
                    elif user_ingredient in meal_ingredient or meal_ingredient in user_ingredient:
                        score += 5
                    # Similar ingredients (common variations)
                    elif any(similar in meal_ingredient for similar in get_similar_ingredients(user_ingredient)):
                        score += 3
                
                # Check meal name for similar ingredients too
                similar_ingredients = get_similar_ingredients(user_ingredient)
                if any(sim_ing in meal_name for sim_ing in similar_ingredients):
                    score += 2  # Similar ingredient in meal name
            
            # Major bonus for meal type match (prioritize meal type)
            meal_category = meal.get('Category', '').lower()
            if meal_type.lower() in meal_category:
                score += 15  # Major bonus for exact meal type match
            elif any(meal_type_word in meal_category for meal_type_word in get_meal_type_variations(meal_type)):
                score += 10  # Bonus for meal type variations
            
            # Bonus for regional preference
            if state.lower() in meal.get('Region', '').lower():
                score += 3
            
            # 🔥 CRITICAL: Major bonus for medical safety
            medical_score = meal.get('medical_score', 0)
            score += medical_score * 2  # Double the medical score importance
            
            if score > 0:
                matching_meals.append({
                    'meal': meal,
                    'score': score,
                    'matched_ingredients': [ing for ing in ingredient_list if any(ing in meal_ing for meal_ing in meal_ingredients)]
                })
        
        # Sort by score (highest first)
        matching_meals.sort(key=lambda x: x['score'], reverse=True)
        
        # 🔥 STEP 3: Generate response based on matches
        if matching_meals:
            # Remove duplicates based on meal name
            seen_meals = set()
            unique_matches = []
            
            for match in matching_meals:
                meal_name = match['meal'].get('Food Item', match['meal'].get('name', 'Unknown')).strip()
                # Normalize meal name for better deduplication
                normalized_name = meal_name.lower().replace(' ', '').replace('-', '').replace('+', '')
                if normalized_name not in seen_meals:
                    seen_meals.add(normalized_name)
                    unique_matches.append(match)
            
            # Use top unique matches
            top_matches = unique_matches[:3]
            
            response = f"Perfect {meal_type.title()} Matches for Your Ingredients\n\n"
            response += f"Your Ingredients: {ingredients}\n"
            response += f"Meal Type: {meal_type.title()}\n"
            response += f"Diet: {diet_type.title()}\n"
            response += f"Region: {state.title()}\n\n"
            response += "─" * 40 + "\n\n"
            
            for i, match in enumerate(top_matches, 1):
                meal = match['meal']
                score = match['score']
                matched_ingredients = match['matched_ingredients']
                
                meal_name = meal.get('Food Item', meal.get('name', 'Unknown'))
                calories = meal.get('approx_calories', meal.get('calories', 200))
                ingredients_text = ', '.join(meal.get('Ingredients', meal.get('ingredients', []))[:5])
                
                response += f"{i}. {meal_name}\n"
                response += f"Category: {meal.get('Category', 'General')}\n"
                response += f"Calories: {calories}\n"
                response += f"Match Score: {score}/10\n"
                response += f"Uses: {', '.join(matched_ingredients)}\n"
                response += f"Ingredients: {ingredients_text}...\n\n"
            
            response += "─" * 40 + "\n"
            response += f"*Found {len(matching_meals)} meals using your ingredients!*"
            
            # Save to Firebase if available
            if db:
                await save_meal_to_firebase(user_id, response, db)
            
            return response
        
        # 🔥 STEP 4: AI Generation if no matches found
        else:
            logger.info("No static matches found, using AI generation")
            
            # Try to find partial matches even if no perfect matches
            partial_matches = []
            for meal in all_meals:
                meal_ingredients = [ing.lower().strip() for ing in meal.get('Ingredients', meal.get('ingredients', []))]
                meal_name = meal.get('Food Item', meal.get('name', '')).lower()
                
                # Check if any ingredient is mentioned in meal name or ingredients
                for ingredient in ingredient_list:
                    if (ingredient in meal_name or 
                        any(ingredient in ing for ing in meal_ingredients) or
                        any(ing in ingredient for ing in meal_ingredients)):
                        partial_matches.append({
                            'meal': meal,
                            'score': 5,  # Lower score for partial matches
                            'matched_ingredients': [ingredient]
                        })
                        break
            
            if partial_matches:
                # Remove duplicates from partial matches
                seen_partial = set()
                unique_partial = []
                
                for match in partial_matches:
                    meal_name = match['meal'].get('Food Item', match['meal'].get('name', 'Unknown')).strip()
                    # Normalize meal name for better deduplication
                    normalized_name = meal_name.lower().replace(' ', '').replace('-', '').replace('+', '')
                    if normalized_name not in seen_partial:
                        seen_partial.add(normalized_name)
                        unique_partial.append(match)
                
                # Use top unique partial matches
                top_partial = unique_partial[:3]
                
                response = f"Partial {meal_type.title()} Matches for Your Ingredients\n\n"
                response += f"Your Ingredients: {ingredients}\n"
                response += f"Meal Type: {meal_type.title()}\n"
                response += f"Diet: {diet_type.title()}\n"
                response += f"Region: {state.title()}\n\n"
                response += "─" * 40 + "\n\n"
                
                for i, match in enumerate(top_partial, 1):
                    meal = match['meal']
                    score = match['score']
                    matched_ingredients = match['matched_ingredients']
                    
                    meal_name = meal.get('Food Item', meal.get('name', 'Unknown'))
                    calories = meal.get('approx_calories', meal.get('calories', 200))
                    ingredients_text = ', '.join(meal.get('Ingredients', meal.get('ingredients', []))[:5])
                    
                    response += f"{i}. {meal_name}\n"
                    response += f"Category: {meal.get('Category', 'General')}\n"
                    response += f"Calories: {calories}\n"
                    response += f"Match Score: {score}/10 (Partial Match)\n"
                    response += f"Uses: {', '.join(matched_ingredients)}\n"
                    response += f"Ingredients: {ingredients_text}...\n\n"
                
                response += "─" * 40 + "\n"
                response += f"Found {len(partial_matches)} partial matches!\n\n"
                response += "💡 Tip: These meals use some of your ingredients. You may need to add more ingredients for a complete meal."
                
                # Save to Firebase if available
                if db:
                    await save_meal_to_firebase(user_id, response, db)
                
                return response
            
            # If no partial matches either, try AI or fallback
            if not AI_AVAILABLE:
                return generate_fallback_ingredient_response(ingredients, diet_type, state, meal_type)
            
            # Prepare context for AI
            context_meals = []
            for meal in all_meals[:20]:  # Use top 20 meals as context
                context_meals.append({
                    'name': meal.get('Food Item', meal.get('name', 'Unknown')),
                    'calories': meal.get('approx_calories', meal.get('calories', 200)),
                    'ingredients': meal.get('Ingredients', meal.get('ingredients', [])),
                    'category': meal.get('Category', 'General')
                })
            
            # Build AI prompt for realistic meal generation
            prompt = f"""<s>[INST] You are a nutrition expert. Create a realistic {meal_type} using these ingredients.

USER INGREDIENTS: {ingredients}
MEAL TYPE: {meal_type}
DIET: {diet_type.title()}
REGION: {state.title()}

AVAILABLE {meal_type.upper()} EXAMPLES (for reference):
{json.dumps([m for m in context_meals[:10] if meal_type.lower() in m.get('category', '').lower()], indent=2)}

INSTRUCTIONS:
1. Create a realistic {meal_type} using ONLY the provided ingredients
2. Make it a proper {meal_type} that actually exists in {state.title()} cuisine
3. Use realistic cooking methods and combinations
4. Don't create fantasy dishes - stick to real Indian {meal_type} recipes
5. If ingredients are insufficient, suggest what to add for a complete {meal_type}

FORMAT YOUR RESPONSE EXACTLY LIKE THIS:

{meal_type.title()} Created from Your Ingredients

Ingredients Used: [list the ingredients you used]
Missing Ingredients: [what you'd need to add for a complete {meal_type}]

Recipe:
[Step-by-step cooking instructions for a {meal_type} using only the provided ingredients]

Nutritional Info:
Calories: [estimated for {meal_type}]
Protein: [estimated]
Carbs: [estimated]

Tips:
[Suggestions for improvement or variations for {meal_type}]

Created specifically for your available ingredients as a {meal_type} [/INST]"""

            # Call AI API
            connector = aiohttp.TCPConnector(ssl=False)  # Disable SSL verification for API calls
            async with aiohttp.ClientSession(connector=connector) as session:
                headers = {
                    'Authorization': f'Bearer {OPENROUTER_API_KEY}',
                    'Content-Type': 'application/json',
                    'HTTP-Referer': 'https://nutriobot.com',
                    'X-Title': 'NutrioBot'
                }
                
                data = {
                    'model': 'mistralai/mistral-7b-instruct',
                    'messages': [
                        {'role': 'system', 'content': 'You are a helpful nutrition expert specializing in Indian cuisine.'},
                        {'role': 'user', 'content': prompt}
                    ],
                    'max_tokens': 800,
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
                        return generate_fallback_ingredient_response(ingredients, diet_type, state, meal_type)
        
    except Exception as e:
        logger.error(f"Error in ingredient-based meal generation: {e}")
        return generate_fallback_ingredient_response(ingredients, diet_type, state, meal_type)

def get_meal_type_variations(meal_type: str) -> List[str]:
    """Get meal type variations for better matching."""
    meal_type_map = {
        'breakfast': ['breakfast', 'morning', 'breakfast meal'],
        'lunch': ['lunch', 'afternoon', 'lunch meal'],
        'dinner': ['dinner', 'evening', 'dinner meal', 'night'],
        'snack': ['snack', 'evening snack', 'morning snack', 'light meal']
    }
    return meal_type_map.get(meal_type.lower(), [meal_type.lower()])

def get_similar_ingredients(ingredient: str) -> List[str]:
    """Get similar ingredient variations."""
    similar_map = {
        'rice': ['basmati', 'brown rice', 'white rice', 'steamed rice', 'rice'],
        'dal': ['lentils', 'toor dal', 'moong dal', 'masoor dal', 'urad dal', 'dal'],
        'tomato': ['tomatoes', 'tomato puree', 'tomato paste', 'tomato'],
        'onion': ['onions', 'red onion', 'white onion', 'onion'],
        'potato': ['potatoes', 'aloo', 'baby potatoes', 'potato'],
        'egg': ['eggs', 'boiled egg', 'fried egg', 'egg'],
        'milk': ['dairy milk', 'cow milk', 'buffalo milk', 'milk'],
        'flour': ['wheat flour', 'atta', 'maida', 'all purpose flour', 'flour'],
        'oil': ['cooking oil', 'vegetable oil', 'ghee', 'butter', 'oil'],
        'spices': ['salt', 'pepper', 'turmeric', 'cumin', 'coriander', 'garam masala', 'spices'],
        'vegetables': ['carrot', 'beans', 'peas', 'cabbage', 'cauliflower', 'vegetables'],
        'chicken': ['chicken', 'chicken breast', 'chicken thigh', 'chicken meat'],
        'fish': ['fish', 'salmon', 'tuna', 'mackerel', 'fish fillet'],
        'bread': ['bread', 'roti', 'chapati', 'naan', 'paratha'],
        'curd': ['curd', 'yogurt', 'dahi', 'curd'],
        'paneer': ['paneer', 'cottage cheese', 'paneer'],
        'cheese': ['cheese', 'cheddar', 'mozzarella', 'cheese'],
        'sugar': ['sugar', 'jaggery', 'honey', 'sweetener'],
        'salt': ['salt', 'namak', 'salt'],
        'turmeric': ['turmeric', 'haldi', 'turmeric powder'],
        'cumin': ['cumin', 'jeera', 'cumin seeds'],
        'coriander': ['coriander', 'dhania', 'coriander leaves', 'coriander powder']
    }
    
    ingredient_lower = ingredient.lower().strip()
    for key, variations in similar_map.items():
        if ingredient_lower in key or key in ingredient_lower:
            return variations
    return [ingredient]

def generate_fallback_ingredient_response(ingredients: str, diet_type: str, state: str, meal_type: str = "meal") -> str:
    """Generate fallback response when no matches found."""
    
    # Suggest similar ingredients based on what user provided
    ingredient_list = [ing.strip().lower() for ing in ingredients.split(',')]
    suggestions = []
    
    for ingredient in ingredient_list:
        similar = get_similar_ingredients(ingredient)
        if len(similar) > 1:  # If we have variations
            suggestions.extend(similar[:3])  # Take first 3 variations
    
    # Remove duplicates and limit suggestions
    unique_suggestions = list(set(suggestions))[:8]
    
    return f"""No Perfect {meal_type.title()} Matches Found

Your Ingredients: {ingredients}
Meal Type: {meal_type.title()}

Suggestions:
1. Add more ingredients - Try adding common items like rice, dal, spices
2. Use regular meal plan - Get complete meal suggestions
3. Try different ingredients - Use more basic ingredients

Common additions for {meal_type} in {diet_type} {state.title()} cuisine:
- Rice, dal, vegetables, spices
- Onions, tomatoes, potatoes
- Oil, salt, turmeric, cumin

Similar ingredients you could try:
{', '.join(unique_suggestions) if unique_suggestions else 'Try basic ingredients like rice, dal, vegetables'}

Try our regular meal plan feature for complete meal suggestions!"""

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
        
        # Load meals from static database for context based on state
        meals = load_meal_data_from_csv(state=state, diet_type=diet.title(), max_meals=50)
        if not meals:
            # Fallback to JSON for other states
            meals = load_meal_data_from_json(state)
        
        # 🔥 CRITICAL: Filter meals by medical condition for accuracy
        medical_filtered_meals = filter_meals_by_medical_condition(meals, medical)
        
        # Use medical-filtered meals if available, otherwise use original meals
        if medical_filtered_meals:
            meals = medical_filtered_meals
            logger.info(f"Using {len(meals)} medical-filtered meals for {medical}")
        else:
            logger.warning(f"No medical-filtered meals found, using {len(meals)} original meals")
        
        # Prepare detailed meal context for AI with medical information
        meal_context = []
        for meal in meals[:15]:  # Use more meals for better selection
            meal_context.append({
                'name': meal.get('Food Item', meal.get('name', 'Unknown')),
                'calories': meal.get('approx_calories', meal.get('Calories (kcal)', 200)),
                'carbs': meal.get('Carbs (g)', 0),
                'protein': meal.get('Protein (g)', 0),
                'fat': meal.get('Fat (g)', 0),
                'ingredients': meal.get('Ingredients', []),
                'category': meal.get('Category', meal.get('Meal', 'General')),
                'healthy_tag': meal.get('Healthy Tag', ''),
                'medical_score': meal.get('medical_score', 0)
            })
        
        # Build AI prompt optimized for medical accuracy
        prompt = f"""<s>[INST] You are a certified nutritionist and medical expert specializing in therapeutic nutrition. Create a HIGHLY ACCURATE and SAFE meal plan for this user.

⚠️ CRITICAL: This user has medical condition: {medical}
You MUST prioritize medical safety and accuracy above all else.

USER PROFILE:
Name: {name}
Age: {age}
Diet: {diet.title()}
Region: {state.title()}
Medical Condition: {medical} ⚠️ CRITICAL
Activity: {activity}

AVAILABLE MEALS (Pre-filtered for {medical} safety):
{json.dumps(meals[:20], indent=2)}

MEDICAL GUIDELINES FOR {medical.upper()}:
- Meals are pre-filtered for your condition
- Higher medical_score = better for your condition
- Follow nutritional limits strictly
- Avoid foods that could worsen your condition

INSTRUCTIONS (MEDICAL PRIORITY):
1. ONLY select meals from the provided list (these are medically safe)
2. Prioritize meals with higher medical_score
3. Ensure nutritional balance within medical limits
4. Create one meal each: Breakfast, Lunch, Dinner, Snack
5. Calculate total calories and nutrients
6. Double-check all selections are safe for {medical}

FORMAT YOUR RESPONSE EXACTLY LIKE THIS:

**Medical Meal Plan - {medical.title()} Safe**

**Profile:** {name}
**Region:** {state.title()}
**Diet:** {diet.title()}
**Medical Condition:** {medical} ⚠️
**Activity:** {activity}

────────────────────────────────────────

**Breakfast**
[Select from list - prioritize high medical_score]
Calories: [calories]
Carbs: [carbs]g | Protein: [protein]g | Fat: [fat]g

**Lunch**
[Select from list - prioritize high medical_score]
Calories: [calories]
Carbs: [carbs]g | Protein: [protein]g | Fat: [fat]g

**Dinner**
[Select from list - prioritize high medical_score]
Calories: [calories]
Carbs: [carbs]g | Protein: [protein]g | Fat: [fat]g

**Snack**
[Select from list - prioritize high medical_score]
Calories: [calories]
Carbs: [carbs]g | Protein: [protein]g | Fat: [fat]g

────────────────────────────────────────
**Total:** Calories: [total] | Carbs: [total]g | Protein: [total]g | Fat: [total]g

✅ **Medically Safe for {medical}**
⚠️ **Always consult your doctor before making dietary changes** [/INST]"""

        # Call AI API
        async with aiohttp.ClientSession() as session:
            headers = {
                'Authorization': f'Bearer {OPENROUTER_API_KEY}',
                'Content-Type': 'application/json',
                'HTTP-Referer': 'https://nutriobot.com',
                'X-Title': 'NutrioBot'
            }
            
            data = {
                'model': 'mistralai/mistral-7b-instruct',
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