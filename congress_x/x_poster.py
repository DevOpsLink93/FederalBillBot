# Federal Bill X Poster
# Processes bills by recording them to .txt file and storing in database

import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional

# Import database functions
try:
    from ..sqlite.new_Legislation_log import log_bill_from_data, bill_exists, init_db_connection
except ImportError:
    from pathlib import Path
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from sqlite.new_Legislation_log import log_bill_from_data, bill_exists, init_db_connection

LOG = logging.getLogger("x_poster")

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


class XPoster:
    def __init__(self, output_file: str = "federal_bills.txt"):
        """
        Initialize XPoster with output file path.

        Args:
            output_file: Path to the .txt file for recording bills
        """
        self.output_file = output_file
        LOG.info(f"XPoster initialized with output file: {output_file}")

    def format_bill_text(self, bill_data: Dict[str, Any], include_url: bool = True) -> str:
        """
        Format bill data as [Bill_Number](URL) - Title of Bill or Bill_Number - Title of Bill.
        No truncation - full bill text for post creation.

        Args:
            bill_data: Bill data dictionary
            include_url: Whether to include the URL in the formatted text

        Returns:
            Formatted bill text
        """
        bill_number = bill_data.get('formatted_bill_number', '')
        title = bill_data.get('title', '')
        url = bill_data.get('url', '')

        # Create the basic format with or without URL
        if include_url and url and url != 'Unknown':
            bill_text = f"[{bill_number}]({url}) - {title}"
        else:
            bill_text = f"{bill_number} - {title}"

        return bill_text

    def append_to_txt_file(self, bill_text: str, add_new_post_indicator: bool = False) -> None:
        """
        Append formatted bill text to the .txt file.

        Args:
            bill_text: Formatted bill text to append
            add_new_post_indicator: Whether to add "new post" indicator
        """
        try:
            if add_new_post_indicator:
                bill_text = f"new post\n{bill_text}"

            with open(self.output_file, 'a', encoding='utf-8') as f:
                f.write(bill_text + '\n')
            LOG.info(f"Successfully appended bill to {self.output_file}")
        except Exception as e:
            LOG.error(f"Failed to write to {self.output_file}: {e}")
            raise

    def store_in_database(self, bill_data: Dict[str, Any]) -> bool:
        """
        Store bill data in the database using new_Legislation_log.py
        First checks if bill already exists to prevent duplicates.

        Args:
            bill_data: Bill data dictionary
            
        Returns:
            True if bill was stored, False if it already existed
        """
        try:
            # Extract bill info
            bill_number = bill_data.get('bill_number', '')
            bill_type = bill_data.get('bill_type', '')
            congress = bill_data.get('congress', '')
            formatted_number = bill_data.get('formatted_bill_number', f"{bill_type}.{bill_number}")
            
            # Check if bill already exists in database
            try:
                conn = init_db_connection()
                if bill_exists(conn, congress, bill_number, bill_type):
                    LOG.warning(f"⚠️  Bill {formatted_number} already exists in database - skipping to prevent duplicate posting")
                    conn.close()
                    return False
                conn.close()
            except Exception as e:
                LOG.error(f"❌ Database validation check failed for {formatted_number}: {e}")
                raise
            
            # Prepare data for database logging
            db_data = {
                'bill_number': bill_number,
                'bill_type': bill_type,
                'congress': congress,
                'title': bill_data.get('title', 'Unknown'),
                'summary': bill_data.get('summary', 'Unknown'),
                'sponsor': bill_data.get('sponsor', 'Unknown'),
                'introduced_date': bill_data.get('introduced_date', 'Unknown'),
                'status': 'Introduced',
                'url': bill_data.get('url', 'Unknown')
            }

            log_bill_from_data(db_data)
            LOG.info(f"✅ Successfully stored bill {formatted_number} in database")
            return True

        except Exception as e:
            LOG.error(f"Failed to store bill in database: {e}")
            raise

    def create_bills_png(self, bills_data: list, output_path: str = "federal_bills_summary.png") -> str:
        """
        Create a PNG image summarizing bills with formatted text.

        Args:
            bills_data: List of bill data dictionaries (for this image chunk)
            output_path: Path to save the PNG file

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
                return False

        try:
            # Image settings
            width = 1200
            padding = 40
            line_height = 25
            title_font_size = 24
            bill_font_size = 16
            header_spacing = 60

            # Create title
            est_tz = timezone(timedelta(hours=-5))  # EST is UTC-5
            est_time = datetime.now(est_tz)
            title = f"@FedBillAlert Summary - {est_time.strftime('%Y-%m-%d %I:%M %p EST')}"

            # Format all bills
            formatted_bills = []
            for bill_data in bills_data:
                formatted_text = self.format_bill_text(bill_data, include_url=False)
                formatted_bills.append(formatted_text)

            # Pre-calculate actual height needed by simulating text wrapping
            # This ensures we create an image tall enough for all content
            try:
                title_font = ImageFont.truetype("arial.ttf", title_font_size)
                bill_font = ImageFont.truetype("arial.ttf", bill_font_size)
            except OSError:
                title_font = ImageFont.load_default()
                bill_font = ImageFont.load_default()

            # Calculate height for each bill considering text wrapping
            max_line_width = width - (padding * 2)
            total_bill_height = 0
            
            for bill_text in formatted_bills:
                # Simulate text wrapping to count lines
                words = bill_text.split()
                lines = []
                current_line = ""

                for word in words:
                    test_line = current_line + " " + word if current_line else word
                    bbox = ImageDraw.Draw(Image.new('RGB', (1, 1), color='white')).textbbox((0, 0), test_line, font=bill_font)
                    line_width = bbox[2] - bbox[0]

                    if line_width <= max_line_width:
                        current_line = test_line
                    else:
                        if current_line:
                            lines.append(current_line)
                        current_line = word

                if current_line:
                    lines.append(current_line)

                # Add height for this bill's lines plus separator
                total_bill_height += len(lines) * line_height + line_height  # +line_height for separator

            # Calculate image height based on actual wrapped content
            title_height = header_spacing
            extra_bottom_padding = line_height * 2
            total_height = title_height + total_bill_height + (padding * 2) + extra_bottom_padding

            # Create image
            image = Image.new('RGB', (width, total_height), color='white')
            draw = ImageDraw.Draw(image)

            # Draw title
            title_bbox = draw.textbbox((0, 0), title, font=title_font)
            title_width = title_bbox[2] - title_bbox[0]
            title_x = (width - title_width) // 2
            draw.text((title_x, padding), title, fill='black', font=title_font)

            # Draw bills
            y_position = padding + header_spacing
            for i, bill_text in enumerate(formatted_bills):
                # Handle long lines by wrapping them
                max_line_width = width - (padding * 2)
                words = bill_text.split()
                lines = []
                current_line = ""

                for word in words:
                    test_line = current_line + " " + word if current_line else word
                    bbox = draw.textbbox((0, 0), test_line, font=bill_font)
                    line_width = bbox[2] - bbox[0]

                    if line_width <= max_line_width:
                        current_line = test_line
                    else:
                        if current_line:
                            lines.append(current_line)
                        current_line = word

                if current_line:
                    lines.append(current_line)

                # Draw each line centered
                for line in lines:
                    bbox = draw.textbbox((0, 0), line, font=bill_font)
                    line_width = bbox[2] - bbox[0]
                    line_x = (width - line_width) // 2
                    draw.text((line_x, y_position), line, fill='black', font=bill_font)
                    y_position += line_height

                # Add horizontal separator line after each bill (except the last one)
                if i < len(formatted_bills) - 1:
                    y_position += line_height // 2  # Add some space before the line
                    # Draw horizontal line across most of the width
                    line_start_x = padding
                    line_end_x = width - padding
                    draw.line((line_start_x, y_position, line_end_x, y_position), fill='black', width=1)
                    y_position += line_height // 2  # Add space after the line

            # Save image
            image.save(output_path, "PNG")
            file_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0
            LOG.info(f"Successfully created PNG image at: {os.path.abspath(output_path)} ({file_size} bytes)")
            return output_path

        except Exception as e:
            LOG.error(f"Failed to create PNG image: {e}")
            return ""

    def create_multiple_bills_pngs(self, bills_data: list, base_filename: str = "federal_bills_summary.png") -> tuple[list, list]:
        """
        Create multiple PNG images from bills data with threading support.
        Main thread: up to 4 images with max 15 bills per image (60 bills max).
        If more bills exist, create a reply thread with up to 4 more images.
        Final image in reply thread aggregates all remaining bills.
        Deduplicates bills before processing to prevent duplicates in images.

        Args:
            bills_data: List of all bill data dictionaries
            base_filename: Base filename for PNG images (will add _1, _2, etc.)

        Returns:
            Tuple of (main_thread_images, reply_thread_images) lists
        """
        if not bills_data:
            LOG.info("No bills to create images for")
            return [], []
        
        # Deduplicate bills by formatted_bill_number to prevent duplicates in images
        seen_bills = {}
        deduplicated_bills = []
        for bill in bills_data:
            bill_id = bill.get('formatted_bill_number', '')
            if bill_id and bill_id not in seen_bills:
                seen_bills[bill_id] = True
                deduplicated_bills.append(bill)
            elif not bill_id:
                # If no formatted_bill_number, include it (shouldn't happen but be safe)
                deduplicated_bills.append(bill)
        
        if len(deduplicated_bills) < len(bills_data):
            LOG.warning(f"Deduplicated bills: {len(bills_data)} -> {len(deduplicated_bills)} (removed {len(bills_data) - len(deduplicated_bills)} duplicates)")
        
        bills_data = deduplicated_bills

        main_thread_images = []
        reply_thread_images = []
        total_bills = len(bills_data)
        max_images_per_thread = 4
        bills_per_image = 15
        max_bills_main_thread = max_images_per_thread * bills_per_image  # 60 bills

        # Split bills into main thread and reply thread
        main_bills = bills_data[:max_bills_main_thread]
        reply_bills = bills_data[max_bills_main_thread:]

        # Create main thread images
        LOG.info(f"Creating main thread: {len(main_bills)} bills")
        main_thread_images = self._create_image_set(main_bills, base_filename, is_reply=False)

        # Create reply thread images if there are remaining bills
        if reply_bills:
            LOG.info(f"Creating reply thread: {len(reply_bills)} bills (exceeds 60 bill main thread limit)")
            # Create alternate filename for reply thread
            name_parts = base_filename.rsplit('.', 1)
            reply_filename = f"{name_parts[0]}_reply.{name_parts[1]}" if len(name_parts) > 1 else f"{base_filename}_reply"
            reply_thread_images = self._create_image_set(reply_bills, reply_filename, is_reply=True)

        total_images = len(main_thread_images) + len(reply_thread_images)
        LOG.info(f"Successfully created {total_images} PNG image(s) - Main thread: {len(main_thread_images)}, Reply thread: {len(reply_thread_images)}")
        return main_thread_images, reply_thread_images

    def _create_image_set(self, bills_data: list, base_filename: str, is_reply: bool = False) -> list:
        """
        Helper method to create a set of images (either main thread or reply thread).
        Creates up to 4 images with 15 bills each, final image aggregates remaining bills.

        Args:
            bills_data: List of bill data dictionaries for this image set
            base_filename: Base filename for PNG images
            is_reply: Whether this is a reply thread (affects logging)

        Returns:
            List of created image file paths
        """
        image_paths = []
        total_bills = len(bills_data)
        max_images = 4
        bills_per_image = 15

        if total_bills == 0:
            return image_paths

        # Calculate how many images are needed for this set
        if total_bills <= bills_per_image:
            num_images = 1
        else:
            # Calculate images needed: up to 4, with 15 bills each except the last
            num_images = min((total_bills + bills_per_image - 1) // bills_per_image, max_images)

        thread_type = "reply" if is_reply else "main"
        LOG.info(f"Creating {num_images} PNG image(s) in {thread_type} thread from {total_bills} bills")

        # Create images
        for image_num in range(1, num_images + 1):
            # Calculate start and end indices
            start_idx = (image_num - 1) * bills_per_image
            
            # For the last image, include all remaining bills
            if image_num == num_images:
                end_idx = total_bills
            else:
                end_idx = min(start_idx + bills_per_image, total_bills)

            # Get bills for this image
            bills_chunk = bills_data[start_idx:end_idx]

            if not bills_chunk:
                break

            # Create filename for this image
            if num_images == 1:
                image_filename = base_filename
            else:
                # Insert image number before file extension
                name_parts = base_filename.rsplit('.', 1)
                image_filename = f"{name_parts[0]}_part{image_num}.{name_parts[1]}" if len(name_parts) > 1 else f"{base_filename}_part{image_num}"

            # Create the PNG image
            image_path = self.create_bills_png(bills_chunk, image_filename)
            
            if image_path:
                image_paths.append(image_path)
                final_indicator = " (final - aggregated)" if (image_num == num_images and len(bills_chunk) > bills_per_image) else ""
                LOG.info(f"{thread_type.upper()} Image {image_num}/{num_images}: {len(bills_chunk)} bills{final_indicator}")
            else:
                LOG.error(f"Failed to create {thread_type} image {image_num}/{num_images}")

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

    def process_bills_into_posts(self, bills_data: list) -> int:
        """
        Process multiple bills by grouping them into posts of <= 280 characters each.
        Each post contains multiple bills separated by newlines.

        Args:
            bills_data: List of bill data dictionaries

        Returns:
            Number of bills processed
        """
        try:
            LOG.info(f"Processing {len(bills_data)} bills into posts")

            # Format all bills
            formatted_bills = []
            for bill_data in bills_data:
                formatted_text = self.format_bill_text(bill_data)
                formatted_bills.append((bill_data, formatted_text))

            # Group bills into posts
            posts = []
            current_post_bills = []

            for bill_data, bill_text in formatted_bills:
                bill_length = len(bill_text)

                # If this bill alone is > 280 characters, it becomes its own post
                if bill_length > 280:
                    # Save current post first if it exists
                    if current_post_bills:
                        post_text = "\n".join([text for _, text in current_post_bills])
                        posts.append(("content", post_text))
                        current_post_bills = []

                    # This bill becomes its own post (will be truncated to 280 chars when written)
                    posts.append(("new_post", bill_text[:280]))

                # Check if adding this bill to current post would exceed 280 characters
                elif current_post_bills:
                    # Calculate current post length with new bill added
                    current_post_text = "\n".join([text for _, text in current_post_bills] + [bill_text])
                    if len(current_post_text) > 280:
                        # Save current post and start new one
                        post_text = "\n".join([text for _, text in current_post_bills])
                        posts.append(("content", post_text))
                        # Start new post with current bill
                        current_post_bills = [(bill_data, bill_text)]
                    else:
                        # Add to current post
                        current_post_bills.append((bill_data, bill_text))
                else:
                    # Start new post with this bill
                    current_post_bills = [(bill_data, bill_text)]

            # Add final post if it has content
            if current_post_bills:
                post_text = "\n".join([text for _, text in current_post_bills])
                posts.append(("content", post_text))

            # Write all posts to .txt file with "new post" indicators
            for i, (post_type, post_text) in enumerate(posts):
                if i > 0:  # Add "new post" indicator for posts after the first one
                    self.append_to_txt_file(f"new post\n{post_text}")
                else:
                    self.append_to_txt_file(post_text)

            # Store all bills in database
            for bill_data, _ in formatted_bills:
                try:
                    was_stored = self.store_in_database(bill_data)
                    if not was_stored:
                        LOG.debug(f"Bill {bill_data.get('formatted_bill_number')} already existed in database")
                except Exception as e:
                    LOG.error(f"Failed to store bill {bill_data.get('formatted_bill_number', 'Unknown')} in database: {e}")

            LOG.info(f"Successfully created {len(posts)} posts from {len(bills_data)} bills")
            return len(bills_data)

        except Exception as e:
            LOG.error(f"Failed to process bills into posts: {e}")
            return 0

    def process_bill(self, bill_data: Dict[str, Any]) -> bool:
        """
        Process a bill by recording it to .txt file and storing in database.

        Args:
            bill_data: Bill data dictionary

        Returns:
            True if successful, False otherwise
        """
        try:
            LOG.info(f"Processing bill: {bill_data.get('formatted_bill_number', 'Unknown')}")

            # Format the bill text
            bill_text = self.format_bill_text(bill_data)

            # Record to .txt file first
            self.append_to_txt_file(bill_text)

            # Then store in database
            self.store_in_database(bill_data)

            LOG.info(f"Successfully processed bill: {bill_data.get('formatted_bill_number', 'Unknown')}")
            return True

        except Exception as e:
            LOG.error(f"Failed to process bill {bill_data.get('formatted_bill_number', 'Unknown')}: {e}")
            return False

    def post_posts_to_x(self, posts: list, image_paths: list = None, total_bills: int = 0, reply_to_tweet_id: str = None) -> tuple[int, str]:
        """
        Post multiple posts to X.com using the same format as the .txt file.
        Supports both standalone posts and replies to existing tweets.
        Distributes images across posts in round-robin fashion (up to 4 images max).

        Args:
            posts: List of post text strings (same format as written to .txt file)
            image_paths: Optional list of image file paths to attach to posts
            total_bills: Total number of bills discovered (for tweet text)
            reply_to_tweet_id: Optional tweet ID to reply to (creates reply thread)

        Returns:
            Tuple of (number of posts successfully posted, tweet_id of first/main post)
        """
        # Handle backward compatibility - convert single string to list
        if isinstance(image_paths, str):
            image_paths = [image_paths] if image_paths else []
        elif image_paths is None:
            image_paths = []
        
        # Limit to maximum 4 images per posting cycle
        image_paths = image_paths[:4]
        try:
            # Import X API client and API
            from ..api.x_api_call import get_x_api_client, get_x_api
        except ImportError:
            # Fallback for when relative imports don't work
            from pathlib import Path
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
            from api.x_api_call import get_x_api_client, get_x_api

        try:
            client = get_x_api_client()
            api = get_x_api()

            # Upload all images and store their media IDs
            media_ids_by_image = {}  # Map image path to media ID
            
            for image_path in image_paths:
                if not image_path or not os.path.exists(image_path):
                    LOG.warning(f"Image path does not exist or is invalid: {image_path}")
                    continue
                    
                try:
                    LOG.info(f"Uploading image to X: {os.path.abspath(image_path)}")
                    # Check file accessibility and size (Twitter limit is 5MB for images)
                    file_size = os.path.getsize(image_path)
                    if file_size > 5 * 1024 * 1024:  # 5MB
                        LOG.error(f"Image file too large: {file_size} bytes (max 5MB)")
                        continue
                    elif file_size == 0:
                        LOG.error(f"Image file is empty: {image_path}")
                        continue
                    else:
                        # Verify file is readable
                        try:
                            with open(image_path, 'rb') as f:
                                f.read(1)  # Try to read first byte
                        except Exception as read_e:
                            LOG.error(f"Image file not readable: {read_e}")
                            continue

                        media = api.media_upload(image_path)
                        if hasattr(media, 'media_id') and media.media_id:
                            media_ids_by_image[image_path] = media.media_id
                            LOG.info(f"Image uploaded successfully, media ID: {media.media_id}")
                        else:
                            LOG.error(f"Media upload failed - no media_id returned from upload. Media object: {media}")
                except Exception as e:
                    LOG.error(f"Failed to upload image {image_path}: {e}")
                    LOG.error(f"Exception type: {type(e).__name__}")
                    continue

            posted_count = 0
            first_tweet_id = None

            for post_idx, post_text in enumerate(posts):
                try:
                    # Clean the post text (remove any "new post" indicators and extra whitespace)
                    clean_text = post_text.strip()
                    if clean_text.startswith("new post"):
                        clean_text = clean_text[9:].strip()  # Remove "new post\n" prefix

                    # Generate timestamp in EST
                    from datetime import datetime, timezone, timedelta
                    est_tz = timezone(timedelta(hours=-5))  # EST is UTC-5
                    est_time = datetime.now(est_tz)
                    date_str = est_time.strftime('%Y-%m-%d')
                    time_str = est_time.strftime('%I:%M %p')

                    # Create the tweet text with bill count
                    bill_count_text = f" - {total_bills} bills discovered" if total_bills > 0 else ""
                    tweet_text = f"Introduced Legislation Detected {date_str} - {time_str}. Total Count {bill_count_text}. For full details please go to www.congress.gov."

                    # Final check that we're within limits
                    if len(tweet_text) > 280:
                        tweet_text = tweet_text[:277] + "..."

                    reply_indicator = " (reply)" if reply_to_tweet_id else ""
                    LOG.info(f"Posting to X{reply_indicator}: {tweet_text[:100]}...")

                    # Distribute images in round-robin fashion across posts
                    media_ids = []
                    if media_ids_by_image and post_idx < len(media_ids_by_image):
                        # Get the image for this post in round-robin fashion
                        image_idx = post_idx % len(media_ids_by_image)
                        image_path_for_post = list(media_ids_by_image.keys())[image_idx]
                        media_id = media_ids_by_image[image_path_for_post]
                        media_ids = [media_id]

                    # Post to X with optional media
                    if media_ids and len(media_ids) > 0:
                        LOG.info(f"Creating tweet with {len(media_ids)} media attachment(s): {media_ids}")
                        if reply_to_tweet_id:
                            response = client.create_tweet(text=tweet_text, media_ids=media_ids, reply_settings="everyone", in_reply_to_tweet_id=reply_to_tweet_id)
                        else:
                            response = client.create_tweet(text=tweet_text, media_ids=media_ids)
                        LOG.info("Posted to X with image attachment")
                    else:
                        LOG.info("Creating tweet without media attachment")
                        if reply_to_tweet_id:
                            response = client.create_tweet(text=tweet_text, reply_settings="everyone", in_reply_to_tweet_id=reply_to_tweet_id)
                        else:
                            response = client.create_tweet(text=tweet_text)
                    
                    tweet_id = getattr(response, "data", {}).get("id") if hasattr(response, "data") else None

                    if tweet_id:
                        LOG.info(f"Successfully posted to X.com, Tweet ID: {tweet_id}")
                        if first_tweet_id is None:
                            first_tweet_id = tweet_id
                        posted_count += 1

                        # Rate limiting: wait between posts
                        import time
                        LOG.info("Rate limiting: waiting 30 seconds before next post...")
                        time.sleep(30)  # Wait 30 seconds between posts to prevent hang
                    else:
                        LOG.warning("Posted to X.com but no Tweet ID returned")

                except Exception as e:
                    LOG.error(f"Failed to post individual post to X.com: {e}")
                    # Continue with next post instead of failing completely
                    continue

            LOG.info(f"Successfully posted {posted_count} out of {len(posts)} posts to X.com")
            return posted_count if posted_count > 0 else 0, first_tweet_id

        except ImportError:
            LOG.warning("X API client not available - check api/x_api_call.py and credentials")
            return 0, None
        except Exception as e:
            LOG.error(f"Failed to initialize X posting: {e}")
            return 0, None

    def process_bills_into_posts(self, bills_data: list, post_to_x: bool = False, create_png: bool = False, png_filename: str = "federal_bills_summary.png") -> tuple[int, bool]:
        """
        Process multiple bills and create ONE tweet with all bills and images attached.
        Supports threaded posting: main thread (up to 4 images, 60 bills max) + optional reply thread.
        Deduplicates bills before processing to prevent duplicate entries in images and posts.

        Args:
            bills_data: List of bill data dictionaries
            post_to_x: Whether to post to X.com
            create_png: Whether to create PNG image with all bills
            png_filename: Filename for PNG image (default: federal_bills_summary.png)

        Returns:
            Tuple of (number of bills processed, whether X posting was successful)
        """
        try:
            # Deduplicate bills by formatted_bill_number to prevent duplicates in posts and images
            seen_bills = {}
            deduplicated_bills = []
            for bill in bills_data:
                bill_id = bill.get('formatted_bill_number', '')
                if bill_id and bill_id not in seen_bills:
                    seen_bills[bill_id] = True
                    deduplicated_bills.append(bill)
                elif not bill_id:
                    # If no formatted_bill_number, include it (shouldn't happen but be safe)
                    deduplicated_bills.append(bill)
            
            if len(deduplicated_bills) < len(bills_data):
                LOG.warning(f"Deduplicated bills: {len(bills_data)} -> {len(deduplicated_bills)} (removed {len(bills_data) - len(deduplicated_bills)} duplicates)")
            
            bills_data = deduplicated_bills
            
            LOG.info(f"Processing {len(bills_data)} bills - posting as ONE tweet with images (threading support enabled)")

            # Format all bills
            formatted_bills = []
            for bill_data in bills_data:
                formatted_text = self.format_bill_text(bill_data)
                formatted_bills.append((bill_data, formatted_text))

            # Create single post text with all bills
            post_text = "\n".join([bill_text for _, bill_text in formatted_bills])
            
            # Write to .txt file
            self.append_to_txt_file(post_text, add_new_post_indicator=False)

            # Create PNG images if requested (with threading support)
            main_thread_images = []
            reply_thread_images = []
            if create_png and bills_data:
                LOG.info("Creating PNG image(s) with bills (threading-aware)...")
                main_thread_images, reply_thread_images = self.create_multiple_bills_pngs(bills_data, png_filename)
                
                total_images = len(main_thread_images) + len(reply_thread_images)
                if total_images > 0:
                    LOG.info(f"Successfully created {total_images} PNG image(s) - Main: {len(main_thread_images)}, Reply: {len(reply_thread_images)}")
                else:
                    LOG.error("Failed to create PNG images")

            # Post to X.com with threading support
            posted_count = 0
            posting_successful = False
            if post_to_x:
                try:
                    from ..api.x_api_call import get_x_api_client, get_x_api
                except ImportError:
                    from pathlib import Path
                    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
                    from api.x_api_call import get_x_api_client, get_x_api

                try:
                    client = get_x_api_client()  # v2 API Client for posting
                    api = get_x_api()  # v1.1 API for media uploads (has limited access)
                    
                    # Post main thread
                    if main_thread_images:
                        # Upload main thread images and collect media IDs using v1.1 API
                        media_ids = []
                        for image_path in main_thread_images:
                            try:
                                LOG.info(f"Uploading main thread image: {image_path}")
                                media = api.media_upload(image_path)
                                media_ids.append(str(media.media_id))  # Convert to string for v2 API
                                LOG.info(f"✅ Uploaded main thread image - Media ID: {media.media_id}")
                            except Exception as e:
                                LOG.warning(f"Failed to upload image {image_path}: {e}")
                        
                        # Post main thread tweet
                        try:
                            # Generate timestamp in EST
                            est_tz = timezone(timedelta(hours=-5))  # EST is UTC-5
                            est_time = datetime.now(est_tz)
                            date_str = est_time.strftime('%Y-%m-%d')
                            time_str = est_time.strftime('%I:%M %p')
                            
                            # Create proper tweet text summary
                            bill_count = len(bills_data)
                            tweet_text = f"Introduced Legislation Detected {date_str} - {time_str}. {bill_count} bills discovered. See images for details or visit congress.gov."
                            
                            # Ensure tweet is within 280 character limit
                            if len(tweet_text) > 280:
                                tweet_text = tweet_text[:277] + "..."
                            
                            if media_ids:
                                # Create tweet with media IDs using v2 API
                                response = client.create_tweet(text=tweet_text, media_ids=media_ids)
                                main_tweet_id = response.data['id']
                                LOG.info(f"✅ Posted main thread with {len(media_ids)} images to X.com - Tweet ID: {main_tweet_id}")
                                posted_count += 1
                                posting_successful = True
                            else:
                                # Create tweet without media using v2 API
                                response = client.create_tweet(text=tweet_text)
                                main_tweet_id = response.data['id']
                                LOG.info(f"✅ Posted main thread (no images) to X.com - Tweet ID: {main_tweet_id}")
                                posted_count += 1
                                posting_successful = True
                            
                            # Post reply thread if it exists
                            if reply_thread_images:
                                LOG.info(f"🔗 Starting reply thread with {len(reply_thread_images)} images")
                                import time
                                time.sleep(2)  # Brief delay before reply
                                
                                # Upload reply thread images
                                reply_media_ids = []
                                for image_path in reply_thread_images:
                                    try:
                                        LOG.info(f"Uploading reply thread image: {image_path}")
                                        media = api.media_upload(image_path)
                                        reply_media_ids.append(str(media.media_id))
                                        LOG.info(f"✅ Uploaded reply thread image - Media ID: {media.media_id}")
                                    except Exception as e:
                                        LOG.warning(f"Failed to upload reply image {image_path}: {e}")
                                
                                # Post reply tweets
                                if reply_media_ids:
                                    reply_tweet_text = f"Continued thread with additional bills from this session."
                                    if len(reply_tweet_text) > 280:
                                        reply_tweet_text = reply_tweet_text[:277] + "..."
                                    
                                    response = client.create_tweet(text=reply_tweet_text, media_ids=reply_media_ids, in_reply_to_tweet_id=main_tweet_id)
                                    reply_tweet_id = response.data['id']
                                    LOG.info(f"✅ Posted reply thread with {len(reply_media_ids)} images - Tweet ID: {reply_tweet_id}")
                                    posted_count += 1
                        except Exception as e:
                            LOG.error(f"Failed to post main thread tweet: {e}")
                            posting_successful = False
                    else:
                        # No images, post text only
                        try:
                            est_tz = timezone(timedelta(hours=-5))
                            est_time = datetime.now(est_tz)
                            date_str = est_time.strftime('%Y-%m-%d')
                            time_str = est_time.strftime('%I:%M %p')
                            
                            bill_count = len(bills_data)
                            tweet_text = f"Introduced Legislation Detected {date_str} - {time_str}. {bill_count} bills discovered. Visit congress.gov for details."
                            
                            if len(tweet_text) > 280:
                                tweet_text = tweet_text[:277] + "..."
                            
                            response = client.create_tweet(text=tweet_text)
                            main_tweet_id = response.data['id']
                            LOG.info(f"✅ Posted tweet (no images) to X.com - Tweet ID: {main_tweet_id}")
                            posted_count += 1
                            posting_successful = True
                        except Exception as e:
                            LOG.error(f"Failed to post text-only tweet: {e}")
                            posting_successful = False
                        
                except Exception as e:
                    LOG.error(f"Failed to initialize X API client: {e}")
                    posting_successful = False
            else:
                LOG.info("X posting disabled - bills written to .txt file only")
                posting_successful = False

            # Store all bills in database
            LOG.info("Saving bills to database...")
            bills_saved = 0
            for bill_data, _ in formatted_bills:
                try:
                    was_stored = self.store_in_database(bill_data)
                    if was_stored:
                        bills_saved += 1
                except Exception as e:
                    LOG.error(f"Failed to store bill {bill_data.get('formatted_bill_number', 'Unknown')} in database: {e}")

            LOG.info(f"Successfully saved {bills_saved} out of {len(formatted_bills)} bills to database")

            # Archive images after successful X posting
            if posting_successful:
                all_images = main_thread_images + reply_thread_images
                if all_images:
                    LOG.info("🔄 Archiving images after successful X posting...")
                    archive_success = self.archive_images(all_images)
                    if archive_success:
                        LOG.info("✅ Images successfully archived")
                    else:
                        LOG.warning("⚠️  Some images may not have been archived")
            elif (main_thread_images or reply_thread_images) and not post_to_x:
                LOG.info("Images not archived (X posting disabled)")
            
            total_images = len(main_thread_images) + len(reply_thread_images)
            LOG.info(f"Processing complete - {len(bills_data)} bills, {total_images} images (main: {len(main_thread_images)}, reply: {len(reply_thread_images)}). X posting success: {posting_successful}")
            return len(bills_data), posting_successful

        except Exception as e:
            LOG.error(f"Failed to process bills into posts: {e}")
            return 0, False