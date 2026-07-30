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

# --- 2. STREAMLIT WIDE LAYOUT ---
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
Example: {"356363": "2", "341407": "5"}
"""

def clean_digits(text):
    return re.sub(r'\D', '', str(text))

# --- 4. INTERACTIVE UI & LIVE PREVIEW ---
if tags_file:
    st.markdown("---")
    
    ui_col, preview_col = st.columns([1, 1.5])
    
    with ui_col:
        st.subheader("Placement Controls")
        st.write("Adjust the sliders below to position the text on the preview on the right.")
        
        font_size = st.slider("Global Font Size", 20, 120, 75, step=5)
        
        st.markdown("**Quantity Position**")
        qty_x = st.slider("Quantity Left/Right (X)", -300, 500, 10, step=5)
        qty_y = st.slider("Quantity Up/Down (Y)", -300, 500, 0, step=5)
        
        st.markdown("**Date Position**")
        date_x = st.slider("Date Left/Right (X)", -300, 500, 0, step=5)
        date_y = st.slider("Date Up/Down (Y)", -300, 500, 30, step=5)
        
        st.markdown("**Initials Position**")
        init_x = st.slider("Initials Left/Right (X)", -300, 500, 0, step=5)
        init_y = st.slider("Initials Up/Down (Y)", -300, 500, 30, step=5)
        
        generate_clicked = st.button("Generate Filled Tags", type="primary", use_container_width=True)

    with preview_col:
        st.subheader("Live Tag Preview")
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_preview:
            tmp_preview.write(tags_file.getvalue())
            preview_path = tmp_preview.name
            
        try:
            doc = fitz.open(preview_path)
            page = doc[0] 
            
            # Search for label words
            count_rects = page.search_for("Count")
            date_rects = page.search_for("Date")
            initials_rects = page.search_for("Initials")
            
            # Establish baseline coordinates
            base_count_x, base_count_y = 180, 180
            base_date_x, base_date_y = 180, 100
            base_init_x, base_init_y = 180, 250
            
            if count_rects:
                base_count_x = count_rects[0].x1 + 10
                base_count_y = count_rects[0].y1
            if date_rects:
                base_date_x = date_rects[0].x0
                base_date_y = date_rects[0].y1 + 30
            if initials_rects:
                base_init_x = initials_rects[0].x0
                base_init_y = initials_rects[0].y1 + 30
                
            # ALWAYS add the slider offsets to the base position
            count_loc = fitz.Point(base_count_x + qty_x, base_count_y + qty_y)
            date_loc = fitz.Point(base_date_x + date_x, base_date_y + date_y)
            initials_loc = fitz.Point(base_init_x + init_x, base_init_y + init_y)
                
            formatted_date = count_date.strftime("%m/%d")
            display_initials = initials if initials else "ABC"
            
            # Draw preview text in RED
            page.insert_text(date_loc, formatted_date, fontsize=font_size, fontname="helvetica-bold", color=(1, 0, 0))
            page.insert_text(initials_loc, display_initials, fontsize=font_size, fontname="helvetica-bold", color=(1, 0, 0))
            page.insert_text(count_loc, "99", fontsize=font_size, fontname="helvetica-bold", color=(1, 0, 0))
            
            pix = page.get_pixmap(dpi=150)
            st.image(pix.tobytes(), use_container_width=True)
            doc.close()
        except Exception as e:
            st.error(f"Could not generate preview: {e}")
        finally:
            os.remove(preview_path)

    # --- 5. FINAL PROCESSING ---
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
                
                # Request structured JSON response from Gemini
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
                    
                    # Search anchors for final tags
                    count_rects = page.search_for("Count")
                    date_rects = page.search_for("Date")
                    initials_rects = page.search_for("Initials")
                    
                    base_count_x, base_count_y = 180, 180
                    base_date_x, base_date_y = 180, 100
                    base_init_x, base_init_y = 180, 250
                    
                    if count_rects:
                        base_count_x = count_rects[0].x1 + 10
                        base_count_y = count_rects[0].y1
                    if date_rects:
                        base_date_x = date_rects[0].x0
                        base_date_y = date_rects[0].y1 + 30
                    if initials_rects:
                        base_init_x = initials_rects[0].x0
                        base_init_y = initials_rects[0].y1 + 30
                        
                    count_loc = fitz.Point(base_count_x + qty_x, base_count_y + qty_y)
                    date_loc = fitz.Point(base_date_x + date_x, base_date_y + date_y)
                    initials_loc = fitz.Point(base_init_x + init_x, base_init_y + init_y)
                    
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
