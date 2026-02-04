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

# Import image generator
try:
    from .x_image_generator import XImageGenerator
except ImportError:
    from x_image_generator import XImageGenerator

LOG = logging.getLogger("x_poster")


class XPoster:
    def __init__(self, output_file: str = "federal_bills.txt"):
        """
        Initialize XPoster with output file path.

        Args:
            output_file: Path to the .txt file for recording bills
        """
        self.output_file = output_file
        self.image_generator = XImageGenerator()
        LOG.info(f"XPoster initialized with output file: {output_file}")

    def format_bill_text(self, bill_data: Dict[str, Any], include_url: bool = True) -> str:
        """
        Format bill data as [Bill] - [Title of Bill].
        For images, uses simple format without URL.

        Args:
            bill_data: Bill data dictionary
            include_url: Whether to include the URL in the formatted text

        Returns:
            Formatted bill text
        """
        bill_number = bill_data.get('formatted_bill_number', '')
        title = bill_data.get('title', '')
        url = bill_data.get('url', '')

        # Create the format: Bill - [Title of Bill]
        if include_url and url and url != 'Unknown':
            bill_text = f"{bill_number}({url}) - {title}"
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

    def process_bills_into_posts(self, bills_data: list, post_to_x: bool = False, create_png: bool = False, png_filename: str = "federal_bills_summary.png") -> tuple[int, bool]:
        """
        Process multiple bills and create ONE tweet with all bills and images attached.
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
                    deduplicated_bills.append(bill)

            if len(deduplicated_bills) < len(bills_data):
                LOG.warning(f"Deduplicated bills: {len(bills_data)} -> {len(deduplicated_bills)} (removed {len(bills_data) - len(deduplicated_bills)} duplicates)")

            bills_data = deduplicated_bills

            LOG.info(f"Processing {len(bills_data)} bills - posting as ONE tweet with images")

            # Format all bills
            formatted_bills = []
            for bill_data in bills_data:
                formatted_text = self.format_bill_text(bill_data)
                formatted_bills.append((bill_data, formatted_text))

            # Create single post text with all bills
            post_text = "\n".join([bill_text for _, bill_text in formatted_bills])

            # Write to .txt file
            self.append_to_txt_file(post_text, add_new_post_indicator=False)

            # Create PNG images if requested
            image_paths = []
            if create_png and bills_data:
                LOG.info("Creating PNG image(s) with bills...")
                image_paths = self.image_generator.create_multiple_bills_pngs(bills_data, png_filename)

                if image_paths:
                    LOG.info(f"Successfully created {len(image_paths)} PNG image(s)")
                else:
                    LOG.error("Failed to create PNG images")

            # Post to X.com as ONE tweet with all images
            posted_count = 0
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

                    # Upload all images and collect media IDs using v1.1 API
                    media_ids = []
                    for idx, image_path in enumerate(image_paths):
                        try:
                            LOG.info(f"Uploading image: {image_path}")
                            # Use Tweepy API v1.1 method for media uploads
                            media = api.media_upload(image_path)
                            # Add alt text for accessibility
                            alt_text = f"Bill summary image - Part {idx+1} of {len(image_paths)}"
                            try:
                                api.create_media_metadata(media_id=media.media_id, alt_text=alt_text)
                                LOG.info(f"✅ Uploaded image - Media ID: {media.media_id} with alt text")
                            except AttributeError:
                                LOG.warning(f"⚠️  Alt text method not available for media {media.media_id}, proceeding without alt text")
                                LOG.info(f"✅ Uploaded image - Media ID: {media.media_id}")
                            media_ids.append(str(media.media_id))  # Convert to string for v2 API
                        except Exception as e:
                            LOG.warning(f"Failed to upload image {image_path}: {e}")

                    # Post single tweet with all images using v2 API (has broader endpoint access)
                    try:
                        # Generate timestamp in EST
                        est_tz = timezone(timedelta(hours=-5))  # EST is UTC-5
                        est_time = datetime.now(est_tz)
                        date_str = est_time.strftime('%Y-%m-%d')
                        time_str = est_time.strftime('%I:%M %p')

                        # Create proper tweet text summary (NOT the raw bill list)
                        bill_count = len(bills_data)
                        tweet_text = f"🚨 NOTICE: Congress Unviels New Bills ({date_str}, {bill_count} identified)! View key details in the Attached Images or directly at https://www.congress.gov/bills-with-chamber-action/browse-by-date📄."

                        # Ensure tweet is within 280 character limit
                        if len(tweet_text) > 280:
                            tweet_text = tweet_text[:277] + "..."

                        if media_ids:
                            # X.com API has a maximum of 4 media items per tweet
                            limited_media_ids = media_ids[:4]
                            if len(media_ids) > 4:
                                LOG.warning(f"⚠️  X.com supports max 4 media per tweet, limiting {len(media_ids)} images to 4")
                            # Create tweet with media IDs using v2 API (broader access)
                            response = client.create_tweet(text=tweet_text, media_ids=limited_media_ids)
                            tweet_id = response.data['id']
                            LOG.info(f"✅ Posted tweet with {len(limited_media_ids)} images to X.com - Tweet ID: {tweet_id}")
                            posted_count = 1
                        else:
                            # Create tweet without media using v2 API
                            response = client.create_tweet(text=tweet_text)
                            tweet_id = response.data['id']
                            LOG.info(f"✅ Posted tweet (no images) to X.com - Tweet ID: {tweet_id}")
                            posted_count = 1

                    except Exception as e:
                        LOG.error(f"Failed to post tweet: {e}")
                        posted_count = 0

                except Exception as e:
                    LOG.error(f"Failed to initialize X API client: {e}")
                    posted_count = 0
            else:
                LOG.info("X posting disabled - bills written to .txt file only")
                posted_count = 0

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

            # Return result tuple
            posting_successful = posted_count > 0 if post_to_x else False

            # Archive images after successful X posting
            if posting_successful and image_paths:
                LOG.info("🔄 Archiving images after successful X posting...")
                archive_success = self.image_generator.archive_images(image_paths)
                if archive_success:
                    LOG.info("✅ Images successfully archived")
                else:
                    LOG.warning("⚠️  Some images may not have been archived")
            elif image_paths and not post_to_x:
                LOG.info("Images not archived (X posting disabled)")

            LOG.info(f"Processing complete - {len(bills_data)} bills in ONE tweet, {len(image_paths)} images. X posting success: {posting_successful}")
            return len(bills_data), posting_successful

        except Exception as e:
            LOG.error(f"Failed to process bills into posts: {e}")
            return 0, False

    def post_all_images_sequentially(self, bills_data: list, create_png: bool = True, png_filename: str = "federal_bills_summary.png") -> tuple[int, int]:
        """
        Create multiple PNG images (8 bills per image) and post images to X.com in groups of 4 per tweet.
        X.com supports up to 4 media items per tweet, so images are grouped accordingly.
        Continues posting until all bills have been posted with images.

        Args:
            bills_data: List of bill data dictionaries
            create_png: Whether to create PNG images (default: True)
            png_filename: Base filename for PNG images

        Returns:
            Tuple of (total bills processed, total tweets posted successfully)
        """
        try:
            # Deduplicate bills by formatted_bill_number to prevent duplicates
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
            total_bills = len(bills_data)
            
            if total_bills == 0:
                LOG.warning("No bills to process")
                return 0, 0

            LOG.info(f"Starting sequential posting for {total_bills} bills (10 bills per image, up to 4 images per tweet)...")

            # Create PNG images
            image_paths = []
            if create_png:
                LOG.info("Creating PNG images with 10 bills per image...")
                image_paths = self.image_generator.create_multiple_bills_pngs(bills_data, png_filename)
                if not image_paths:
                    LOG.error("Failed to create PNG images")
                    return total_bills, 0
                LOG.info(f"Successfully created {len(image_paths)} PNG image(s)")
            else:
                LOG.warning("PNG creation disabled - no images to post")
                return total_bills, 0

            # Initialize X API
            try:
                from ..api.x_api_call import get_x_api_client, get_x_api
            except ImportError:
                from pathlib import Path
                import sys
                sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
                from api.x_api_call import get_x_api_client, get_x_api

            try:
                client = get_x_api_client()  # v2 API Client for posting
                api = get_x_api()  # v1.1 API for media uploads
            except Exception as e:
                LOG.error(f"Failed to initialize X API client: {e}")
                return total_bills, 0

            # Group images into chunks of 4 (X.com supports up to 4 media per tweet)
            max_images_per_tweet = 4
            tweets_posted = 0
            total_images = len(image_paths)
            main_tweet_id = None  # Track the first tweet for threading replies

            for tweet_idx in range(0, total_images, max_images_per_tweet):
                try:
                    image_chunk = image_paths[tweet_idx:tweet_idx + max_images_per_tweet]
                    chunk_num = (tweet_idx // max_images_per_tweet) + 1
                    total_chunks = (total_images + max_images_per_tweet - 1) // max_images_per_tweet

                    LOG.info(f"Processing tweet {chunk_num}/{total_chunks} with {len(image_chunk)} image(s)...")

                    # Upload all images in this chunk
                    media_ids = []
                    for image_idx, image_path in enumerate(image_chunk, 1):
                        try:
                            LOG.info(f"Uploading image {tweet_idx + image_idx}/{total_images}: {image_path}")
                            media = api.media_upload(image_path)
                            media_ids.append(str(media.media_id))
                            LOG.info(f"✅ Uploaded image - Media ID: {media.media_id}")
                        except Exception as e:
                            LOG.warning(f"Failed to upload image {image_path}: {e}")
                            continue

                    if not media_ids:
                        LOG.warning(f"No media IDs for tweet {chunk_num}, skipping...")
                        continue

                    # Generate timestamp in EST
                    est_tz = timezone(timedelta(hours=-5))  # EST is UTC-5
                    est_time = datetime.now(est_tz)
                    date_str = est_time.strftime('%Y-%m-%d')
                    time_str = est_time.strftime('%I:%M %p')

                    # Create tweet text for this batch of images
                    images_shown = sum(10 for _ in image_chunk)  # Approximate bills shown
                    if total_chunks > 1:
                        if chunk_num == 1:
                            tweet_text = f"Introduced Legislation - {date_str} {time_str} EST. Tweet {chunk_num} of {total_chunks}. See images for bill details or visit https://tinyurl.com/recentbills"
                        else:
                            tweet_text = f"📋 Continuation: Tweet {chunk_num} of {total_chunks}. See images for additional bill details or visit https://tinyurl.com/recentbills"
                    else:
                        tweet_text = f"Introduced Legislation - {date_str} {time_str} EST. {total_images} image(s) with bill details. Visit https://tinyurl.com/recentbills"

                    # Ensure tweet is within 280 character limit
                    if len(tweet_text) > 280:
                        tweet_text = tweet_text[:277] + "..."

                    # Post tweet with images
                    try:
                        # If this is not the first tweet and we have more than 1 chunk, reply to the main tweet
                        if chunk_num > 1 and main_tweet_id:
                            LOG.info(f"Posting tweet {chunk_num} as reply to main tweet {main_tweet_id}...")
                            response = client.create_tweet(
                                text=tweet_text, 
                                media_ids=media_ids,
                                in_reply_to_tweet_id=main_tweet_id,
                                reply_settings="mentionedUsers"
                            )
                        else:
                            # First tweet
                            response = client.create_tweet(text=tweet_text, media_ids=media_ids)
                            main_tweet_id = response.data['id']  # Store the ID for threading
                        
                        tweet_id = response.data['id']
                        LOG.info(f"✅ Posted tweet {chunk_num}/{total_chunks} with {len(media_ids)} image(s) to X.com - Tweet ID: {tweet_id}")
                        tweets_posted += 1
                    except Exception as e:
                        LOG.error(f"Failed to post tweet {chunk_num}: {e}")
                        continue

                except Exception as e:
                    LOG.error(f"Error processing tweet {chunk_num}: {e}")
                    continue

            # Store all bills in database
            LOG.info("Saving bills to database...")
            bills_saved = 0
            for bill_data in bills_data:
                try:
                    was_stored = self.store_in_database(bill_data)
                    if was_stored:
                        bills_saved += 1
                except Exception as e:
                    LOG.error(f"Failed to store bill {bill_data.get('formatted_bill_number', 'Unknown')} in database: {e}")

            LOG.info(f"Successfully saved {bills_saved} out of {total_bills} bills to database")

            # Archive images after successful posting
            if tweets_posted > 0 and image_paths:
                LOG.info("🔄 Archiving images after successful X posting...")
                archive_success = self.image_generator.archive_images(image_paths)
                if archive_success:
                    LOG.info("✅ Images successfully archived")
                else:
                    LOG.warning("⚠️  Some images may not have been archived")

            LOG.info(f"Sequential posting complete - {total_bills} bills, {total_images} images, {tweets_posted} tweets posted successfully")
            return total_bills, tweets_posted

        except Exception as e:
            LOG.error(f"Failed to post images sequentially: {e}")
            return 0, 0

    def post_bills_as_thread(self, house_bills: list, senate_bills: list, post_to_x: bool = False, create_png: bool = False, png_filename_base: str = "federal_bills") -> tuple[int, bool]:
        """
        Post House and Senate bills separately with independent threading.
        
        Posting logic:
        - Post House bills as separate tweet(s) with overflow images in threads
        - Post Senate bills as separate tweet(s) with overflow images in threads
        - Each chamber has its own main tweet and thread (if images > 4)
        - No cross-chamber threading
        
        Args:
            house_bills: List of House bill data dictionaries
            senate_bills: List of Senate bill data dictionaries
            post_to_x: Whether to post to X.com
            create_png: Whether to create PNG images
            png_filename_base: Base filename for PNG images
            
        Returns:
            Tuple of (total bills posted, whether posting was successful)
        """
        try:
            # Deduplicate both lists
            def deduplicate_bills(bills_list):
                seen_bills = {}
                deduplicated = []
                for bill in bills_list:
                    bill_id = bill.get('formatted_bill_number', '')
                    if bill_id and bill_id not in seen_bills:
                        seen_bills[bill_id] = True
                        deduplicated.append(bill)
                    elif not bill_id:
                        deduplicated.append(bill)
                return deduplicated
            
            house_bills = deduplicate_bills(house_bills)
            senate_bills = deduplicate_bills(senate_bills)
            
            total_bills = len(house_bills) + len(senate_bills)
            
            # Check if we have any bills at all
            if total_bills == 0:
                LOG.info("No bills to post (neither House nor Senate)")
                return 0, False
            
            LOG.info(f"📌 Separate posting: {len(house_bills)} House bills, {len(senate_bills)} Senate bills")
            
            # Initialize API for posting
            client = None
            api = None
            if post_to_x:
                try:
                    from ..api.x_api_call import get_x_api_client, get_x_api
                except ImportError:
                    from pathlib import Path
                    import sys
                    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
                    from api.x_api_call import get_x_api_client, get_x_api
                
                try:
                    client = get_x_api_client()
                    api = get_x_api()
                except Exception as e:
                    LOG.error(f"Failed to initialize X API: {e}")
                    return 0, False
            
            total_posted = 0
            overall_success = True
            
            # Process House bills if they exist
            if house_bills:
                LOG.info(f"📍 Processing {len(house_bills)} House bills...")
                # Insert chamber suffix before file extension
                name_parts = png_filename_base.rsplit('.', 1)
                house_filename = f"{name_parts[0]}-house.{name_parts[1]}" if len(name_parts) > 1 else f"{png_filename_base}-house"
                house_success = self._post_bills_chamber(
                    house_bills, "House", 
                    post_to_x, client, api, create_png,
                    house_filename
                )
                if house_success:
                    total_posted += len(house_bills)
                else:
                    overall_success = False
            
            # Process Senate bills if they exist
            if senate_bills:
                LOG.info(f"📍 Processing {len(senate_bills)} Senate bills...")
                # Insert chamber suffix before file extension
                name_parts = png_filename_base.rsplit('.', 1)
                senate_filename = f"{name_parts[0]}-senate.{name_parts[1]}" if len(name_parts) > 1 else f"{png_filename_base}-senate"
                senate_success = self._post_bills_chamber(
                    senate_bills, "Senate",
                    post_to_x, client, api, create_png,
                    senate_filename
                )
            
            LOG.info(f"✅ Separate posting complete - {total_posted} total bills posted")
            return total_posted, overall_success
            
        except Exception as e:
            LOG.error(f"Failed to post bills separately: {e}")
            return 0, False

    def _post_bills_chamber(self, bills: list, chamber_label: str, post_to_x: bool, client, api, create_png: bool, png_filename_base: str) -> bool:
        """
        Post bills for a single chamber (House or Senate) with threading for overflow images.
        
        Args:
            bills: List of bill data dictionaries for this chamber
            chamber_label: "House Bills" or "Senate Bills"
            post_to_x: Whether to post to X.com
            client: X API v2 client
            api: X API v1.1 client
            create_png: Whether to create PNG images
            png_filename_base: Base filename for PNG images
            
        Returns:
            True if posting was successful, False otherwise
        """
        try:
            LOG.info(f"Starting {chamber_label} posting...")
            
            # Create images for this chamber
            image_paths = []
            if create_png and bills:
                LOG.info(f"Creating PNG images for {chamber_label}...")
                image_paths = self.image_generator.create_multiple_bills_pngs(bills, png_filename_base)
                if image_paths:
                    LOG.info(f"✅ Created {len(image_paths)} image(s) for {chamber_label}")
            
            # Post bills to .txt file
            bills_text = "\n".join([self.format_bill_text(bill) for bill in bills])
            self.append_to_txt_file(bills_text, add_new_post_indicator=False)
            
            # Post to X.com if enabled
            main_tweet_id = None
            if post_to_x and client and api and image_paths:
                try:
                    # Upload main post images
                    main_media_ids = []
                    for image_path in image_paths:
                        try:
                            LOG.info(f"Uploading {chamber_label} image: {image_path}")
                            media = api.media_upload(image_path)
                            main_media_ids.append(str(media.media_id))
                            LOG.info(f"✅ Uploaded {chamber_label} image - Media ID: {media.media_id}")
                        except Exception as e:
                            LOG.warning(f"Failed to upload {chamber_label} image {image_path}: {e}")
                    
                    # Create main post text
                    est_tz = timezone(timedelta(hours=-5))
                    est_time = datetime.now(est_tz)
                    date_str = est_time.strftime('%Y-%m-%d')
                    
                    # Dynamic intro based on bill count
                    if len(bills) <= 14:
                        intro = f"🏛️ LATEST UPDATES: The {chamber_label.title()} introduced {len(bills)} new bills."
                    else:
                        intro = f"🚨 BUSY DAY ON THE HILL: A massive {len(bills)} new bills were just introduced in the {chamber_label.title()}!"
                    
                    # Combine with the standard footer
                    main_tweet_text = f"{intro}\n\n📅 Date: {date_str}\n👇 See the breakdown in the attached images.\n🔗 Source: https://www.congress.gov/bills-with-chamber-action/browse-by-date"
                    
                    if len(main_tweet_text) > 280:
                        main_tweet_text = main_tweet_text[:277] + "..."
                    
                    # Post main tweet (max 4 images)
                    overflow_image_paths = []
                    if main_media_ids:
                        limited_main_media_ids = main_media_ids[:4]
                        
                        if len(main_media_ids) > 4:
                            LOG.warning(f"⚠️  X.com supports max 4 media per tweet, posting 4 in main tweet and {len(main_media_ids) - 4} in thread reply")
                            overflow_image_paths = image_paths[4:]
                        
                        response = client.create_tweet(text=main_tweet_text, media_ids=limited_main_media_ids)
                        main_tweet_id = response.data['id']
                        LOG.info(f"✅ Posted main {chamber_label} tweet to X.com - Tweet ID: {main_tweet_id}")
                    
                    # Post thread reply if there are overflow images
                    if overflow_image_paths and main_tweet_id:
                        LOG.info(f"Posting thread reply for {chamber_label} overflow images...")
                        try:
                            thread_media_ids = []
                            for image_path in overflow_image_paths:
                                try:
                                    LOG.info(f"Uploading {chamber_label} thread image: {image_path}")
                                    media = api.media_upload(image_path)
                                    thread_media_ids.append(str(media.media_id))
                                    LOG.info(f"✅ Uploaded {chamber_label} thread image - Media ID: {media.media_id}")
                                except Exception as e:
                                    LOG.warning(f"Failed to upload {chamber_label} thread image {image_path}: {e}")
                            
                            if thread_media_ids:
                                thread_tweet_text = f"📋 {chamber_label} - Additional bill images (continuation)"
                                if len(thread_tweet_text) > 280:
                                    thread_tweet_text = thread_tweet_text[:277] + "..."
                                
                                limited_thread_media_ids = thread_media_ids[:4]
                                if len(thread_media_ids) > 4:
                                    LOG.warning(f"⚠️  Limiting thread reply to 4 media items")
                                
                                response = client.create_tweet(
                                    text=thread_tweet_text,
                                    reply_settings="mentionedUsers",
                                    in_reply_to_tweet_id=main_tweet_id,
                                    media_ids=limited_thread_media_ids
                                )
                                thread_tweet_id = response.data['id']
                                LOG.info(f"✅ Posted {chamber_label} thread reply to X.com - Tweet ID: {thread_tweet_id}")
                        
                        except Exception as e:
                            LOG.error(f"Failed to post {chamber_label} thread reply: {e}")
                    
                    # Archive images
                    if image_paths:
                        LOG.info(f"🔄 Archiving {chamber_label} images...")
                        self.image_generator.archive_images(image_paths)
                
                except Exception as e:
                    LOG.error(f"Failed to post {chamber_label} to X: {e}")
                    return False
            
            # Store all bills in database
            LOG.info(f"Saving {chamber_label} to database...")
            bills_saved = 0
            for bill_data in bills:
                try:
                    was_stored = self.store_in_database(bill_data)
                    if was_stored:
                        bills_saved += 1
                except Exception as e:
                    LOG.warning(f"Failed to store bill in database: {e}")
            
            LOG.info(f"✅ Successfully saved {bills_saved} out of {len(bills)} {chamber_label.lower()} to database")
            return True
            
        except Exception as e:
            LOG.error(f"Failed to post {chamber_label}: {e}")
            return False