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

# --- 2. STREAMLIT WIDE LAYOUT CONFIGURATION ---
st.set_page_config(layout="wide", page_title="BJ's Inventory Tag Filler")

st.title("BJ's Inventory Tag Filler")
st.write("Upload multi-page Tags and Hotlist PDFs to automatically extract and fill inventory tags.")

# User Inputs
col_input1, col_input2 = st.columns(2)
with col_input1:
    initials = st.text_input("Enter your Initials:", value="JS")
with col_input2:
    count_date = st.date_input("Select the Date:")

tags_file = st.file_uploader("Upload Tags.pdf", type="pdf")
hotlist_file = st.file_uploader("Upload Hotlist.pdf", type="pdf")

# --- 3. AI EXTRACTION PROMPTS ---

hotlist_extraction_prompt = """
You are analyzing an inventory 'Hotlist' document containing product tables across one or more pages.
Your job is to read every row in the document table:
1. Locate the item number in the 'Article' column (e.g., numbers like 356363, 341407, 28980, etc.).
2. Follow that exact row horizontally to find the primary number under the 'Delivery Quantity' column.
3. Extract ONLY the main quantity integer (e.g., for '2.000 CV' return '2', for '120.000 CV' return '120'). Ignore unit text like 'CV', 'EA', or stacked decimals.

Return the result STRICTLY as a valid JSON object where keys are the Article numbers (strings) and values are the Delivery Quantities (strings).
Example output: {"356363": "2", "341407": "5", "28980": "7"}
"""

tag_article_prompt = """
Examine this inventory tag page.
Locate the primary, large item/article number displayed on the tag (e.g., 356363, 224527, etc.).
Return ONLY the clean numerical digits of this article number. Do not include any extra text or labels.
"""

def clean_digits(text):
    """Helper function to strip out non-digit characters."""
    return re.sub(r'\D', '', str(text))

def insert_safe_text(page, location, text, size, color, angle):
    """Helper function to insert text with optional rotation matrix."""
    if angle != 0:
        page.insert_text(
            location, 
            text, 
            fontsize=size, 
            fontname="helvetica-bold", 
            color=color, 
            morph=(location, fitz.Matrix(angle))
        )
    else:
        page.insert_text(
            location, 
            text, 
            fontsize=size, 
            fontname="helvetica-bold", 
            color=color
        )

# --- 4. INTERACTIVE UI & LIVE PREVIEW ---
if tags_file:
    st.markdown("---")
    
    ui_col, preview_col = st.columns([1, 1.5])
    
    with ui_col:
        st.subheader("Placement & Rotation Controls")
        
        font_size = st.slider("Global Font Size", 20, 120, 75, step=5)
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
            
            insert_safe_text(page, date_loc, formatted_date, font_size, (1, 0, 0), text_rotation)
            insert_safe_text(page, initials_loc, display_initials, font_size, (1, 0, 0), text_rotation)
            insert_safe_text(page, count_loc, "99", font_size, (1, 0, 0), text_rotation)
            
            pix = page.get_pixmap(dpi=100)
            st.image(pix.tobytes(), use_container_width=True)
            doc.close()
        except Exception as e:
            st.error(f"Could not generate preview: {e}")
        finally:
            if os.path.exists(preview_path):
                os.remove(preview_path)

    # --- 5. FINAL MULTI-PAGE PROCESSING ---
    if generate_clicked:
        if not initials or not hotlist_file:
            st.warning("Please fill in your initials and upload the Hotlist PDF.")
        else:
            st.info("Processing Hotlist pages with Gemini AI... please wait.")
            
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_tags:
                tmp_tags.write(tags_file.getvalue())
                tags_path = tmp_tags.name
                
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_hotlist:
                tmp_hotlist.write(hotlist_file.getvalue())
                hotlist_path = tmp_hotlist.name

            try:
                # Step A: Load text across Hotlist.pdf
                hotlist_doc = fitz.open(hotlist_path)
                contents_payload = [hotlist_extraction_prompt]
                
                full_text = ""
                for page_idx in range(len(hotlist_doc)):
                    page = hotlist_doc[page_idx]
                    page_text = page.get_text()
                    if page_text.strip():
                        full_text += f"\n--- PAGE {page_idx + 1} ---\n" + page_text

                # If text exists, send text payload
                if full_text.strip():
                    contents_payload.append(f"Extracted Hotlist Text:\n{full_text}")
                else:
                    # Fallback to image payload at 100 DPI for scanned documents
                    for page_idx in range(len(hotlist_doc)):
                        page = hotlist_doc[page_idx]
                        pix = page.get_pixmap(dpi=100)
                        img_bytes = pix.tobytes("jpeg")
                        contents_payload.append(types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"))

                hotlist_doc.close()
                
                # Step B: Call Gemini 3.6 Flash with timeout config
                response = client.models.generate_content(
                    model='gemini-3.6-flash',
                    contents=contents_payload,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json"
                    )
                )
                
                raw_quantities = json.loads(response.text)
                delivery_quantities = {clean_digits(k): str(v) for k, v in raw_quantities.items()}
                
                st.success(f"Successfully processed Hotlist! Extracted {len(delivery_quantities)} article entries.")
                st.info("Writing counts onto your tags...")
                
                formatted_date = count_date.strftime("%m/%d")
                pdf_document = fitz.open(tags_path)
                matches_summary = []
                
                # Step C: Loop through every page in Tags.pdf
                for page_num in range(len(pdf_document)):
                    page = pdf_document[page_num]
                    page_text = page.get_text()
                    
                    if page_text.strip():
                        tag_payload = [tag_article_prompt, f"Page Text:\n{page_text}"]
                    else:
                        pix_tag = page.get_pixmap(dpi=100)
                        tag_img_bytes = pix_tag.tobytes("jpeg")
                        tag_payload = [
                            tag_article_prompt,
                            types.Part.from_bytes(data=tag_img_bytes, mime_type="image/jpeg")
                        ]
                    
                    tag_response = client.models.generate_content(
                        model='gemini-3.6-flash',
                        contents=tag_payload
                    )
                    
                    article_number = clean_digits(tag_response.text.strip())
                    quantity_to_write = delivery_quantities.get(article_number, "N/A")
                    
                    matches_summary.append({
                        "Tag Page": page_num + 1, 
                        "Article Found": article_number, 
                        "Delivery Quantity": quantity_to_write
                    })
                    
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
                    
                    insert_safe_text(page, date_loc, formatted_date, font_size, (0, 0, 0), text_rotation)
                    insert_safe_text(page, initials_loc, initials, font_size, (0, 0, 0), text_rotation)
                    insert_safe_text(page, count_loc, quantity_to_write, font_size, (0, 0, 0), text_rotation)
                    
                with st.expander("View Page-by-Page Summary"):
                    st.write(matches_summary)
                    
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
                if os.path.exists(tags_path):
                    os.remove(tags_path)
                if os.path.exists(hotlist_path):
                    os.remove(hotlist_path)
                if os.path.exists("Filled_Tags.pdf"):
                    os.remove("Filled_Tags.pdf")
