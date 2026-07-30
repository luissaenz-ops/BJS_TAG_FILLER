import streamlit as st
from google import genai
import fitz 
import tempfile
import os
import json

# --- 1. SETUP GEMINI API VIA SECRETS ---
api_key = st.secrets.get("GEMINI_API_KEY", "")

if not api_key:
    st.error("Missing Gemini API Key. Please add 'GEMINI_API_KEY' to your Streamlit Secrets.")
    st.stop()

# The new way to initialize the client
client = genai.Client(api_key=api_key)

# --- 2. APP USER INTERFACE ---
st.title("BJ's Inventory Tag Filler")
st.write("Upload your Tags and Hotlist to automatically fill in inventory quantities.")

initials = st.text_input("Enter your Initials:")
count_date = st.date_input("Select the Date:")

tags_file = st.file_uploader("Upload Tags.pdf", type="pdf")
hotlist_file = st.file_uploader("Upload Hotlist.pdf", type="pdf")

# --- 3. AI EXTRACTION PROMPT ---
extraction_prompt = """
You are a data extraction assistant. I will provide the text from an inventory 'Hotlist'. 
Your job is to find the 'Article' number and match it to the 'Delivery Quantity'.
Rules:
1. Track the row exactly from the Article number to the Delivery Quantity column.
2. Only extract the primary number. Ignore extra zeros, letters like 'CV' or 'EA', and stacked text.
3. Return the data ONLY in a strict JSON dictionary format where the Article number is the key, and the Delivery Quantity is the value. 
Example: {"356363": "2", "341407": "5"}
"""

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
            
            # Send to Gemini AI using the new SDK and the 3.6 flash model
            response = client.models.generate_content(
                model='gemini-3.6-flash',
                contents=[extraction_prompt, hotlist_text]
            )
            clean_json = response.text.replace('```json', '').replace('```', '').strip()
            delivery_quantities = json.loads(clean_json)
            
            st.success("Successfully parsed Hotlist data!")
            st.info("Generating filled PDF...")

            # Fill in the Tags PDF
            pdf_document = fitz.open(tags_path)
            
            for page_num in range(len(pdf_document)):
                page = pdf_document[page_num]
                page_text = page.get_text()
                
                tag_prompt = "Find the 6-digit article number on this tag and return ONLY the number. Nothing else."
                
                # Using the new SDK for the tag prompt with the 3.6 flash model
                tag_response = client.models.generate_content(
                    model='gemini-3.6-flash',
                    contents=[tag_prompt, page_text]
                )
                article_number = tag_response.text.strip()
                
                quantity_to_write = str(delivery_quantities.get(article_number, "N/A"))
                
                date_location = fitz.Point(100, 150) 
                initials_location = fitz.Point(100, 180)
                count_location = fitz.Point(100, 210)
                
                page.insert_text(date_location, str(count_date), fontsize=12, color=(0, 0, 0))
                page.insert_text(initials_location, initials, fontsize=12, color=(0, 0, 0))
                page.insert_text(count_location, quantity_to_write, fontsize=12, color=(0, 0, 0))
                
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
