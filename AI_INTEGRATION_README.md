# 🤖 AI-Powered Meal Plan Integration

## Overview
Your Nutriomeal bot now includes AI-powered meal plan generation using OpenRouter's Mistral 7B model! This enhancement provides personalized, dynamic meal plans based on user profiles.

## 🚀 Features

### Age-Based Personalization
- **Under 25**: Conversational, chill, Gen-Z tone with lots of emojis
- **25-40**: Calm, balanced, practical tone with moderate emojis  
- **Over 40**: Respectful, slightly formal, health-conscious tone

### Regional Food Integration
- **Maharashtra**: Poha, Varan Bhaat, Misal Pav, etc.
- **Karnataka**: Bisi Bele Bath, Ragi Mudde, Neer Dosa, etc.
- **Tamil Nadu**: Upma, Rasam, Sambar, Idli, etc.
- **Andhra Pradesh**: Pesarattu, Gongura Pachadi, etc.
- **Kerala**: Appam, Puttu, Kerala Fish Curry, etc.
- **Punjab**: Sarson da Saag, Makki di Roti, etc.
- **Bengal**: Machher Jhol, Aloo Posto, etc.
- **Gujarat**: Dhokla, Khandvi, etc.
- **Rajasthan**: Dal Baati Churma, Gatte ki Sabzi, etc.

### Smart Fallback System
- AI generation is attempted first
- Falls back to existing JSON-based meal plans if AI fails
- No disruption to user experience

## 🔧 Setup

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Environment Variables
Add to your `.env` file:
```env
# Required for AI functionality
OPENROUTER_API_KEY=your_openrouter_api_key_here

# Existing variables
BOT_TOKEN=your_telegram_bot_token_here
FIREBASE_CREDENTIALS_PATH=firebase-credentials.json
```

### 3. Get OpenRouter API Key
1. Visit [OpenRouter.ai](https://openrouter.ai)
2. Sign up and get your API key
3. Add it to your `.env` file

## 📁 File Structure

```
nutriobot-main/
├── main.py                    # Main bot with AI integration
├── ai_meal_generator.py       # AI meal generation module
├── requirements.txt           # Updated dependencies
├── .env                      # Environment variables
└── AI_INTEGRATION_README.md  # This file
```

## 🔄 How It Works

### 1. Profile Completion Trigger
When a user completes their profile, the bot automatically:
- Shows "AI is crafting your personalized meal plan..." message
- Generates AI meal plan using their profile data
- Sends the personalized plan with action buttons
- Falls back to JSON-based plan if AI fails

### 2. Manual Meal Plan Request
When users request a meal plan:
- AI generation is attempted first
- Falls back to existing JSON logic if AI unavailable
- Maintains all existing functionality

### 3. Firebase Integration
- AI-generated meal plans are stored in Firebase
- Path: `users/{user_id}/meals/{today}`
- Includes metadata: generation time, source, word count

## 🛠️ Helper Functions

### `build_prompt_from_profile(profile: dict) -> str`
Builds personalized AI prompts based on user profile:
- Age-based tone selection
- Regional food suggestions
- Health considerations
- Activity level adjustments

### `call_openrouter(prompt: str) -> str`
Makes API calls to OpenRouter with Mistral 7B:
- Temperature: 0.8 (for variety)
- Max tokens: 2000
- 30-second timeout

### `format_telegram_message(response: str) -> str`
Safely formats AI responses for Telegram:
- Escapes special characters
- Ensures Markdown compatibility
- Truncates if too long (>4000 chars)

## 🎯 Example AI Prompt

For a 42-year-old vegetarian woman from Tamil Nadu with diabetes:

```
Create a full-day vegetarian Indian meal plan for a 42-year-old female from Tamil Nadu with light activity level.

**Profile Details:**
- Name: Priya
- Age: 42 years
- Gender: female
- Diet: vegetarian
- Region: Tamil Nadu
- Activity Level: light
- Health Considerations: diabetes

**Requirements:**
- Tone: respectful, slightly formal, health-conscious tone
- Style: minimal emojis, respectful and informative
- Regional Focus: Include some regional dishes from Tamil Nadu like Upma, Rasam, Sambar, Idli, Dosa.
- Include time slots for each meal
- Include approximate calories and protein content
- Consider health conditions: diabetes
- Format as a friendly Telegram message using Markdown
- Keep response under 1200 words
- Use Good day! 🌸 as opening
- End with Wishing you good health! 🙏

**Meal Structure:**
- Breakfast (7-9 AM)
- Lunch (12-2 PM) 
- Dinner (7-9 PM)
- Optional Snack (3-4 PM)

**Format Guidelines:**
- Use **bold** for meal names and important info
- Use bullet points for ingredients
- Include calorie estimates
- Mention health benefits where relevant
- Keep it engaging and personalized

Please create a comprehensive, personalized meal plan that feels like it was made specifically for Priya.
```

## 🔧 Customization

### Adding New Regions
Edit `REGIONAL_FOODS` in `ai_meal_generator.py`:
```python
REGIONAL_FOODS = {
    "your_state": [
        "Regional Dish 1",
        "Regional Dish 2",
        # ... more dishes
    ]
}
```

### Changing AI Model
Update in `ai_meal_generator.py`:
```python
MODEL_NAME = "gpt-3.5-turbo"  # or any other OpenRouter model
```

### Adjusting Tone Styles
Modify `get_age_based_tone()` function to add new age groups or tone styles.

## 🐛 Troubleshooting

### AI Not Working
1. Check `OPENROUTER_API_KEY` in `.env`
2. Verify API key is valid on OpenRouter dashboard
3. Check logs for specific error messages
4. Bot will automatically fall back to JSON-based plans

### Rate Limiting
- OpenRouter has rate limits
- Bot includes built-in rate limiting
- Consider upgrading OpenRouter plan for higher limits

### Firebase Issues
- AI plans are saved to Firebase if available
- Bot works without Firebase (plans just won't be cached)
- Check Firebase credentials and permissions

## 📊 Monitoring

### Log Messages
- `✅ AI meal plan generated successfully`
- `⚠️ AI generation failed, using fallback`
- `❌ OpenRouter API error: {status_code}`

### Firebase Storage
AI meal plans are stored with metadata:
```json
{
  "generated_at": "2024-01-15T10:30:00",
  "meal_plan": "AI-generated content...",
  "source": "ai_mistral_7b",
  "word_count": 450
}
```

## 🚀 Future Enhancements

### Easy to Add:
- More regional food templates
- Additional tone styles
- Different AI models
- Meal plan caching
- User feedback integration
- Seasonal meal adjustments

### Modular Design:
- All AI logic is in separate module
- Easy to swap AI providers
- Configurable parameters
- Extensible architecture

## 💡 Tips

1. **Test with different profiles** to see age-based tone changes
2. **Monitor API usage** on OpenRouter dashboard
3. **Check Firebase logs** for meal plan storage
4. **Use fallback gracefully** - users won't notice if AI fails
5. **Regional foods** only appear if state is provided in profile

---

**🎉 Your bot now has AI superpowers! Users will get personalized, dynamic meal plans that feel like they were crafted just for them!** 