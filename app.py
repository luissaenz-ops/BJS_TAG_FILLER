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

# --- 2. SESSION STATE & PROFILE MANAGEMENT ---
st.set_page_config(layout="wide", page_title="BJ's Inventory Tag Filler")

# Initialize default profiles in session state
if "profiles" not in st.session_state:
    st.session_state.profiles = {
        "Default Layout": {
            "font_size": 75,
            "text_rotation": 0,
            "qty_x": 10, "qty_y": 0,
            "date_x": 0, "date_y": 30,
            "init_x": 0, "init_y": 30
        }
    }

# Memory storage for AI Learning
if "ai_learning_memory" not in st.session_state:
    st.session_state.ai_learning_memory = []

st.title("BJ's Inventory Tag Filler")
st.write("Smart PDF tag filler with orientation auto-detection, AI learning memory, and custom profile management.")

# Sidebar - Profile Manager & Export/Import
with st.sidebar:
    st.header("Profile Manager")
    
    # Select existing profile
    selected_profile_name = st.selectbox("Load Saved Profile:", list(st.session_state.profiles.keys()))
    
    # Profile Save Action
    new_profile_name = st.text_input("New Profile Name:")
    save_profile_btn = st.button("Save Current Settings as Profile")
    
    st.markdown("---")
    # Profile Export / Import JSON
    profiles_json = json.dumps(st.session_state.profiles, indent=2)
    st.download_button("Export Profiles (.json)", data=profiles_json, file_name="tag_profiles.json", mime="application/json")
    
    uploaded_profile = st.file_uploader("Import Profiles (.json)", type="json")
    if uploaded_profile:
        try:
            imported_data = json.load(uploaded_profile)
            st.session_state.profiles.update(imported_data)
            st.success("Profiles imported successfully!")
        except Exception as e:
            st.error(f"Invalid profile file: {e}")

# Helper function to load selected profile settings into sliders
curr_profile = st.session_state.profiles.get(selected_profile_name, st.session_state.profiles["Default Layout"])

# Top Inputs
col_input1, col_input2 = st.columns(2)
with col_input1:
    initials = st.text_input("Enter your Initials:", value="JS")
with col_input2:
    count_date = st.date_input("Select the Date:")

tags_file = st.file_uploader("Upload Tags File (Any Name)", type="pdf")
hotlist_file = st.file_uploader("Upload Hotlist File (Any Name)", type="pdf")

# --- 3. HELPER FUNCTIONS ---

def clean_digits(text):
    """Strips non-digits to ensure clean matching keys."""
    return re.sub(r'\D', '', str(text))

def get_page_text_and_rotation(page):
    """Handles automatic page orientation detection."""
    rotation_angle = page.rotation
    text = page.get_text()
    return text, rotation_angle

def insert_safe_text(page, location, text, size, color, angle):
    """Inserts bold text with safe matrix rotation."""
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

# --- 4. INTERACTIVE UI & CONTROLS ---
if tags_file:
    st.markdown("---")
    
    ui_col, preview_col = st.columns([1, 1.5])
    
    with ui_col:
        st.subheader("Placement & Orientation Controls")
        
        font_size = st.slider("Global Font Size", 20, 120, int(curr_profile["font_size"]), step=5)
        text_rotation = st.selectbox("Text Rotation Angle", options=[0, 90, 180, 270], index=[0, 90, 180, 270].index(curr_profile["text_rotation"]))
        
        st.markdown("**Quantity Position**")
        qty_x = st.slider("Quantity Left/Right (X)", -300, 500, int(curr_profile["qty_x"]), step=5)
        qty_y = st.slider("Quantity Up/Down (Y)", -300, 500, int(curr_profile["qty_y"]), step=5)
        
        st.markdown("**Date Position**")
        date_x = st.slider("Date Left/Right (X)", -300, 500, int(curr_profile["date_x"]), step=5)
        date_y = st.slider("Date Up/Down (Y)", -300, 500, int(curr_profile["date_y"]), step=5)
        
        st.markdown("**Initials Position**")
        init_x = st.slider("Initials Left/Right (X)", -300, 500, int(curr_profile["init_x"]), step=5)
        init_y = st.slider("Initials Up/Down (Y)", -300, 500, int(curr_profile["init_y"]), step=5)
        
        # Save profile logic
        if save_profile_btn and new_profile_name:
            st.session_state.profiles[new_profile_name] = {
                "font_size": font_size,
                "text_rotation": text_rotation,
                "qty_x": qty_x, "qty_y": qty_y,
                "date_x": date_x, "date_y": date_y,
                "init_x": init_x, "init_y": init_y
            }
            st.success(f"Profile '{new_profile_name}' saved!")
            st.rerun()
            
        generate_clicked = st.button("Generate Filled Tags", type="primary", use_container_width=True)

    with preview_col:
        st.subheader("Live Tag Preview (Page 1)")
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_preview:
            tmp_preview.write(tags_file.getvalue())
            preview_path = tmp_preview.name
            
        try:
            doc = fitz.open(preview_path)
            page = doc[0] 
            
            # Find coordinates
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
            
            # Draw red preview text
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

    # --- 5. MULTI-PAGE PROCESSING WITH LEARNING MEMORY ---
    if generate_clicked:
        if not initials or not hotlist_file:
            st.warning("Please fill in your initials and upload the Hotlist PDF.")
        else:
            st.info("Reading Hotlist with Gemini AI... please wait.")
            
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_tags:
                tmp_tags.write(tags_file.getvalue())
                tags_path = tmp_tags.name
                
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_hotlist:
                tmp_hotlist.write(hotlist_file.getvalue())
                hotlist_path = tmp_hotlist.name

            try:
                # Include adaptive learning memory in prompt
                memory_context = ""
                if st.session_state.ai_learning_memory:
                    memory_context = f"\nPrevious successful extractions for reference:\n{json.dumps(st.session_state.ai_learning_memory[-5:])}\n"
                
                hotlist_extraction_prompt = f"""
                You are analyzing an inventory 'Hotlist' document containing product tables across pages.
                {memory_context}
                Read every row:
                1. Find item number in 'Article' column.
                2. Extract primary integer in 'Delivery Quantity' column (e.g. '2.000 CV' -> '2').
                Return strictly JSON object: {{"Article": "DeliveryQuantity"}}.
                """

                hotlist_doc = fitz.open(hotlist_path)
                contents_payload = [hotlist_extraction_prompt]
                
                full_text = ""
                for page_idx in range(len(hotlist_doc)):
                    page = hotlist_doc[page_idx]
                    page_text, page_rot = get_page_text_and_rotation(page)
                    if page_text.strip():
                        full_text += f"\n--- PAGE {page_idx + 1} (Rotation: {page_rot} deg) ---\n" + page_text

                if full_text.strip():
                    contents_payload.append(f"Extracted Hotlist Text:\n{full_text}")
                else:
                    for page_idx in range(len(hotlist_doc)):
                        page = hotlist_doc[page_idx]
                        pix = page.get_pixmap(dpi=100)
                        img_bytes = pix.tobytes("jpeg")
                        contents_payload.append(types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"))

                hotlist_doc.close()
                
                response = client.models.generate_content(
                    model='gemini-3.6-flash',
                    contents=contents_payload,
                    config=types.GenerateContentConfig(response_mime_type="application/json")
                )
                
                raw_quantities = json.loads(response.text)
                delivery_quantities = {clean_digits(k): str(v) for k, v in raw_quantities.items()}
                
                # Save to AI learning memory
                st.session_state.ai_learning_memory.append(delivery_quantities)
                
                st.success(f"Extracted {len(delivery_quantities)} article entries from Hotlist.")
                st.info("Writing filled tags...")
                
                formatted_date = count_date.strftime("%m/%d")
                pdf_document = fitz.open(tags_path)
                matches_summary = []
                
                tag_article_prompt = """
                Locate the primary item/article number displayed on this tag page.
                Return ONLY clean numerical digits.
                """

                for page_num in range(len(pdf_document)):
                    page = pdf_document[page_num]
                    page_text, page_rot = get_page_text_and_rotation(page)
                    
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
                        "Delivery Quantity": quantity_to_write,
                        "Page Rotation": f"{page_rot}°"
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
                    
                with st.expander("View Page Summary"):
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
