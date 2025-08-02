# Contributing to Nutrio Bot

Thank you for your interest in contributing to Nutrio Bot! This document provides guidelines and information for contributors.

## 🤝 How to Contribute

### Reporting Issues
- Use the GitHub issue tracker
- Provide clear, detailed information about the problem
- Include steps to reproduce the issue
- Mention your Python version and operating system

### Suggesting Features
- Open a feature request issue
- Describe the feature and its benefits
- Consider implementation complexity
- Check if the feature aligns with the project goals

### Code Contributions
1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Add tests if applicable
5. Commit your changes (`git commit -m 'Add amazing feature'`)
6. Push to the branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

## 🛠️ Development Setup

### Prerequisites
- Python 3.8+
- Git
- A Telegram bot token (for testing)

### Local Development
1. Clone your fork
```bash
git clone https://github.com/your-username/nutrio.git
cd nutrio
```

2. Install dependencies
```bash
pip install -r requirements.txt
```

3. Set up environment
```bash
cp env_example.txt .env
# Edit .env with your bot token
```

4. Run the bot
```bash
python main.py
```

## 📝 Code Style Guidelines

### Python Code
- Follow PEP 8 style guidelines
- Use meaningful variable and function names
- Add docstrings for functions and classes
- Keep functions focused and concise
- Use type hints where appropriate

### Commit Messages
- Use clear, descriptive commit messages
- Start with a verb (Add, Fix, Update, etc.)
- Keep the first line under 50 characters
- Add more details in the body if needed

### Pull Request Guidelines
- Provide a clear description of changes
- Include any relevant issue numbers
- Add screenshots for UI changes
- Ensure all tests pass
- Update documentation if needed

## 🧪 Testing

### Manual Testing
- Test all bot features thoroughly
- Test error scenarios and edge cases
- Verify input validation works correctly
- Check rate limiting functionality

### Code Review Checklist
- [ ] Code follows style guidelines
- [ ] Functions have proper docstrings
- [ ] Error handling is implemented
- [ ] Input validation is in place
- [ ] No hardcoded secrets
- [ ] Logging is appropriate

## 🚀 Deployment

### Before Merging
- Ensure the bot runs without errors
- Test with real Telegram bot
- Verify Firebase integration (if applicable)
- Check all conversation flows work

### Security Considerations
- Never commit sensitive data (tokens, credentials)
- Use environment variables for configuration
- Validate all user inputs
- Implement proper rate limiting

## 📚 Documentation

### Code Documentation
- Add docstrings to all functions
- Include parameter types and return values
- Provide usage examples where helpful
- Document complex algorithms

### User Documentation
- Update README.md for new features
- Add setup instructions for new dependencies
- Include troubleshooting steps
- Provide usage examples

## 🎯 Project Goals

### Current Focus Areas
- Improving meal recommendation algorithms
- Adding more regional cuisines
- Enhancing user experience
- Optimizing performance
- Expanding test coverage

### Future Roadmap
- Multi-language support
- Advanced nutritional analysis
- Recipe sharing features
- Community features
- Mobile app integration

## 🆘 Getting Help

### Questions and Support
- Open a GitHub issue for questions
- Join our community discussions
- Check existing issues and PRs
- Review the README and documentation

### Communication
- Be respectful and inclusive
- Provide constructive feedback
- Help other contributors
- Follow the project's code of conduct

## 📄 License

By contributing to Nutrio Bot, you agree that your contributions will be licensed under the MIT License.

---

Thank you for contributing to making Nutrio Bot better! 🍎 