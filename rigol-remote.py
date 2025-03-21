# -*- coding: utf-8 -*-

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
  /* Classe aggiuntiva per uniformare la dimensione di pulsanti/label */
  .button-size {
    width: 100px;
    height: 40px;
    display: flex;
    align-items: center;
    justify-content: center;
    margin: 0; /* Per eliminare possibili margini interni */
  }
  .slider-size {
    width: 100px;
    height: 10px;
    display: flex;
    align-items: center;
    justify-content: center;
    margin: 0; /* Per eliminare possibili margini interni */
  }
  .vslider-size {
    width: 100px;
    height: 100px;
    display: flex;
    align-items: center;
    justify-content: center;
    margin: 0; /* Per eliminare possibili margini interni */
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

def query_offset_state():
    global selected_ip, selected_port
    screen = 0
    offset = 0
    command_screen = ":TIMEbase:MAIN:SCALe?\n"
    command_offset = ":TIMebase:MAIN:OFFSet?\n"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(5)
        s.connect((selected_ip, selected_port))
        s.sendall(command_screen.encode())
        response = s.recv(1024)
        screen = float(response.decode().strip())
        s.sendall(command_offset.encode()) 
        response = s.recv(1024)
        offset = float(response.decode().strip())
        return -offset/screen*5

def query_voltage_offset(channel):
    global selected_ip, selected_port
    range = 0
    offset = 0
    command_range = f":CHANnel{channel}:RANGe?\n"
    command_offset = f":CHANnel{channel}:OFFSet?\n"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(5)
        s.connect((selected_ip, selected_port))
        s.sendall(command_range.encode())
        response = s.recv(1024)
        range = float(response.decode().strip())
        s.sendall(command_offset.encode())
        response = s.recv(1024)
        offset = float(response.decode().strip())
        return -offset/range*40

def query_trigger():
    global selected_ip, selected_port
    range = 0
    offset = 0
    trigger = 0
    command_range = ":CHANnel1:RANGe?\n"
    command_offset = ":CHANnel1:OFFSet?\n"
    command_trigger = ":TRIGger:EDGe:LEVel?\n"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(5)
        s.connect((selected_ip, selected_port))
        s.sendall(command_range.encode())
        response = s.recv(1024)
        range = float(response.decode().strip())
        s.sendall(command_offset.encode())
        response = s.recv(1024)
        offset = float(response.decode().strip())
        s.sendall(command_trigger.encode())
        response = s.recv(1024)
        trigger = float(response.decode().strip())
        return -(trigger+offset)/range*40

async def update_channel_states():
    """Updates the channel states by querying the instrument and updates the channel buttons accordingly."""
    global channel1_state, channel2_state, ch1_button, ch2_button
    new_state1 = await asyncio.to_thread(query_channel_state, 1)
    new_state2 = await asyncio.to_thread(query_channel_state, 2)
    channel1_state = new_state1
    channel2_state = new_state2
    if channel1_state:
        ch1_button.props['class'] = "button-size button-green"
    else:
        ch1_button.props['class'] = "button-size button-grey"
    ch1_button.update()

    if channel2_state:
        ch2_button.props['class'] = "button-size button-green"
    else:
        ch2_button.props['class'] = "button-size button-grey"
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
        run_stop_button.props['class'] = "button-size button-green"
        run_stop_button.update()
        offset_slider.value = 0
        offset_slider.update()
        pos_ch1_slider.value = await asyncio.to_thread(query_voltage_offset, 1)
        pos_ch1_slider.update()
        pos_ch2_slider.value = await asyncio.to_thread(query_voltage_offset, 2)
        pos_ch2_slider.update()
        trig_slider.value = await asyncio.to_thread(query_trigger)
        trig_slider.update()

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
display_container = ui.column().classes("q-pa-md").style("max-width: 1200px; margin: auto;")
display_container.visible = False

with display_container:
    # Primo blocco: riga con canvas a sinistra e griglia di pulsanti a destra
    main_row = ui.row().classes("items-start")  # allineiamo in alto
    with main_row:
        # Left side: Canvas container
        canvas_container = ui.column().style("flex: 1;")
        with canvas_container:
            ui.html('''
            <canvas id="myCanvas" width="800" height="480"
                    style="display: block; background: #000;"></canvas>
            ''')

        # Right side: Grid di pulsanti/label
        with ui.grid(columns=3).classes("gap-5"):  # 3 colonne, 5 righe con i 15 elementi
            # Prima riga
            clear_button = ui.button("CLEAR").classes("button-size button-grey")
            auto_button = ui.button("AUTO").classes("button-size button-grey")
            run_stop_button = ui.button("RUN/STOP").classes("button-size button-red")  # parte come STOP
            # Seconda riga
            ch1_button = ui.button("CH1").classes("button-size button-grey")
            ch2_button = ui.button("CH2").classes("button-size button-grey")
            with ui.dropdown_button('Time', auto_close=False).props('style="text-transform:none;"').classes("button-size"):
                with ui.dropdown_button('ns', auto_close=True).props('style="text-transform:none;"'):
                    ui.item('5', on_click=lambda: asyncio.create_task(set_time(0.000000005)))
                    ui.item('10', on_click=lambda: asyncio.create_task(set_time(0.00000001)))
                    ui.item('20', on_click=lambda: asyncio.create_task(set_time(0.00000002)))
                    ui.item('50', on_click=lambda: asyncio.create_task(set_time(0.00000005)))
                    ui.item('100', on_click=lambda: asyncio.create_task(set_time(0.0000001)))
                    ui.item('200', on_click=lambda: asyncio.create_task(set_time(0.0000002)))
                    ui.item('500', on_click=lambda: asyncio.create_task(set_time(0.0000005)))
                with ui.dropdown_button('µs', auto_close=True).props('style="text-transform:none;"'):
                    ui.item('1', on_click=lambda: asyncio.create_task(set_time(0.000001)))
                    ui.item('2', on_click=lambda: asyncio.create_task(set_time(0.000002)))
                    ui.item('5', on_click=lambda: asyncio.create_task(set_time(0.000005)))
                    ui.item('10', on_click=lambda: asyncio.create_task(set_time(0.00001)))
                    ui.item('20', on_click=lambda: asyncio.create_task(set_time(0.00002)))
                    ui.item('50', on_click=lambda: asyncio.create_task(set_time(0.00005)))
                    ui.item('100', on_click=lambda: asyncio.create_task(set_time(0.0001)))
                    ui.item('200', on_click=lambda: asyncio.create_task(set_time(0.0002)))
                    ui.item('500', on_click=lambda: asyncio.create_task(set_time(0.0005)))
                with ui.dropdown_button('ms', auto_close=True).props('style="text-transform:none;"'):
                    ui.item('1', on_click=lambda: asyncio.create_task(set_time(0.001)))
                    ui.item('2', on_click=lambda: asyncio.create_task(set_time(0.002)))
                    ui.item('5', on_click=lambda: asyncio.create_task(set_time(0.005)))
                    ui.item('10', on_click=lambda: asyncio.create_task(set_time(0.01)))
                    ui.item('20', on_click=lambda: asyncio.create_task(set_time(0.02)))
                    ui.item('50', on_click=lambda: asyncio.create_task(set_time(0.05)))
                    ui.item('100', on_click=lambda: asyncio.create_task(set_time(0.1)))
                    ui.item('200', on_click=lambda: asyncio.create_task(set_time(0.2)))
                    ui.item('500', on_click=lambda: asyncio.create_task(set_time(0.5)))
                with ui.dropdown_button('s', auto_close=True).props('style="text-transform:none;"'):
                    ui.item('1', on_click=lambda: asyncio.create_task(set_time(1)))
                    ui.item('5', on_click=lambda: asyncio.create_task(set_time(2)))
                    ui.item('5', on_click=lambda: asyncio.create_task(set_time(5)))
                    ui.item('10', on_click=lambda: asyncio.create_task(set_time(10)))
                    ui.item('20', on_click=lambda: asyncio.create_task(set_time(20)))
                    ui.item('50', on_click=lambda: asyncio.create_task(set_time(50)))

            # Terza riga
            with ui.dropdown_button('Scale CH1', auto_close=False).props('style="text-transform:none;"').classes("button-size"):
                with ui.dropdown_button('mV', auto_close=True).props('style="text-transform:none;"'):
                    ui.item('1', on_click=lambda: asyncio.create_task(set_voltage(0.001,1)))
                    ui.item('2', on_click=lambda: asyncio.create_task(set_voltage(0.002,1)))
                    ui.item('5', on_click=lambda: asyncio.create_task(set_voltage(0.005,1)))
                    ui.item('10', on_click=lambda: asyncio.create_task(set_voltage(0.01,1)))
                    ui.item('20', on_click=lambda: asyncio.create_task(set_voltage(0.02,1)))
                    ui.item('50', on_click=lambda: asyncio.create_task(set_voltage(0.05,1)))
                    ui.item('100', on_click=lambda: asyncio.create_task(set_voltage(0.1,1)))
                    ui.item('200', on_click=lambda: asyncio.create_task(set_voltage(0.2,1)))
                    ui.item('500', on_click=lambda: asyncio.create_task(set_voltage(0.5,1)))
                with ui.dropdown_button('V', auto_close=True).props('style="text-transform:none;"'):
                    ui.item('1', on_click=lambda: asyncio.create_task(set_voltage(1,1)))
                    ui.item('2', on_click=lambda: asyncio.create_task(set_voltage(2,1)))
                    ui.item('5', on_click=lambda: asyncio.create_task(set_voltage(5,1)))
                    ui.item('10', on_click=lambda: asyncio.create_task(set_voltage(10,1)))
            
            with ui.dropdown_button('Scale CH2', auto_close=False).props('style="text-transform:none;"').classes("button-size"):
                with ui.dropdown_button('mV', auto_close=True).props('style="text-transform:none;"'):
                    ui.item('1', on_click=lambda: asyncio.create_task(set_voltage(0.001,2)))
                    ui.item('2', on_click=lambda: asyncio.create_task(set_voltage(0.002,2)))
                    ui.item('5', on_click=lambda: asyncio.create_task(set_voltage(0.005,2)))
                    ui.item('10', on_click=lambda: asyncio.create_task(set_voltage(0.01,2)))
                    ui.item('20', on_click=lambda: asyncio.create_task(set_voltage(0.02,2)))
                    ui.item('50', on_click=lambda: asyncio.create_task(set_voltage(0.05,2)))
                    ui.item('100', on_click=lambda: asyncio.create_task(set_voltage(0.1,2)))
                    ui.item('200', on_click=lambda: asyncio.create_task(set_voltage(0.2,2)))
                    ui.item('500', on_click=lambda: asyncio.create_task(set_voltage(0.5,2)))
                with ui.dropdown_button('V', auto_close=True).props('style="text-transform:none;"'):
                    ui.item('1', on_click=lambda: asyncio.create_task(set_voltage(1,2)))
                    ui.item('2', on_click=lambda: asyncio.create_task(set_voltage(2,2)))
                    ui.item('5', on_click=lambda: asyncio.create_task(set_voltage(5,2)))
                    ui.item('10', on_click=lambda: asyncio.create_task(set_voltage(10,2)))

            with ui.column():
                ui.label('Time Offset').style('color: white; font-size: 0.8rem').classes("slider-size")
                offset_slider = ui.slider(min=-30, max=30, value=0, on_change=lambda e: asyncio.create_task(set_offset(e.value))).classes("slider-size")
            # Quarta riga
            with ui.column():
                ui.label('CH1 VOffset').style('color: white; font-size: 0.8rem').classes("slider-size")
                pos_ch1_slider = ui.slider(min=-20, max=20, value=0, on_change=lambda e: asyncio.create_task(set_voltage_offset(e.value, 1))).props('vertical').classes("vslider-size")
            with ui.column():
                ui.label('CH2 VOffset').style('color: white; font-size: 0.8rem').classes("slider-size")
                pos_ch2_slider = ui.slider(min=-20, max=20, value=0, on_change=lambda e: asyncio.create_task(set_voltage_offset(e.value, 2))).props('vertical').classes("vslider-size")
            with ui.column():
                ui.label('Trigger').style('color: white; font-size: 0.8rem').classes("slider-size")
                trig_slider = ui.slider(min=-30, max=30, value=0, on_change=lambda e: asyncio.create_task(set_trigger(e.value))).props('vertical').classes("vslider-size")

    # Secondo blocco: etichetta di info strumentazione sotto, a piena larghezza
    instrument_label = ui.label("").style("color: yellow; white-space: pre-line; margin-top: 20px;")

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

    offset_slider.value = await asyncio.to_thread(query_offset_state)
    offset_slider.update() 

    pos_ch1_slider.value = await asyncio.to_thread(query_voltage_offset, 1)
    pos_ch1_slider.update()
    
    pos_ch2_slider.value = await asyncio.to_thread(query_voltage_offset, 2)
    pos_ch2_slider.update()
    
    trig_slider.value = await asyncio.to_thread(query_trigger)
    trig_slider.update()
    
    # Avvia un timer per aggiornare periodicamente il canvas
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

async def set_time(time):
    """Set time"""
    try:
        await asyncio.to_thread(send_command_to_scope, f":TIMebase:MAIN:SCALe {time}")
    except:
        print("Error setting time")

async def set_offset(offset):
    """Set time offset"""
    global selected_ip, selected_port
    try:
        screen = 0
        command = ":TIMEbase:MAIN:SCALe?\n"
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(5)
            s.connect((selected_ip, selected_port))
            s.sendall(command.encode())
            response = s.recv(1024)
            screen = float(response.decode().strip())*12
        await asyncio.to_thread(send_command_to_scope, f":TIMebase:MAIN:OFFSet {-screen/60*offset}")
    except:
        print("Error setting time offset")

async def set_voltage_offset(offset, channel):
    """Set voltage offset per channel"""
    global selected_ip, selected_port
    try:
        range = 0
        command = f":CHANnel{channel}:RANGe?\n"
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(5)
            s.connect((selected_ip, selected_port))
            s.sendall(command.encode())
            response = s.recv(1024)
            range = float(response.decode().strip())
        await asyncio.to_thread(send_command_to_scope, f":CHANnel{channel}:OFFSet {-offset*range/40}")
    except:
        print("Error setting voltage offset")

async def set_trigger(trig):
    """Set trigger value"""
    global selected_ip, selected_port
    try:
        range = 0
        offset = 0
        command_range = ":CHANnel1:RANGe?\n"
        command_offset = ":CHANnel1:OFFSet?\n"
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(5)
            s.connect((selected_ip, selected_port))
            s.sendall(command_range.encode())
            response = s.recv(1024)
            range = float(response.decode().strip())
            s.sendall(command_offset.encode())
            response = s.recv(1024)
            offset = float(response.decode().strip())
        await asyncio.to_thread(send_command_to_scope, f":TRIGger:EDGe:LEVel {-trig*range/40-offset}")
    except:
        print("Error setting trigger offset")

async def set_voltage(volt, channel):
    """Set Voltage Scale"""
    try:
        await asyncio.to_thread(send_command_to_scope, f":CHANnel{channel}:SCALe {volt}")
    except:
        print("Error setting voltage")

async def toggle_channel(channel, button):
    """Toggles the channel: if off, sends the command to turn it ON and updates the button to green; if on, sends the command to turn it OFF and updates the button to grey."""
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
                button.props['class'] = "button-size button-green"
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
                button.props['class'] = "button-size button-green"
                button.update()
            except Exception as e:
                print("Error turning CH2 on:", e)

# Assegniamo gli handler ai pulsanti effettivi
clear_button.on("click", lambda: asyncio.create_task(send_command(":CLEAR")))
auto_button.on("click", lambda: asyncio.create_task(auto_action()))
run_stop_button.on("click", lambda: asyncio.create_task(toggle_run_stop()))
ch1_button.on("click", lambda: asyncio.create_task(toggle_channel(1, ch1_button)))
ch2_button.on("click", lambda: asyncio.create_task(toggle_channel(2, ch2_button)))

ui.run(title="Rigol Remote")

