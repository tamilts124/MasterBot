import os
import base64
import json
from typing import Optional
from langchain_core.tools import tool
try:
    import pyautogui
    pyautogui.FAILSAFE = False
    GUI_AVAILABLE = True
except Exception:
    # This happens in headless environments like GitHub Actions without xvfb
    GUI_AVAILABLE = False

@tool
def capture_screenshot(filename: str = "screenshot.png") -> str:
    """Capture a screenshot of the current primary monitor.
    Returns the path to the saved image. Use this to 'see' what's on the screen.
    """
    if not GUI_AVAILABLE:
        return "[ERROR] GUI tools are not available in this environment (no DISPLAY detected)."
    try:
        shot = pyautogui.screenshot()
        shot.save(filename)
        return f"[SUCCESS] Screenshot saved to: {os.path.abspath(filename)}"
    except Exception as e:
        return f"[ERROR] Failed to capture screenshot: {str(e)}"

@tool
def get_mouse_position() -> str:
    """Get the current (x, y) coordinates of the mouse cursor.
    """
    if not GUI_AVAILABLE:
        return "[ERROR] GUI tools are not available (no mouse detected)."
    x, y = pyautogui.position()
    return f"Mouse Position: ({x}, {y})"

@tool
def mouse_move(x: int, y: int) -> str:
    """Move the mouse cursor to specific (x, y) coordinates.
    """
    if not GUI_AVAILABLE:
        return "[ERROR] GUI tools are not available."
    try:
        pyautogui.moveTo(x, y)
        return f"[SUCCESS] Mouse moved to ({x}, {y})"
    except Exception as e:
        return f"[ERROR] Mouse move failed: {str(e)}"

@tool
def mouse_click(x: Optional[int] = None, y: Optional[int] = None, button: str = "left") -> str:
    """Click the mouse at current position or specific (x, y) coordinates.
    Args:
        x, y: Optional coordinates. If None, clicks current position.
        button: 'left', 'right', or 'middle'.
    """
    if not GUI_AVAILABLE:
        return "[ERROR] GUI tools are not available."
    try:
        pyautogui.click(x=x, y=y, button=button)
        return f"[SUCCESS] Performed {button} click at ({x or 'current'}, {y or 'current'})"
    except Exception as e:
        return f"[ERROR] Mouse click failed: {str(e)}"

@tool
def keyboard_type(text: str) -> str:
    """Type a string of text using the keyboard.
    """
    if not GUI_AVAILABLE:
        return "[ERROR] GUI tools are not available."
    try:
        pyautogui.write(text, interval=0.1)
        return f"[SUCCESS] Typed: {text}"
    except Exception as e:
        return f"[ERROR] Keyboard typing failed: {str(e)}"

@tool
def keyboard_press(key: str) -> str:
    """Press a specific keyboard key (e.g., 'enter', 'esc', 'tab', 'f1').
    """
    if not GUI_AVAILABLE:
        return "[ERROR] GUI tools are not available."
    try:
        pyautogui.press(key)
        return f"[SUCCESS] Pressed key: {key}"
    except Exception as e:
        return f"[ERROR] Key press failed: {str(e)}"

@tool
def get_screen_size() -> str:
    """Get the current screen resolution (width and height).
    Use this to calibrate your mouse coordinates.
    """
    if not GUI_AVAILABLE:
        return "[ERROR] GUI tools are not available."
    w, h = pyautogui.size()
    return f"Screen Resolution: {w}x{h}"

@tool
def image_to_array(image_path: str = "screenshot.png") -> str:
    """Convert an image file into a numerical pixel array.
    Use this if you need to perform direct mathematical or algorithmic analysis on screen pixels.
    Args:
        image_path: The path to the image file to convert (default 'screenshot.png').
    """
    if not os.path.exists(image_path):
        return f"[ERROR] Image file not found: {image_path}."

    try:
        from PIL import Image
        import numpy as np
        
        # Load original image without resizing to preserve dimensions
        img = Image.open(image_path).convert('RGB')
        arr = np.array(img)
        
        # Return a summarized view to protect context window
        shape = arr.shape
        avg_color = np.mean(arr, axis=(0, 1)).astype(int).tolist()
        
        # Use numpy's built-in truncation for string representation
        # This shows the start and end of the array but skips the middle
        array_str = np.array2string(arr, threshold=100, edgeitems=3, precision=0, separator=', ')
        
        from .common import _truncate_output
        output = f"Image Shape (Original): {shape}\n"
        output += f"Average RGB Color: {avg_color}\n"
        output += f"Numerical Array Representation (Truncated for Context):\n{array_str}"
        
        return _truncate_output(output)
    except Exception as e:
        return f"[ERROR] Image conversion failed: {str(e)}"

@tool
def analyze_screenshot(prompt: str, image_path: str = "screenshot.png") -> str:
    """Use a vision-capable AI model (gemma4:31b-cloud) to analyze a screenshot and answer questions about its content.
    Args:
        prompt: The specific question or instruction for the AI (e.g., 'What text is in the center of the screen?', 'Where is the Submit button?').
        image_path: The path to the image file to analyze (default 'screenshot.png').
    """
    if not os.path.exists(image_path):
        capture_screenshot(image_path)
        
    if not os.path.exists(image_path):
        return f"[ERROR] Image file not found: {image_path}."

    try:
        from langchain_ollama import ChatOllama
        from langchain_core.messages import HumanMessage
        
        # --- SAS CONFIG ---
        api_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        api_key = os.environ.get("API_KEYS", "").split(",")[0]
        model_name = "gemma4:31b-cloud" # Target vision model
                
        # Initialize the vision model
        vision_model = ChatOllama(
            model=model_name,
            base_url=api_url,
            temperature=0,
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {}
        )
        
        with open(image_path, "rb") as image_file:
            image_data = base64.b64encode(image_file.read()).decode("utf-8")
            
        message = HumanMessage(
            content=[
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_data}"}}
            ]
        )
        
        response = vision_model.invoke([message])
        return f"[ANALYSIS OF {image_path}]:\n{response.content}"
    except Exception as e:
        return f"[ERROR] Cloud vision analysis failed: {str(e)}."