# -*- coding: utf-8 -*-
import socket
import asyncio
import base64
from nicegui import ui

# Add global styles with a dark background (similar to ChatGPT dark mode)
# and custom classes for buttons.
ui.add_head_html('''
<style>
  body { background-color: #343541; }
  .button-ch1 {
    background-color: #F9FC53 !important;
    color: black !important;
  }
  .button-ch2 {
    background-color: #00FFFF !important;
    color: black !important;
  }
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
  /* Additional class to standardize button/label sizes */
  .button-size {
    width: 100px;
    height: 40px;
    display: flex;
    align-items: center;
    justify-content: center;
    margin: 0; /* Eliminates any potential internal margins */
  }
  .slider-size {
    width: 100px;
    height: 10px;
    display: flex;
    align-items: center;
    justify-content: center;
    margin: 0; /* Eliminates any potential internal margins */
  }
  .filler-size {
    width: 100px;
    height: 33px;
    display: flex;
    align-items: center;
    justify-content: center;
    margin: 0; /* Eliminates any potential internal margins */
  }
  .meas1-size {
    width: 100px;
    height: 10px;
    display: flex;
    align-items: center;
    justify-content: center;
    margin: 0; /* Eliminates any potential internal margins */
    background-color: #F9FC53;
    padding: 15px 0;
    color: black !important;
  }
  .meas2-size {
    width: 100px;
    height: 10px;
    display: flex;
    align-items: center;
    justify-content: center;
    margin: 0; /* Eliminates any potential internal margins */
    background-color: #00FFFF;
    padding: 15px 0;
    color: black !important;
  }
  .vslider-size {
    width: 100px;
    height: 100px;
    display: flex;
    align-items: center;
    justify-content: center;
    margin: 0; /* Eliminates any potential internal margins */
  }
  .square-button {
    width: 20px;
    height: 20px;
    display: flex;
    align-items: center;
    justify-content: center;
    margin: 0;
    padding: 0;
    border: none;       /* Removes the default border */
    min-height: 0;       /* Cancels any browser-set min-height */
    box-sizing: border-box;  /* Includes padding and border in the total dimensions */
    color: black !important;
  }
  .middle-label .q-field__native {
    width: 60px;
    height: 20px;
    display: flex;
    align-items: center;
    justify-content: center;
    text-align: center;
    margin: 0;
    color: black;
    font-size: 0.7rem;
  }
</style>
''')

# Global variables for connection and toggles.
selected_ip = None
selected_port = None
instrument_name = None

run_state = False         # False = STOP, True = RUN
channel1_state = False    # False = OFF, True = ON
channel2_state = False
run_stop_button = None    # Will be assigned later
ch1_button = None         # Will be assigned later
ch2_button = None         # Will be assigned later

yellow_rigol = "#F9FC53"
blue_rigol = "#00FFFF"
orange_rigol = "#E88632"

# Global UI elements (assigned later in the UI definition)
instrument_label = None
pos_ch1_input = None
pos_ch2_input = None
trigger_input = None
meas_ch1_freq = None
meas_ch1_period = None
meas_ch1_vmin = None
meas_ch1_vmax = None
meas_ch1_pduty = None
meas_ch2_freq = None
meas_ch2_period = None
meas_ch2_vmin = None
meas_ch2_vmax = None
meas_ch2_pduty = None
connection_status = None
ip_input = None
port_input = None

# --- Helper functions for socket communication ---

def socket_query(command, timeout=30, recv_size=1024):
    """Sends a command to the oscilloscope and returns the response."""
    global selected_ip, selected_port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        s.connect((selected_ip, selected_port))
        s.sendall(command.encode())
        return s.recv(recv_size)

def socket_query_pair(cmd1, cmd2, timeout=30, recv_size=1024):
    """Sends two consecutive commands to the oscilloscope and returns their responses."""
    global selected_ip, selected_port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        s.connect((selected_ip, selected_port))
        s.sendall(cmd1.encode())
        resp1 = s.recv(recv_size)
        s.sendall(cmd2.encode())
        resp2 = s.recv(recv_size)
        return resp1, resp2

# --- Core functions for oscilloscope control ---

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

def convert_unit(value):
    """Converts a numerical value to a string with an appropriate unit."""
    if abs(value) < 1e-6:
        return f'{value*1e9:.1f} n'
    if abs(value) < 1e-3:
        return f'{value*1e6:.1f} µ'
    if abs(value) < 1:
        return f'{value*1e3:.1f} m'
    if abs(value) < 1e3:
        return f'{value:.1f} '
    if abs(value) < 1e6:
        return f'{value/1e3:.1f} k'
    if abs(value) < 1e9:
        return f'{value/1e6:.1f} M'
    if abs(value) < 1e12:
        return f'{value/1e9:.1f} G'
    return '*** '

def send_command_to_scope(command):
    """Sends a specific command to the oscilloscope."""
    global selected_ip, selected_port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(30)
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
    command = f":CHANnel{channel}:DISPlay?\n"
    response = socket_query(command, timeout=30)
    state = response.decode().strip()
    return state == "1"

async def set_offset_manual(event):
    """Handles manual time offset setting on Enter key event."""
    if event.args.get('key') == 'Enter':
        await set_offset(offset_input.value)

async def set_trigger_manual(event):
    """Handles manual trigger level setting on Enter key event."""
    if event.args.get('key') == 'Enter':
        await set_trigger(trigger_input.value)

async def set_ch1_voltage_offset_manual(event):
    """Handles manual CH1 voltage offset setting on Enter key event."""
    if event.args.get('key') == 'Enter':
        await set_voltage_offset(pos_ch1_input.value, 1)

async def set_ch2_voltage_offset_manual(event):
    """Handles manual CH2 voltage offset setting on Enter key event."""
    if event.args.get('key') == 'Enter':
        await set_voltage_offset(pos_ch2_input.value, 2)

def query_offset_state():
    """Queries the main timebase offset from the oscilloscope."""
    response = socket_query(":TIMebase:MAIN:OFFSet?\n", timeout=30)
    return float(response.decode().strip())

def query_voltage_offset(channel):
    """Queries the voltage offset for a given channel."""
    response = socket_query(f":CHANnel{channel}:OFFSet?\n", timeout=30)
    return float(response.decode().strip())

def query_trigger():
    """Queries the trigger level from the oscilloscope."""
    response = socket_query(":TRIGger:EDGe:LEVel?\n", timeout=30)
    return float(response.decode().strip())

def query_meas(item, channel, conv=True):
    """
    Queries a measurement item from a specified channel.
    Returns a converted value with unit if conv is True, otherwise a formatted string.
    """
    response = socket_query(f":MEASure:ITEM? {item},CHANnel{channel}\n", timeout=30)
    try:
        value = float(response.decode().strip())
        if conv:
            return convert_unit(value)
        else:
            formatted = f'{value:.2f} '
            return formatted if len(formatted) <= 30 else "*** "
    except:
        return "*** "

async def update_channel_states():
    """
    Updates the channel states by querying the instrument and updates the channel buttons accordingly.
    """
    global channel1_state, channel2_state, ch1_button, ch2_button
    new_state1 = await asyncio.to_thread(query_channel_state, 1)
    new_state2 = await asyncio.to_thread(query_channel_state, 2)
    channel1_state = new_state1
    channel2_state = new_state2
    if channel1_state:
        ch1_button.props['class'] = "button-size button-ch1"
    else:
        ch1_button.props['class'] = "button-size button-grey"
    ch1_button.update()

    if channel2_state:
        ch2_button.props['class'] = "button-size button-ch2"
    else:
        ch2_button.props['class'] = "button-size button-grey"
    ch2_button.update()

async def auto_action():
    """
    Sends the :AUToscale command; after a short delay, updates the channel states and sets the RUN state (button becomes green).
    """
    global run_state, run_stop_button, pos_ch1_input, pos_ch2_input, trigger_input
    try:
        await asyncio.to_thread(send_command_to_scope, ":AUToscale")
        # Wait for the instrument to update channel states
        await asyncio.sleep(1.0)
        await update_channel_states()
        run_state = True
        run_stop_button.props['class'] = "button-size button-green"
        run_stop_button.update()
        val = await asyncio.to_thread(query_voltage_offset, 1)
        pos_ch1_input.value = convert_unit(val) + 'V'
        pos_ch1_input.update()
        val = await asyncio.to_thread(query_voltage_offset, 2)
        pos_ch2_input.value = convert_unit(val) + 'V'
        pos_ch2_input.update()
        val = await asyncio.to_thread(query_trigger)
        trigger_input.value = convert_unit(val) + 'V'
        trigger_input.update()
    except Exception as e:
        print("Error sending :AUToscale:", e)

async def on_connect():
    """Verifies the connection and starts data acquisition."""
    global selected_ip, selected_port, instrument_name, run_state, run_stop_button, instrument_label, pos_ch1_input, pos_ch2_input, trigger_input, connection_status, ip_input, port_input
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
    if len(fields) == 4:
        instrument_label.set_text(
            f"Manufacturer: {fields[0]} - "
            f"Model: {fields[1]} - "
            f"Serial: {fields[2]} - "
            f"Version: {fields[3]}"
        )
    else:
        instrument_label.set_text(instrument_name)

    connection_card.visible = False
    instrument_label.visible = True
    display_container.visible = True
    loading_overlay.delete()

    # Automatically send :RUN and update the RUN/STOP button to RUN (green)
    try:
        await asyncio.to_thread(send_command_to_scope, ":RUN")
        run_state = True
        run_stop_button.props['class'] = "button-size button-green"
        run_stop_button.update()
    except Exception as e:
        print("Error initializing RUN:", e)

    # Query channel states at startup.
    await update_channel_states()

    val = await asyncio.to_thread(query_voltage_offset, 1)
    pos_ch1_input.value = convert_unit(val) + 'V'
    pos_ch1_input.update()

    val = await asyncio.to_thread(query_voltage_offset, 2)
    pos_ch2_input.value = convert_unit(val) + 'V'
    pos_ch2_input.update()

    val = await asyncio.to_thread(query_trigger)
    trigger_input.value = convert_unit(val) + 'V'
    trigger_input.update()

    offset_input.value = convert_unit(await asyncio.to_thread(query_offset_state)) + 's'
    offset_input.update()

    # Start a timer to periodically update the canvas
    with display_container:
        ui.timer(0.3, update_canvas)

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
    """
    Toggles between RUN and STOP: if RUN, sends :STOP and updates button to red;
    otherwise sends :RUN and updates button to green.
    """
    global run_state, run_stop_button
    if run_state:
        try:
            await asyncio.to_thread(send_command_to_scope, ":STOP")
            run_state = False
            run_stop_button.props['class'] = "button-size button-red"
            run_stop_button.update()
        except Exception as e:
            print("Error switching to STOP:", e)
    else:
        try:
            await asyncio.to_thread(send_command_to_scope, ":RUN")
            run_state = True
            run_stop_button.props['class'] = "button-size button-green"
            run_stop_button.update()
        except Exception as e:
            print("Error switching to RUN:", e)

async def measurement():
    """Performs measurements and updates the measurement display labels."""
    with display_container:
        meas_ch1_freq.set_text(str(await asyncio.to_thread(query_meas, 'FREQuency', 1)) + 'Hz')
        meas_ch1_freq.update()
        meas_ch1_period.set_text(str(await asyncio.to_thread(query_meas, 'PERiod', 1)) + 's')
        meas_ch1_period.update()
        meas_ch1_vmin.set_text(str(await asyncio.to_thread(query_meas, 'VMIN', 1)) + 'V')
        meas_ch1_vmin.update()
        meas_ch1_vmax.set_text(str(await asyncio.to_thread(query_meas, 'VMAX', 1)) + 'V')
        meas_ch1_vmax.update()
        meas_ch1_pduty.set_text(str(await asyncio.to_thread(query_meas, 'PDUTy', 1, False)))
        meas_ch1_pduty.update()
        meas_ch2_freq.set_text(str(await asyncio.to_thread(query_meas, 'FREQuency', 2)) + 'Hz')
        meas_ch2_freq.update()
        meas_ch2_period.set_text(str(await asyncio.to_thread(query_meas, 'PERiod', 2)) + 's')
        meas_ch2_period.update()
        meas_ch2_vmin.set_text(str(await asyncio.to_thread(query_meas, 'VMIN', 2)) + 'V')
        meas_ch2_vmin.update()
        meas_ch2_vmax.set_text(str(await asyncio.to_thread(query_meas, 'VMAX', 2)) + 'V')
        meas_ch2_vmax.update()
        meas_ch2_pduty.set_text(str(await asyncio.to_thread(query_meas, 'PDUTy', 2, False)))
        meas_ch2_pduty.update()

async def set_time(time_value):
    """Sets the time scale of the oscilloscope."""
    try:
        await asyncio.to_thread(send_command_to_scope, f":TIMebase:MAIN:SCALe {time_value}")
    except:
        print("Error setting time")

async def set_offset(offset):
    """Sets the time offset of the oscilloscope."""
    try:
        resp1, resp2 = socket_query_pair(":TIMEbase:MAIN:SCALe?\n", ":TIMebase:MAIN:OFFSet?\n", timeout=30)
        screen = float(resp1.decode().strip())
        curr_offset = float(resp2.decode().strip())
        screen_step = screen / 5
        if offset == "+":
            curr_offset += screen_step
        elif offset == "-":
            curr_offset -= screen_step
        else:
            curr_offset = float(offset)
        await asyncio.to_thread(send_command_to_scope, f":TIMebase:MAIN:OFFSet {curr_offset}")
        offset_input.value = f"{convert_unit(curr_offset)}s"
        offset_input.update()
    except:
        print("Error setting time offset")

async def set_voltage_offset(offset, channel):
    """Sets the voltage offset for a given channel."""
    try:
        cmd_scale = f":CHANnel{channel}:SCALe?\n"
        cmd_offset = f":CHANnel{channel}:OFFSet?\n"
        resp1, resp2 = socket_query_pair(cmd_scale, cmd_offset, timeout=30)
        scale = float(resp1.decode().strip())
        curr_offset = float(resp2.decode().strip())
        if offset == '+':
            curr_offset += scale / 5
        elif offset == '-':
            curr_offset -= scale / 5
        else:
            curr_offset = float(offset)
        await asyncio.to_thread(send_command_to_scope, f":CHANnel{channel}:OFFSet {curr_offset}")
        if channel == 1:
            pos_ch1_input.value = f"{convert_unit(curr_offset)}V"
            pos_ch1_input.update()
        elif channel == 2:
            pos_ch2_input.value = f"{convert_unit(curr_offset)}V"
            pos_ch2_input.update()
    except:
        print("Error setting voltage offset")

async def set_trigger(trig):
    """Sets the trigger level of the oscilloscope."""
    try:
        resp1, resp2 = socket_query_pair(":CHANnel1:SCALe?\n", ":TRIGger:EDGe:LEVel?\n", timeout=30)
        scale = float(resp1.decode().strip())
        curr_trigger = float(resp2.decode().strip())
        if trig == '+':
            curr_trigger += scale / 5
        elif trig == '-':
            curr_trigger -= scale / 5
        else:
            curr_trigger = float(trig)
        await asyncio.to_thread(send_command_to_scope, f":TRIGger:EDGe:LEVel {curr_trigger}")
        trigger_input.value = f"{convert_unit(curr_trigger)}V"
        trigger_input.update()
    except:
        print("Error setting trigger offset")

async def set_voltage(volt, channel):
    """Sets the voltage scale for a given channel."""
    try:
        await asyncio.to_thread(send_command_to_scope, f":CHANnel{channel}:SCALe {volt}")
    except:
        print("Error setting voltage")

async def toggle_channel(channel, button):
    """
    Toggles the specified channel.
    If the channel is off, sends the command to turn it ON and updates the button to its channel color;
    if it is on, sends the command to turn it OFF and updates the button to grey.
    """
    global channel1_state, channel2_state
    if channel == 1:
        if channel1_state:
            try:
                await asyncio.to_thread(send_command_to_scope, ":CHANnel1:DISPlay OFF")
                channel1_state = False
                button.props['class'] = "button-size button-grey"
                button.update()
            except Exception as e:
                print("Error turning CH1 off:", e)
        else:
            try:
                await asyncio.to_thread(send_command_to_scope, ":CHANnel1:DISPlay ON")
                channel1_state = True
                button.props['class'] = "button-size button-ch1"
                button.update()
            except Exception as e:
                print("Error turning CH1 on:", e)
    elif channel == 2:
        if channel2_state:
            try:
                await asyncio.to_thread(send_command_to_scope, ":CHANnel2:DISPlay OFF")
                channel2_state = False
                button.props['class'] = "button-size button-grey"
                button.update()
            except Exception as e:
                print("Error turning CH2 off:", e)
        else:
            try:
                await asyncio.to_thread(send_command_to_scope, ":CHANnel2:DISPlay ON")
                channel2_state = True
                button.props['class'] = "button-size button-ch2"
                button.update()
            except Exception as e:
                print("Error turning CH2 on:", e)

# --- User Interface (UI) definition ---

# Connection card
connection_card = ui.card().classes('q-pa-md q-ma-md').style('max-width: 400px; margin: auto;')
with connection_card:
    ui.label("Oscilloscope Connection")
    ip_input = ui.input(label="IP Address", placeholder="e.g. 192.168.212.202")
    port_input = ui.input(label="Port", placeholder="e.g. 5555")
    connection_status = ui.label("")
    connect_button = ui.button("Connect")

# Main display container (initially hidden)
display_container = ui.column().classes("q-pa-md").style("max-width: 1200px; margin: auto;")
display_container.visible = False

with display_container:
    # First block: row with canvas on the left and a grid of buttons on the right.
    # Also creates the instrument info label (used later to display instrument details).
    main_row = ui.row().classes("items-start")  # Align at the top
    with main_row:
        instrument_label = ui.label("").style("color: yellow; white-space: pre-line; margin-top: 20px;")
        # Left side: Canvas container
        canvas_container = ui.column().style("flex: 1;")
        with canvas_container:
            ui.html('''
            <canvas id="myCanvas" width="800" height="480"
                    style="display: block; background: #000;"></canvas>
            ''')
        # Right side: Grid of buttons/labels
        with ui.grid(columns=3).classes("gap-5"):
            # First row
            clear_button = ui.button("CLEAR").classes("button-size button-grey")
            auto_button = ui.button("AUTO").classes("button-size button-grey")
            run_stop_button = ui.button("RUN/STOP").classes("button-size button-red")  # Starts as STOP
            # Second row
            ch1_button = ui.button("CH1").classes("button-size button-grey")
            ch2_button = ui.button("CH2").classes("button-size button-grey")
            with ui.dropdown_button('Time', auto_close=False).props(f'style="text-transform:none; color: black !important; background-color: {orange_rigol} !important;"').classes("button-size"):
                with ui.dropdown_button('ns', auto_close=True).props(f'style="text-transform:none; color: black !important; background-color: {orange_rigol} !important;"'):
                    ui.item('5', on_click=lambda: (asyncio.create_task(set_time(0.000000005)), ui.notify('Time set to 5 ns')))
                    ui.item('10', on_click=lambda: (asyncio.create_task(set_time(0.00000001)), ui.notify('Time set to 10 ns')))
                    ui.item('20', on_click=lambda: (asyncio.create_task(set_time(0.00000002)), ui.notify('Time set to 20 ns')))
                    ui.item('50', on_click=lambda: (asyncio.create_task(set_time(0.00000005)), ui.notify('Time set to 50 ns')))
                    ui.item('100', on_click=lambda: (asyncio.create_task(set_time(0.0000001)), ui.notify('Time set to 100 ns')))
                    ui.item('200', on_click=lambda: (asyncio.create_task(set_time(0.0000002)), ui.notify('Time set to 200 ns')))
                    ui.item('500', on_click=lambda: (asyncio.create_task(set_time(0.0000005)), ui.notify('Time set to 500 ns')))
                with ui.dropdown_button('µs', auto_close=True).props(f'style="text-transform:none; color: black !important; background-color: {orange_rigol} !important;"'):
                    ui.item('1', on_click=lambda: (asyncio.create_task(set_time(0.000001)), ui.notify('Time set to 1 µs')))
                    ui.item('2', on_click=lambda: (asyncio.create_task(set_time(0.000002)), ui.notify('Time set to 2 µs')))
                    ui.item('5', on_click=lambda: (asyncio.create_task(set_time(0.000005)), ui.notify('Time set to 5 µs')))
                    ui.item('10', on_click=lambda: (asyncio.create_task(set_time(0.00001)), ui.notify('Time set to 10 µs')))
                    ui.item('20', on_click=lambda: (asyncio.create_task(set_time(0.00002)), ui.notify('Time set to 20 µs')))
                    ui.item('50', on_click=lambda: (asyncio.create_task(set_time(0.00005)), ui.notify('Time set to 50 µs')))
                    ui.item('100', on_click=lambda: (asyncio.create_task(set_time(0.0001)), ui.notify('Time set to 100 µs')))
                    ui.item('200', on_click=lambda: (asyncio.create_task(set_time(0.0002)), ui.notify('Time set to 200 µs')))
                    ui.item('500', on_click=lambda: (asyncio.create_task(set_time(0.0005)), ui.notify('Time set to 500 µs')))
                with ui.dropdown_button('ms', auto_close=True).props(f'style="text-transform:none; color: black !important; background-color: {orange_rigol} !important;"'):
                    ui.item('1', on_click=lambda: (asyncio.create_task(set_time(0.001)), ui.notify('Time set to 1 ms')))
                    ui.item('2', on_click=lambda: (asyncio.create_task(set_time(0.002)), ui.notify('Time set to 2 ms')))
                    ui.item('5', on_click=lambda: (asyncio.create_task(set_time(0.005)), ui.notify('Time set to 5 ms')))
                    ui.item('10', on_click=lambda: (asyncio.create_task(set_time(0.01)), ui.notify('Time set to 10 ms')))
                    ui.item('20', on_click=lambda: (asyncio.create_task(set_time(0.02)), ui.notify('Time set to 20 ms')))
                    ui.item('50', on_click=lambda: (asyncio.create_task(set_time(0.05)), ui.notify('Time set to 50 ms')))
                    ui.item('100', on_click=lambda: (asyncio.create_task(set_time(0.1)), ui.notify('Time set to 100 ms')))
                    ui.item('200', on_click=lambda: (asyncio.create_task(set_time(0.2)), ui.notify('Time set to 200 ms')))
                    ui.item('500', on_click=lambda: (asyncio.create_task(set_time(0.5)), ui.notify('Time set to 500 ms')))
                with ui.dropdown_button('s', auto_close=True).props(f'style="text-transform:none; color: black !important; background-color: {orange_rigol} !important;"'):
                    ui.item('1', on_click=lambda: (asyncio.create_task(set_time(1)), ui.notify('Time set to 1 s')))
                    ui.item('2', on_click=lambda: (asyncio.create_task(set_time(2)), ui.notify('Time set to 2 s')))
                    ui.item('5', on_click=lambda: (asyncio.create_task(set_time(5)), ui.notify('Time set to 5 s')))
                    ui.item('10', on_click=lambda: (asyncio.create_task(set_time(10)), ui.notify('Time set to 10 s')))
                    ui.item('20', on_click=lambda: (asyncio.create_task(set_time(20)), ui.notify('Time set to 20 s')))
                    ui.item('50', on_click=lambda: (asyncio.create_task(set_time(50)), ui.notify('Time set to 50 s')))
            # Third row
            with ui.dropdown_button('Scale CH1', auto_close=False).props(f'style="text-transform:none; color: black !important; background-color: {yellow_rigol} !important; padding-right: 0px;"').classes("button-size"):
                with ui.dropdown_button('mV', auto_close=True).props(f'style="text-transform:none; color: black !important; background-color: {yellow_rigol} !important;"'):
                    ui.item('1', on_click=lambda: (asyncio.create_task(set_voltage(0.001,1)), ui.notify('CH1 Scale set to 1 mV')))
                    ui.item('2', on_click=lambda: (asyncio.create_task(set_voltage(0.002,1)), ui.notify('CH1 Scale set to 2 mV')))
                    ui.item('5', on_click=lambda: (asyncio.create_task(set_voltage(0.005,1)), ui.notify('CH1 Scale set to 5 mV')))
                    ui.item('10', on_click=lambda: (asyncio.create_task(set_voltage(0.01,1)), ui.notify('CH1 Scale set to 10 mV')))
                    ui.item('20', on_click=lambda: (asyncio.create_task(set_voltage(0.02,1)), ui.notify('CH1 Scale set to 20 mV')))
                    ui.item('50', on_click=lambda: (asyncio.create_task(set_voltage(0.05,1)), ui.notify('CH1 Scale set to 50 mV')))
                    ui.item('100', on_click=lambda: (asyncio.create_task(set_voltage(0.1,1)), ui.notify('CH1 Scale set to 100 mV')))
                    ui.item('200', on_click=lambda: (asyncio.create_task(set_voltage(0.2,1)), ui.notify('CH1 Scale set to 200 mV')))
                    ui.item('500', on_click=lambda: (asyncio.create_task(set_voltage(0.5,1)), ui.notify('CH1 Scale set to 500 mV')))
                with ui.dropdown_button('V', auto_close=True).props(f'style="text-transform:none; color: black !important; background-color: {yellow_rigol} !important;"'):
                    ui.item('1', on_click=lambda: (asyncio.create_task(set_voltage(1,1)), ui.notify('CH1 Scale set to 1 V')))
                    ui.item('2', on_click=lambda: (asyncio.create_task(set_voltage(2,1)), ui.notify('CH1 Scale set to 2 V')))
                    ui.item('5', on_click=lambda: (asyncio.create_task(set_voltage(5,1)), ui.notify('CH1 Scale set to 5 V')))
                    ui.item('10', on_click=lambda: (asyncio.create_task(set_voltage(10,1)), ui.notify('CH1 Scale set to 10 V')))
            with ui.dropdown_button('Scale CH2', auto_close=False).props(f'style="text-transform:none; color: black !important; background-color: {blue_rigol} !important; padding-right: 0px;"').classes("button-size"):
                with ui.dropdown_button('mV', auto_close=True).props(f'style="text-transform:none; color: black !important; background-color: {blue_rigol} !important;"'):
                    ui.item('1', on_click=lambda: (asyncio.create_task(set_voltage(0.001,2)), ui.notify('CH2 Scale set to 1 mV')))
                    ui.item('2', on_click=lambda: (asyncio.create_task(set_voltage(0.002,2)), ui.notify('CH2 Scale set to 2 mV')))
                    ui.item('5', on_click=lambda: (asyncio.create_task(set_voltage(0.005,2)), ui.notify('CH2 Scale set to 5 mV')))
                    ui.item('10', on_click=lambda: (asyncio.create_task(set_voltage(0.01,2)), ui.notify('CH2 Scale set to 10 mV')))
                    ui.item('20', on_click=lambda: (asyncio.create_task(set_voltage(0.02,2)), ui.notify('CH2 Scale set to 20 mV')))
                    ui.item('50', on_click=lambda: (asyncio.create_task(set_voltage(0.05,2)), ui.notify('CH2 Scale set to 50 mV')))
                    ui.item('100', on_click=lambda: (asyncio.create_task(set_voltage(0.1,2)), ui.notify('CH2 Scale set to 100 mV')))
                    ui.item('200', on_click=lambda: (asyncio.create_task(set_voltage(0.2,2)), ui.notify('CH2 Scale set to 200 mV')))
                    ui.item('500', on_click=lambda: (asyncio.create_task(set_voltage(0.5,2)), ui.notify('CH2 Scale set to 500 mV')))
                with ui.dropdown_button('V', auto_close=True).props(f'style="text-transform:none; color: black !important; background-color: {blue_rigol} !important;"'):
                    ui.item('1', on_click=lambda: (asyncio.create_task(set_voltage(1,2)), ui.notify('CH2 Scale set to 1 V')))
                    ui.item('2', on_click=lambda: (asyncio.create_task(set_voltage(2,2)), ui.notify('CH2 Scale set to 2 V')))
                    ui.item('5', on_click=lambda: (asyncio.create_task(set_voltage(5,2)), ui.notify('CH2 Scale set to 5 V')))
                    ui.item('10', on_click=lambda: (asyncio.create_task(set_voltage(10,2)), ui.notify('CH2 Scale set to 10 V')))
            with ui.column().style(f"gap: 10px; background-color: {orange_rigol}; border-radius: 4px; height: 40px;"):
                ui.label('Time Offset').style('color: black; font-size: 0.8rem').classes("slider-size pt-2")
                with ui.row().style("gap: 0"):
                    ui.button('-', on_click=lambda: (asyncio.create_task(set_offset('-')))).style(f"background-color: {orange_rigol} !important;").classes("square-button")
                    offset_input = ui.input(value="").classes("middle-label").props('borderless').tooltip('Type time offset in seconds without unit')
                    offset_input.on('keyup', set_offset_manual)
                    ui.button('+', on_click=lambda: (asyncio.create_task(set_offset('+')))).style(f"background-color: {orange_rigol} !important;").classes("square-button")
            # Fourth row
            with ui.column().style(f"gap: 10px; background-color: {yellow_rigol}; border-radius: 4px; height: 40px;"):
                ui.label('CH1 VOffset').style('color: black; font-size: 0.8rem').classes("slider-size pt-2")
                with ui.row().style("gap: 0"):
                    ui.button('-', on_click=lambda: (asyncio.create_task(set_voltage_offset('-', 1)))).style(f"background-color: {yellow_rigol} !important;").classes("square-button")
                    pos_ch1_input = ui.input(value="").classes("middle-label").props('borderless').tooltip('Type voltage offset in volts without unit')
                    pos_ch1_input.on('keyup', set_ch1_voltage_offset_manual)
                    ui.button('+', on_click=lambda: (asyncio.create_task(set_voltage_offset('+', 1)))).style(f"background-color: {yellow_rigol} !important;").classes("square-button")
            with ui.column().style(f"gap: 10px; background-color: {blue_rigol}; border-radius: 4px; height: 40px;"):
                ui.label('CH2 VOffset').style('color: black; font-size: 0.8rem').classes("slider-size pt-2")
                with ui.row().style("gap: 0"):
                    ui.button('-', on_click=lambda: (asyncio.create_task(set_voltage_offset('-', 2)))).style(f"background-color: {blue_rigol} !important;").classes("square-button")
                    pos_ch2_input = ui.input(value="").classes("middle-label").props('borderless').tooltip('Type voltage offset in volts without unit')
                    pos_ch2_input.on('keyup', set_ch2_voltage_offset_manual)
                    ui.button('+', on_click=lambda: (asyncio.create_task(set_voltage_offset('+', 2)))).style(f"background-color: {blue_rigol} !important;").classes("square-button")
            with ui.column().style(f"gap: 10px; background-color: {orange_rigol}; border-radius: 4px; height: 40px;"):
                ui.label('Trigger').style('color: black; font-size: 0.8rem').classes("slider-size pt-2")
                with ui.row().style("gap: 0"):
                    ui.button('-', on_click=lambda: (asyncio.create_task(set_trigger('-')))).style(f"background-color: {orange_rigol} !important;").classes("square-button")
                    trigger_input = ui.input(value="").classes("middle-label").props('borderless').tooltip('Type voltage offset in volts without unit')
                    trigger_input.on('keyup', set_trigger_manual)
                    ui.button('+', on_click=lambda: (asyncio.create_task(set_trigger('+')))).style(f"background-color: {orange_rigol} !important;").classes("square-button")
        with ui.row().classes('items-center').style('gap: 136px;'):
            with ui.grid(columns=5).classes("gap-4"):
                with ui.column():
                    ui.label('CH1 Freq').style('color: white; font-size: 0.8rem').classes("slider-size")
                    meas_ch1_freq = ui.label('').style('color: white; font-size: 0.8rem').classes("meas1-size")
                with ui.column():
                    ui.label('CH1 Period').style('color: white; font-size: 0.8rem').classes("slider-size")
                    meas_ch1_period = ui.label('').style('color: white; font-size: 0.8rem').classes("meas1-size")
                with ui.column():
                    ui.label('CH1 V Min').style('color: white; font-size: 0.8rem').classes("slider-size")
                    meas_ch1_vmin = ui.label('').style('color: white; font-size: 0.8rem').classes("meas1-size")
                with ui.column():
                    ui.label('CH1 V Max').style('color: white; font-size: 0.8rem').classes("slider-size")
                    meas_ch1_vmax = ui.label('').style('color: white; font-size: 0.8rem').classes("meas1-size")
                with ui.column():
                    ui.label('CH1 +Duty').style('color: white; font-size: 0.8rem').classes("slider-size")
                    meas_ch1_pduty = ui.label('').style('color: white; font-size: 0.8rem').classes("meas1-size")
                with ui.column():
                    ui.label('CH2 Freq').style('color: white; font-size: 0.8rem').classes("slider-size")
                    meas_ch2_freq = ui.label('').style('color: white; font-size: 0.8rem').classes("meas2-size")
                with ui.column():
                    ui.label('CH2 Period').style('color: white; font-size: 0.8rem').classes("slider-size")
                    meas_ch2_period = ui.label('').style('color: white; font-size: 0.8rem').classes("meas2-size")
                with ui.column():
                    ui.label('CH2 V Min').style('color: white; font-size: 0.8rem').classes("slider-size")
                    meas_ch2_vmin = ui.label('').style('color: white; font-size: 0.8rem').classes("meas2-size")
                with ui.column():
                    ui.label('CH2 V Max').style('color: white; font-size: 0.8rem').classes("slider-size")
                    meas_ch2_vmax = ui.label('').style('color: white; font-size: 0.8rem').classes("meas2-size")
                with ui.column():
                    ui.label('CH2 +Duty').style('color: white; font-size: 0.8rem').classes("slider-size")
                    meas_ch2_pduty = ui.label('').style('color: white; font-size: 0.8rem').classes("meas2-size")
            measure_button = ui.button("MEASURE").classes("button-size button-grey")

# Loading overlay
loading_overlay = ui.column().style(
    "position: fixed; top: 0; left: 0; width: 100%; height: 100%;"
    "background-color: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 1000;"
)
loading_overlay.visible = False
with loading_overlay:
    ui.spinner(size=50)
    ui.label("Connecting...").classes("text-white")

# Assign event handlers to buttons
connect_button.on("click", lambda: asyncio.create_task(on_connect()))
clear_button.on("click", lambda: asyncio.create_task(send_command(":CLEAR")))
auto_button.on("click", lambda: asyncio.create_task(auto_action()))
run_stop_button.on("click", lambda: asyncio.create_task(toggle_run_stop()))
ch1_button.on("click", lambda: asyncio.create_task(toggle_channel(1, ch1_button)))
ch2_button.on("click", lambda: asyncio.create_task(toggle_channel(2, ch2_button)))
measure_button.on("click", lambda: asyncio.create_task(measurement()))

ui.run(title="Rigol Remote", port=12022)

