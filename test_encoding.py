import sys
import io
import os

# Apply our encoding fix
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'buffer'):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Set environment variables to force UTF-8
os.environ['PYTHONIOENCODING'] = 'utf-8'
os.environ['PYTHONLEGACYWINDOWSSTDIO'] = 'utf-8'

# Test printing various Unicode characters
print("Testing Unicode characters:")
print("Emoji: 🚀")
print("Special characters: ♢ ∞ ♠ ♣ ♥ § ¶ † ‡ · º ÷ « » ░ ▒ ▓ ■ □ ▲ ▼ ◄ ► ‼ ¶ § ◊ ♫ Ω ™ ♦ ♂ ♀ ♪ ♫ ☼ ► ◄ ↨ ∟ ↔ ▲ ▼")
print("Accented characters: é è ê ë à á â ã ä å æ ç è é ê ë ì í î ï ñ ò ó ô õ ö ø œ ù ú û ü ý þ ÿ")
print("Other Unicode: 中 文 日 本 語 한국어 العربية русский язык")

print("Test completed successfully!")