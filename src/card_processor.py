import os
import json
import re
from .resources import load_limited_list, load_typeline_conf

class CardDataError(Exception):
    pass

def normalize_card_text(text):
    # Keep the line break before ①, but collapse it for ②+ style markers and bullets.
    normalized = text.replace('\r\n', '\n')
    return re.sub(r'\n(?=[②-⑳●])', '', normalized)

def type_name(value):
    if value is None:
        return "null"
    return type(value).__name__

def is_str(value):
    return isinstance(value, str)

def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)

def require_type(obj, field_name, expected_type, context):
    if field_name not in obj:
        raise CardDataError(f"{context}: missing required field '{field_name}'")

    value = obj[field_name]
    if expected_type == "str" and not is_str(value):
        raise CardDataError(
            f"{context}: field '{field_name}' expected str, got {type_name(value)}"
        )
    if expected_type == "int" and not is_int(value):
        raise CardDataError(
            f"{context}: field '{field_name}' expected int, got {type_name(value)}"
        )
    if expected_type == "list" and not isinstance(value, list):
        raise CardDataError(
            f"{context}: field '{field_name}' expected list, got {type_name(value)}"
        )

    return value

def require_optional_type(obj, field_name, expected_type, context):
    if field_name not in obj:
        return None
    return require_type(obj, field_name, expected_type, context)

def describe_card(card):
    card_id = card.get("id") if isinstance(card, dict) else None
    name = card.get("name") if isinstance(card, dict) else None
    if is_str(name) and name:
        return f"card id {card_id} ({name})"
    return f"card id {card_id}"

def validate_json2_card(card, source_key):
    context = f"json2 entry {source_key}"
    if not isinstance(card, dict):
        raise CardDataError(f"{context}: expected object, got {type_name(card)}")

    card_id = require_type(card, "id", "int", context)
    cn_name = require_type(card, "cn_name", "str", context)
    desc = ""
    pdesc = ""
    types_str = ""

    text = card.get("text", {})
    if text is None:
        raise CardDataError(f"{context}: field 'text' expected object, got null")
    if not isinstance(text, dict):
        raise CardDataError(
            f"{context}: field 'text' expected object, got {type_name(text)}"
        )

    if "desc" in text:
        desc = require_type(text, "desc", "str", context)
        desc = normalize_card_text(desc)
    if "pdesc" in text:
        pdesc = require_type(text, "pdesc", "str", context)
        pdesc = normalize_card_text(pdesc)
    if "types" in text:
        types_str = require_type(text, "types", "str", context)

    return card_id, {
        "name": cn_name,
        "desc": desc,
        "pdesc": pdesc,
        "types": types_str
    }

def validate_image_ids(card):
    context = describe_card(card)
    card_images = require_type(card, "card_images", "list", context)
    if not card_images:
        raise CardDataError(f"{context}: field 'card_images' must not be empty")

    image_ids = []
    for index, image in enumerate(card_images):
        image_context = f"{context} card_images[{index}]"
        if not isinstance(image, dict):
            raise CardDataError(
                f"{image_context}: expected object, got {type_name(image)}"
            )
        image_ids.append(require_type(image, "id", "int", image_context))

    return image_ids

def find_card_info(main_id, image_ids, id_to_data):
    card_info = id_to_data.get(main_id)
    if card_info:
        return card_info, main_id

    for image_id in image_ids:
        card_info = id_to_data.get(image_id)
        if card_info:
            return card_info, image_id

    return None, None

def validate_card_fields(card, card_type, frame_type):
    context = describe_card(card)
    processed_frame_type = frame_type.replace('_', '-')

    if card_type == "monster":
        attribute = require_type(card, "attribute", "str", context).lower()
    else:
        attribute = card_type

    race = None
    if card_type in ["spell", "trap"]:
        race = require_type(card, "race", "str", context).lower()

    is_link = "link" in frame_type.lower()
    is_pendulum = "pendulum" in frame_type.lower()

    if card_type == "monster":
        require_type(card, "atk", "int", context)
        if is_link:
            require_type(card, "linkval", "int", context)
            linkmarkers = require_type(card, "linkmarkers", "list", context)
            for index, marker in enumerate(linkmarkers):
                if not is_str(marker):
                    raise CardDataError(
                        f"{context}: field 'linkmarkers[{index}]' expected str, got {type_name(marker)}"
                    )
        else:
            require_type(card, "def", "int", context)
            require_type(card, "level", "int", context)

        require_optional_type(card, "scale", "int", context)
        if is_pendulum and "scale" not in card:
            raise CardDataError(f"{context}: missing required field 'scale'")

    return {
        "processed_frame_type": processed_frame_type,
        "attribute": attribute,
        "race": race,
        "is_link": is_link,
        "is_pendulum": is_pendulum
    }

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
        # Load json2 to build a map of id -> data
        print("Loading json2.json for name and description lookup...")
        try:
            with open(json2_path, 'r', encoding='utf-8') as f:
                json2_data = json.load(f)
        except Exception as e:
            print(f"Error loading json2.json: {e}")
            return

        if not isinstance(json2_data, dict):
            print(f"Error loading json2.json: expected object, got {type_name(json2_data)}")
            return

        id_to_data = {}
        invalid_json2_ids = {}
        data_error_count = 0
        for source_key, card in json2_data.items():
            try:
                card_id, card_info = validate_json2_card(card, source_key)
                id_to_data[card_id] = card_info
            except CardDataError as e:
                data_error_count += 1
                if isinstance(card, dict) and is_int(card.get("id")):
                    invalid_json2_ids[card["id"]] = str(e)
                print(f"Data error: {e}. Skipping json2 entry.")

        print(f"Loaded {len(id_to_data)} cards from json2.json.")

        try:
            with open(json1_path, 'r', encoding='utf-8') as f:
                json1_data = json.load(f)
        except Exception as e:
            print(f"Error loading json1.json: {e}")
            return

        if not isinstance(json1_data, dict):
            print(f"Error loading json1.json: expected object, got {type_name(json1_data)}")
            return

        json1_cards = json1_data.get("data", [])
        if not isinstance(json1_cards, list):
            print(f"Error loading json1.json: field 'data' expected list, got {type_name(json1_cards)}")
            return

        json1_count = len(json1_cards)
        print(f"Loaded {json1_count} cards from json1.json.")

        cards_data = {}
        not_found_count = 0
        skipped_count = 0
        for index, card in enumerate(json1_cards):
            try:
                if not isinstance(card, dict):
                    raise CardDataError(
                        f"json1 data[{index}]: expected object, got {type_name(card)}"
                    )

                context = describe_card(card)
                main_id = require_type(card, "id", "int", context)
                image_ids = validate_image_ids(card)
                card_info, _ = find_card_info(main_id, image_ids, id_to_data)

                if not card_info:
                    invalid_match_ids = [card_id for card_id in [main_id] + image_ids if card_id in invalid_json2_ids]
                    if invalid_match_ids:
                        invalid_id = invalid_match_ids[0]
                        raise CardDataError(
                            f"{context}: matching json2 card id {invalid_id} is invalid: {invalid_json2_ids[invalid_id]}"
                        )
                    print(f"Info: Card with id {main_id} not found in json2. Skipping.")
                    not_found_count += 1
                    skipped_count += 1
                    continue

                cn_name = card_info["name"]
                desc = card_info["desc"]
                pdesc = card_info["pdesc"]
                types_str = card_info["types"]

                # Determine cardType based on frameType
                frame_type = require_type(card, "frameType", "str", context)
                card_type = "monster"
                if frame_type == "spell":
                    card_type = "spell"
                elif frame_type == "trap":
                    card_type = "trap"

                validated = validate_card_fields(card, card_type, frame_type)
                processed_frame_type = validated["processed_frame_type"]
                attribute = validated["attribute"]
                min_id = min(image_ids)

                for card_id in image_ids:
                    # Use string of int for key (JSON requirement), int for values.
                    unique_id = min_id
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
                        card_obj["race"] = validated["race"]

                    if card_type == "monster":
                        card_obj["atk"] = card["atk"]

                        # Construct typeline
                        typeline_parts = []
                        # 1. First element from json1 typeline, translated
                        typeline = card.get("typeline", [])
                        if typeline is None:
                            raise CardDataError(
                                f"{context}: field 'typeline' expected list, got null"
                            )
                        if not isinstance(typeline, list):
                            raise CardDataError(
                                f"{context}: field 'typeline' expected list, got {type_name(typeline)}"
                            )
                        if typeline:
                            first_type = typeline[0]
                            if not is_str(first_type):
                                raise CardDataError(
                                    f"{context}: field 'typeline[0]' expected str, got {type_name(first_type)}"
                                )
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

                        if not validated["is_link"]:
                            card_obj["def"] = card["def"]
                            card_obj["level"] = card["level"]
                        else:
                            card_obj["linkVal"] = card["linkval"]
                            card_obj["linkMarkers"] = [m.lower() for m in card["linkmarkers"]]

                        if validated["is_pendulum"]:
                            card_obj["scale"] = card["scale"]
                            card_obj["pendulumDescription"] = pdesc

                    cards_data[str(card_id)] = card_obj
            except CardDataError as e:
                data_error_count += 1
                skipped_count += 1
                print(f"Data error: {e}. Skipping card.")

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
        if not_found_count > 0:
            print(f"Info skipped: {not_found_count} cards (not found in json2)")
        if data_error_count > 0:
            print(f"Data errors: {data_error_count} entries skipped")
        if skipped_count > 0:
            print(f"Skipped total: {skipped_count} cards")
        print("-" * 30)
    else:
        print(f"json1.json or json2.json not found, cannot generate cards.json.")
