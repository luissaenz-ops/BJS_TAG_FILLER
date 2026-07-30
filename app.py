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

# --- 2. STREAMLIT LAYOUT CONFIGURATION ---
st.set_page_config(layout="wide")

st.title("BJ's Inventory Tag Filler")
st.write("Upload multi-page Tags and Hotlist PDFs to automatically extract and print inventory delivery quantities.")

# User Inputs
col_input1, col_input2 = st.columns(2)
with col_input1:
    initials = st.text_input("Enter your Initials:", value="JS")
with col_input2:
    count_date = st.date_input("Select the Date:")

tags_file = st.file_uploader("Upload Tags.pdf", type="pdf")
hotlist_file = st.file_uploader("Upload Hotlist.pdf", type="pdf")

# --- 3. AI EXTRACTION PROMPTS ---

# Prompt to parse the entire Hotlist table across all pages
hotlist_extraction_prompt = """
You are analyzing an inventory 'Hotlist' document that may contain multiple pages.
Scan every row in the table:
1. Identify the item number in the 'Article' column (this is typically a 4 to 8 digit number).
2. Follow that specific row horizontally to find the corresponding value under the 'Delivery Quantity' column.
3. Extract only the primary quantity number (e.g., if it says '2.000 CV' or '120.000 CV', return '2' or '120'). Ignore unit labels like 'CV', 'EA', or trailing decimals/zeros.

Return the result strictly as a JSON object where each key is the Article number (as a string) and the value is the extracted Delivery Quantity (as a string).
Example output: {"356363": "2", "341407": "5", "28980": "7"}
"""

# Prompt to extract the main article number from a single tag
tag_article_prompt = """
Examine the text/content of this inventory tag page.
Locate the primary, large item/article number on the tag (this is the main identifying article number for the product, which can vary in digit length).
Return ONLY the clean digits of this article number. Do not include extra words or labels.
"""

def clean_digits(text):
    """Helper function to keep only digits from a string."""
    return re.sub(r'\D', '', str(text))

def insert_safe_text(page, location, text, size, color, angle):
    """Helper function to safely insert rotated text onto a PDF page."""
    if angle != 0:
        page.insert_text(location, text, fontsize=size, fontname="helvetica-bold", color=color, morph=(location, fitz.Matrix(angle)))
    else:
        page.insert_text(location, text, fontsize=size, fontname="helvetica-bold", color=color)

# --- 4. INTERACTIVE UI & LIVE PREVIEW ---
if tags_file:
    st.markdown("---")
    
    ui_col, preview_col = st.columns([1, 1.5])
    
    with ui_col:
        st.subheader("Placement & Rotation Controls")
        
        font_size = st.slider("Global Font Size", 20, 120, 75, step=5)
        
        # Rotation selector (0, 90, 180, 270 degrees)
        text_rotation = st.selectbox("Text Rotation Angle (Degrees)", options=[0, 90, 180, 270], index=0)
        
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
        st.subheader("Live Tag Preview (Page 1)")
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_preview:
            tmp_preview.write(tags_file.getvalue())
            preview_path = tmp_preview.name
            
        try:
            doc = fitz.open(preview_path)
            page = doc[0] 
            
            # Locate anchor words on page 1
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
                
            formatted_date = count_date.strftime("%m/%d")
            display_initials = initials if initials else "ABC"
            
            # Render red preview text with rotation
            insert_safe_text(page, date_loc, formatted_date, font_size, (1, 0, 0), text_rotation)
            insert_safe_text(page, initials_loc, display_initials, font_size, (1, 0, 0), text_rotation)
            insert_safe_text(page, count_loc, "99", font_size, (1, 0, 0), text_rotation)
            
            pix = page.get_pixmap(dpi=150)
            st.image(pix.tobytes(), use_container_width=True)
            doc.close()
        except Exception as e:
            st.error(f"Could not generate preview: {e}")
        finally:
            os.remove(preview_path)

    # --- 5. FINAL MULTI-PAGE PROCESSING ---
    if generate_clicked:
        if not initials or not hotlist_file:
            st.warning("Please fill in your initials and upload the Hotlist PDF.")
        else:
            st.info("Reading all pages of the Hotlist with Gemini AI... please wait.")
            
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_tags:
                tmp_tags.write(tags_file.getvalue())
                tags_path = tmp_tags.name
                
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_hotlist:
                tmp_hotlist.write(hotlist_file.getvalue())
                hotlist_path = tmp_hotlist.name

            try:
                # Step A: Extract full text across ALL pages of Hotlist.pdf
                hotlist_doc = fitz.open(hotlist_path)
                full_hotlist_text = ""
                for page_idx in range(len(hotlist_doc)):
                    full_hotlist_text += f"\n--- HOTLIST PAGE {page_idx + 1} ---\n"
                    full_hotlist_text += hotlist_doc[page_idx].get_text()
                hotlist_doc.close()
                
                # Step B: Pass complete Hotlist text to Gemini to generate the mapping dictionary
                response = client.models.generate_content(
                    model='gemini-3.6-flash',
                    contents=[hotlist_extraction_prompt, full_hotlist_text],
                    config=types.GenerateContentConfig(response_mime_type="application/json")
                )
                
                raw_quantities = json.loads(response.text)
                # Normalize all dictionary keys to pure digits
                delivery_quantities = {clean_digits(k): str(v) for k, v in raw_quantities.items()}
                
                st.success(f"Successfully processed Hotlist! Extracted {len(delivery_quantities)} article entries.")
                st.info("Processing each tag page...")
                
                formatted_date = count_date.strftime("%m/%d")
                pdf_document = fitz.open(tags_path)
                
                # Step C: Iterate through every page in Tags.pdf
                for page_num in range(len(pdf_document)):
                    page = pdf_document[page_num]
                    page_text = page.get_text()
                    
                    # Ask Gemini to find the primary article number on this tag page
                    tag_response = client.models.generate_content(
                        model='gemini-3.6-flash',
                        contents=[tag_article_prompt, page_text]
                    )
                    
                    article_number = clean_digits(tag_response.text.strip())
                    
                    # Match extracted article number with Hotlist dictionary
                    quantity_to_write = delivery_quantities.get(article_number, "N/A")
                    
                    # Locate positions
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
                    
                    # Insert final black text with selected rotation
                    insert_safe_text(page, date_loc, formatted_date, font_size, (0, 0, 0), text_rotation)
                    insert_safe_text(page, initials_loc, initials, font_size, (0, 0, 0), text_rotation)
                    insert_safe_text(page, count_loc, quantity_to_write, font_size, (0, 0, 0), text_rotation)
                    
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
                st.error(f"An error occurred during processing: {e}")
                
            finally:
                os.remove(tags_path)
                os.remove(hotlist_path)
                if os.path.exists("Filled_Tags.pdf"):
                    os.remove("Filled_Tags.pdf")
