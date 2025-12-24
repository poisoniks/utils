import cv2
import numpy as np
import mss
import pyautogui
import math
import time
import threading
from pynput import keyboard

# =================================================================================
# [0] GLOBAL SETUP
# =================================================================================
# CRITICAL: Removes the default 0.1s delay after every mouse action.
# Without this, the rapid spin logic will be too slow to be effective.
pyautogui.PAUSE = 0

# =================================================================================
# [1] CONFIGURATION - VISION
# =================================================================================
# COORDINATES: Use a tool like Paint or ShareX to find these on your screen.
# Defined as the bounding box of the purple histogram area at the bottom.
GAME_REGION = {
    'top': 835,
    'left': 800,
    'width': 1090,
    'height': 160
}

# HSV Color Ranges (Hue, Saturation, Value)
# Lower V (Value) ensures we ignore the black background.
LOWER_PURPLE = np.array([120, 50, 150])
UPPER_PURPLE = np.array([170, 255, 255])

# Radar Dot: High saturation/value to distinguish the dot from the pale radar cone.
LOWER_DOT_PURPLE = np.array([130, 150, 150])
UPPER_DOT_PURPLE = np.array([170, 255, 255])

# --- BUTTON COLORS ---
# Tuned to distinguish "Approaching" (Dark Red) from "Collectable" (Bright Red).
# BRIGHT RED (Collectable): V > 172
LOWER_RED_BRIGHT1 = np.array([0, 160, 172])
UPPER_RED_BRIGHT1 = np.array([10, 255, 255])
LOWER_RED_BRIGHT2 = np.array([170, 160, 172])
UPPER_RED_BRIGHT2 = np.array([180, 255, 255])

# DARK RED (Approaching): V < 171
LOWER_RED_DARK1 = np.array([0, 70, 50])
UPPER_RED_DARK1 = np.array([10, 255, 171])
LOWER_RED_DARK2 = np.array([170, 70, 50])
UPPER_RED_DARK2 = np.array([180, 255, 171])

# THRESHOLDS
WAVE_THRESHOLD = 0.45       # Percentage of purple pixels required to consider it a "wave"
SIGNAL_TIMEOUT = 3.0        # Seconds to wait before entering recovery mode if signal is lost
COLLECT_CONFIRM_DELAY = 0.25 # Delay to prevent clicking on 1-frame animation flashes

# =================================================================================
# [2] CONFIGURATION - RADAR
# =================================================================================
# GEOMETRY: Find the center of the radar circle and the distance to the drag handle.
RADAR_CONFIG = {
    'center_x': 1585,
    'center_y': 565,
    'radius': 140,

    # --- RAPID SPIN STRATEGY ---
    'rapid_spin_step': 15,          # Degrees to jump per frame. Higher = Faster but less precise.
    'rapid_spin_delay': 0.0,        # Sleep between jumps. 0.0 = Max speed.
    'spin_duration': 3.0,           # Time to gather data before forcing a decision.
    'instant_lock_threshold': 0.7,  # If signal > 70%, abort spin and lock immediately.

    # --- TRACKING STRATEGY ---
    'tracking_sweep': 16,     # Degrees to wobble left/right while tracking.
    'tracking_step': 3,       # Step size for the wobble.
    'recovery_speed': 0.03
}

# =================================================================================
# [3] CONFIGURATION - UI ELEMENTS
# =================================================================================
UI_CONFIG = {
    # Region to monitor for the Red Button
    'collect_btn_region': {'top': 290, 'left': 1650, 'width': 350, 'height': 60},
    # Exact coordinates to click when collecting
    'collect_btn_click': (1750, 320)
}

# =================================================================================

running = True
current_strength = 0.0
can_collect = False
is_approaching = False
radar_dot_angle = None
bot_state = "IDLE"
debug_btn_hsv = (0, 0, 0)

def on_press(key):
    """Global hotkey listener to stop the script safely."""
    global running
    try:
        if key.char == 'q':
            print("\n[KILL SWITCH] 'q' detected. Exiting...")
            running = False
            return False
    except AttributeError:
        pass

def move_mouse_on_circle():
    """Main Control Loop: Handles Radar Movement and State Machine."""
    global running, current_strength, bot_state, can_collect, is_approaching, radar_dot_angle

    cx = RADAR_CONFIG['center_x']
    cy = RADAR_CONFIG['center_y']
    r = RADAR_CONFIG['radius']

    print("[BOT] Mouse thread ready. Switch to game!")
    time.sleep(3)

    # Initial Grab
    pyautogui.moveTo(cx + r, cy)
    pyautogui.mouseDown()
    time.sleep(0.1) # Essential pause: Game engine needs time to register the 'Down' event.
    print("[BOT] Mouse DOWN. Starting Loop.")

    angle = 0
    state = "RAPID_SPIN"

    spin_start_time = 0
    spin_samples = []
    last_valid_signal_time = 0

    try:
        while running:
            bot_state = state

            # --- PRIORITY 1: COLLECTION ---
            if can_collect:
                print(f"[BOT] COLLECTION TRIGGERED! Avg Color: {debug_btn_hsv}")
                pyautogui.mouseUp()

                # Click Collect
                btn_x, btn_y = UI_CONFIG['collect_btn_click']
                pyautogui.click(btn_x, btn_y)
                time.sleep(0.2)

                print("[BOT] Collected. Resetting to Spin.")

                # Re-Grab Radar immediately to maintain max speed
                pyautogui.moveTo(cx + r, cy)
                pyautogui.mouseDown()
                time.sleep(0.1) # Essential pause for game input polling

                state = "RAPID_SPIN"
                spin_start_time = 0
                angle = 0
                continue

            # --- STATE 1: RAPID SPIN (Search Mode) ---
            # Rotates quickly to find a general signal peak.
            if state == "RAPID_SPIN":
                if spin_start_time == 0:
                    spin_start_time = time.time()
                    spin_samples = []

                # Move Fast
                angle += RADAR_CONFIG['rapid_spin_step']
                if angle >= 360: angle -= 360

                # Execute Move
                rads = math.radians(angle)
                pyautogui.moveTo(cx + r * math.cos(rads), cy + r * math.sin(rads))

                spin_samples.append((angle, current_strength))

                # INSTANT LOCK: If signal is very strong or we see the visual dot, skip waiting.
                if current_strength > RADAR_CONFIG['instant_lock_threshold'] or radar_dot_angle is not None:
                    print(f"[BOT] Signal Found! Switching to Tracking.")
                    state = "TRACKING"
                    last_valid_signal_time = time.time()
                    continue

                # TIME LIMIT: If no instant lock, analyze data after duration.
                if (time.time() - spin_start_time) > RADAR_CONFIG['spin_duration']:
                    if spin_samples:
                        # Find the angle with the HIGHEST recorded strength
                        best_sample = max(spin_samples, key=lambda x: x[1])
                        best_ang = best_sample[0]
                        max_str = best_sample[1]

                        if max_str > WAVE_THRESHOLD:
                            print(f"[BOT] Spin Peak: {max_str:.2f} at {best_ang}°. Tracking.")
                            angle = best_ang
                            state = "TRACKING"
                            last_valid_signal_time = time.time()
                        else:
                            spin_start_time = 0 # Restart spin loop
                            spin_samples = []
                    else:
                        spin_start_time = 0

                if RADAR_CONFIG['rapid_spin_delay'] > 0:
                    time.sleep(RADAR_CONFIG['rapid_spin_delay'])

            # --- STATE 2: TRACKING (Wobble/Pursue Mode) ---
            # Used while flying towards the particle to keep the signal maximized.
            elif state == "TRACKING":

                # A. VISUAL OVERRIDE (Dot visible on Radar)
                # If we see the dot, snap directly to it. No math needed.
                if radar_dot_angle is not None:
                    angle = radar_dot_angle
                    rads = math.radians(angle)
                    pyautogui.moveTo(cx + r * math.cos(rads), cy + r * math.sin(rads))

                    last_valid_signal_time = time.time()
                    continue

                # B. BLIND TRACKING (Wave Wobble)
                # Sweep a small sector around the current angle to find the local max.
                sweep_range = RADAR_CONFIG['tracking_sweep']
                step = RADAR_CONFIG['tracking_step']

                best_local_angle = angle
                max_local_str = 0

                # Sweep Left -> Right to check neighbors
                for sweep_ang in range(int(angle - sweep_range), int(angle + sweep_range), step):
                    rads = math.radians(sweep_ang)
                    pyautogui.moveTo(cx + r * math.cos(rads), cy + r * math.sin(rads))

                    s = current_strength
                    if s > max_local_str:
                        max_local_str = s
                        best_local_angle = sweep_ang

                    time.sleep(0.05) # Small delay to let histogram update

                # Move to best found angle
                angle = best_local_angle
                rads = math.radians(angle)
                pyautogui.moveTo(cx + r * math.cos(rads), cy + r * math.sin(rads))

                time.sleep(0.5) # Hold direction briefly

                # Check Signal Health
                if max_local_str >= (WAVE_THRESHOLD * 0.8) or is_approaching:
                    last_valid_signal_time = time.time()

                # Lost Signal Logic (Timeout)
                elif (time.time() - last_valid_signal_time) > SIGNAL_TIMEOUT:
                    print(f"[BOT] Lost Signal during Tracking. Respinning.")
                    state = "RAPID_SPIN"
                    spin_start_time = 0

    finally:
        pyautogui.mouseUp()
        print("[BOT] Mouse UP. Thread stopped.")

def vision_loop():
    """Computer Vision Loop: Analyzes screen for Histogram, Dot, and Buttons."""
    global running, current_strength, can_collect, is_approaching, radar_dot_angle, debug_btn_hsv

    # Kernel to close gaps between histogram bars (makes them a solid shape)
    gap_filling_kernel = np.ones((1, 25), np.uint8)

    # Calculate radar region for dot detection
    rx = RADAR_CONFIG['center_x']
    ry = RADAR_CONFIG['center_y']
    rr = RADAR_CONFIG['radius']

    radar_region = {
        'top': int(ry - rr - 20),
        'left': int(rx - rr - 20),
        'width': int((rr * 2) + 40),
        'height': int((rr * 2) + 40)
    }

    # Setup Always-On-Top Window
    cv2.namedWindow('Bot Vision')
    cv2.setWindowProperty('Bot Vision', cv2.WND_PROP_TOPMOST, 1)

    collect_first_seen_time = 0

    with mss.mss() as sct:
        print("[VISION] Vision thread started.")

        while running:
            # --- 1. HISTOGRAM PROCESSING ---
            img = np.array(sct.grab(GAME_REGION))
            img_hsv = cv2.cvtColor(cv2.cvtColor(img, cv2.COLOR_BGRA2BGR), cv2.COLOR_BGR2HSV)
            # Fill gaps and calculate fill ratio
            mask = cv2.morphologyEx(cv2.inRange(img_hsv, LOWER_PURPLE, UPPER_PURPLE), cv2.MORPH_CLOSE, gap_filling_kernel)
            current_strength = cv2.countNonZero(mask) / mask.size

            # --- 2. BUTTON PROCESSING ---
            btn_img = np.array(sct.grab(UI_CONFIG['collect_btn_region']))
            btn_hsv = cv2.cvtColor(cv2.cvtColor(btn_img, cv2.COLOR_BGRA2BGR), cv2.COLOR_BGR2HSV)

            # Calculate mean color for debugging
            mean_color = cv2.mean(btn_hsv)
            debug_btn_hsv = (int(mean_color[0]), int(mean_color[1]), int(mean_color[2]))

            mask_bright = cv2.inRange(btn_hsv, LOWER_RED_BRIGHT1, UPPER_RED_BRIGHT1) + cv2.inRange(btn_hsv, LOWER_RED_BRIGHT2, UPPER_RED_BRIGHT2)
            bright_pixels = cv2.countNonZero(mask_bright)
            is_bright_now = bright_pixels > (mask_bright.size * 0.3)

            # FLASH PROTECTION: Require button to be bright for a duration
            if is_bright_now:
                if collect_first_seen_time == 0:
                    collect_first_seen_time = time.time()
                elif (time.time() - collect_first_seen_time) > COLLECT_CONFIRM_DELAY:
                    if not can_collect:
                        print(f"[DEBUG] Confirmed Collect! Pixels: {bright_pixels}")
                    can_collect = True
            else:
                collect_first_seen_time = 0
                can_collect = False

            if not can_collect:
                mask_dark = cv2.inRange(btn_hsv, LOWER_RED_DARK1, UPPER_RED_DARK1) + cv2.inRange(btn_hsv, LOWER_RED_DARK2, UPPER_RED_DARK2)
                is_approaching = cv2.countNonZero(mask_dark) > (mask_dark.size * 0.3)
            else:
                is_approaching = True

            # --- 3. RADAR DOT PROCESSING ---
            radar_img = np.array(sct.grab(radar_region))
            radar_hsv = cv2.cvtColor(cv2.cvtColor(radar_img, cv2.COLOR_BGRA2BGR), cv2.COLOR_BGR2HSV)

            # Mask out the center (Red player character/glow) to avoid false positives
            h, w = radar_img.shape[:2]
            center_mask = np.ones((h, w), dtype="uint8") * 255
            cv2.circle(center_mask, (w//2, h//2), 30, 0, -1)

            dot_mask_raw = cv2.inRange(radar_hsv, LOWER_DOT_PURPLE, UPPER_DOT_PURPLE)
            dot_mask = cv2.bitwise_and(dot_mask_raw, dot_mask_raw, mask=center_mask)

            contours, _ = cv2.findContours(dot_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            found_dot = False
            detected_coords = None

            for cnt in contours:
                area = cv2.contourArea(cnt)
                # Filter noise (<40) and large structures like the arc (>600)
                if 40 < area < 600:
                    # Check for circularity to distinguish dot from arc fragments
                    perimeter = cv2.arcLength(cnt, True)
                    if perimeter == 0: continue
                    circularity = (4 * math.pi * area) / (perimeter * perimeter)

                    if circularity > 0.6: # 1.0 is perfect circle
                        M = cv2.moments(cnt)
                        if M["m00"] != 0:
                            cX = int(M["m10"] / M["m00"])
                            cY = int(M["m01"] / M["m00"])

                            center_img_x = w // 2
                            center_img_y = h // 2
                            dx = cX - center_img_x
                            dy = cY - center_img_y

                            angle_rad = math.atan2(dy, dx)
                            angle_deg = math.degrees(angle_rad)
                            if angle_deg < 0: angle_deg += 360

                            radar_dot_angle = angle_deg
                            found_dot = True
                            detected_coords = (cX, cY)
                            break

            if not found_dot:
                radar_dot_angle = None

            # --- VISUALIZATION ---
            mask_bgr = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)

            # Overlay Radar view
            radar_bgr = cv2.cvtColor(radar_img, cv2.COLOR_BGRA2BGR)
            radar_debug_small = cv2.resize(radar_bgr, (100, 100))
            mask_bgr[0:100, 0:100] = radar_debug_small

            if detected_coords:
                 cv2.putText(mask_bgr, "DOT FOUND", (110, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)

            color = (0, 0, 255)
            status_text = bot_state
            if bot_state == "TRACKING": color = (0, 255, 0) # Green
            elif bot_state == "RAPID_SPIN": color = (255, 0, 255) # Magenta
            
            if can_collect: cv2.putText(mask_bgr, "COLLECT!", (300, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
            elif is_approaching: cv2.putText(mask_bgr, "APPROACHING...", (300, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
            
            if radar_dot_angle: cv2.putText(mask_bgr, f"DOT: {radar_dot_angle:.0f}", (300, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 255), 1)
            cv2.putText(mask_bgr, f"Btn HSV: {debug_btn_hsv}", (300, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.putText(mask_bgr, f"Str: {current_strength:.2f} | {status_text}", (10, 30), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
            
            cv2.imshow('Bot Vision', mask_bgr)
            cv2.waitKey(1)

    cv2.destroyAllWindows()

if __name__ == "__main__":
    listener = keyboard.Listener(on_press=on_press)
    listener.start()
    
    mouse_thread = threading.Thread(target=move_mouse_on_circle)
    mouse_thread.start()
    
    vision_loop()
    
    mouse_thread.join()
    print("Script finished.")
