from flask import Blueprint, render_template, redirect, url_for, request, session
import traceback
from ..image_processing import (
    fetch_bussing_images_by_date,
    fetch_images_by_date_for_tool, # Renamed
    fetch_station_images_by_date,
    fetch_bussing_images,
    fetch_frame_images,
    fetch_station_images
)
from ..config import Config # To access ALL_TOOLS

data_input_bp = Blueprint('data_input_routes', __name__, template_folder='../templates')

@data_input_bp.route('/data_input', methods=['GET', 'POST'])
def data_input():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        tool = request.form.get('tool')
        search_by = request.form.get('search_by')
        sub_id_str = request.form.get('sub_id')
        frame_id_str = request.form.get('frame_id')
        date_str = request.form.get('date') 

        image_urls_dict = {} # Changed from list to dict to match usage
        error_msg = None # Renamed for clarity

        try:
            if search_by == 'date' and date_str:
                if tool == 'bussing':
                    image_urls_dict = fetch_bussing_images_by_date(date_str)
                elif tool == 'frame':
                    image_urls_dict = fetch_images_by_date_for_tool(tool, date_str)
                elif tool in Config.ALL_TOOLS: # Check against all tools, not just a subset
                    image_urls_dict = fetch_station_images_by_date(tool, date_str)
                else:
                    error_msg = "Invalid tool selected for date search."
            
            elif search_by == 'sub_id': # 'sub_id' now covers both sub_id and frame_id logic
                ids_to_process_str = frame_id_str if tool == 'frame' else sub_id_str
                if not ids_to_process_str:
                    error_msg = "Please provide the required ID(s)."
                else:
                    ids_list = [item_id.strip() for item_id in ids_to_process_str.split(',') if item_id.strip()]
                    if not ids_list:
                        error_msg = "No valid IDs provided after stripping and splitting."
                    else:
                        for item_id in ids_list:
                            result_for_id = {}
                            if tool == 'bussing':
                                result_for_id = fetch_bussing_images(sub_id=item_id)
                            elif tool == 'frame':
                                result_for_id = fetch_frame_images(frame_id=item_id)
                            elif tool in Config.ALL_TOOLS:
                                result_for_id = fetch_station_images(tool, item_id)
                            else:
                                error_msg = f"Invalid tool '{tool}' selected for ID search."
                                break # Stop processing further IDs if tool is invalid
                            
                            if result_for_id: # Ensure result is not empty
                                image_urls_dict.update(result_for_id)
                        if not image_urls_dict and not error_msg: # If loop finished but no images
                            error_msg = f"No images found for the provided IDs for tool '{tool}'."
            else:
                error_msg = "Invalid search criteria. Please select search by 'date' or 'ID' and provide input."

            # Check if image_urls_dict contains an error message from fetch functions
            if isinstance(image_urls_dict, dict) and image_urls_dict.get("error") and not error_msg:
                error_msg = image_urls_dict["error"]
                image_urls_dict = {} # Clear if it was an error dict

            return render_template('result.html', image_urls=image_urls_dict, tool=tool, error=error_msg)

        except ValueError as ve: # Catch specific ValueErrors from image processing
            error_msg = str(ve)
            return render_template('result.html', image_urls={}, tool=tool, error=error_msg)
        except Exception as e:
            error_msg = f"An unexpected error occurred: {traceback.format_exc()}"
            print(error_msg) # Log the full traceback for server-side debugging
            return render_template('result.html', image_urls={}, tool=tool, error="An unexpected error occurred. Please check server logs.")

    return render_template('data_input.html', tools=Config.ALL_TOOLS, error=None)