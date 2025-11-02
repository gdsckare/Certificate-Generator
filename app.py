import os
import re
import io
import zipfile
import threading
import uuid
import shutil
import pandas as pd
import time
from flask import Flask, render_template, request, send_file, redirect, url_for, send_from_directory, jsonify
from PIL import Image, ImageDraw, ImageFont
from werkzeug.utils import secure_filename

BASE_DIR =os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)),"app")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
OUTPUT_FOLDER = os.path.join(BASE_DIR, "outputs")
print(BASE_DIR)
# Use the provided font in the repository (outside the app directory)
FONT_PATH = os.path.join(BASE_DIR, "fonts", "Product Sans Regular.ttf")
FONTS_DIRS = [
    os.path.join(BASE_DIR, "fonts"),
    os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, "fonts")),
]

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# In-memory job registry for async generation progress
JOBS = {}
JOBS_LOCK = threading.Lock()
JOB_TTL_SECONDS = int(os.environ.get("JOB_TTL_SECONDS", "600"))  # 10 minutes after done
JOB_STALE_SECONDS = int(os.environ.get("JOB_STALE_SECONDS", "3600"))  # 1 hour if stuck running

# UI/branding links (override via env if needed)
CONTRIBUTOR_NAME = os.environ.get("CONTRIBUTOR_NAME", "Inukurthi Bharath Kumar")
CONTRIBUTOR_GITHUB = os.environ.get("CONTRIBUTOR_GITHUB", "https://github.com/bharath-inukurthi")
LINKEDIN_URL = os.environ.get("LINKEDIN_URL", "https://www.linkedin.com/in/bharath-kumar-inukurthi")
PORTFOLIO_URL = os.environ.get("PORTFOLIO_URL", "https://")
GITHUB_URL = os.environ.get("GITHUB_URL", "https://github.com/gdsckare/Certificate-Generator")
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "bharathinukurthi1@gmail.com")
GDG_NAME = os.environ.get("GDG_NAME", "GDG On Campus KARE")

@app.context_processor
def inject_globals():
    return dict(
        CONTRIBUTOR_NAME=CONTRIBUTOR_NAME,
        CONTRIBUTOR_GITHUB=CONTRIBUTOR_GITHUB,
        LINKEDIN_URL=LINKEDIN_URL,
        PORTFOLIO_URL=PORTFOLIO_URL,
        CONTACT_EMAIL=CONTACT_EMAIL,
        GITHUB_URL=GITHUB_URL,
        GDG_NAME=GDG_NAME,
    )
def normalize_filename_value(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    s = str(value).strip()
    # Convert numeric-like strings to int when whole number to avoid trailing .0
    try:
        num = float(s)
        if num.is_integer():
            s = str(int(num))
    except Exception:
        # handle simple pattern like 123.0
        if s.endswith('.0') and s[:-2].isdigit():
            s = s[:-2]
    # sanitize forbidden filename characters
    s = s.replace(os.sep, '_')
    s = re.sub(r'[\\/*?:"<>|]+', '_', s)
    return s or None

def load_font(size, font_filename: str | None = None):
    # Try a specifically selected font first
    if font_filename:
        # Absolute path support
        if os.path.isabs(font_filename) and os.path.exists(font_filename):
            try:
                return ImageFont.truetype(font_filename, size)
            except Exception:
                pass
        # Search known font directories
        for d in FONTS_DIRS:
            try:
                candidate = os.path.join(d, font_filename)
                if os.path.exists(candidate):
                    return ImageFont.truetype(candidate, size)
            except Exception:
                continue
    # Fallback candidates
    candidates = [
        FONT_PATH,
        os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, "fonts", "Product Sans Regular.ttf")),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "fonts", "Product Sans Regular.ttf")),
    ]
    for path in candidates:
        try:
            if os.path.exists(path):
                return ImageFont.truetype(path, size)
        except Exception:
            continue
    try:
        return ImageFont.truetype("arial.ttf", size)
    except Exception:
        return ImageFont.load_default()

def list_available_fonts():
    found = []
    seen = set()
    for d in FONTS_DIRS:
        try:
            if os.path.isdir(d):
                for name in os.listdir(d):
                    if name.lower().endswith('.ttf'):
                        if name not in seen:
                            seen.add(name)
                            found.append(name)
        except Exception:
            continue
    found.sort()
    base = os.path.basename(FONT_PATH)
    if base in found:
        found.remove(base)
        found.insert(0, base)
    return found


# Default text positions (normalized: x%, y%)
positions = {
    "col1": (0.5, 0.5),  # center
    "col2": (0.7, 0.7)
}

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        file = request.files.get("file")
        image = request.files.get("image")
        headers_present = bool(request.form.get("headers_present"))

        if not file or not image:
            return "Please upload both Excel/CSV and an image."

        # Save files
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(file_path)

        image_filename = secure_filename(image.filename)
        image_path = os.path.join(app.config["UPLOAD_FOLDER"], image_filename)
        image.save(image_path)

        # Read dataframe (respect headers flag for column discovery)
        if filename.endswith(".csv"):
            df = pd.read_csv(file_path, header=0 if headers_present else None)
        else:
            df = pd.read_excel(file_path, header=0 if headers_present else None)

        columns = [str(c) for c in df.columns.tolist()]
        return render_template(
            "options.html",
            columns=columns,
            image=image_filename,
            data_file=filename,
            headers_present=headers_present,
            fonts=list_available_fonts(),
        )

    return render_template("index.html")


@app.route("/generate", methods=["POST"])
def generate():
    column_positions = {}
    font_sizes = {}
    selected_font_filename = None
    file_column = request.form.get("file_column")  # optional, by name
    image_filename = request.form.get("image")
    data_filename = request.form.get("data_file")
    headers_present = request.form.get("headers_present") in ("true", "True", "1", "on", "yes")

    # Handle font selection/upload (sync)
    font_choice = request.form.get("font_choice")
    if font_choice == "other":
        file = request.files.get("font_file")
        if file and file.filename.lower().endswith('.ttf'):
            fname = secure_filename(file.filename)
            for d in FONTS_DIRS:
                try:
                    os.makedirs(d, exist_ok=True)
                    file.save(os.path.join(d, fname))
                    selected_font_filename = fname
                    break
                except Exception:
                    continue
    elif font_choice:
        selected_font_filename = font_choice

    img = Image.open(os.path.join(UPLOAD_FOLDER, image_filename))
    img_w, img_h = img.size

    # Collect column settings (normalized positions 0-1)
    for key in request.form:
        if key.startswith("pos_") and key.endswith("_x"):
            col = key[len("pos_"):-2]
            # robust parsing with defaults
            try:
                x = float(request.form.get(f"pos_{col}_x", 0.5))
            except Exception:
                x = 0.5
            try:
                y = float(request.form.get(f"pos_{col}_y", 0.5))
            except Exception:
                y = 0.5
            try:
                size = int(float(request.form.get(f"size_{col}", 40)))
            except Exception:
                size = 40
            # clamp and store
            x = 0 if x < 0 else (1 if x > 1 else x)
            y = 0 if y < 0 else (1 if y > 1 else y)
            size = max(1, size)
            column_positions[col] = (x, y)
            font_sizes[col] = size

    # Read dataframe (assume headers present, columns by name)
    data_path = os.path.join(UPLOAD_FOLDER, data_filename)
    if data_filename.endswith(".csv"):
        df = pd.read_csv(data_path, header=0 if headers_present else None)
    else:
        df = pd.read_excel(data_path, header=0 if headers_present else None)

    # Map displayed column names (stringified) back to actual df keys
    col_key_map = {str(c): c for c in df.columns}

    # Prepare zip fully in-memory (no disk writes)
    zip_bytes = io.BytesIO()
    with zipfile.ZipFile(zip_bytes, mode='w', compression=zipfile.ZIP_DEFLATED) as zipf:
        for idx, row in df.iterrows():
            base = img.copy()
            draw = ImageDraw.Draw(base)
            for col, (x_norm, y_norm) in column_positions.items():
                if col in col_key_map:
                    value = row[col_key_map[col]]
                else:
                    continue
                if pd.isna(value):
                    continue
                text = str(value)
                font = load_font(font_sizes.get(col, 40), selected_font_filename)
                bbox = draw.textbbox((0, 0), text, font=font)
                text_w = bbox[2] - bbox[0]
                text_h = bbox[3] - bbox[1]
                x = int(x_norm * img_w - text_w / 2)
                y = int(y_norm * img_h - (text_h / 2 + bbox[1]))
                draw.text((x, y), text, fill=(0, 0, 0, 255), font=font)

            if file_column and file_column in col_key_map:
                candidate = normalize_filename_value(row[col_key_map[file_column]])
                if candidate:
                    out_name = f"{candidate}.png"
                else:
                    out_name = f"generated_{idx}.png"
            else:
                out_name = f"generated_{idx}.png"

            img_buf = io.BytesIO()
            base.save(img_buf, format='PNG')
            img_buf.seek(0)
            zipf.writestr(out_name, img_buf.read())
    zip_bytes.seek(0)

    # best-effort: delete uploaded files now that generation is complete
    try:
        if image_filename:
            fp = os.path.join(UPLOAD_FOLDER, image_filename)
            if os.path.exists(fp):
                os.remove(fp)
        if data_filename:
            fp = os.path.join(UPLOAD_FOLDER, data_filename)
            if os.path.exists(fp):
                os.remove(fp)
    except Exception:
        pass

    return send_file(zip_bytes, mimetype='application/zip', as_attachment=True, download_name='certificates.zip')
def run_generation_job(job_id, image_filename, data_filename, headers_present, column_positions, font_sizes, file_column):
    try:
        img = Image.open(os.path.join(UPLOAD_FOLDER, image_filename))
        img_w, img_h = img.size

        data_path = os.path.join(UPLOAD_FOLDER, data_filename)
        if data_filename.endswith(".csv"):
            df = pd.read_csv(data_path, header=0 if headers_present else None)
        else:
            df = pd.read_excel(data_path, header=0 if headers_present else None)

        col_key_map = {str(c): c for c in df.columns}

        with JOBS_LOCK:
            job = JOBS.get(job_id)
        if not job:
            return
        output_dir = job["output_dir"]
        os.makedirs(output_dir, exist_ok=True)

        total = len(df)
        with JOBS_LOCK:
            job["total"] = total
            job["completed"] = 0
            job["updated"] = time.time()
        for idx, row in df.iterrows():
            base = img.copy()
            draw = ImageDraw.Draw(base)
            for col, (x_norm, y_norm) in column_positions.items():
                if col in col_key_map:
                    value = row[col_key_map[col]]
                else:
                    continue
                if pd.isna(value):
                    continue
                text = str(value)
                with JOBS_LOCK:
                    job = JOBS.get(job_id)
                    job_font = job.get("font_filename") if job else None
                font = load_font(font_sizes.get(col, 40), job_font)
                bbox = draw.textbbox((0, 0), text, font=font)
                text_w = bbox[2] - bbox[0]
                text_h = bbox[3] - bbox[1]
                x = int(x_norm * img_w - text_w / 2)
                y = int(y_norm * img_h - (text_h / 2 + bbox[1]))
                draw.text((x, y), text, fill=(0, 0, 0, 255), font=font)

            if file_column and file_column in col_key_map:
                candidate = normalize_filename_value(row[col_key_map[file_column]])
                if candidate:
                    out_name = f"{candidate}.png"
                else:
                    out_name = f"generated_{idx}.png"
            else:
                out_name = f"generated_{idx}.png"

            out_path = os.path.join(output_dir, out_name)
            base.save(out_path)

            with JOBS_LOCK:
                job["completed"] += 1
                job["updated"] = time.time()

        with JOBS_LOCK:
            job["status"] = "done"
            job["updated"] = time.time()
    except Exception as e:
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if job is not None:
                job["status"] = "error"
                job["error"] = str(e)
                job["updated"] = time.time()


@app.route("/start_generate", methods=["POST"])
def start_generate():
    column_positions = {}
    font_sizes = {}
    file_column = request.form.get("file_column")
    image_filename = request.form.get("image")
    data_filename = request.form.get("data_file")
    headers_present = request.form.get("headers_present") in ("true", "True", "1", "on", "yes")

    # Collect column settings (normalized positions 0-1)
    for key in request.form:
        if key.startswith("pos_") and key.endswith("_x"):
            col = key[len("pos_"):-2]
            try:
                x = float(request.form.get(f"pos_{col}_x", 0.5))
            except Exception:
                x = 0.5
            try:
                y = float(request.form.get(f"pos_{col}_y", 0.5))
            except Exception:
                y = 0.5
            try:
                size = int(float(request.form.get(f"size_{col}", 40)))
            except Exception:
                size = 40
            x = 0 if x < 0 else (1 if x > 1 else x)
            y = 0 if y < 0 else (1 if y > 1 else y)
            size = max(1, size)
            column_positions[col] = (x, y)
            font_sizes[col] = size

    # Handle font selection/upload (async)
    selected_font_filename = None
    font_choice = request.form.get("font_choice")
    if font_choice == "other":
        file = request.files.get("font_file")
        if file and file.filename.lower().endswith('.ttf'):
            fname = secure_filename(file.filename)
            for d in FONTS_DIRS:
                try:
                    os.makedirs(d, exist_ok=True)
                    file.save(os.path.join(d, fname))
                    selected_font_filename = fname
                    break
                except Exception:
                    continue
    elif font_choice:
        selected_font_filename = font_choice

    # Determine total rows for progress
    total_rows = 0
    try:
        data_path = os.path.join(UPLOAD_FOLDER, data_filename)
        if data_filename.endswith(".csv"):
            df_tmp = pd.read_csv(data_path, header=0 if headers_present else None)
        else:
            df_tmp = pd.read_excel(data_path, header=0 if headers_present else None)
        total_rows = len(df_tmp)
    except Exception:
        total_rows = 0

    # Create unique job and output dir
    job_id = uuid.uuid4().hex
    job_output_dir = os.path.join(OUTPUT_FOLDER, job_id)
    with JOBS_LOCK:
        JOBS[job_id] = {
        "status": "running",
        "completed": 0,
        "total": total_rows,
        "output_dir": job_output_dir,
        "error": None,
        "created": time.time(),
        "updated": time.time(),
        "uploads": {"image": image_filename, "data": data_filename},
        "font_filename": selected_font_filename,
    }

    thread = threading.Thread(target=run_generation_job, args=(job_id, image_filename, data_filename, headers_present, column_positions, font_sizes, file_column), daemon=True)
    thread.start()

    return jsonify({"job_id": job_id, "total": total_rows})


@app.route("/progress/<job_id>", methods=["GET"])
def progress(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "job not found"}), 404
    return jsonify({
        "status": job.get("status", "running"),
        "completed": job.get("completed", 0),
        "total": job.get("total", 0),
        "error": job.get("error"),
    })


@app.route("/download/<job_id>", methods=["GET"])
def download(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        return "Job not found", 404
    output_dir = job.get("output_dir")
    if not output_dir or not os.path.isdir(output_dir):
        return "No output available", 404

    # Build zip in memory
    zip_bytes = io.BytesIO()
    with zipfile.ZipFile(zip_bytes, mode='w', compression=zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(output_dir):
            for f in files:
                fp = os.path.join(root, f)
                arcname = os.path.basename(fp)
                zipf.write(fp, arcname=arcname)
    zip_bytes.seek(0)

    # Remove output directory now that zip is ready
    try:
        shutil.rmtree(output_dir, ignore_errors=True)
    except Exception:
        pass

    # Best-effort: remove any existing preview file to keep outputs clean
    try:
        preview_file = os.path.join(OUTPUT_FOLDER, "preview.png")
        if os.path.exists(preview_file):
            os.remove(preview_file)
    except Exception:
        pass

    # Also remove uploaded files for this job
    try:
        uploads = job.get("uploads", {})
        img_name = uploads.get("image")
        data_name = uploads.get("data")
        if img_name:
            fp = os.path.join(UPLOAD_FOLDER, img_name)
            if os.path.exists(fp):
                os.remove(fp)
        if data_name:
            fp = os.path.join(UPLOAD_FOLDER, data_name)
            if os.path.exists(fp):
                os.remove(fp)
    except Exception:
        pass

    # Cleanup job
    try:
        with JOBS_LOCK:
            JOBS.pop(job_id, None)
    except Exception:
        pass

    return send_file(zip_bytes, mimetype='application/zip', as_attachment=True, download_name='certificates.zip')


@app.route("/preview", methods=["POST"])
def preview():
    """Render a preview using the first row of data for all mapped columns."""
    image_filename = request.form.get("image")
    data_filename = request.form.get("data_file")
    headers_present = request.form.get("headers_present") in ("true", "True", "1", "on", "yes")

    img = Image.open(os.path.join(UPLOAD_FOLDER, image_filename))
    img_w, img_h = img.size

    # Build mapping from form
    column_positions = {}
    font_sizes = {}
    selected_font_filename = None
    for key in request.form:
        if key.startswith("pos_") and key.endswith("_x"):
            col = key[len("pos_"):-2]
            # robust parsing with defaults
            try:
                x = float(request.form.get(f"pos_{col}_x", 0.5))
            except Exception:
                x = 0.5
            try:
                y = float(request.form.get(f"pos_{col}_y", 0.5))
            except Exception:
                y = 0.5
            try:
                size = int(float(request.form.get(f"size_{col}", 40)))
            except Exception:
                size = 40
            # clamp
            x = 0 if x < 0 else (1 if x > 1 else x)
            y = 0 if y < 0 else (1 if y > 1 else y)
            size = max(1, size)
            column_positions[col] = (x, y)
            font_sizes[col] = size

    # Handle font selection/upload (preview)
    font_choice = request.form.get("font_choice")
    if font_choice == "other":
        file = request.files.get("font_file")
        if file and file.filename.lower().endswith('.ttf'):
            fname = secure_filename(file.filename)
            for d in FONTS_DIRS:
                try:
                    os.makedirs(d, exist_ok=True)
                    file.save(os.path.join(d, fname))
                    selected_font_filename = fname
                    break
                except Exception:
                    continue
    elif font_choice:
        selected_font_filename = font_choice

    # Load first row of data if provided
    first_row = None
    df = None
    if data_filename:
        data_path = os.path.join(UPLOAD_FOLDER, data_filename)
        if os.path.exists(data_path):
            if data_filename.endswith(".csv"):
                df = pd.read_csv(data_path, header=0 if headers_present else None)
            else:
                df = pd.read_excel(data_path, header=0 if headers_present else None)
            # Use the next row after headers for preview when available
            if headers_present and len(df) > 1:
                first_row = df.iloc[1]
            else:
                first_row = df.iloc[0] if len(df) > 0 else None

    # Map displayed names back to df keys
    col_key_map = {str(c): c for c in df.columns} if df is not None else {}

    base = img.copy()
    draw = ImageDraw.Draw(base)
    for col, (x_norm, y_norm) in column_positions.items():
        sample = col
        if first_row is not None and df is not None and col in col_key_map:
            val = first_row[col_key_map[col]]
            if not pd.isna(val):
                sample = str(val)
        font = load_font(font_sizes.get(col, 40), selected_font_filename)
        bbox = draw.textbbox((0, 0), sample, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        x = int(x_norm * img_w - text_w / 2)
        y = int(y_norm * img_h - (text_h / 2 + bbox[1]))
        draw.text((x, y), sample, fill=(0, 0, 0, 255), font=font)

    # Return preview directly from memory (avoid writing to disk)
    output_bytes = io.BytesIO()
    base.save(output_bytes, format='PNG')
    output_bytes.seek(0)

    return send_file(output_bytes, mimetype="image/png")


def _cleanup_jobs_loop():
    """Background janitor that removes finished or stale jobs and their outputs."""
    while True:
        now = time.time()
        to_delete = []
        with JOBS_LOCK:
            for job_id, job in list(JOBS.items()):
                status = job.get("status", "running")
                updated = job.get("updated", job.get("created", now))
                output_dir = job.get("output_dir")
                if status in ("done", "error") and (now - updated) > JOB_TTL_SECONDS:
                    to_delete.append((job_id, output_dir))
                elif status == "running" and (now - updated) > JOB_STALE_SECONDS:
                    # stale running job
                    to_delete.append((job_id, output_dir))
        # perform deletions outside lock
        for job_id, output_dir in to_delete:
            try:
                if output_dir and os.path.isdir(output_dir):
                    shutil.rmtree(output_dir, ignore_errors=True)
            except Exception:
                pass
            # Also attempt to delete uploaded files for this job
            try:
                with JOBS_LOCK:
                    job = JOBS.get(job_id)
                    uploads = job.get("uploads", {}) if job else {}
                img_name = uploads.get("image")
                data_name = uploads.get("data")
                if img_name:
                    fp = os.path.join(UPLOAD_FOLDER, img_name)
                    if os.path.exists(fp):
                        os.remove(fp)
                if data_name:
                    fp = os.path.join(UPLOAD_FOLDER, data_name)
                    if os.path.exists(fp):
                        os.remove(fp)
            except Exception:
                pass
            with JOBS_LOCK:
                JOBS.pop(job_id, None)
        time.sleep(60)


# Start background cleanup thread
_janitor_thread = threading.Thread(target=_cleanup_jobs_loop, daemon=True)
_janitor_thread.start()


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


@app.route("/assets/<path:filename>")
def assets_file(filename):
    assets_dir = os.path.join(BASE_DIR, "assets")
    return send_from_directory(assets_dir, filename)

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
