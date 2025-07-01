import io
import requests
from PIL import Image, UnidentifiedImageError, ImageFile
from io import BytesIO
import base64
import cairosvg
from .utils import query_database
from .config import Config
from collections import defaultdict # Add this import

def fetch_image_from_url(image_url):
    try:
        print(f"Fetching image from URL: {image_url}")
        r = requests.get(image_url, stream=True)
        r.raise_for_status()
        image = Image.open(io.BytesIO(r.content)).convert("RGBA")
        print(f"Fetched image with size {image.size} and format {image.format}")
        # Debug save can be conditional or removed for production
        # buffer = BytesIO()
        # image.save(buffer, format="PNG")
        # with open("debug_fetched_image.png", "wb") as f:
        #     f.write(buffer.getvalue())
        return image
    except requests.exceptions.RequestException as e:
        print(f"Error fetching image from {image_url}: {e}")
        raise
    except UnidentifiedImageError as e:
        print(f"Could not identify the image fetched from {image_url}: {e}")
        return None

def fetch_svg_content(svg_url):
    try:
        print(f"Fetching SVG content from {svg_url}")
        svg_response = requests.get(svg_url)
        svg_response.raise_for_status()
        print(f"Fetched SVG content with size {len(svg_response.content)} bytes")
        # Debug save can be conditional or removed for production
        # with open("debug_fetched_svg.svg", "wb") as f:
        #     f.write(svg_response.content)
        return svg_response.content
    except requests.exceptions.RequestException as e:
        print(f"Error fetching SVG from {svg_url}: {e}")
        raise
    except UnidentifiedImageError as e: # This exception is less likely for SVG text content
        print(f"Error (UnidentifiedImageError) fetching SVG from {svg_url}: {e}")
        return None

def convert_svg_to_png(svg_content_bytes, width, height):
    # This is your current SVG conversion logic.
    # Keep in mind the issues you were facing with cairosvg for text.
    # When rsvg-convert is set up, this function would be the place to integrate it.
    try:
        print(f"Converting SVG to PNG with width={width}, height={height}")
        png_bytes = cairosvg.svg2png(bytestring=svg_content_bytes, output_width=width, output_height=height)
        print(f"SVG converted to PNG successfully")
        return png_bytes
    except Exception as e:
        print(f"Failed to convert SVG to PNG: {e}")
        # Saving the problematic SVG content (bytes)
        with open("temporary_debug_svg_failure.svg", "wb") as f:
            f.write(svg_content_bytes)
        # Consider not re-raising as ValueError immediately if you want to fallback gracefully
        # For now, keeping original behavior:
        raise ValueError(f"Failed to convert SVG to PNG: {e}")


def overlay_images(base_image_pil_or_bytes, overlay_png_bytes):
    try:
        print(f"Overlaying images")
        ImageFile.LOAD_TRUNCATED_IMAGES = True

        if isinstance(base_image_pil_or_bytes, Image.Image):
            base_image_pil = base_image_pil_or_bytes.convert("RGBA")
        else: # Assuming bytes
            base_image_pil = Image.open(BytesIO(base_image_pil_or_bytes)).convert("RGBA")
        
        overlay_image_pil = Image.open(BytesIO(overlay_png_bytes)).convert("RGBA")

        if base_image_pil.size != overlay_image_pil.size:
            print(f"Resizing overlay from {overlay_image_pil.size} to {base_image_pil.size}")
            overlay_image_pil = overlay_image_pil.resize(base_image_pil.size, Image.Resampling.LANCZOS)

        if overlay_image_pil.mode != 'RGBA': # Should already be RGBA from .convert()
            overlay_image_pil = overlay_image_pil.convert("RGBA")

        combined_pil = Image.alpha_composite(base_image_pil, overlay_image_pil)
        
        buffer = BytesIO()
        combined_pil.save(buffer, format="PNG")
        buffer.seek(0)
        # Debug save can be conditional
        # with open("combined_debug_image.png", "wb") as f:
        #     f.write(buffer.getvalue())
        print(f"Images overlaid successfully")
        return base64.b64encode(buffer.getvalue()).decode('utf-8')
    except UnidentifiedImageError as e:
        print(f"Could not identify image file during overlay: {e}")
        raise ValueError(f"Could not identify image file: {e}")
    except Exception as e:
        print(f"Failed to merge images: {e}")
        raise ValueError(f"Failed to merge images: {e}")

def _fetch_image_paths_db(query, args): # Renamed to avoid conflict if you had a global fetch_image_paths
    results = query_database(query, args)
    if not results:
        # Returning None instead of raising error immediately allows for graceful handling
        print(f"No image paths found for query: {query} with args: {args}")
        return None
    return results

# Helper for "station" tools: fetch by SubID
def fetch_station_images(station, sub_id):
    query = """
    SELECT StoredFilePath
    FROM [ModuleAssembly].[ImageDataMart].[Image]
    WHERE SubId = ? AND Station = ?
    """
    image_path_rows = _fetch_image_paths_db(query, (sub_id, station))
    if not image_path_rows:
        return {}

    from collections import defaultdict
    grouped_files = defaultdict(dict)
    for row in image_path_rows:
        path = row.StoredFilePath
        try:
            base, ext = path.rsplit('.', 1)
            grouped_files[base][ext.lower()] = path
        except ValueError:
            print(f"Warning: Could not parse file path {path}")
            continue
    
    processed_images = []
    for _, files in grouped_files.items():
        bmp_file = files.get('bmp')
        svg_file = files.get('svg')
        jpg_file = files.get('jpg')

        base_pil_image = None
        base_image_url_for_log = ""

        if bmp_file:
            url = Config.IMAGE_BASE_URL + bmp_file.replace("\\", "/")
            base_image_url_for_log = url
            try:
                base_pil_image = fetch_image_from_url(url)
            except Exception as e:
                print(f"Failed to fetch BMP {url}: {e}")
        
        if not base_pil_image and jpg_file:
            url = Config.IMAGE_BASE_URL + jpg_file.replace("\\", "/")
            base_image_url_for_log = url
            try:
                base_pil_image = fetch_image_from_url(url)
            except Exception as e:
                print(f"Failed to fetch JPG {url}: {e}")

        if not base_pil_image:
            continue # Skip if no base image

        # Attempt SVG overlay
        if svg_file:
            svg_url = Config.IMAGE_BASE_URL + svg_file.replace("\\", "/")
            try:
                svg_content_bytes = fetch_svg_content(svg_url)
                if svg_content_bytes:
                    overlay_png_bytes = convert_svg_to_png(svg_content_bytes, base_pil_image.width, base_pil_image.height)
                    if overlay_png_bytes:
                        combined_base64 = overlay_images(base_pil_image, overlay_png_bytes) # Pass PIL object
                        processed_images.append(f"data:image/png;base64,{combined_base64}")
                        continue # Successfully overlaid
            except Exception as e:
                print(f"Failed to process or overlay SVG {svg_url} for {base_image_url_for_log}: {e}")
        
        # Fallback to base image if no SVG or overlay failed
        buffer = BytesIO()
        base_pil_image.save(buffer, format='PNG')
        processed_images.append(f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode('utf-8')}")
        
    return {sub_id: processed_images} if processed_images else {}


# Helper for "station" tools: fetch by Date
def fetch_station_images_by_date(station, date_str):
    query = """
    SELECT DISTINCT TOP 100 SubId
    FROM [ModuleAssembly].[ImageDataMart].[Image]
    WHERE CAST(CollectedDateTimeOffset AS DATE) = ? AND Station = ? 
    ORDER BY SubId DESC 
    """ # Using CAST for date comparison, ensure date_str is in 'YYYY-MM-DD'
      # Added ORDER BY to get potentially more relevant recent images
    
    # The original query used: CollectedDateTimeOffset >= ? AND CollectedDateTimeOffset < DATEADD(day, 1, ?)
    # If date_str is just a date, the CAST approach is simpler. If it's a datetime, the original is better.
    # Assuming date_str is 'YYYY-MM-DD' from a date picker.
    sub_id_rows = query_database(query, (date_str, station))
    if not sub_id_rows:
        return {"error": f"No SubIds found for station {station} on date {date_str}."}

    sub_ids = [row.SubId for row in sub_id_rows if row.SubId]
    
    all_fetched_images = {}
    valid_id_count = 0
    
    for s_id in sub_ids:
        if valid_id_count >= 6: # Limit to 6 valid SubIDs with images
            break
        fetched_for_subid = fetch_station_images(station, s_id)
        if fetched_for_subid.get(s_id): # Check if images were actually found for this SubId
            all_fetched_images.update(fetched_for_subid)
            valid_id_count += 1
            
    return all_fetched_images if all_fetched_images else {"error": f"No images found for station {station} on {date_str} after checking SubIds."}

# For "frame" tool
def fetch_frame_images(frame_id):
    query = """
    SELECT StoredFilePath, Camera, Mode
    FROM [ModuleAssembly].[ImageDataMart].[Image]
    WHERE MaterialId = ?
    """
    # Original code used fetch_image_paths which raised ValueError.
    # Using _fetch_image_paths_db which returns None on no results for consistency.
    results = _fetch_image_paths_db(query, (frame_id,))
    if not results:
        print(f"No image data found for frame_id: {frame_id}")
        return {}

    grouped_images_by_cam_mode = {
        "Cam 1": {f"Mode {i}": None for i in range(2, 7)},
        "Cam 2": {f"Mode {i}": None for i in range(2, 7)},
    }
    cam_mapping = {"CAM1": "Cam 1", "CAM2": "Cam 2"}
    mode_mapping = {f"MODE{i}": f"Mode {i}" for i in range(2, 7)}
    an_image_was_fetched_and_processed = False

    for result_row in results:
        image_file_path = result_row.StoredFilePath
        base_image_url = Config.IMAGE_BASE_URL + image_file_path.replace("\\", "/")
        # Derive SVG URL: replace extension. Handles .bmp or .jpg
        svg_file_path = '.'.join(image_file_path.split('.')[:-1]) + '.svg'
        svg_url = Config.IMAGE_BASE_URL + svg_file_path.replace("\\", "/")
        
        camera_key = cam_mapping.get(result_row.Camera.strip())
        mode_key = mode_mapping.get(result_row.Mode.strip())

        if not camera_key or not mode_key:
            print(f"Warning: Unknown camera/mode mapping for {result_row.Camera}/{result_row.Mode}")
            continue
        
        try:
            # Fetch base image (BMP/JPG) as bytes directly
            base_image_response = requests.get(base_image_url)
            base_image_response.raise_for_status()
            base_image_bytes = base_image_response.content # These are bytes

            # Attempt SVG overlay
            svg_content_bytes = fetch_svg_content(svg_url) # Returns bytes or None
            if svg_content_bytes:
                # Need PIL image object to get width/height for SVG conversion
                pil_base_for_size = Image.open(BytesIO(base_image_bytes))
                overlay_png_bytes = convert_svg_to_png(svg_content_bytes, pil_base_for_size.width, pil_base_for_size.height)
                if overlay_png_bytes:
                    # overlay_images expects base image as bytes and overlay as PNG bytes
                    combined_base64 = overlay_images(base_image_bytes, overlay_png_bytes)
                    grouped_images_by_cam_mode[camera_key][mode_key] = f"data:image/png;base64,{combined_base64}"
                    an_image_was_fetched_and_processed = True
                    continue # Move to next result row
            
            # Fallback: No SVG or SVG processing failed, use base image
            # Convert base_image_bytes to base64 PNG string
            pil_img = Image.open(BytesIO(base_image_bytes))
            buffer = BytesIO()
            pil_img.save(buffer, format="PNG")
            base64_png_str = base64.b64encode(buffer.getvalue()).decode('utf-8')
            grouped_images_by_cam_mode[camera_key][mode_key] = f"data:image/png;base64,{base64_png_str}"
            an_image_was_fetched_and_processed = True

        except requests.RequestException as e:
            print(f"Request error for {base_image_url} or {svg_url}: {e}")
        except UnidentifiedImageError as e:
            print(f"UnidentifiedImageError for {base_image_url}: {e}")
        except Exception as e:
            print(f"Unexpected error processing frame image {base_image_url}: {e}")
            
    return {frame_id: grouped_images_by_cam_mode} if an_image_was_fetched_and_processed else {}

def fetch_images_by_date_for_tool(tool_name, date_str): # Renamed from fetch_images_by_date
    # This function was specific to 'frame' tool in original code
    if tool_name != 'frame':
        return {"error": "This date search is configured for 'frame' tool only."}
    
    query = """
    SELECT DISTINCT TOP 100 MaterialId AS FrameId
    FROM [ModuleAssembly].[ImageDataMart].[Image]
    WHERE CAST(CollectedDateTimeOffset AS DATE) = ? 
    ORDER BY MaterialId DESC
    """ # Using CAST for date comparison
    print(f"Fetching frame images for date: {date_str}")
    frame_id_rows = query_database(query, (date_str,))
    if not frame_id_rows:
        return {"error": f"No FrameIDs found for date {date_str}."}

    frame_ids = [row.FrameId for row in frame_id_rows if row.FrameId]
    
    all_fetched_images = {}
    valid_id_count = 0
    
    for f_id in frame_ids:
        if valid_id_count >= 6:
            break
        fetched_for_frameid = fetch_frame_images(frame_id=f_id)
        # Check if the dictionary for f_id is not empty and contains actual image data
        if fetched_for_frameid.get(f_id) and any(any(cam.values()) for cam in fetched_for_frameid[f_id].values()):
            all_fetched_images.update(fetched_for_frameid)
            valid_id_count += 1
            
    return all_fetched_images if all_fetched_images else {"error": f"No frame images found for {date_str} after checking FrameIDs."}

# For "bussing" tool
def fetch_bussing_images(sub_id):
    query = """
    SELECT StoredFilePath, Camera, Zone
    FROM [ModuleAssembly].[ImageDataMart].[Image]
    WHERE SubId = ? AND Station = 'BB' 
    """
    image_path_rows = _fetch_image_paths_db(query, (sub_id,))
    if not image_path_rows:
        return {sub_id: {}} # Return empty structure for the sub_id if no paths

    # Group files by their base name, camera, and zone to pair image with its SVG
    # Key: (camera_db_val, zone_db_val, base_filename_without_ext_and_some_path_parts)
    # Value: {'bmp': path, 'jpg': path, 'svg': path}
    files_by_cam_zone_base = defaultdict(lambda: defaultdict(str))

    for row in image_path_rows:
        path = row.StoredFilePath
        camera_db_val = row.Camera.strip() if row.Camera else None
        zone_db_val = row.Zone.strip() if row.Zone else None # Zone from DB (e.g., 'CAP1')

        if not camera_db_val or not zone_db_val:
            print(f"Warning: Missing Camera or Zone for path {path} in bussing for SubId {sub_id}.")
            continue
        
        try:
            # The base filename needs to be consistent for grouping BMP/JPG with SVG
            # Example path: .../CAM1/250609_184051_250609812832_CAM1_CAP6_NG.svg
            # We want something like '.../CAM1/250609_184051_250609812832_CAM1_CAP6_NG' as the key part
            base_filename_key, ext = path.rsplit('.', 1)
            files_by_cam_zone_base[(camera_db_val, zone_db_val, base_filename_key)][ext.lower()] = path
        except ValueError:
            print(f"Warning: Could not parse file path {path} for bussing SubId {sub_id}.")
            continue

    grouped_images_by_cam_zone_display = {
        "Cam 1": {f"Zone {i}": None for i in range(1, 9)},
        "Cam 2": {f"Zone {i}": None for i in range(1, 9)}
    }
    cam_mapping = {"CAM1": "Cam 1", "CAM2": "Cam 2"}
    zone_mapping_from_db = {f"CAP{i}": f"Zone {i}" for i in range(1, 9)} # DB 'CAP1' to display 'Zone 1'
    an_image_was_processed = False

    for (camera_db_val, zone_db_val, base_file_key_path_part), files in files_by_cam_zone_base.items():
        camera_key_display = cam_mapping.get(camera_db_val)
        zone_key_display = zone_mapping_from_db.get(zone_db_val) # zone_db_val is e.g. 'CAP1'

        if not camera_key_display or not zone_key_display:
            print(f"Warning: Unknown camera/zone mapping for bussing: Cam DB={camera_db_val}, Zone DB={zone_db_val} for SubId {sub_id}")
            continue

        base_pil_image = None
        base_image_url_for_log = ""
        
        # Prioritize BMP, then JPG for base image
        base_image_stored_path = files.get('bmp') or files.get('jpg')
        svg_stored_path = files.get('svg')

        if base_image_stored_path:
            url = Config.IMAGE_BASE_URL + base_image_stored_path.replace("\\", "/")
            base_image_url_for_log = url
            try:
                base_pil_image = fetch_image_from_url(url) # Returns PIL Image or None
            except Exception as e:
                print(f"Failed to fetch base image {url} for bussing (SubId {sub_id}): {e}")
                # Continue to next group if base image fails, as overlay isn't possible
                continue 
        
        if not base_pil_image:
            # This can happen if base_image_stored_path was None, or fetch_image_from_url returned None or raised error
            if base_image_stored_path: # Only print if we attempted to fetch
                 print(f"Base image {base_image_url_for_log} could not be loaded for bussing (SubId {sub_id}).")
            # else: # This case means no BMP/JPG was found for this group, which is fine if an SVG was found (though unlikely for bussing)
            #    print(f"No BMP/JPG path found for Cam={camera_db_val}, Zone={zone_db_val}, BaseKey={base_file_key_path_part} (SubId {sub_id})")
            continue # Skip this group if no base image

        # Attempt SVG overlay if SVG path exists and base image was loaded
        final_image_base64 = None
        if svg_stored_path:
            svg_url = Config.IMAGE_BASE_URL + svg_stored_path.replace("\\", "/")
            try:
                svg_content_bytes = fetch_svg_content(svg_url) # Returns bytes or raises
                if svg_content_bytes:
                    # Ensure base_pil_image has width and height
                    if hasattr(base_pil_image, 'width') and hasattr(base_pil_image, 'height'):
                        overlay_png_bytes = convert_svg_to_png(svg_content_bytes, base_pil_image.width, base_pil_image.height) # Raises on failure
                        if overlay_png_bytes:
                            # overlay_images expects a PIL object or bytes for base, and bytes for overlay
                            final_image_base64 = overlay_images(base_pil_image, overlay_png_bytes) 
                    else:
                        print(f"Base PIL image for {base_image_url_for_log} is invalid or missing dimensions. Skipping SVG overlay.")
            except Exception as e: # Catch errors from fetch_svg_content, convert_svg_to_png, overlay_images
                print(f"Failed to process or overlay SVG {svg_url} for {base_image_url_for_log} (bussing, SubId {sub_id}): {e}")
        
        # If overlay was successful, final_image_base64 will be set.
        # Otherwise, fall back to using the base_pil_image.
        if final_image_base64:
            grouped_images_by_cam_zone_display[camera_key_display][zone_key_display] = f"data:image/png;base64,{final_image_base64}"
            an_image_was_processed = True
        elif base_pil_image: # Fallback to base image if SVG overlay wasn't done or failed
            try:
                buffer = BytesIO()
                base_pil_image.save(buffer, format='PNG') # Save the PIL image to buffer
                image_base64_fallback = base64.b64encode(buffer.getvalue()).decode('utf-8')
                grouped_images_by_cam_zone_display[camera_key_display][zone_key_display] = f"data:image/png;base64,{image_base64_fallback}"
                an_image_was_processed = True
            except Exception as e:
                print(f"Error converting base image to base64 for fallback {base_image_url_for_log} (bussing, SubId {sub_id}): {e}")
            
    return {sub_id: grouped_images_by_cam_zone_display} if an_image_was_processed else {sub_id: grouped_images_by_cam_zone_display} # Return structure even if empty

def fetch_bussing_images_by_date(date_str):
    query = """
    SELECT DISTINCT TOP 100 SubId
    FROM [ModuleAssembly].[ImageDataMart].[Image]
    WHERE CAST(CollectedDateTimeOffset AS DATE) = ? AND Station = 'BB'
    ORDER BY SubId DESC
    """
    print(f"Fetching bussing images for date: {date_str}")
    sub_id_rows = query_database(query, (date_str,))
    if not sub_id_rows:
         return {"error": f"No SubIDs found for bussing (Station BB) on date {date_str}."}

    sub_ids = [row.SubId for row in sub_id_rows if row.SubId]
    
    all_fetched_images = {}
    valid_id_count = 0
    
    for s_id in sub_ids:
        if valid_id_count >= 6:
            break
        fetched_for_subid = fetch_bussing_images(sub_id=s_id)
        if fetched_for_subid.get(s_id) and any(any(cam.values()) for cam in fetched_for_subid[s_id].values()):
            all_fetched_images.update(fetched_for_subid)
            valid_id_count += 1
            
    return all_fetched_images if all_fetched_images else {"error": f"No bussing images found for {date_str} after checking SubIDs."}
