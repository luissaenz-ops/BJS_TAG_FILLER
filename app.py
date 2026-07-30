import streamlit as st
from google import genai
from google.genai import types 
import fitz  # PyMuPDF
import tempfile
import os
import json
import re

# --- 1. SETUP GEMINI API VIA SECRETS ---
api_key = st.secrets.get("GEMINI_API_KEY", "")

if not api_key:
    st.error("Missing Gemini API Key. Please add 'GEMINI_API_KEY' to your Streamlit Secrets.")
    st.stop()

client = genai.Client(api_key=api_key)

# --- 2. WIDE APP LAYOUT ---
# This makes the app take up the full width of your monitor for a better UI
st.set_page_config(layout="wide")

st.title("BJ's Inventory Tag Filler")
st.write("Upload your Tags and Hotlist to automatically fill in inventory quantities.")

# User Inputs
col_input1, col_input2 = st.columns(2)
with col_input1:
    initials = st.text_input("Enter your Initials:", value="JS")
with col_input2:
    count_date = st.date_input("Select the Date:")

tags_file = st.file_uploader("Upload Tags.pdf", type="pdf")
hotlist_file = st.file_uploader("Upload Hotlist.pdf", type="pdf")

# --- 3. AI EXTRACTION PROMPT ---
extraction_prompt = """
Extract the 'Article' number and match it to the 'Delivery Quantity' from this Hotlist document.
1. Track the row exactly from the Article number to the Delivery Quantity column.
2. Only extract the primary integer for the quantity. Ignore extra zeros, 'CV', 'EA', and stacked text.
Return the data as a JSON object where the keys are Article numbers (strings) and the values are the Delivery Quantities (strings).
"""

def clean_digits(text):
    return re.sub(r'\D', '', str(text))

# --- 4. INTERACTIVE UI & LIVE PREVIEW ---
if tags_file:
    st.markdown("---")
    
    # Split the screen: Controls on left, Preview on right
    ui_col, preview_col = st.columns([1, 1.5])
    
    with ui_col:
        st.subheader("Placement Controls")
        st.write("Move the sliders below to adjust the red text on the right.")
        
        font_size = st.slider("Global Font Size", 20, 120, 75, step=5)
        
        st.markdown("**Quantity Position**")
        qty_x = st.slider("Quantity Left/Right", -200, 200, 10, step=5)
        qty_y = st.slider("Quantity Up/Down", -200, 200, 0, step=5)
        
        st.markdown("**Date Position**")
        date_x = st.slider("Date Left/Right", -200, 200, 0, step=5)
        date_y = st.slider("Date Up/Down", -200, 200, 30, step=5)
        
        st.markdown("**Initials Position**")
        init_x = st.slider("Initials Left/Right", -200, 200, 0, step=5)
        init_y = st.slider("Initials Up/Down", -200, 200, 30, step=5)
        
        # We put the final generate button right below the controls
        generate_clicked = st.button("Generate Filled Tags", type="primary", use_container_width=True)

    with preview_col:
        st.subheader("Live Tag Preview")
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_preview:
            tmp_preview.write(tags_file.getvalue())
            preview_path = tmp_preview.name
            
        try:
            doc = fitz.open(preview_path)
            page = doc[0] 
            
            count_rects = page.search_for("Count")
            date_rects = page.search_for("Date")
            initials_rects = page.search_for("Initials")
            
            # Default starting points
            count_loc = fitz.Point(180, 180)
            date_loc = fitz.Point(180, 100)
            initials_loc = fitz.Point(180, 250)
            
            # Apply detected anchors + your sliders (Fixed math)
            if count_rects:
                count_loc = fitz.Point(count_rects[0].x1 + qty_x, count_rects[0].y1 + qty_y)
            if date_rects:
                date_loc = fitz.Point(date_rects[0].x0 + date_x, date_rects[0].y1 + date_y)
            if initials_rects:
                initials_loc = fitz.Point(initials_rects[0].x0 + init_x, initials_rects[0].y1 + init_y)
                
            formatted_date = count_date.strftime("%m/%d")
            display_initials = initials if initials else "ABC"
            
            # Draw placeholder text in RED
            page.insert_text(date_loc, formatted_date, fontsize=font_size, fontname="helvetica-bold", color=(1, 0, 0))
            page.insert_text(initials_loc, display_initials, fontsize=font_size, fontname="helvetica-bold", color=(1, 0, 0))
            page.insert_text(count_loc, "99", fontsize=font_size, fontname="helvetica-bold", color=(1, 0, 0))
            
            pix = page.get_pixmap(dpi=150)
            st.image(pix.tobytes(), use_column_width=True)
            doc.close()
        except Exception as e:
            st.error(f"Could not generate preview: {e}")
        finally:
            os.remove(preview_path)

    # --- 5. FINAL PROCESSING (Triggers when button is clicked) ---
    if generate_clicked:
        if not initials or not hotlist_file:
            st.warning("Please fill in your initials and upload the Hotlist PDF.")
        else:
            st.info("Reading the Hotlist with AI... please wait.")
            
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_tags:
                tmp_tags.write(tags_file.getvalue())
                tags_path = tmp_tags.name
                
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_hotlist:
                tmp_hotlist.write(hotlist_file.getvalue())
                hotlist_path = tmp_hotlist.name

            try:
                hotlist_doc = fitz.open(hotlist_path)
                hotlist_text = ""
                for page in hotlist_doc:
                    hotlist_text += page.get_text()
                hotlist_doc.close()
                
                response = client.models.generate_content(
                    model='gemini-3.6-flash',
                    contents=[extraction_prompt, hotlist_text],
                    config=types.GenerateContentConfig(response_mime_type="application/json")
                )
                
                raw_quantities = json.loads(response.text)
                delivery_quantities = {clean_digits(k): str(v) for k, v in raw_quantities.items()}
                
                st.success("Successfully parsed Hotlist data! Generating your tags...")
                
                formatted_date = count_date.strftime("%m/%d")
                pdf_document = fitz.open(tags_path)
                
                for page_num in range(len(pdf_document)):
                    page = pdf_document[page_num]
                    
                    tag_prompt = "Find the 6-digit article number on this tag page. Return ONLY the 6 digits."
                    tag_response = client.models.generate_content(
                        model='gemini-3.6-flash',
                        contents=[tag_prompt, page.get_text()]
                    )
                    
                    article_number = clean_digits(tag_response.text.strip())
                    quantity_to_write = delivery_quantities.get(article_number, "N/A")
                    
                    # Recalculate anchors for the final document
                    count_rects = page.search_for("Count")
                    date_rects = page.search_for("Date")
                    initials_rects = page.search_for("Initials")
                    
                    count_loc = fitz.Point(180, 180)
                    date_loc = fitz.Point(180, 100)
                    initials_loc = fitz.Point(180, 250)
                    
                    if count_rects:
                        count_loc = fitz.Point(count_rects[0].x1 + qty_x, count_rects[0].y1 + qty_y)
                    if date_rects:
                        date_loc = fitz.Point(date_rects[0].x0 + date_x, date_rects[0].y1 + date_y)
                    if initials_rects:
                        initials_loc = fitz.Point(initials_rects[0].x0 + init_x, initials_rects[0].y1 + init_y)
                    
                    # Draw final text in BLACK
                    page.insert_text(date_loc, formatted_date, fontsize=font_size, fontname="helvetica-bold", color=(0, 0, 0))
                    page.insert_text(initials_loc, initials, fontsize=font_size, fontname="helvetica-bold", color=(0, 0, 0))
                    page.insert_text(count_loc, quantity_to_write, fontsize=font_size, fontname="helvetica-bold", color=(0, 0, 0))
                    
                output_path = "Filled_Tags.pdf"
                pdf_document.save(output_path)
                pdf_document.close()
                
                with open(output_path, "rb") as f:
                    st.download_button(
                        label="Download Completed Tags PDF",
                        data=f,
                        file_name="Completed_Tags.pdf",
                        mime="application/pdf",
                        type="primary"
                    )
                    
            except Exception as e:
                st.error(f"An error occurred: {e}")
                
            finally:
                os.remove(tags_path)
                os.remove(hotlist_path)
                if os.path.exists("Filled_Tags.pdf"):
                    os.remove("Filled_Tags.pdf")
                    
