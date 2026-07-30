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
initials = st.text_input("Enter your Initials:")
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

# --- 4. PROCESSING ---
if st.button("Generate Filled Tags"):
    if not initials or not tags_file or not hotlist_file:
        st.warning("Please fill in all fields and upload both PDFs.")
    else:
        st.info("Reading the Hotlist with AI... please wait.")
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_tags:
            tmp_tags.write(tags_file.read())
            tags_path = tmp_tags.name
            
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_hotlist:
            tmp_hotlist.write(hotlist_file.read())
            hotlist_path = tmp_hotlist.name

        try:
            # Extract text from Hotlist
            hotlist_doc = fitz.open(hotlist_path)
            hotlist_text = ""
            for page in hotlist_doc:
                hotlist_text += page.get_text()
            hotlist_doc.close()
            
            # Request JSON response from Gemini
            response = client.models.generate_content(
                model='gemini-3.6-flash',
                contents=[extraction_prompt, hotlist_text],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )
            
            # Clean dictionary keys
            raw_quantities = json.loads(response.text)
            delivery_quantities = {clean_digits(k): str(v) for k, v in raw_quantities.items()}
            
            st.success("Successfully parsed Hotlist data!")
            
            # Format the date to MM/DD
            formatted_date = count_date.strftime("%m/%d")
            
            # Fill in the Tags PDF
            pdf_document = fitz.open(tags_path)
            matches_summary = []
            
            for page_num in range(len(pdf_document)):
                page = pdf_document[page_num]
                page_text = page.get_text()
                
                # Ask Gemini for the article number on this tag
                tag_prompt = "Find the 6-digit article number on this tag page. Return ONLY the 6 digits."
                tag_response = client.models.generate_content(
                    model='gemini-3.6-flash',
                    contents=[tag_prompt, page_text]
                )
                
                article_number = clean_digits(tag_response.text.strip())
                quantity_to_write = delivery_quantities.get(article_number, "N/A")
                matches_summary.append({"Page": page_num + 1, "Article": article_number, "Found Count": quantity_to_write})
                
                # --- FIND LOCATIONS ON THE PAGE ---
                # Strictly search for only these three words
                count_rects = page.search_for("Count")
                date_rects = page.search_for("Date")
                initials_rects = page.search_for("Initials")
                
                # Default fallbacks
                count_location = fitz.Point(180 + x_offset, 180 + y_offset)
                date_location = fitz.Point(180 + x_offset, 100 + y_offset)
                initials_location = fitz.Point(180 + x_offset, 250 + y_offset)
                
                # 1. Place Delivery Quantity (to the right of 'Count')
                if count_rects:
                    rect = count_rects[0]
                    # rect.x1 is the right edge of the word. We add a little padding plus your offset.
                    count_location = fitz.Point(rect.x1 + 10 + x_offset, rect.y1 + y_offset)
                    
                # 2. Place MM/DD Date (under 'Date')
                if date_rects:
                    rect = date_rects[0]
                    # rect.y1 is the bottom edge of the word. We add 30 pixels to move it below the word.
                    date_location = fitz.Point(rect.x0 + x_offset, rect.y1 + y_offset + 30)
                    
                # 3. Place Initials (under 'Initials')
                if initials_rects:
                    rect = initials_rects[0]
                    # rect.y1 is the bottom edge of the word. We add 30 pixels to move it below the word.
                    initials_location = fitz.Point(rect.x0 + x_offset, rect.y1 + y_offset + 30)
                
                # --- DRAW THE BIG, BOLD TEXT ---
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
