import os
import io
from PIL import Image
from werkzeug.utils import secure_filename
from flask import current_app

MAX_IMAGE_BYTES = 100 * 1024  # 100 KB limit (102,400 bytes)

def is_allowed_image(filename):
    """Check if file extension is allowed."""
    if not filename or '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    allowed = current_app.config.get('ALLOWED_EXTENSIONS', {'png', 'jpg', 'jpeg', 'webp'})
    return ext in allowed

def get_file_size(file_storage):
    """Safely get size of uploaded FileStorage without moving the pointer permanently."""
    if not file_storage:
        return 0
    file_storage.seek(0, os.SEEK_END)
    size = file_storage.tell()
    file_storage.seek(0)
    return size

def validate_and_save_image(file_storage, prefix="img", max_bytes=MAX_IMAGE_BYTES):
    """
    Validates and saves an uploaded image file.
    Guarantees that the saved file is strictly <= max_bytes (100KB).
    If the uploaded image is larger than max_bytes, it compresses and optimizes it
    to bring it under max_bytes.
    
    Returns:
        (saved_filename, error_message): Tuple where saved_filename is the saved
        file's name (or None on failure), and error_message is None on success.
    """
    if not file_storage or not file_storage.filename or not file_storage.filename.strip():
        return None, None

    if not is_allowed_image(file_storage.filename):
        return None, "Invalid image format. Allowed formats: PNG, JPG, JPEG, WEBP."

    original_size = get_file_size(file_storage)
    upload_folder = current_app.config.get('UPLOAD_FOLDER')
    if not upload_folder:
        return None, "Upload folder is not configured."
    os.makedirs(upload_folder, exist_ok=True)

    safe_prefix = "".join(c for c in str(prefix) if c.isalnum() or c in ('_', '-'))
    raw_filename = secure_filename(f"{safe_prefix}_{file_storage.filename}")

    try:
        file_storage.seek(0)
        img = Image.open(file_storage)
        img.verify()  # Verify it's a valid image
        file_storage.seek(0)
        img = Image.open(file_storage)  # Re-open after verify
    except Exception:
        return None, "The uploaded file is not a valid image or is corrupted."

    orig_format = (img.format or 'JPEG').upper()
    if orig_format == 'PNG':
        save_ext = 'png'
        save_format = 'PNG'
    elif orig_format == 'WEBP':
        save_ext = 'webp'
        save_format = 'WEBP'
    else:
        save_ext = 'jpg'
        save_format = 'JPEG'

    base_name = os.path.splitext(raw_filename)[0]
    dest_filename = f"{base_name}.{save_ext}"
    dest_path = os.path.join(upload_folder, dest_filename)

    # If already <= 100KB, save directly
    if original_size <= max_bytes:
        file_storage.seek(0)
        file_storage.save(dest_path)
        return dest_filename, None

    # If > 100KB, optimize/compress to fit strictly within max_bytes
    try:
        # Normalize color mode
        if save_format == 'JPEG' and img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            if 'A' in img.getbands():
                background.paste(img, mask=img.split()[img.getbands().index('A')])
            else:
                background.paste(img)
            img = background
        elif save_format == 'PNG' and img.mode not in ('RGB', 'RGBA', 'L', 'LA'):
            img = img.convert('RGBA')
        elif save_format not in ('PNG', 'WEBP') and img.mode != 'RGB':
            img = img.convert('RGB')

        # Limit maximum dimensions to 800x800 for web performance
        max_dim = 800
        if img.width > max_dim or img.height > max_dim:
            img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

        buffer = io.BytesIO()
        compressed = False

        # Try progressive quality reduction
        for quality in [85, 75, 65, 50, 35, 25]:
            buffer.seek(0)
            buffer.truncate(0)
            if save_format in ('JPEG', 'WEBP'):
                img.save(buffer, format=save_format, quality=quality, optimize=True)
            else:
                img.save(buffer, format=save_format, optimize=True)
            if buffer.tell() <= max_bytes:
                compressed = True
                break

        # If PNG still exceeds 100KB, convert to JPEG for higher compression efficiency
        if not compressed and save_format == 'PNG':
            save_format = 'JPEG'
            save_ext = 'jpg'
            dest_filename = f"{base_name}.jpg"
            dest_path = os.path.join(upload_folder, dest_filename)
            if img.mode in ('RGBA', 'LA'):
                bg = Image.new('RGB', img.size, (255, 255, 255))
                bg.paste(img, mask=img.split()[img.getbands().index('A')])
                img = bg
            elif img.mode != 'RGB':
                img = img.convert('RGB')

            for quality in [80, 65, 50, 35]:
                buffer.seek(0)
                buffer.truncate(0)
                img.save(buffer, format='JPEG', quality=quality, optimize=True)
                if buffer.tell() <= max_bytes:
                    compressed = True
                    break

        # If still exceeding, downscale further
        if not compressed:
            img.thumbnail((450, 450), Image.Resampling.LANCZOS)
            buffer.seek(0)
            buffer.truncate(0)
            img.save(buffer, format='JPEG', quality=50, optimize=True)
            if buffer.tell() <= max_bytes:
                compressed = True

        final_size = buffer.tell()
        if final_size > max_bytes:
            return None, f"Image size ({round(original_size / 1024, 1)} KB) exceeds the 100KB limit and could not be compressed under 100KB. Please upload an image under 100KB."

        with open(dest_path, 'wb') as f:
            f.write(buffer.getvalue())

        return dest_filename, None
    except Exception as e:
        return None, f"Failed to process image: {str(e)}"
