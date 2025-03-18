import socket
import asyncio
import base64
from nicegui import ui

# Add global styles: dark background (like ChatGPT dark mode) and custom classes for buttons.
ui.add_head_html('''
<style>
  body { background-color: #343541; }
  .button-green {
    background-color: green !important;
    color: white !important;
  }
  .button-red {
    background-color: red !important;
    color: white !important;
  }
  .button-grey {
    background-color: grey !important;
    color: white !important;
  }
</style>
''')

# Global variables for the connection and toggles.
selected_ip = None
selected_port = None
instrument_name = None

run_state = False         # False = STOP, True = RUN
channel1_state = False    # False = OFF, True = ON
channel2_state = False
run_stop_button = None    # Will be assigned later
ch1_button = None         # Will be assigned later
ch2_button = None         # Will be assigned later

def check_connection(ip, port):
    """Sends the *IDN? command to verify the connection and retrieve instrument information."""
    command = "*IDN?\n"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(5)
        s.connect((ip, port))
        s.sendall(command.encode())
        response = s.recv(1024)
        return response.decode().strip() if response else "Unknown"

def get_png_image():
    """
    Retrieves the PNG image from the oscilloscope in SCPI binary block format.
    """
    global selected_ip, selected_port
    command = ':DISPlay:DATA? ON,OFF,PNG\n'
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(60)
        s.connect((selected_ip, selected_port))
        s.sendall(command.encode())
        header = s.recv(2)
        if len(header) < 2 or header[0:1] != b'#':
            raise ValueError("Invalid header received")
        try:
            n_digits = int(header[1:2].decode())
        except Exception as e:
            raise ValueError("Unable to parse number of digits in header") from e
        length_bytes = bytearray()
        while len(length_bytes) < n_digits:
            chunk = s.recv(n_digits - len(length_bytes))
            if not chunk:
                break
            length_bytes.extend(chunk)
        data_length = int(length_bytes.decode().lstrip("0") or "0")
        data = bytearray()
        while len(data) < data_length:
            chunk = s.recv(min(4096, data_length - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        if len(data) < data_length:
            raise ValueError("Incomplete PNG data received")
        return bytes(data)

def convert_png_data_to_data_url(data):
    """Converts binary PNG data into a data URL for display in the canvas."""
    encoded = base64.b64encode(data).decode('utf-8')
    return f"data:image/png;base64,{encoded}"

def send_command_to_scope(command):
    """Sends a specific command to the oscilloscope."""
    global selected_ip, selected_port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(5)
        s.connect((selected_ip, selected_port))
        s.sendall((command + "\n").encode())

async def send_command(command):
    """Sends a command to the oscilloscope asynchronously."""
    try:
        await asyncio.to_thread(send_command_to_scope, command)
    except Exception as e:
        print(f"Failed to send command {command}: {e}")

def query_channel_state(channel):
    """Queries the specified channel state and returns True if active, False otherwise."""
    global selected_ip, selected_port
    command = f":CHANnel{channel}:DISPlay?\n"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(5)
        s.connect((selected_ip, selected_port))
        s.sendall(command.encode())
        response = s.recv(1024)
        state = response.decode().strip()
        return state == "1"

async def update_channel_states():
    """Updates the channel states by querying the instrument and updates the channel buttons accordingly."""
    global channel1_state, channel2_state, ch1_button, ch2_button
    new_state1 = await asyncio.to_thread(query_channel_state, 1)
    new_state2 = await asyncio.to_thread(query_channel_state, 2)
    channel1_state = new_state1
    channel2_state = new_state2
    if channel1_state:
        ch1_button.props['class'] = "button-green"
    else:
        ch1_button.props['class'] = "button-grey"
    ch1_button.update()
    if channel2_state:
        ch2_button.props['class'] = "button-green"
    else:
        ch2_button.props['class'] = "button-grey"
    ch2_button.update()

async def auto_action():
    """
    Sends the :AUToscale command; after a short delay, updates the channel states and sets the RUN state (button becomes green).
    """
    global run_state, run_stop_button
    try:
        await asyncio.to_thread(send_command_to_scope, ":AUToscale")
        # Wait for the instrument to update channel states
        await asyncio.sleep(1.0)
        await update_channel_states()
        run_state = True
        run_stop_button.props['class'] = "button-green"
        run_stop_button.update()
    except Exception as e:
        print("Error sending :AUToscale:", e)

# --- Create the user interface ---

# Connection card
connection_card = ui.card().classes('q-pa-md q-ma-md').style('max-width: 400px; margin: auto;')
with connection_card:
    ui.label("Oscilloscope Connection")
    ip_input = ui.input(label="IP Address", placeholder="e.g. 192.168.212.202")
    port_input = ui.input(label="Port", placeholder="e.g. 5555")
    connection_status = ui.label("")
    connect_button = ui.button("Connect")

# Main display container (initially hidden)
display_container = ui.row().classes("q-pa-md").style("max-width: 1200px; margin: auto;")
display_container.visible = False

with display_container:
    # Left side: Canvas container (with instrument info label below the canvas)
    canvas_container = ui.column().style("flex: 1;")
    with canvas_container:
        ui.html('''
        <canvas id="myCanvas" width="800" height="480"
                style="display: block; background: #000;"></canvas>
        ''')
        # Instrument info label now inside the canvas container for alignment.
        instrument_label = ui.label("")
        instrument_label.style("color: yellow; white-space: pre-line;")
    # Right side: Controls container (two rows)
    controls_container = ui.column().style("margin-left: 20px;")
    with controls_container:
        main_controls = ui.row()
        with main_controls:
            clear_button = ui.button("CLEAR")
            auto_button = ui.button("AUTO")
            # The RUN/STOP button starts as STOP (red) initially.
            run_stop_button = ui.button("RUN/STOP").classes("button-red")
        channels_row = ui.row()
        with channels_row:
            ch1_button = ui.button("CH1").classes("button-grey")
            ch2_button = ui.button("CH2").classes("button-grey")
        clear_button.on("click", lambda: asyncio.create_task(send_command(":CLEAR")))
        auto_button.on("click", lambda: asyncio.create_task(auto_action()))

# Loading overlay
loading_overlay = ui.column().style(
    "position: fixed; top: 0; left: 0; width: 100%; height: 100%;"
    "background-color: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 1000;"
)
loading_overlay.visible = False
with loading_overlay:
    ui.spinner(size=50)
    ui.label("Connecting...").classes("text-white")

async def on_connect():
    """Verifies the connection and starts data acquisition."""
    global selected_ip, selected_port, instrument_name, run_state, run_stop_button
    loading_overlay.visible = True
    ip = ip_input.value.strip()
    try:
        port = int(port_input.value.strip())
    except ValueError:
        connection_status.set_text("Invalid port")
        loading_overlay.visible = False
        return
    try:
        instrument = await asyncio.to_thread(check_connection, ip, port)
    except Exception as e:
        connection_status.set_text(f"Connection failed: {e}")
        loading_overlay.visible = False
        return
    selected_ip = ip
    selected_port = port
    instrument_name = instrument
    connection_status.set_text("Connection successful!")
    fields = instrument_name.split(',')
    instrument_label.set_text(f"Manufacturer: {fields[0]}\nModel: {fields[1]}\nSerial: {fields[2]}\nVersion: {fields[3]}")
    connection_card.visible = False
    instrument_label.visible = True
    display_container.visible = True
    loading_overlay.delete()
    # Automatically send :RUN and update the RUN/STOP button to RUN (green)
    try:
        await asyncio.to_thread(send_command_to_scope, ":RUN")
        run_state = True
        run_stop_button.props['class'] = "button-green"
        run_stop_button.update()
    except Exception as e:
        print("Error initializing RUN:", e)
    # Query channel states at startup.
    await update_channel_states()
    with display_container:
        ui.timer(0.3, update_canvas)

connect_button.on("click", lambda: asyncio.create_task(on_connect()))

async def update_canvas():
    """Updates the canvas with the acquired PNG image."""
    try:
        png_data = await asyncio.to_thread(get_png_image)
    except Exception as e:
        print(f"Error updating canvas: {e}")
        return
    data_url = convert_png_data_to_data_url(png_data)
    js_code = f'''
    (function() {{
        let canvas = document.getElementById("myCanvas");
        if (!canvas) return;
        let ctx = canvas.getContext("2d");
        let tempImg = new Image();
        tempImg.onload = function() {{
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            ctx.drawImage(tempImg, 0, 0, canvas.width, canvas.height);
        }};
        tempImg.src = "{data_url}";
    }})();
    '''
    ui.run_javascript(js_code)

async def toggle_run_stop():
    """Toggles between RUN and STOP: if RUN, sends :STOP and updates button to red; otherwise sends :RUN and updates button to green."""
    global run_state, run_stop_button
    if run_state:
        try:
            await asyncio.to_thread(send_command_to_scope, ":STOP")
            run_state = False
            run_stop_button.props['class'] = "button-red"
            run_stop_button.update()
        except Exception as e:
            print("Error switching to STOP:", e)
    else:
        try:
            await asyncio.to_thread(send_command_to_scope, ":RUN")
            run_state = True
            run_stop_button.props['class'] = "button-green"
            run_stop_button.update()
        except Exception as e:
            print("Error switching to RUN:", e)

async def toggle_channel(channel, button):
    """Toggles the channel: if off, sends the command to turn it ON and updates the button to green; if on, sends the command to turn it OFF and updates the button to grey."""
    global channel1_state, channel2_state
    if channel == 1:
        if channel1_state:
            try:
                await asyncio.to_thread(send_command_to_scope, ":CHANnel1:DISPlay OFF")
                channel1_state = False
                button.props['class'] = "button-grey"
                button.update()
            except Exception as e:
                print("Error turning CH1 off:", e)
        else:
            try:
                await asyncio.to_thread(send_command_to_scope, ":CHANnel1:DISPlay ON")
                channel1_state = True
                button.props['class'] = "button-green"
                button.update()
            except Exception as e:
                print("Error turning CH1 on:", e)
    elif channel == 2:
        if channel2_state:
            try:
                await asyncio.to_thread(send_command_to_scope, ":CHANnel2:DISPlay OFF")
                channel2_state = False
                button.props['class'] = "button-grey"
                button.update()
            except Exception as e:
                print("Error turning CH2 off:", e)
        else:
            try:
                await asyncio.to_thread(send_command_to_scope, ":CHANnel2:DISPlay ON")
                channel2_state = True
                button.props['class'] = "button-green"
                button.update()
            except Exception as e:
                print("Error turning CH2 on:", e)

# Assign toggle handlers for the buttons.
run_stop_button.on("click", lambda: asyncio.create_task(toggle_run_stop()))
ch1_button.on("click", lambda: asyncio.create_task(toggle_channel(1, ch1_button)))
ch2_button.on("click", lambda: asyncio.create_task(toggle_channel(2, ch2_button)))

ui.run(title="Rigol Remote")

