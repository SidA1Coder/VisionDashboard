import traceback
from flask import Blueprint, render_template, request, session, redirect, url_for
import pandas as pd
import plotly
import plotly.express as px
import plotly.graph_objects as go
import json
import numpy as np
from ..utils import get_db_connection # For pd.read_sql
from ..config import TRENDS_TOOLS # Using specific tools list for trends

trends_bp = Blueprint('trends_routes', __name__, template_folder='../templates')

@trends_bp.route('/trends', methods=['GET', 'POST'])
def trends():
    if not session.get('logged_in'): # Ensure user is logged in
        return redirect(url_for('auth.login'))

    chartJSONs = []
    error_msg = None
    selected_tool_from_form = request.form.get('tool') if request.method == 'POST' else None
    start_date_str = request.form.get('start_date') if request.method == 'POST' else None
    end_date_str = request.form.get('end_date') if request.method == 'POST' else None

    # Use the TRENDS_TOOLS from config for the dropdown
    # The actual selected tool for processing will be selected_tool_from_form

    if request.method == 'POST':
        if not all([selected_tool_from_form, start_date_str, end_date_str]):
            error_msg = "Please select a tool and provide both start and end dates."
        else:
            db_conn = None
            try:
                db_conn = get_db_connection()
                if selected_tool_from_form == "frame":
                    # Frame-specific trend logic (Original logic maintained)
                    query_frame = """
                        SELECT 
                            CAST([TimeStamp] AS DATE) AS Date,
                            [SourceLocation],
                            [ExitProductStatus],
                            CASE 
                                WHEN [ExitProductStatus] = '0' THEN 'Press_Init'
                                WHEN [ExitProductStatus] = '100' THEN 'Accept'
                                WHEN [ExitProductStatus] = '200' THEN 'Manual_Load'
                                WHEN [ExitProductStatus] = '300' THEN 'Clean_Insp_Fail'
                                WHEN [ExitProductStatus] = '400' THEN 'Primer_Insp_Fail'
                                WHEN [ExitProductStatus] = '500' THEN 'Tape1_Retry_Fail'
                                WHEN [ExitProductStatus] = '510' THEN 'Tape1_Force_Reject'
                                WHEN [ExitProductStatus] = '520' THEN 'Tape2_Retry_Fail'
                                WHEN [ExitProductStatus] = '530' THEN 'Tape2_Force_Reject'
                                WHEN [ExitProductStatus] = '600' THEN 'Silicone1_Process_Fail'
                                WHEN [ExitProductStatus] = '610' THEN 'Silicone1_Force_Reject'
                                WHEN [ExitProductStatus] = '640' THEN 'Silicone2_Process_Fail'
                                WHEN [ExitProductStatus] = '650' THEN 'Silicone2_Force_Reject'
                                WHEN [ExitProductStatus] = '700' THEN 'Silicone_Inspection_Fail'
                                WHEN [ExitProductStatus] = '800' THEN 'Silicone_Expired'
                                WHEN [ExitProductStatus] = '900' THEN 'Scrap'
                                ELSE 'Other'
                            END AS Rail_Status
                        FROM [ODS].[mfg].[ProcessHistoryPdrMaterialProducedEvent]
                        WHERE CAST([TimeStamp] AS DATE) BETWEEN ? AND ? 
                    """ # Using CAST for date comparison
                    df_frame = pd.read_sql(query_frame, db_conn, params=[start_date_str, end_date_str])
                    
                    if df_frame.empty:
                        error_msg = "No data found for 'frame' tool in the selected date range."
                    else:
                        grouped_frame = df_frame.groupby(['Date', 'SourceLocation', 'Rail_Status']).size().unstack(fill_value=0).reset_index()
                        grouped_frame['Rails_Produced'] = grouped_frame.sum(axis=1, numeric_only=True)
                        # Ensure all potential scrap columns exist before summing
                        scrapped_cols_sum = ['Press_Init', 'Scrap', 'Silicone_Expired', 'Silicone_Inspection_Fail', 
                                             'Silicone1_Force_Reject', 'Silicone1_Process_Fail', 
                                             'Silicone2_Force_Reject', 'Silicone2_Process_Fail']
                        grouped_frame['Total_Rails_Scrapped'] = sum(grouped_frame.get(col, 0) for col in scrapped_cols_sum)
                        
                        accepted_yield = grouped_frame.get('Accept', 0) + grouped_frame.get('Manual_Load', 0)
                        grouped_frame['YIELD'] = (accepted_yield * 100) / grouped_frame['Rails_Produced'].replace(0, np.nan)

                        fig_frame_tpt = go.Figure()
                        fig_frame_tpt.add_bar(x=grouped_frame['Date'], y=grouped_frame['Rails_Produced'], name='Rails Produced', marker_color='blue')
                        fig_frame_tpt.add_bar(x=grouped_frame['Date'], y=grouped_frame['Total_Rails_Scrapped'], name='Total Rails Scrapped', marker_color='red')
                        fig_frame_tpt.add_trace(go.Scatter(x=grouped_frame['Date'], y=grouped_frame['YIELD'], name='Yield (%)', yaxis='y2', mode='lines+markers', marker_color='green'))
                        fig_frame_tpt.update_layout(title="Back Side Rails TPT/YIELD", xaxis_title="Date", yaxis=dict(title="Count"), yaxis2=dict(title="Yield (%)", overlaying='y', side='right', range=[90, 100]), barmode='group')
                        chartJSONs.append({"label": "Back Side Rails TPT/YIELD", "json": json.dumps(fig_frame_tpt, cls=plotly.utils.PlotlyJSONEncoder)})

                        scrap_detail_cols = [col for col in scrapped_cols_sum if col in grouped_frame.columns]
                        if scrap_detail_cols: # Only proceed if there are scrap columns to melt
                            scrap_df_frame = grouped_frame[['Date', 'SourceLocation'] + scrap_detail_cols]
                            scrap_df_frame = scrap_df_frame.melt(id_vars=['Date', 'SourceLocation'], value_vars=scrap_detail_cols, var_name='ScrapType', value_name='Count')
                            if not scrap_df_frame.empty:
                                fig_frame_scrap = px.bar(scrap_df_frame, x='Date', y='Count', color='ScrapType', title='Rail Scrap Counting Detail', barmode='stack', facet_col='SourceLocation')
                                chartJSONs.append({"label": "Rail Scrap Counting Detail", "json": json.dumps(fig_frame_scrap, cls=plotly.utils.PlotlyJSONEncoder)})
                
                elif selected_tool_from_form == "Silicon":
                    # Silicon-specific trend logic (Original logic maintained)
                    query_silicon_yield = """
                        SELECT
                            CAST(ReadTime AS DATE) AS Date,
                            DATEPART(HOUR, ReadTime) AS Hour,
                            EquipmentName,
                            ISNULL(NULLIF(RailStatus, ''), 'PASS') AS Action_Corrected
                        FROM [ODS].[mfg].[ProcessHistoryRailSiliconPressure2]
                        WHERE CAST(ReadTime AS DATE) BETWEEN ? AND ?
                    """
                    df_silicon_yield = pd.read_sql(query_silicon_yield, db_conn, params=[start_date_str, end_date_str])

                    if df_silicon_yield.empty:
                        error_msg = "No data found for 'Silicon' tool (Yield by Hour) in the selected date range."
                    else:
                        grouped_sil_yield = df_silicon_yield.groupby(['Date', 'Hour', 'EquipmentName', 'Action_Corrected']).size().unstack(fill_value=0).reset_index()
                        for col_yield in ['PASS', 'Accept', 'Reject']:
                            if col_yield not in grouped_sil_yield.columns: grouped_sil_yield[col_yield] = 0
                        grouped_sil_yield['Total'] = grouped_sil_yield[['PASS', 'Accept', 'Reject']].sum(axis=1)
                        grouped_sil_yield['PASS%'] = (grouped_sil_yield['PASS'] * 100) / grouped_sil_yield['Total'].replace(0, np.nan)
                        grouped_sil_yield['ACCEPT%'] = (grouped_sil_yield['Accept'] * 100) / grouped_sil_yield['Total'].replace(0, np.nan)
                        grouped_sil_yield['REJECT%'] = (grouped_sil_yield['Reject'] * 100) / grouped_sil_yield['Total'].replace(0, np.nan)

                        fig_sil_yield = px.bar(grouped_sil_yield, x='Hour', y=['PASS%', 'ACCEPT%', 'REJECT%'], color_discrete_map={'PASS%': 'green', 'ACCEPT%': 'blue', 'REJECT%': 'red'}, facet_col='EquipmentName', barmode='stack', title="PGT3 - Silicone Vision Warning Rate by Line by Hour", labels={'value': 'Yield (%)', 'Hour': 'Hour of Day'})
                        fig_sil_yield.update_layout(yaxis=dict(range=[0, 100]), legend_title_text='Result', template='plotly_white')
                        chartJSONs.append({"label": "PGT3 - Silicone Vision Warning Rate by Line by Hour", "json": json.dumps(fig_sil_yield, cls=plotly.utils.PlotlyJSONEncoder)})

                    # Silicon Vision Failed Reason Logic
                    # Bead Color
                    query_color = """
                        SELECT CAST(ReadTime AS DATE) AS Date, EquipmentName,
                            CASE
                                WHEN BeadZone IN (2,5,9,14,19,22) AND (BeadColor > 999 OR BeadColor = 0) THEN 'Unread'
                                WHEN BeadZone IN (2,5,9,14,19,22) AND (BeadColor > 100 OR BeadColor < 10) THEN 'Fail'
                                WHEN BeadZone IN (2,5,9,14,19,22) AND (BeadColor < 100 OR BeadColor > 10) THEN 'PASS'
                                ELSE NULL END AS BeadColorResult
                        FROM [ODS].[mfg].[ProcessHistoryRailSiliconBeadInspection] WHERE CAST(ReadTime AS DATE) BETWEEN ? AND ? """
                    df_color = pd.read_sql(query_color, db_conn, params=[start_date_str, end_date_str])
                    if not df_color.empty:
                        color_pivot = df_color.pivot_table(index=['Date', 'EquipmentName'], columns='BeadColorResult', aggfunc='size', fill_value=0).reset_index()
                        for col in ['Fail', 'PASS', 'Unread']:
                            if col not in color_pivot.columns: color_pivot[col] = 0
                        color_pivot['ColorYieldLoss'] = (color_pivot['Fail'] + color_pivot['Unread']) / (color_pivot['Fail'] + color_pivot['PASS'] + color_pivot['Unread']).replace(0, np.nan)
                    else: color_pivot = pd.DataFrame(columns=['Date', 'EquipmentName', 'ColorYieldLoss'])


                    # Bead Width
                    query_width = """
                        SELECT CAST(ReadTime AS DATE) AS Date, EquipmentName,
                            CASE
                                WHEN BeadZone IN (1,2,5,6,9,11,14,15,19,20,22,23) AND (BeadWidth > 999 OR BeadWidth = 0) THEN 'Unread'
                                WHEN BeadZone IN (1,2,5,6,9,11,14,15,19,20,22,23) AND (BeadWidth > 11 OR BeadWidth < 3.5) THEN 'Fail'
                                WHEN BeadZone IN (1,2,5,6,9,11,14,15,19,20,22,23) AND (BeadWidth < 11 OR BeadWidth > 3.5) THEN 'PASS'
                                ELSE NULL END AS BeadWidthResult
                        FROM [ODS].[mfg].[ProcessHistoryRailSiliconBeadInspection] WHERE CAST(ReadTime AS DATE) BETWEEN ? AND ? """
                    df_width = pd.read_sql(query_width, db_conn, params=[start_date_str, end_date_str])
                    if not df_width.empty:
                        width_pivot = df_width.pivot_table(index=['Date', 'EquipmentName'], columns='BeadWidthResult', aggfunc='size', fill_value=0).reset_index()
                        for col in ['Fail', 'PASS', 'Unread']:
                            if col not in width_pivot.columns: width_pivot[col] = 0
                        width_pivot['WidthYieldLoss'] = (width_pivot['Fail'] + width_pivot['Unread']) / (width_pivot['Fail'] + width_pivot['PASS'] + width_pivot['Unread']).replace(0, np.nan)
                    else: width_pivot = pd.DataFrame(columns=['Date', 'EquipmentName', 'WidthYieldLoss'])

                    # Bead Gap
                    query_gap = """
                        SELECT CAST(ReadTime AS DATE) AS Date, EquipmentName,
                            CASE
                                WHEN BeadZone IN (3,7,12,17,21) AND (BeadGap > 999 OR BeadGap = 0) THEN 'Unread'
                                WHEN BeadZone IN (3,7,12,17,21) AND (BeadGap > 67 OR BeadGap < 30) THEN 'Fail'
                                WHEN BeadZone IN (3,7,12,17,21) AND (BeadGap < 67 OR BeadGap > 30) THEN 'PASS'
                                ELSE NULL END AS BeadGapResult
                        FROM [ODS].[mfg].[ProcessHistoryRailSiliconBeadInspection] WHERE CAST(ReadTime AS DATE) BETWEEN ? AND ? """
                    df_gap = pd.read_sql(query_gap, db_conn, params=[start_date_str, end_date_str])
                    if not df_gap.empty:
                        gap_pivot = df_gap.pivot_table(index=['Date', 'EquipmentName'], columns='BeadGapResult', aggfunc='size', fill_value=0).reset_index()
                        for col in ['Fail', 'PASS', 'Unread']:
                            if col not in gap_pivot.columns: gap_pivot[col] = 0
                        gap_pivot['GapYieldLoss'] = (gap_pivot['Fail'] + gap_pivot['Unread']) / (gap_pivot['Fail'] + gap_pivot['PASS'] + gap_pivot['Unread']).replace(0, np.nan)
                    else: gap_pivot = pd.DataFrame(columns=['Date', 'EquipmentName', 'GapYieldLoss'])

                    # Tape Length
                    query_tape = """
                        SELECT CAST(ReadTime AS DATE) AS Date, EquipmentName,
                            CASE
                                WHEN TapeLength > 999 OR TapeLength = 0 THEN 'Unread'
                                WHEN TapeLength > 25.4 OR TapeLength < 19 THEN 'Fail'
                                WHEN TapeLength < 25.4 OR TapeLength > 19 THEN 'PASS'
                                ELSE NULL END AS TapeLengthResult
                        FROM [ODS].[mfg].[ProcessHistoryRailSiliconTapeInspection] WHERE CAST(ReadTime AS DATE) BETWEEN ? AND ? """
                    df_tape = pd.read_sql(query_tape, db_conn, params=[start_date_str, end_date_str])
                    if not df_tape.empty:
                        tape_pivot = df_tape.pivot_table(index=['Date', 'EquipmentName'], columns='TapeLengthResult', aggfunc='size', fill_value=0).reset_index()
                        for col in ['Fail', 'PASS', 'Unread']:
                            if col not in tape_pivot.columns: tape_pivot[col] = 0
                        tape_pivot['TapeYieldLoss'] = (tape_pivot['Fail'] + tape_pivot['Unread']) / (tape_pivot['Fail'] + tape_pivot['PASS'] + tape_pivot['Unread']).replace(0, np.nan)
                    else: tape_pivot = pd.DataFrame(columns=['Date', 'EquipmentName', 'TapeYieldLoss'])
                    
                    # Merge all yield loss DFs
                    merged_loss_df = color_pivot[['Date', 'EquipmentName', 'ColorYieldLoss']].copy()
                    for df_to_merge, loss_col_name in [
                        (width_pivot, 'WidthYieldLoss'), 
                        (gap_pivot, 'GapYieldLoss'), 
                        (tape_pivot, 'TapeYieldLoss')]:
                        if not df_to_merge.empty:
                            merged_loss_df = pd.merge(merged_loss_df, df_to_merge[['Date', 'EquipmentName', loss_col_name]], on=['Date', 'EquipmentName'], how='outer')
                        else: # Ensure column exists even if df is empty
                            merged_loss_df[loss_col_name] = np.nan 
                    
                    merged_loss_df = merged_loss_df.fillna(0) # Fill NaNs from outer merges or empty DFs

                    if not merged_loss_df.empty and any(col for col in ['ColorYieldLoss', 'WidthYieldLoss', 'GapYieldLoss', 'TapeYieldLoss'] if col in merged_loss_df.columns):
                        melted_loss = merged_loss_df.melt(id_vars=['Date', 'EquipmentName'], 
                                                          value_vars=[col for col in ['ColorYieldLoss', 'WidthYieldLoss', 'GapYieldLoss', 'TapeYieldLoss'] if col in merged_loss_df.columns],
                                                          var_name='Reason', value_name='YieldLoss')
                        melted_loss['YieldLoss'] = melted_loss['YieldLoss'] * 100  # convert to percent
                        if not melted_loss.empty:
                            fig_sil_loss = px.bar(melted_loss, x='Date', y='YieldLoss', color='Reason', facet_col='EquipmentName', barmode='stack', title="PGT3 - Vision Failed Reason Yield Loss", labels={'YieldLoss': 'Yield Loss (%)', 'Date': 'Date'})
                            fig_sil_loss.update_layout(yaxis=dict(range=[0, 100]), legend_title_text='Reason', template='plotly_white')
                            chartJSONs.append({"label": "PGT3 - Vision Failed Reason Yield Loss", "json": json.dumps(fig_sil_loss, cls=plotly.utils.PlotlyJSONEncoder)})
                    elif not error_msg: # If no data for loss charts but yield chart was made
                        print("No data for Silicon Vision Failed Reason Yield Loss chart.")


                else:
                    error_msg = f"Trend data for tool '{selected_tool_from_form}' is not yet implemented."
            
            except Exception as e:
                error_msg = f"Error generating trend data: {e}"
                print(traceback.format_exc())
            finally:
                if db_conn:
                    db_conn.close()
    
    return render_template(
        'trends.html',
        tools=TRENDS_TOOLS, # Pass the configured list for the dropdown
        chartJSONs=chartJSONs,
        error=error_msg,
        selected_tool=selected_tool_from_form, # Pass back the actually selected tool
        start_date=start_date_str,
        end_date=end_date_str
    )