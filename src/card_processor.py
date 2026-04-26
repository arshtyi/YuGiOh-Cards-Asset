import os
import json
import re
from .resources import load_limited_list, load_typeline_conf

def normalize_card_text(text):
    # Keep the line break before ①, but collapse it for ②+ style markers and bullets.
    normalized = text.replace('\r\n', '\n')
    return re.sub(r'\n(?=[②-⑳●])', '', normalized)

def generate_cards_json(tmp_dir, output_path, res_dir="res"):
    # Generate cards.json from json1.json
    print("Generating cards.json from json1.json...")
    json1_path = os.path.join(tmp_dir, "json1.json")
    json2_path = os.path.join(tmp_dir, "json2.json")

    # Load limited lists
    limited_lists = load_limited_list(res_dir)

    # Load typeline configuration
    typeline_map = load_typeline_conf(res_dir)

    if os.path.exists(json1_path) and os.path.exists(json2_path):
        try:
            # Load json2 to build a map of id -> data
            print("Loading json2.json for name and description lookup...")
            with open(json2_path, 'r', encoding='utf-8') as f:
                json2_data = json.load(f)

            # json2_data is a dict where values are card objects
            id_to_data = {}
            for card in json2_data.values():
                if "id" in card:
                    card_id = card["id"]
                    cn_name = card.get("cn_name")
                    desc = ""
                    pdesc = ""
                    types_str = ""
                    if "text" in card:
                        if "desc" in card["text"]:
                            desc = normalize_card_text(card["text"]["desc"])
                        if "pdesc" in card["text"]:
                            pdesc = normalize_card_text(card["text"]["pdesc"])
                        if "types" in card["text"]:
                            types_str = card["text"]["types"]

                    id_to_data[card_id] = {
                        "name": cn_name,
                        "desc": desc,
                        "pdesc": pdesc,
                        "types": types_str
                    }

            print(f"Loaded {len(id_to_data)} cards from json2.json.")

            with open(json1_path, 'r', encoding='utf-8') as f:
                json1_data = json.load(f)

            json1_count = len(json1_data.get("data", []))
            print(f"Loaded {json1_count} cards from json1.json.")

            cards_data = {}
            skipped_count = 0
            if "data" in json1_data:
                for card in json1_data["data"]:
                    # Get the main ID of the card
                    main_id = card.get("id")

                    # Try to find card_info using main_id
                    card_info = id_to_data.get(main_id)

                    # If not found, try using IDs from card_images
                    if not card_info and "card_images" in card:
                        for image in card["card_images"]:
                            if "id" in image:
                                img_id = image["id"]
                                card_info = id_to_data.get(img_id)
                                if card_info:
                                    break

                    # If still not found, skip this card
                    if not card_info:
                        print(f"Error: Card with id {main_id} not found in json2. Skipping.")
                        skipped_count += 1
                        continue

                    cn_name = card_info["name"]
                    desc = card_info["desc"]
                    pdesc = card_info["pdesc"]
                    types_str = card_info["types"]

                    # Determine cardType based on frameType
                    frame_type = card.get("frameType")
                    processed_frame_type = frame_type.replace('_', '-') if frame_type else None

                    card_type = "monster"
                    if frame_type == "spell":
                        card_type = "spell"
                    elif frame_type == "trap":
                        card_type = "trap"

                    # Determine attribute
                    if card_type == "monster":
                        attribute = card.get("attribute", "").lower()
                    else:
                        attribute = card_type

                    if "card_images" in card:
                        # Calculate minimum ID for uniqueId
                        image_ids = []
                        for image in card["card_images"]:
                            if "id" in image:
                                try:
                                    image_ids.append(int(image["id"]))
                                except ValueError:
                                    pass

                        min_id = min(image_ids) if image_ids else None

                        for image in card["card_images"]:
                            if "id" in image:
                                try:
                                    card_id = int(image["id"])
                                    # Use string of int for key (JSON requirement), int for values
                                    unique_id = min_id if min_id is not None else card_id
                                    card_obj = {
                                        "id": card_id,
                                        "uniqueId": unique_id,
                                        "cardImage": card_id,
                                        "name": cn_name,
                                        "description": desc,
                                        "cardType": card_type,
                                        "attribute": attribute,
                                        "frameType": processed_frame_type
                                    }

                                    # Add limited status
                                    limited_status = {}
                                    for format_name in ["ocg", "tcg", "md"]:
                                        if unique_id in limited_lists[format_name]:
                                            limited_status[format_name] = limited_lists[format_name][unique_id]

                                    if limited_status:
                                        card_obj["limit"] = limited_status

                                    if card_type in ["spell", "trap"]:
                                        card_obj["race"] = card.get("race", "").lower()

                                    if card_type == "monster":
                                        if "atk" in card:
                                            card_obj["atk"] = card["atk"]

                                        # Construct typeline
                                        typeline_parts = []
                                        # 1. First element from json1 typeline, translated
                                        if "typeline" in card and isinstance(card["typeline"], list) and len(card["typeline"]) > 0:
                                            first_type = card["typeline"][0]
                                            translated_first = typeline_map.get(first_type, first_type)
                                            typeline_parts.append(translated_first)

                                        # 2. Elements from json2 types, reversed
                                        if types_str:
                                            # Extract content inside [...]
                                            match = re.match(r"^\[(.*?)\]", types_str)
                                            if match:
                                                content = match.group(1)
                                                parts = content.split("|")
                                                if len(parts) > 1:
                                                    # Skip first, reverse the rest
                                                    remaining = parts[1:]
                                                    remaining.reverse()
                                                    typeline_parts.extend(remaining)

                                        if typeline_parts:
                                            card_obj["typeline"] = f"【{'/'.join(typeline_parts)}】"

                                        # Check if it is a link monster
                                        is_link = frame_type and "link" in frame_type.lower()
                                        if not is_link:
                                            if "def" in card:
                                                card_obj["def"] = card["def"]
                                            if "level" in card:
                                                card_obj["level"] = card["level"]
                                        else:
                                            # Link monster specific attributes
                                            if "linkval" in card:
                                                card_obj["linkVal"] = card["linkval"]
                                            if "linkmarkers" in card:
                                                card_obj["linkMarkers"] = [m.lower() for m in card["linkmarkers"]]

                                        # Check if it is a pendulum monster
                                        is_pendulum = frame_type and "pendulum" in frame_type.lower()
                                        if is_pendulum:
                                            if "scale" in card:
                                                card_obj["scale"] = card["scale"]
                                            card_obj["pendulumDescription"] = pdesc

                                    cards_data[str(card_id)] = card_obj
                                except ValueError:
                                    print(f"Warning: Could not convert id {image['id']} to int.")

            # Merge token.json
            token_path = os.path.join(res_dir, "token.json")
            token_count = 0
            count_before_token = len(cards_data)

            if os.path.exists(token_path):
                try:
                    with open(token_path, 'r', encoding='utf-8') as f:
                        token_data = json.load(f)
                        token_count = len(token_data)
                        cards_data.update(token_data)
                        print(f"Merged {token_count} tokens from {token_path}")
                except Exception as e:
                    print(f"Error merging token.json: {e}")
            else:
                print(f"Warning: {token_path} not found.")

            count_after_token = len(cards_data)

            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(cards_data, f, ensure_ascii=False, indent=4, sort_keys=True)

            print("-" * 30)
            print(f"Summary:")
            print(f"json1.json: {json1_count} cards")
            print(f"json2.json: {len(id_to_data)} cards")
            print(f"cards.json (before tokens): {count_before_token} cards")
            print(f"token.json: {token_count} cards")
            print(f"cards.json (final): {count_after_token} cards")
            if skipped_count > 0:
                print(f"Skipped: {skipped_count} cards (not found in json2)")
            print("-" * 30)

        except Exception as e:
            print(f"Error generating cards.json: {e}")
    else:
        print(f"json1.json or json2.json not found, cannot generate cards.json.")
