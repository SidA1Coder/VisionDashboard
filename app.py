from flask import Flask, render_template, redirect, url_for, request, session
import pyodbc
import struct
import traceback
import requests
from PIL import Image, UnidentifiedImageError, ImageFile
from io import BytesIO
import base64
import cairosvg
import io

# Initialize Flask app
app = Flask(__name__)
app.secret_key = 'your_secret_key'


# Database query function
def query_database(query, args=(), one=False):
    try:
        conn = pyodbc.connect(
            r'DRIVER={ODBC Driver 13 for SQL Server};'
            r'SERVER=pgt3messqlods.fs.local;'
            r'DATABASE=ODS;'
            r'Trusted_Connection=yes;'
        )
        conn.add_output_converter(-155, handle_datetimeoffset)
        cur = conn.cursor()
        cur.execute(query, args)
        rv = cur.fetchall()
        cur.close()
        conn.close()
        return (rv[0] if rv else None) if one else rv
    except Exception as e:
        print(f"Error querying database: {e}")
        raise


# Handle datetime conversion
def handle_datetimeoffset(dto_value):
    tup = struct.unpack("<6hI2h", dto_value)
    tweaked = [tup[i] // 100 if i == 6 else tup[i] for i in range(len(tup))]
    return "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}.{:07d} {:+03d}:{:02d}".format(*tweaked)


@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username == 'FSROC' and password == 'Rockets1':
            session['logged_in'] = True
            return redirect(url_for('dashboard'))
        else:
            error = 'Invalid Credentials. Please try again.'
            return render_template('login.html', error=error)
    return render_template('login.html')


@app.route('/dashboard')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('dashboard.html')


@app.route('/data_input', methods=['GET', 'POST'])
def data_input():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    if request.method == 'POST':
        tool = request.form.get('tool')
        search_by = request.form.get('search_by')
        sub_id = request.form.get('sub_id')
        frame_id = request.form.get('frame_id')
        date = request.form.get('date') 

        try:
            image_urls = []
            error = None
            if search_by == 'date' and date:
                if tool == 'bussing':
                    image_urls = fetch_bussing_images_by_date(date)
                elif tool == 'frame':
                    image_urls = fetch_images_by_date(tool, date)
            elif search_by == 'sub_id':
                if tool == 'bussing' and sub_id:
                    # Support multiple Sub IDs if needed
                    sub_ids = [sid.strip() for sid in sub_id.split(',') if sid.strip()]
                    images = {}
                    for sid in sub_ids:
                        result = fetch_bussing_images(sub_id=sid)
                        if result:
                            images.update(result)
                    image_urls = images
                elif tool == 'frame' and frame_id:
                    # Support multiple Frame IDs
                    frame_ids = [fid.strip() for fid in frame_id.split(',') if fid.strip()]
                    images = {}
                    for fid in frame_ids:
                        result = fetch_frame_images(frame_id=fid)
                        if result:
                            images.update(result)
                    image_urls = images
                else:
                    error = "Please provide the correct ID based on the selected tool."
            else:
                error = "Please provide the correct ID or Date based on the selected tool."
            return render_template('result.html', image_urls=image_urls, tool=tool, error=error)
        except ValueError as ve:
            error = str(ve)
            return render_template('result.html', image_urls=[], tool=tool, error=error)
        except Exception as e:
            error = traceback.format_exc()
            return render_template('result.html', image_urls=[], tool=tool, error=error)

    return render_template('data_input.html')


def fetch_image_paths(query, args):
    results = query_database(query, args)
    if not results:
        raise ValueError("No images found for the provided ID.")
    return results

def fetch_images_by_date(tool, date):
    query = """
    SELECT DISTINCT TOP 100 MaterialId AS FrameId
    FROM [ModuleAssembly].[ImageDataMart].[Image]
    WHERE CollectedDateTimeOffset >= ? AND CollectedDateTimeOffset < DATEADD(day, 1, ?)
    """
    print(f"Fetching images for date: {date}")
    image_paths = query_database(query, (date, date))
    frame_ids = [result.FrameId for result in image_paths if result.FrameId]
    
    images = {}
    valid_id_count = 0
    index = 0
    
    while valid_id_count < 6 and index < len(frame_ids):
        frame_id = frame_ids[index]
        fetched_images = fetch_frame_images(frame_id=frame_id)
        index += 1
        if fetched_images:
            total_valid_images = sum(
                len([img for img in cam_images.values() if img]) 
                for cam_images in fetched_images[frame_id].values()
            )
            if total_valid_images > 0:
                images.update(fetched_images)
                valid_id_count += 1
    
    return images if images else {"error": "No images found for the provided date."}

def fetch_bussing_images_by_date(date):
    query = """
    SELECT DISTINCT TOP 100 SubId
    FROM [ModuleAssembly].[ImageDataMart].[Image]
    WHERE CollectedDateTimeOffset >= ? AND CollectedDateTimeOffset < DATEADD(day, 1, ?)
    AND Station = 'BB'
    """
    print(f"Fetching bussing images for date: {date}")
    image_paths = query_database(query, (date, date))
    sub_ids = [result.SubId for result in image_paths if result.SubId]

    images = {}
    valid_id_count = 0
    index = 0
    
    while valid_id_count < 6 and index < len(sub_ids):
        sub_id = sub_ids[index]
        fetched_images = fetch_bussing_images(sub_id=sub_id)
        index += 1
        if fetched_images:
            total_valid_images = sum(
                len([img for img in cam_images.values() if img]) 
                for cam_images in fetched_images[sub_id].values()
            )
            if total_valid_images > 0:
                images.update(fetched_images)
                valid_id_count += 1
    
    return images if images else {"error": "No images found for the provided date."}
def fetch_bussing_images(sub_id):
    query = """
    SELECT StoredFilePath, Camera, Zone, CollectedDateTimeOffset
    FROM [ModuleAssembly].[ImageDataMart].[Image]
    WHERE SubId = ?
    """
    image_paths = fetch_image_paths(query, (sub_id,))
    base_url = "http://pgt3messf.mfg.fs:19081/ImageDataMartApplication/ImageDataMart/images/"

    grouped_images = {
        "Cam 1": {f"Zone {i}": None for i in range(1, 9)},
        "Cam 2": {f"Zone {i}": None for i in range(1, 9)}
    }

    cam_mapping = {"CAM1": "Cam 1", "CAM2": "Cam 2"}
    # Assuming the attribute should be 'Zone'
    zone_mapping = {f"CAP{i}": f"Zone {i}" for i in range(1, 9)}
    image_fetched = False

    for path in image_paths:
        image_url = base_url + path.StoredFilePath.replace("\\", "/")
        camera_key = cam_mapping.get(path.Camera.strip(), None)
        if path.Zone is None:
            continue
        # Fixed to ensure 'Zone' attribute is correctly accessed
        zone_key = zone_mapping.get(path.Zone.strip(), None)
        if not camera_key or not zone_key:
            continue
        
        try:
            image = fetch_image_from_url(image_url)
            if image:
                buffer = BytesIO()
                image.save(buffer, format='PNG')
                image_base64 = f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode('utf-8')}"
                grouped_images[camera_key][zone_key] = image_base64
                image_fetched = True
        except Exception as e:
            continue
    
    return {sub_id: grouped_images} if image_fetched else {}

def fetch_frame_images(frame_id):
    query = """
    SELECT StoredFilePath, Camera, Mode, CollectedDateTimeOffset
    FROM [ModuleAssembly].[ImageDataMart].[Image]
    WHERE MaterialId = ?
    """
    results = fetch_image_paths(query, (frame_id,))
    if not results:
        print(f"No results found for frame_id: {frame_id}")
        return {}

    base_url = "http://pgt3messf.mfg.fs:19081/ImageDataMartApplication/ImageDataMart/images/"
    grouped_images = {
        "Cam 1": {f"Mode {i}": None for i in range(2, 7)},
        "Cam 2": {f"Mode {i}": None for i in range(2, 7)},
    }
    cam_mapping = {"CAM1": "Cam 1", "CAM2": "Cam 2"}
    mode_mapping = {f"MODE{i}": f"Mode {i}" for i in range(2, 7)}
    image_fetched = False

    for result in results:
        image_url = base_url + result.StoredFilePath.replace("\\", "/")
        svg_url = image_url.replace('.bmp', '.svg').replace('.jpg', '.svg')
        camera_key = cam_mapping.get(result.Camera.strip(), None)
        mode_key = mode_mapping.get(result.Mode.strip(), None)
        if not camera_key or not mode_key:
            continue
        try:
            base_image_response = requests.get(image_url)
            base_image_response.raise_for_status()
            base_image = base_image_response.content

            overlay_image_content = fetch_svg_content(svg_url)
            if overlay_image_content:
                base_image_obj = Image.open(BytesIO(base_image)).convert("RGBA")
                overlay_bytes = convert_svg_to_png(overlay_image_content, base_image_obj.width, base_image_obj.height)
                combined_image = overlay_images(base_image, overlay_bytes)
                grouped_images[camera_key][mode_key] = f"data:image/png;base64,{combined_image}"
                image_fetched = True
            else:
                print(f"No overlay content found for SVG: {svg_url}")
        except requests.RequestException as e:
            print(f"Request error processing URLs: Image URL={image_url}, SVG URL={svg_url}, error: {e}")
        except UnidentifiedImageError as e:
            print(f"UnidentifiedImageError for image or SVG: Image URL={image_url}, SVG URL={svg_url}, error: {e}")
        except Exception as e:
            print(f"Unexpected error processing image URLs: {image_url}, {svg_url}, error: {e}")

    return {frame_id: grouped_images} if image_fetched else {}

def fetch_image_from_url(image_url):
    try:
        print(f"Fetching image from URL: {image_url}")
        r = requests.get(image_url, stream=True)
        r.raise_for_status()  # Ensure we catch HTTP errors

        image = Image.open(io.BytesIO(r.content)).convert("RGBA")
        print(f"Fetched image with size {image.size} and format {image.format}")
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        with open("debug_fetched_image.png", "wb") as f:
            f.write(buffer.getvalue())

        return image
    except requests.exceptions.RequestException as e:
        print(f"Error fetching image from {image_url}: {e}")
        raise
    except UnidentifiedImageError as e:
        print(f"Could not identify the image fetched from {image_url}: {e}")
        return None  # Return None instead of raising an error


def fetch_svg_content(svg_url):
    try:
        print(f"Fetching SVG content from {svg_url}")
        svg_response = requests.get(svg_url)
        svg_response.raise_for_status()
        print(f"Fetched SVG content with size {len(svg_response.content)} bytes")

        # Save the SVG for later debugging
        with open("debug_fetched_svg.svg", "wb") as f:
            f.write(svg_response.content)

        return svg_response.content
    except requests.exceptions.RequestException as e:
        print(f"Error fetching SVG from {svg_url}: {e}")
        raise
    except UnidentifiedImageError as e:
        print(f"Could not identify the SVG fetched from {svg_url}: {e}")
        return None  # Return None instead of raising an error


def convert_svg_to_png(svg_content, width, height):
    try:
        print(f"Converting SVG to PNG with width={width}, height={height}")
        png_bytes = cairosvg.svg2png(bytestring=svg_content, output_width=width, output_height=height)
        print(f"SVG converted to PNG successfully")
        return png_bytes
    except Exception as e:
        print(f"Failed to convert SVG to PNG: {e}")
        with open("temporary_debug_svg_failure.svg", "wb") as f:
            f.write(svg_content)
        raise ValueError(f"Failed to convert SVG to PNG: {e}")


def overlay_images(base_image_content, overlay_bytes):
    try:
        print(f"Overlaying images")
        ImageFile.LOAD_TRUNCATED_IMAGES = True
        base_image = Image.open(BytesIO(base_image_content)).convert("RGBA")
        overlay_image = Image.open(BytesIO(overlay_bytes)).convert("RGBA")

        # Ensure the overlay image has an alpha channel
        if overlay_image.mode != 'RGBA':
            overlay_image = overlay_image.convert("RGBA")

        # Merge the images
        combined = Image.alpha_composite(base_image, overlay_image)
        buffer = BytesIO()
        combined.save(buffer, format="PNG")
        buffer.seek(0)

        # Save the combined image for later debugging
        with open("combined_debug_image.png", "wb") as f:
            f.write(buffer.getvalue())

        print(f"Images overlaid successfully")
        return base64.b64encode(buffer.getvalue()).decode('utf-8')
    except UnidentifiedImageError as e:
        print(f"Could not identify image file: {e}")
        raise ValueError(f"Could not identify image file: {e}")
    except Exception as e:
        print(f"Failed to merge images: {e}")
        raise ValueError(f"Failed to merge images: {e}")


@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))


if __name__ == '__main__':
    app.run(debug=True)