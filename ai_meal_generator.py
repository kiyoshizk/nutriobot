#!/usr/bin/env python3
"""
AI-Powered Meal Plan Generator for Nutriomeal Bot
Uses OpenRouter's Mistral 7B model to generate personalized meal plans
"""

import json
import logging
import re
import os
from typing import Dict, Any, Optional, List
from datetime import datetime
import requests

logger = logging.getLogger(__name__)

# Configuration
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')
MODEL_NAME = "mistralai/mistral-7b-instruct"  # Updated model name
TEMPERATURE = 0.8
MAX_TOKENS = 2000

# Region-specific food templates
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
    Build AI prompt from user profile.
    
    Args:
        profile: User profile dictionary
        
    Returns:
        Formatted prompt string for AI
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
    
    # Build concise prompt
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

async def call_openrouter(prompt: str) -> Optional[str]:
    """
    Call OpenRouter API with Mistral 7B model.
    
    Args:
        prompt: The prompt to send to the AI
        
    Returns:
        AI response text or None if failed
    """
    if not OPENROUTER_API_KEY:
        logger.error("OpenRouter API key not found in environment variables")
        return None
    
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS
    }
    
    try:
        response = requests.post(
            OPENROUTER_API_URL,
            headers=headers,
            json=payload,
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            if 'choices' in result and len(result['choices']) > 0:
                content = result['choices'][0]['message']['content']
                logger.info("✅ AI meal plan generated successfully")
                return content
            else:
                logger.error("❌ No content in AI response")
                return None
        else:
            logger.error(f"❌ OpenRouter API error: {response.status_code} - {response.text}")
            return None
            
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Request failed: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        return None

def format_telegram_message(response: str) -> str:
    """
    Format AI response for plain text (no Markdown).
    
    Args:
        response: Raw AI response
        
    Returns:
        Clean plain text string
    """
    if not response:
        return ""
    
    # Remove any potentially problematic characters
    formatted = response.strip()
    
    # Clean up any backslashes from AI response
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
    Save AI-generated meal plan to Firebase.
    
    Args:
        user_id: Telegram user ID
        meal_plan: Generated meal plan text
        db: Firebase database instance
        
    Returns:
        True if saved successfully, False otherwise
    """
    if not db:
        return False
    
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        meal_ref = db.collection('users').document(str(user_id)).collection('meals').document(today)
        
        meal_data = {
            'generated_at': datetime.now().isoformat(),
            'meal_plan': meal_plan,
            'source': 'ai_mistral_7b',
            'word_count': len(meal_plan.split())
        }
        
        meal_ref.set(meal_data)
        logger.info(f"✅ AI meal plan saved to Firebase for user {user_id}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to save AI meal plan to Firebase: {e}")
        return False

async def generate_ai_meal_plan(profile: Dict[str, Any], user_id: int, db=None) -> Optional[str]:
    """
    Main function to generate AI-powered meal plan.
    
    Args:
        profile: User profile dictionary
        user_id: Telegram user ID
        db: Firebase database instance (optional)
        
    Returns:
        Formatted meal plan string or None if failed
    """
    try:
        # Build prompt from profile
        prompt = build_prompt_from_profile(profile)
        logger.info(f"🔧 Built AI prompt for user {user_id}")
        
        # Call OpenRouter API
        ai_response = await call_openrouter(prompt)
        if not ai_response:
            logger.warning(f"⚠️ AI generation failed for user {user_id}, will use fallback")
            return None
        
        # Format for Telegram
        formatted_response = format_telegram_message(ai_response)
        if not formatted_response:
            logger.warning(f"⚠️ AI response formatting failed for user {user_id}")
            return None
        
        # Save to Firebase if available
        if db:
            await save_ai_meal_to_firebase(user_id, formatted_response, db)
        
        logger.info(f"✅ AI meal plan generated successfully for user {user_id}")
        return formatted_response
        
    except Exception as e:
        logger.error(f"❌ Error generating AI meal plan: {e}")
        return None

async def generate_ingredient_based_meal_plan(profile: Dict[str, Any], ingredients: str, user_id: int, db=None, meal_type: str = "meal") -> Optional[str]:
    """
    Generate ingredient-based meal plan using AI.
    
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
        
        # Build prompt with meal type
        prompt = build_ingredient_prompt(profile, ingredients, meal_type)
        
        # Call OpenRouter API
        ai_response = await call_openrouter(prompt)
        
        if not ai_response:
            logger.warning(f"⚠️ Ingredient-based AI generation failed for user {user_id}")
            return None
        
        # Format for Telegram
        formatted_response = format_telegram_message(ai_response)
        if not formatted_response:
            logger.warning(f"⚠️ Ingredient-based AI response formatting failed for user {user_id}")
            return None
        
        # Save to Firebase if available
        if db:
            await save_ai_meal_to_firebase(user_id, formatted_response, db)
        
        logger.info(f"✅ Ingredient-based AI meal plan generated successfully for user {user_id}")
        return formatted_response
        
    except Exception as e:
        logger.error(f"❌ Error generating ingredient-based AI meal plan: {e}")
        return None

def build_ingredient_prompt(profile: Dict[str, Any], ingredients: str, meal_type: str = "meal") -> str:
    """
    Build AI prompt for ingredient-based meal suggestions.
    
    Args:
        profile: User profile dictionary
        ingredients: Available ingredients (comma-separated)
        meal_type: Type of meal (breakfast, lunch, dinner, snack)
        
    Returns:
        Formatted prompt string for AI
    """
    name = profile.get('name', 'User')
    age = profile.get('age', 30)
    diet = profile.get('diet', 'Mixed')
    state = profile.get('state', 'India')
    medical = profile.get('medical', 'None')
    
    # Get age-based tone
    tone_info = get_age_based_tone(age)
    
    # Build concise prompt
    prompt = f"""Create a {diet.lower()} Indian {meal_type} for {name} using ONLY: {ingredients}

**Health Focus:**
- ONLY healthy, whole foods
- NO pav, bread, fried items, sweets, or processed foods
- Consider: {medical}

**Format (PLAIN TEXT, under 200 words):**
{name}'s {meal_type.title()} with Available Ingredients

🍽️ {meal_type.upper()} SUGGESTION
[Meal name] - [Calories]
[Brief description]

**Style:** {tone_info['tone']}
**Opening:** {tone_info['greeting']}
**Closing:** {tone_info['closing']}

Keep it simple and use only the provided ingredients."""
    
    return prompt

def get_fallback_meal_message(profile: Dict[str, Any], streak_data: Dict[str, Any]) -> str:
    """
    Generate fallback meal message when AI fails.
    
    Args:
        profile: User profile dictionary
        streak_data: User streak information
        
    Returns:
        Fallback meal message
    """
    name = profile.get('name', 'User')
    state = profile.get('state', 'India')
    diet = profile.get('diet', 'Mixed')
    medical = profile.get('medical', 'None')
    activity = profile.get('activity', 'Moderate')
    
    return f"""🍽️ **Your Daily Meal Plan - Custom Made!** (Fallback)

👤 **Made for:** {name}'s profile
🏛️ **Region:** {state.title()}
🥬 **Diet:** {diet.title()}
🏥 **Medical:** {medical.title()}
🏃 **Activity:** {activity.title()}
🔥 **Streak:** {streak_data.get('streak_count', 0)} days | 🎯 **Points:** {streak_data.get('streak_points_total', 0)}

*Note: Using our curated meal database while AI is unavailable. Your personalized AI meal plan will be back soon!* 🌟""" 