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

# --- 2. APP USER INTERFACE ---
st.title("BJ's Inventory Tag Filler")
st.write("Upload your Tags and Hotlist to automatically fill in inventory quantities.")

# User Inputs
initials = st.text_input("Enter your Initials:", value="JS")
count_date = st.date_input("Select the Date:")

st.subheader("Text Formatting & Position Controls")
font_size = st.slider("Global Font Size", min_value=20, max_value=120, value=75, step=5)

# Create tabs for independent controls
tab1, tab2, tab3 = st.tabs(["Quantity Placement", "Date Placement", "Initials Placement"])

with tab1:
    qty_x = st.slider("Quantity Horizontal Shift (X)", -200, 200, 10, step=5, key="qx")
    qty_y = st.slider("Quantity Vertical Shift (Y)", -200, 200, 0, step=5, key="qy")
    qty_rot = st.slider("Quantity Rotation", -180, 180, 0, step=5, key="qr")

with tab2:
    date_x = st.slider("Date Horizontal Shift (X)", -200, 200, 0, step=5, key="dx")
    date_y = st.slider("Date Vertical Shift (Y)", -200, 200, 30, step=5, key="dy")
    date_rot = st.slider("Date Rotation", -180, 180, 0, step=5, key="dr")

with tab3:
    init_x = st.slider("Initials Horizontal Shift (X)", -200, 200, 0, step=5, key="ix")
    init_y = st.slider("Initials Vertical Shift (Y)", -200, 200, 30, step=5, key="iy")
    init_rot = st.slider("Initials Rotation", -180, 180, 0, step=5, key="ir")

tags_file = st.file_uploader("Upload Tags.pdf", type="pdf")
hotlist_file = st.file_uploader("Upload Hotlist.pdf", type="pdf")

# --- 3. LIVE PREVIEW SECTION ---
if tags_file:
    st.subheader("Live Tag Preview")
    st.write("Adjust the sliders in the tabs above. The red text shows exactly where your data will print.")
    
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
        count_location = fitz.Point(180, 180)
        date_location = fitz.Point(180, 100)
        initials_location = fitz.Point(180, 250)
        
        # Apply the detected anchors PLUS your individual X/Y shifts
        if count_rects:
            count_location = fitz.Point(count_rects[0].x1 + qty_x, count_rects[0].y1 + qty_y)
        if date_rects:
            date_location = fitz.Point(date_rects[0].x0 + date_x, date_rects[0].y1 + date_y)
        if initials_rects:
            initials_location = fitz.Point(initials_rects[0].x0 + init_x, initials_rects[0].y1 + init_y)
            
        formatted_date = count_date.strftime("%m/%d")
        display_initials = initials if initials else "ABC"
        
        # Draw placeholder text in RED using the morph property for rotation
        page.insert_text(date_location, formatted_date, fontsize=font_size, fontname="helvetica-bold", color=(1, 0, 0), morph=(date_location, fitz.Matrix(date_rot)))
        page.insert_text(initials_location, display_initials, fontsize=font_size, fontname="helvetica-bold", color=(1, 0, 0), morph=(initials_location, fitz.Matrix(init_rot)))
        page.insert_text(count_location, "99", fontsize=font_size, fontname="helvetica-bold", color=(1, 0, 0), morph=(count_location, fitz.Matrix(qty_rot)))
        
        pix = page.get_pixmap(dpi=150)
        st.image(pix.tobytes(), caption="Page 1 Preview")
        
        doc.close()
    except Exception as e:
        st.error(f"Could not generate preview: {e}")
    finally:
        os.remove(preview_path)

# --- 4. AI EXTRACTION PROMPT ---
extraction_prompt = """
Extract the 'Article' number and match it to the 'Delivery Quantity' from this Hotlist document.
1. Track the row exactly from the Article number to the Delivery Quantity column.
2. Only extract the primary integer for the quantity. Ignore extra zeros, 'CV', 'EA', and stacked text.
Return the data as a JSON object where the keys are Article numbers (strings) and the values are the Delivery Quantities (strings).
Example: {"356363": "2", "341407": "5"}
"""

def clean_digits(text):
    return re.sub(r'\D', '', str(text))

# --- 5. FINAL PROCESSING ---
if st.button("Generate Filled Tags"):
    if not initials or not tags_file or not hotlist_file:
        st.warning("Please fill in all fields and upload both PDFs.")
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
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )
            
            raw_quantities = json.loads(response.text)
            delivery_quantities = {clean_digits(k): str(v) for k, v in raw_quantities.items()}
            
            st.success("Successfully parsed Hotlist data!")
            
            formatted_date = count_date.strftime("%m/%d")
            pdf_document = fitz.open(tags_path)
            matches_summary = []
            
            for page_num in range(len(pdf_document)):
                page = pdf_document[page_num]
                page_text = page.get_text()
                
                tag_prompt = "Find the 6-digit article number on this tag page. Return ONLY the 6 digits."
                tag_response = client.models.generate_content(
                    model='gemini-3.6-flash',
                    contents=[tag_prompt, page_text]
                )
                
                article_number = clean_digits(tag_response.text.strip())
                quantity_to_write = delivery_quantities.get(article_number, "N/A")
                matches_summary.append({"Page": page_num + 1, "Article": article_number, "Found Count": quantity_to_write})
                
                count_rects = page.search_for("Count")
                date_rects = page.search_for("Date")
                initials_rects = page.search_for("Initials")
                
                count_location = fitz.Point(180, 180)
                date_location = fitz.Point(180, 100)
                initials_location = fitz.Point(180, 250)
                
                if count_rects:
                    count_location = fitz.Point(count_rects[0].x1 + qty_x, count_rects[0].y1 + qty_y)
                if date_rects:
                    date_location = fitz.Point(date_rects[0].x0 + date_x, date_rects[0].y1 + date_y)
                if initials_rects:
                    initials_location = fitz.Point(initials_rects[0].x0 + init_x, initials_rects[0].y1 + init_y)
                
                # Draw the final text in BLACK, applying the individual rotations
                page.insert_text(date_location, formatted_date, fontsize=font_size, fontname="helvetica-bold", color=(0, 0, 0), morph=(date_location, fitz.Matrix(date_rot)))
                page.insert_text(initials_location, initials, fontsize=font_size, fontname="helvetica-bold", color=(0, 0, 0), morph=(initials_location, fitz.Matrix(init_rot)))
                page.insert_text(count_location, quantity_to_write, fontsize=font_size, fontname="helvetica-bold", color=(0, 0, 0), morph=(count_location, fitz.Matrix(qty_rot)))
                
            with st.expander("View Extraction Summary"):
                st.write(matches_summary)
                
            output_path = "Filled_Tags.pdf"
            pdf_document.save(output_path)
            pdf_document.close()
            
            with open(output_path, "rb") as f:
                st.download_button(
                    label="Download Completed Tags PDF",
                    data=f,
                    file_name="Completed_Tags.pdf",
                    mime="application/pdf"
                )
                
        except Exception as e:
            st.error(f"An error occurred: {e}")
            
        finally:
            os.remove(tags_path)
            os.remove(hotlist_path)
            if os.path.exists("Filled_Tags.pdf"):
                os.remove("Filled_Tags.pdf")
