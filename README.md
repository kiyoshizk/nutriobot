# 🍎 Nutrio - Nutrition Assistant Telegram Bot

A comprehensive nutrition assistant for Indian users in Maharashtra and Karnataka, built with Python Telegram Bot v20+ and Firebase integration.

## 🚀 Features

### 🎯 Core Features
- **Personalized Meal Planning**: AI-powered meal suggestions based on user preferences
- **Regional Cuisine**: Karnataka, Maharashtra, and Andhra Pradesh specific meal recommendations
- **Dietary Preferences**: Support for Vegetarian, Eggitarian, Non-vegetarian, Jain, and Vegan diets
- **Health Considerations**: Meal filtering based on medical conditions (Diabetes, Thyroid, etc.)
- **Grocery Shopping**: Smart ingredient lists with cart functionality
- **External Integration**: Direct links to Blinkit and Zepto for ordering

### 🎮 Gamification
- **Streak System**: Daily engagement tracking with consecutive day bonuses
- **Points System**: Exponential point rewards for maintaining streaks
- **Profile Management**: Comprehensive user profiles with statistics

### 🛒 Shopping Features
- **Smart Cart**: Toggle-based item selection
- **Ingredient Lists**: Auto-generated from meal plans
- **Custom Lists**: Add/remove items manually
- **Order Integration**: Direct links to delivery services

## 📋 Prerequisites

- Python 3.8+
- Telegram Bot Token (from @BotFather)
- Firebase Project (optional, for data persistence)

## 🛠️ Installation

### 1. Clone the Repository
```bash
git clone <repository-url>
cd nutrio
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Environment Setup
```bash
# Create .env file manually
touch .env

# Edit .env file with your configuration
nano .env
```

### 4. Configure Environment Variables
```env
# Required
BOT_TOKEN=your_telegram_bot_token_here

# Optional (for Firebase)
FIREBASE_CREDENTIALS_PATH=firebase-credentials.json
```

### 5. Get Telegram Bot Token
1. Message @BotFather on Telegram
2. Send `/newbot` or use existing bot
3. Copy the token and add to `.env` file

### 6. Firebase Setup (Optional)
1. Create a Firebase project
2. Download service account key
3. Save as `firebase-credentials.json` (add to .gitignore)
4. Update `FIREBASE_CREDENTIALS_PATH` in `.env`

## 🚀 Running the Bot

### Development Mode
```bash
python main.py
```

### Production Mode
```bash
# Use a process manager like PM2 or systemd
python main.py
```

## 📁 Project Structure

```
nutrio/
├── main.py                 # Main bot application
├── requirements.txt        # Python dependencies
├── .env                   # Environment variables (create manually)
├── karnataka.json         # Karnataka meal data
├── maharastra.json        # Maharashtra meal data
├── andhra_dishes.json     # Andhra Pradesh meal data
├── Procfile               # Railway deployment configuration
├── .gitignore             # Git ignore rules
├── LICENSE                # MIT License
├── README.md              # This file
├── CHANGELOG.md           # Version history
├── CODE_OF_CONDUCT.md     # Community guidelines
└── CONTRIBUTING.md        # Contribution guidelines
```

## 🎯 Usage

### Starting the Bot
1. Send `/start` to your bot
2. Follow the profile creation flow (7 steps)
3. Get personalized meal recommendations

### Available Commands
- `/start` - Start the bot and create profile
- `/cancel` - Cancel current operation

### Main Features
- **Daily Meal Plans**: Get personalized daily meal suggestions
- **Weekly Plans**: View 7-day meal plans
- **Grocery Lists**: Generate shopping lists from meal plans
- **Cart Management**: Add/remove items and order online
- **Profile Management**: View and update your preferences
- **Streak Tracking**: Monitor your daily engagement

## 🔧 Configuration

### Rate Limiting
- **Window**: 60 seconds
- **Max Requests**: 30 per window
- **Purpose**: Prevent abuse and ensure smooth operation

### Data Storage
- **Primary**: In-memory storage (fast access)
- **Backup**: Firebase Firestore (persistent)
- **Fallback**: Local JSON files for meal data

### Meal Data Format
```json
{
  "Food Item": "Dish Name",
  "Ingredients": ["ingredient1", "ingredient2"],
  "approx_calories": 250,
  "Health Impact": "Nutritional benefits",
  "Calorie Level": "low|medium|high"
}
```

## 🛡️ Security Features

### Input Validation
- **Name**: Alphanumeric + spaces, 2-50 characters
- **Age**: Numeric, 1-120 range
- **Medical**: Sanitized text, 3-200 characters

### Rate Limiting
- Per-user request tracking
- Automatic window reset
- Graceful rate limit handling

### Data Protection
- Environment variable configuration
- Input sanitization
- Error handling without data exposure

## 🔄 Error Handling

### Graceful Degradation
- **Missing JSON Files**: Fallback meal data
- **Firebase Unavailable**: Memory-only mode
- **Invalid Input**: Clear error messages with retry options

### Logging
- **Level**: INFO and above
- **Format**: Timestamp, logger, level, message
- **Purpose**: Debugging and monitoring

## 🚨 Troubleshooting

### Common Issues

#### Bot Token Error
```
❌ ERROR: BOT_TOKEN environment variable not set!
```
**Solution**: Add your bot token to the `.env` file

#### Missing Dependencies
```
Import "telegram" could not be resolved
```
**Solution**: Run `pip install -r requirements.txt`

#### Firebase Connection Failed
```
❌ Firebase connection failed
```
**Solution**: Check credentials file path and format

#### Rate Limit Exceeded
```
⚠️ Rate Limit Exceeded
```
**Solution**: Wait 60 seconds before making more requests

### Debug Mode
Enable debug logging by modifying the logging level in `main.py`:
```python
logging.basicConfig(level=logging.DEBUG)
```

## 📊 Performance

### Memory Usage
- **Per User**: ~2KB (profile + cart + streak data)
- **Total**: Scales with active users
- **Optimization**: Automatic cleanup of inactive sessions

### Response Time
- **Typical**: <500ms for most operations
- **Meal Generation**: <1s with JSON data
- **Firebase Operations**: <2s (when available)

## 🔮 Future Enhancements

### Planned Features
- [ ] Multi-language support
- [ ] More regional cuisines
- [ ] Nutritional analysis
- [ ] Recipe sharing
- [ ] Community features
- [ ] Advanced analytics

### Technical Improvements
- [ ] Database optimization
- [ ] Caching layer
- [ ] API rate limiting
- [ ] Webhook support
- [ ] Docker deployment

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🆘 Support

For support and questions:
- Create an issue on GitHub
- Check the troubleshooting section
- Review the error logs

## 🙏 Acknowledgments

- Python Telegram Bot community
- Firebase team
- Indian cuisine experts
- Beta testers and feedback providers

---

**Made with ❤️ for healthy eating in India** 

# 🚂 Railway Deployment

## 🚀 Quick Deploy to Railway

### 1. Prepare Your Repository
```bash
# Make sure your code is pushed to GitHub
git add .
git commit -m "Ready for Railway deployment"
git push origin main
```

### 2. Deploy to Railway
1. Go to [Railway.app](https://railway.app)
2. Click "New Project" → "Deploy from GitHub repo"
3. Select your repository
4. Railway will automatically detect the `Procfile`

### 3. Configure Environment Variables
In Railway dashboard, add these environment variables:

#### Required Variables:
- **`BOT_TOKEN`**: `7583422696:AAFwYG0JxhYB-nYhYqSaTdeWzCUhs-2CITU`

#### Firebase Variables (for data persistence):
- **`FIREBASE_CREDENTIALS_JSON`**: Copy the entire content of `firebase-credentials.json` as a single line

### 4. Deploy Configuration
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `python main.py` (handled by Procfile)
- **Port**: Railway auto-detects

### 5. Environment Variables Format
```env
BOT_TOKEN=7583422696:AAFwYG0JxhYB-nYhYqSaTdeWzCUhs-2CITU
FIREBASE_CREDENTIALS_JSON={"type":"service_account","project_id":"nutrio-d7e6e",...}
```

## 🔧 Railway-Specific Files

### Procfile
```
worker: python main.py
```

### Requirements
- `python-telegram-bot==20.7`
- `python-dotenv==1.0.0`
- `firebase-admin==6.2.0`
- `pathlib2==2.3.7`

## 📊 Monitoring
- **Logs**: Available in Railway dashboard
- **Health Check**: Bot responds to `/start` command
- **Uptime**: Railway provides 99.9% uptime

## 🚨 Troubleshooting Railway Deployment

### Common Issues:
1. **Build Failed**: Check `requirements.txt` syntax
2. **Runtime Error**: Verify environment variables
3. **Bot Not Responding**: Check Railway logs for errors
4. **Firebase Issues**: Ensure `FIREBASE_CREDENTIALS_JSON` is properly formatted

### Debug Steps:
1. Check Railway build logs
2. Verify environment variables in Railway dashboard
3. Test bot with `/start` command
4. Check Firebase console for data collection # nutriobot
