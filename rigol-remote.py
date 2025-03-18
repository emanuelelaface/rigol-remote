import socket
import asyncio
import base64
from nicegui import ui

# Add global style for browser background.
ui.add_head_html('''
<style>
  body { background-color: #343541; }
</style>
''')

# Global variables for connection parameters.
selected_ip = None
selected_port = None
instrument_name = None

def check_connection(ip, port):
    """Sends the *IDN? command to check the connection and retrieve the instrument name."""
    command = "*IDN?\n"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(5)
        s.connect((ip, port))
        s.sendall(command.encode())
        response = s.recv(1024)
        instrument = response.decode().strip() if response else "Unknown"
        return instrument

def get_png_image():
    """
    Retrieves the PNG image from the oscilloscope in SCPI binary block format.
    
    The expected format is:
      - 1st byte: '#' character
      - 2nd byte: a digit N indicating how many digits follow for the length
      - Next N bytes: the ASCII representation of the data length (leading zeros removed)
      - Following bytes: the PNG image data of that length
    """
    global selected_ip, selected_port
    command = ':DISPlay:DATA? ON,OFF,PNG\n'
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(60)
        s.connect((selected_ip, selected_port))
        s.sendall(command.encode())
        # Read the first 2 bytes (should be something like b'#4')
        header = s.recv(2)
        if len(header) < 2 or header[0:1] != b'#':
            raise ValueError("Invalid header received")
        # The second byte indicates the number of digits in the length field.
        try:
            n_digits = int(header[1:2].decode())
        except Exception as e:
            raise ValueError("Cannot parse header digit") from e
        # Read the length field (n_digits bytes)
        length_bytes = bytearray()
        while len(length_bytes) < n_digits:
            chunk = s.recv(n_digits - len(length_bytes))
            if not chunk:
                break
            length_bytes.extend(chunk)
        # Convert the length field (strip leading zeros)
        data_length = int(length_bytes.decode().lstrip("0") or "0")
        # Now, read exactly data_length bytes of PNG data.
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
    """Converts binary PNG data into a data URL for display in an HTML canvas."""
    encoded = base64.b64encode(data).decode('utf-8')
    return f"data:image/png;base64,{encoded}"

# Create a connection form inside a card.
connection_card = ui.card().classes('q-pa-md q-ma-md').style('max-width: 400px; margin: auto;')
with connection_card:
    ui.label("Oscilloscope Connection")
    ip_input = ui.input(label="IP Address", placeholder="e.g. 192.168.212.202")
    port_input = ui.input(label="Port", placeholder="e.g. 5555")
    connection_status = ui.label("")
    connect_button = ui.button("Connect")

# Create a container for the canvas (initially hidden).
canvas_container = ui.column()
canvas_container.visible = False
with canvas_container:
    ui.html('''
    <canvas id="myCanvas" width="800" height="480" 
            style="display: block; margin: auto; background: #000;"></canvas>
    ''')

# Label to display the instrument name (initially hidden).
instrument_label = ui.label("")
instrument_label.visible = False

# Create a full-window loading overlay with a spinner.
loading_overlay = ui.column().style(
    "position: fixed; top: 0; left: 0; width: 100%; height: 100%;"
    "background-color: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 1000;"
)
loading_overlay.visible = False
with loading_overlay:
    ui.spinner(size=50)
    ui.label("Connecting...").classes("text-white")

async def on_connect():
    """Called when the Connect button is clicked to verify the connection and start acquisition."""
    global selected_ip, selected_port, instrument_name
    
    # Show the loading overlay.
    loading_overlay.visible = True
    
    ip = ip_input.value.strip()
    try:
        port = int(port_input.value.strip())
    except ValueError:
        connection_status.set_text("Invalid port")
        loading_overlay.visible = False
        return
    try:
        # Check connection using *IDN? command.
        instrument = await asyncio.to_thread(check_connection, ip, port)
    except Exception as e:
        connection_status.set_text(f"Connection failed: {e}")
        loading_overlay.visible = False
        return
    # Save connection parameters and display instrument name.
    selected_ip = ip
    selected_port = port
    instrument_name = instrument
    connection_status.set_text("Connection successful!")
    fields = instrument_name.split(',')
    instrument_label.style("color: yellow; white-space: pre-line;")
    instrument_label.set_text(f"Manufacturer: {fields[0]}\nModel: {fields[1]}\nSerial: {fields[2]}\nVersion: {fields[3]}")

    
    # Hide the connection form and show the canvas and instrument label.
    connection_card.visible = False
    instrument_label.visible = True
    canvas_container.visible = True
    
    # Remove the loading overlay completely.
    loading_overlay.delete()
    
    # Create the timer inside the canvas container's slot.
    with canvas_container:
        ui.timer(0.3, update_canvas)

connect_button.on("click", lambda: asyncio.create_task(on_connect()))

async def update_canvas():
    """Updates the HTML canvas with the PNG image acquired from the oscilloscope."""
    try:
        png_data = await asyncio.to_thread(get_png_image)
    except Exception as e:
        print(f"Canvas update error: {e}")
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

ui.run(title="Rigol Remote")


