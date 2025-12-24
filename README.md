# utils
A repo with random utility things I create, may be useful

## [Automated Minecraft & Crafty Controller Installer](minecraft/minecraft-modded-server-setup-linux.sh)
This bash script provides a streamlined, "one-command" setup for hosting modded Minecraft servers on Ubuntu (20.04+).
It automates the installation of the Crafty Controller web interface, multi-version Java environments (8, 17, and 21), and required system dependencies.
Beyond installation, the script configures a basic UFW firewall with optional IP-whitelisting for the web panel, and automatically fetching and prepping your chosen modpack.
Although, some manual steps are still required in Crafty UI admin panel. But the script provides post-installation instructions to help you link the modpack files within the Crafty UI.

## [Darkness Experiment Automation](the-perfect-tower-2/darkness_experiment.py)

This Python script automates the **Darkness Experiment** minigame in the Laboratory within **The Perfect Tower 2**. It utilizes computer vision (OpenCV) to analyze the game's radar and signal histogram, automatically navigating the radar handle to locate particles. The bot operates using a state machine: it performs a **Rapid Spin** to sweep for signals, transitions to **Tracking** (using both the visual radar dot and histogram strength) once a signal is detected, and automatically clicks the **Collect** button when the particle is reached, including built-in protections against animation flashes.

---

### Configuration & Usage

This script is **NOT** friendly for different monitor sizes and contains a lot of magic numbers. To use this script, you must calibrate the following constants to match your screen resolution and UI layout. You can find these coordinates by taking a screenshot and using an image editor (like Paint or ShareX) to hover over the specific pixels.

#### 1. Vision & UI Regions

* **`GAME_REGION`**: The bounding box (top, left, width, height) of the **purple histogram area** at the bottom of the experiment screen.
* **`UI_CONFIG['collect_btn_region']`**: The area where the "Collect" button appears.
* **`UI_CONFIG['collect_btn_click']`**: The specific `(x, y)` coordinates where the script should click to collect the resource.

#### 2. Radar Geometry

* **`RADAR_CONFIG['center_x']` & `['center_y']`**: The exact center point of the circular radar UI.
* **`RADAR_CONFIG['radius']`**: The distance in pixels from the center of the radar to the draggable handle.

#### 3. Execution

1. Install dependencies: `pip install opencv-python numpy mss pyautogui pynput`.
2. Run the script: `python your_script_name.py`.
3. **Switch to the game window immediately.** The bot will wait 3 seconds, grab the radar handle, and begin the experiment.
4. **Kill Switch**: Press **'q'** at any time to release the mouse and stop the script safely.
