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
col1, col2, col3 = st.columns(3)
with col1:
    font_size = st.slider("Font Size", min_value=20, max_value=120, value=75, step=5)
with col2:
    x_offset = st.slider("Horizontal Shift (X)", min_value=-100, max_value=200, value=20, step=5)
with col3:
    y_offset = st.slider("Vertical Shift (Y)", min_value=-50, max_value=100, value=15, step=5)

tags_file = st.file_uploader("Upload Tags.pdf", type="pdf")
hotlist_file = st.file_uploader("Upload Hotlist.pdf", type="pdf")

# --- 3. LIVE PREVIEW SECTION ---
# This runs automatically as soon as you upload the Tags.pdf!
if tags_file:
    st.subheader("Live Tag Preview")
    st.write("Adjust the sliders above. The red text shows exactly where your data will print.")
    
    # Save a temporary copy just for the preview
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_preview:
        tmp_preview.write(tags_file.getvalue())
        preview_path = tmp_preview.name
        
    try:
        doc = fitz.open(preview_path)
        page = doc[0]  # Grab only the first page
        
        # Search for words to anchor the text
        count_rects = page.search_for("Count")
        date_rects = page.search_for("Date")
        initials_rects = page.search_for("Initials")
        
        # Default fallbacks
        count_location = fitz.Point(180 + x_offset, 180 + y_offset)
        date_location = fitz.Point(180 + x_offset, 100 + y_offset)
        initials_location = fitz.Point(180 + x_offset, 250 + y_offset)
        
        # Apply placements with your slider offsets
        if count_rects:
            count_location = fitz.Point(count_rects[0].x1 + 10 + x_offset, count_rects[0].y1 + y_offset)
        if date_rects:
            date_location = fitz.Point(date_rects[0].x0 + x_offset, date_rects[0].y1 + y_offset + 30)
        if initials_rects:
            initials_location = fitz.Point(initials_rects[0].x0 + x_offset, initials_rects[0].y1 + y_offset + 30)
            
        formatted_date = count_date.strftime("%m/%d")
        display_initials = initials if initials else "ABC"
        
        # Draw placeholder text in RED (1, 0, 0) so it stands out in the preview
        page.insert_text(date_location, formatted_date, fontsize=font_size, fontname="helvetica-bold", color=(1, 0, 0))
        page.insert_text(initials_location, display_initials, fontsize=font_size, fontname="helvetica-bold", color=(1, 0, 0))
        page.insert_text(count_location, "99", fontsize=font_size, fontname="helvetica-bold", color=(1, 0, 0))
        
        # Convert the PDF page to an image and display it
        pix = page.get_pixmap(dpi=150)
        st.image(pix.tobytes(), caption="Page 1 Preview (Red text shows your placement)")
        
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
                
                count_location = fitz.Point(180 + x_offset, 180 + y_offset)
                date_location = fitz.Point(180 + x_offset, 100 + y_offset)
                initials_location = fitz.Point(180 + x_offset, 250 + y_offset)
                
                if count_rects:
                    count_location = fitz.Point(count_rects[0].x1 + 10 + x_offset, count_rects[0].y1 + y_offset)
                if date_rects:
                    date_location = fitz.Point(date_rects[0].x0 + x_offset, date_rects[0].y1 + y_offset + 30)
                if initials_rects:
                    initials_location = fitz.Point(initials_rects[0].x0 + x_offset, initials_rects[0].y1 + y_offset + 30)
                
                # Draw the final text in BLACK (0, 0, 0)
                page.insert_text(date_location, formatted_date, fontsize=font_size, fontname="helvetica-bold", color=(0, 0, 0))
                page.insert_text(initials_location, initials, fontsize=font_size, fontname="helvetica-bold", color=(0, 0, 0))
                page.insert_text(count_location, quantity_to_write, fontsize=font_size, fontname="helvetica-bold", color=(0, 0, 0))
                
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
