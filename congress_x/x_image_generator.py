import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional

LOG = logging.getLogger("x_image_generator")

try:
    from PIL import Image, ImageDraw, ImageFont
    LOG.info("PIL modules imported successfully at module level")
except ImportError as e:
    LOG.error(f"PIL import failed at module level: {e}")
    # Try alternative import methods
    try:
        import PIL.Image as Image
        import PIL.ImageDraw as ImageDraw
        import PIL.ImageFont as ImageFont
        LOG.info("PIL modules imported successfully using alternative method")
    except ImportError as e2:
        LOG.error(f"Alternative PIL import also failed: {e2}")
        Image = None
        ImageDraw = None
        ImageFont = None


class XImageGenerator:
    def __init__(self):
        """Initialize XImageGenerator."""
        LOG.info("XImageGenerator initialized")

    def _wrap_text(self, text: str, max_width: int, font, draw) -> list:
        """
        Wrap text to fit within max_width using the given font.

        Args:
            text: Text to wrap
            max_width: Maximum width in pixels
            font: Font to use for measurement
            draw: ImageDraw object for textbbox

        Returns:
            List of wrapped lines
        """
        lines = []
        words = text.split()
        current_line = ""
        for word in words:
            test_line = current_line + " " + word if current_line else word
            bbox = draw.textbbox((0, 0), test_line, font=font)
            line_width = bbox[2] - bbox[0]
            if line_width <= max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)
        return lines

    def create_bills_png(self, bills_data: list, output_path: str = "federal_bills_summary.png", image_num: Optional[int] = None, total_images: Optional[int] = None) -> str:
        """
        Create a PNG image summarizing bills with formatted text.

        Args:
            bills_data: List of bill data dictionaries (for this image chunk)
            output_path: Path to save the PNG file
            image_num: Optional image number for multi-part (e.g., 1)
            total_images: Optional total number of images for multi-part

        Returns:
            Path to the created image file if successful, empty string otherwise
        """
        # Check module-level PIL availability
        import sys
        current_module = sys.modules[__name__]
        pil_available = all([current_module.Image, current_module.ImageDraw, current_module.ImageFont])
        LOG.info(f"Checking PIL availability: {pil_available}")
        if not pil_available:
            LOG.warning("PIL modules not available at module level, trying runtime import...")
            try:
                # Import PIL modules and assign to module level
                from PIL import Image as PILImage, ImageDraw as PILImageDraw, ImageFont as PILImageFont
                current_module.Image = PILImage
                current_module.ImageDraw = PILImageDraw
                current_module.ImageFont = PILImageFont
                LOG.info("PIL runtime import successful")
            except ImportError as e:
                LOG.error(f"PIL runtime import failed: {e}")
                return ""

        try:
            # Image settings - 16:9 aspect ratio (1920x1080 for higher resolution)
            width = 1920
            height = 1080
            padding = 50
            title_font_size = 40
            bill_font_size = 40  # Increased for larger font
            min_bill_font_size = 20  # Increased min to prioritize legibility
            margin_after_title = 30
            extra_bottom_padding = 20
            separator_height_factor = 1.5  # Increased for better spacing

            # Colors for background stripes
            house_bg_color = (220, 230, 255)  # Light blue for House
            senate_bg_color = (245, 245, 245)  # Light gray for Senate (removed red background)
            other_bg_color = (245, 245, 245)  # Light gray for others

            # Create title
            est_tz = timezone(timedelta(hours=-5))  # EST is UTC-5
            est_time = datetime.now(est_tz)
            title = f"@FedBillAlert Summary - {est_time.strftime('%Y-%m-%d %I:%M %p EST')}"
            if total_images and total_images > 1 and image_num:
                title += f" (Part {image_num} of {total_images}: {len(bills_data)} bills)"
            else:
                title += f" ({len(bills_data)} bills)"

            # Store bill data for processing (we'll format in the drawing loop to include sponsor info)
            bill_data_list = bills_data

            # Load fonts (regular and bold)
            try:
                title_font = ImageFont.truetype("arial.ttf", title_font_size)
                bill_font = ImageFont.truetype("arial.ttf", bill_font_size)
                bold_font = ImageFont.truetype("arialbd.ttf", bill_font_size)  # Bold variant for bill numbers
                is_default_font = False
                LOG.info("Using truetype font (arial.ttf and arialbd.ttf)")
            except OSError:
                title_font = ImageFont.load_default()
                bill_font = ImageFont.load_default()
                bold_font = ImageFont.load_default()  # Fallback, no bold
                is_default_font = True
                LOG.warning("Fallback to default font - scaling disabled")

            # Compute line heights from font metrics
            title_line_height = title_font.getmetrics()[0] + title_font.getmetrics()[1]
            line_height = bill_font.getmetrics()[0] + bill_font.getmetrics()[1]

            # Create temporary draw for measurements
            temp_image = Image.new('RGB', (1, 1), color='white')
            temp_draw = ImageDraw.Draw(temp_image)

            # Compute title height (use bbox for precise height)
            title_bbox = temp_draw.textbbox((0, 0), title, font=title_font)
            title_height = title_bbox[3] - title_bbox[1]

            # Max width for bill text
            max_line_width = width - (padding * 2)

            # Compute total bill height
            def compute_total_bill_height(bill_data_list, bill_font, bold_font, line_height):
                total = 0
                for bill_data in bill_data_list:
                    bill_number = bill_data.get('formatted_bill_number', '')
                    title = bill_data.get('title', '')
                    sponsor = bill_data.get('sponsor', 'Unknown')

                    # Calculate lines for title (after bill number)
                    title_text = f" - {title}" if title else ""
                    bill_number_width = temp_draw.textbbox((0, 0), bill_number, font=bold_font)[2] - temp_draw.textbbox((0, 0), bill_number, font=bold_font)[0]
                    title_lines = self._wrap_text(title_text, max_line_width - bill_number_width - 10, bill_font, temp_draw)

                    # Calculate lines for sponsor with introduced date
                    introduced_date = bill_data.get('introduced_date', 'Unknown')
                    sponsor_text = f"Sponsor: {sponsor} | {introduced_date}"
                    sponsor_lines = self._wrap_text(sponsor_text, max_line_width, bill_font, temp_draw)

                    total_lines = len(title_lines) + len(sponsor_lines)
                    total += total_lines * line_height

                # Add separators (n-1) * separator_space
                if len(bill_data_list) > 1:
                    total += (len(bill_data_list) - 1) * (line_height * separator_height_factor)
                return total

            total_bill_height = compute_total_bill_height(bill_data_list, bill_font, bold_font, line_height)

            # Available height for bills
            available_height = height - (padding * 2) - title_height - margin_after_title - extra_bottom_padding

            # Scale if necessary and not default font
            if total_bill_height > available_height and not is_default_font:
                scale_factor = available_height / total_bill_height
                new_bill_font_size = max(min_bill_font_size, int(bill_font_size * scale_factor))
                bill_font = ImageFont.truetype("arial.ttf", new_bill_font_size)
                bold_font = ImageFont.truetype("arialbd.ttf", new_bill_font_size)
                line_height = bill_font.getmetrics()[0] + bill_font.getmetrics()[1]
                LOG.info(f"Scaled bill font to {new_bill_font_size}pt, line_height={line_height}px")

                # Recompute total_bill_height with new font (wrapping may change)
                total_bill_height = compute_total_bill_height(bill_data_list, bill_font, bold_font, line_height)

                # Further reduce font size incrementally if still doesn't fit (to prevent clipping)
                while total_bill_height > available_height and new_bill_font_size > min_bill_font_size:
                    new_bill_font_size -= 1
                    bill_font = ImageFont.truetype("arial.ttf", new_bill_font_size)
                    bold_font = ImageFont.truetype("arialbd.ttf", new_bill_font_size)
                    line_height = bill_font.getmetrics()[0] + bill_font.getmetrics()[1]
                    total_bill_height = compute_total_bill_height(bill_data_list, bill_font, bold_font, line_height)
                    LOG.info(f"Further scaled bill font to {new_bill_font_size}pt to fit content")

            # Create image with fixed 16:9 dimensions and light gray background
            image = Image.new('RGB', (width, height), color=(245, 245, 245))
            draw = ImageDraw.Draw(image)

            # Draw title centered
            title_bbox = draw.textbbox((0, 0), title, font=title_font)
            title_width = title_bbox[2] - title_bbox[0]
            title_x = (width - title_width) // 2
            draw.text((title_x, padding), title, fill='black', font=title_font)

            # Start position for bills
            y_position = padding + title_height + margin_after_title

            # Draw bills (left-aligned for better readability)
            for i, bill_data in enumerate(bill_data_list):
                # Extract bill information
                bill_number = bill_data.get('formatted_bill_number', '')
                title = bill_data.get('title', '')
                sponsor = bill_data.get('sponsor', 'Unknown')
                sponsor_party = bill_data.get('sponsor_party', 'Unknown')

                # Format text for wrapping calculations
                title_text = f" - {title}" if title else ""
                introduced_date = bill_data.get('introduced_date', 'Unknown')
                sponsor_text = f"Sponsor: {sponsor} | Introduced: {introduced_date}"

                # Compute the height of this bill entry (bill number + title + sponsor)
                title_lines = self._wrap_text(title_text, max_line_width - draw.textbbox((0, 0), bill_number, font=bold_font)[2] - 10, bill_font, draw)
                sponsor_lines = self._wrap_text(sponsor_text, max_line_width, bill_font, draw)
                total_lines = len(title_lines) + len(sponsor_lines)
                bill_entry_height = total_lines * int(line_height * 1.5)

                # Check if there's enough space for this entire bill before drawing it
                if y_position + bill_entry_height + line_height >= height - padding:  # Add line_height for separator
                    LOG.info(f"Reached image height limit - {i}/{len(bill_data_list)} bills displayed")
                    break

                # Determine color based on bill type
                if bill_number.startswith('H.'):
                    bill_color = (47, 79, 47)  # #2F4F2F for House
                    bg_color = house_bg_color
                elif bill_number.startswith('S.'):
                    bill_color = (10, 42, 94)  # #0A2A5E for Senate
                    bg_color = senate_bg_color
                else:
                    bill_color = (0, 0, 0)  # Black for others
                    bg_color = other_bg_color

                # Determine sponsor color based on party
                if sponsor_party.upper() == 'D' or sponsor_party.upper() == 'DEMOCRAT':
                    sponsor_color = (0, 174, 243)  # #00AEF3 for Democrats
                    LOG.debug(f"Using Democrat color for sponsor: {sponsor} (party: {sponsor_party})")
                elif sponsor_party.upper() == 'R' or sponsor_party.upper() == 'REPUBLICAN':
                    sponsor_color = (233, 20, 29)  # #E9141D for Republicans
                    LOG.debug(f"Using Republican color for sponsor: {sponsor} (party: {sponsor_party})")
                else:
                    sponsor_color = (100, 100, 100)  # Gray for unknown/independent
                    LOG.debug(f"Using unknown color for sponsor: {sponsor} (party: {sponsor_party})")

                # Draw background stripe
                draw.rectangle([(padding - 10, y_position - 5), (width - padding + 10, y_position + bill_entry_height + 5)], fill=bg_color)

                # Draw bill number with color
                x_pos = padding
                bold_bbox = draw.textbbox((0, 0), bill_number, font=bold_font)
                bold_width = bold_bbox[2] - bold_bbox[0]
                draw.text((x_pos, y_position), bill_number, fill=bill_color, font=bold_font)
                x_pos += bold_width + 10

                # Draw title (wrapped if needed)
                current_line_y = y_position
                for j, line in enumerate(title_lines):
                    if current_line_y + line_height > height - padding:
                        LOG.info(f"Insufficient space for remaining lines in bill {i+1}")
                        break
                    draw.text((x_pos if j == 0 else padding, current_line_y), line, fill='black', font=bill_font)
                    current_line_y += int(line_height * 1.5)

                # Draw sponsor information
                for j, line in enumerate(sponsor_lines):
                    if current_line_y + line_height > height - padding:
                        LOG.info(f"Insufficient space for sponsor lines in bill {i+1}")
                        break
                    draw.text((padding, current_line_y), line, fill=sponsor_color, font=bill_font)
                    current_line_y += int(line_height * 1.5)

                y_position = current_line_y

                # Add horizontal separator line after each bill (except the last one)
                if i < len(bill_data_list) - 1 and y_position < height - padding:
                    y_position += line_height // 2
                    line_start_x = padding
                    line_end_x = width - padding
                    draw.line((line_start_x, y_position, line_end_x, y_position), fill='black', width=2)  # Thicker separator
                    y_position += line_height // 2

            # Save image with optimization
            image.save(output_path, "PNG", optimize=True)
            file_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0
            LOG.info(f"Successfully created PNG image at: {os.path.abspath(output_path)} ({file_size} bytes)")
            return output_path

        except Exception as e:
            LOG.error(f"Failed to create PNG image: {e}")
            return ""

    def create_multiple_bills_pngs(self, bills_data: list, base_filename: str = "federal_bills_summary.png") -> list:
        """
        Create multiple PNG images from bills data, evenly distributing bills across up to 4 images.
        Deduplicates bills before processing to prevent duplicates in images.

        Args:
            bills_data: List of all bill data dictionaries
            base_filename: Base filename for PNG images (will add _partX)

        Returns:
            List of created image file paths
        """
        if not bills_data:
            LOG.info("No bills to create images for")
            return []

        # Deduplicate bills by formatted_bill_number to prevent duplicates in images
        seen_bills = {}
        deduplicated_bills = []
        for bill in bills_data:
            bill_id = bill.get('formatted_bill_number', '')
            if bill_id and bill_id not in seen_bills:
                seen_bills[bill_id] = True
                deduplicated_bills.append(bill)
            elif not bill_id:
                deduplicated_bills.append(bill)

        if len(deduplicated_bills) < len(bills_data):
            LOG.warning(f"Deduplicated bills: {len(bills_data)} -> {len(deduplicated_bills)} (removed {len(bills_data) - len(deduplicated_bills)} duplicates)")

        bills_data = deduplicated_bills

        image_paths = []
        total_bills = len(bills_data)
        max_images = None  # No limit on number of images
        max_bills_per_image = 8  # 8 bills per image

        if total_bills == 0:
            return []

        # Calculate number of images: ceil(total / max_bills_per_image)
        num_images = (total_bills + max_bills_per_image - 1) // max_bills_per_image
        if max_images is not None:
            num_images = min(num_images, max_images)

        LOG.info(f"Creating {num_images} PNG image(s) from {total_bills} bills")

        # Evenly distribute bills across num_images
        chunk_size = total_bills // num_images
        remainder = total_bills % num_images
        current_start = 0

        for image_num in range(1, num_images + 1):
            this_chunk_size = chunk_size + 1 if (image_num - 1) < remainder else chunk_size
            end_idx = current_start + this_chunk_size
            bills_chunk = bills_data[current_start:end_idx]
            current_start = end_idx

            if not bills_chunk:
                break

            # Create filename for this image
            if num_images == 1:
                image_filename = base_filename
            else:
                name_parts = base_filename.rsplit('.', 1)
                image_filename = f"{name_parts[0]}_part{image_num}.{name_parts[1]}" if len(name_parts) > 1 else f"{base_filename}_part{image_num}"

            # Create the PNG image, passing image_num and total_images for title
            image_path = self.create_bills_png(bills_chunk, image_filename, image_num=image_num, total_images=num_images)

            if image_path:
                image_paths.append(image_path)
                LOG.info(f"Image {image_num}/{num_images}: {len(bills_chunk)} bills")
            else:
                LOG.error(f"Failed to create image {image_num}/{num_images}")

        LOG.info(f"Successfully created {len(image_paths)} PNG image(s)")
        return image_paths

    def archive_images(self, image_paths: list) -> bool:
        """
        Move PNG images to archive folder with today's date.
        Creates a dated subfolder if it doesn't exist.

        Args:
            image_paths: List of image file paths to archive

        Returns:
            True if all images were archived successfully, False otherwise
        """
        if not image_paths:
            LOG.info("No images to archive")
            return True

        try:
            # Create archive directory path with today's date
            archive_base = os.path.join(os.path.dirname(__file__), "..", "archive")
            today_date = datetime.now().strftime("%Y-%m-%d")
            archive_dir = os.path.join(archive_base, today_date)

            # Create archive directory if it doesn't exist
            os.makedirs(archive_dir, exist_ok=True)
            LOG.info(f"📁 Archive directory ready: {archive_dir}")

            archived_count = 0
            for image_path in image_paths:
                try:
                    if not os.path.exists(image_path):
                        LOG.warning(f"Image file not found for archiving: {image_path}")
                        continue

                    # Get filename from path
                    filename = os.path.basename(image_path)
                    archive_path = os.path.join(archive_dir, filename)

                    # Move file to archive
                    import shutil
                    shutil.move(image_path, archive_path)
                    archived_count += 1
                    LOG.info(f"✅ Archived: {filename} → {archive_dir}")

                except Exception as e:
                    LOG.error(f"Failed to archive image {image_path}: {e}")
                    continue

            if archived_count > 0:
                LOG.info(f"📦 Successfully archived {archived_count} out of {len(image_paths)} images to {archive_dir}")
                return True
            else:
                LOG.warning("Failed to archive any images")
                return False

        except Exception as e:
            LOG.error(f"Failed to create archive directory: {e}")
            return False