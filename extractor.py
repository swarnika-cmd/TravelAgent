import os
import json
from dotenv import load_dotenv
import google.generativeai as genai
from schemas import TravelBrief

# Load local environment variables from .env
load_dotenv()

# Configure the Gemini API key
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise ValueError("GEMINI_API_KEY environment variable is not set. Please set it in .env file.")

genai.configure(api_key=api_key)

def to_gemini_schema(schema: dict) -> dict:
    """
    Recursively converts a JSON Schema to a clean Gemini-compatible OpenAPI schema.
    It retains only: type, properties, items, required, description, nullable, enum.
    """
    if not isinstance(schema, dict):
        return schema
    
    # Resolve Pydantic's "anyOf" structure to get type and nullable fields
    if "anyOf" in schema:
        any_of = schema["anyOf"]
        nullable = False
        non_null_schemas = []
        for s in any_of:
            if isinstance(s, dict):
                if s.get("type") == "null":
                    nullable = True
                else:
                    non_null_schemas.append(s)
        
        merged_schema = {}
        if non_null_schemas:
            merged_schema = to_gemini_schema(non_null_schemas[0])
            
        if nullable:
            merged_schema["nullable"] = True
        return merged_schema

    allowed_keys = {"type", "properties", "items", "required", "description", "nullable", "enum"}
    
    cleaned = {}
    for k, v in schema.items():
        if k in allowed_keys:
            if k == "properties" and isinstance(v, dict):
                cleaned[k] = {prop_name: to_gemini_schema(prop_val) for prop_name, prop_val in v.items()}
            elif k == "items" and isinstance(v, dict):
                cleaned[k] = to_gemini_schema(v)
            else:
                cleaned[k] = v
                
    # Normalize types represented as lists (e.g. OpenAPI 3.1 ['string', 'null'])
    if "type" in cleaned:
        t = cleaned["type"]
        if isinstance(t, list):
            if "null" in t:
                cleaned["nullable"] = True
                non_null_types = [x for x in t if x != "null"]
                if non_null_types:
                    cleaned["type"] = non_null_types[0]
            else:
                cleaned["type"] = t[0]
                
    # Default array items type for tuples or empty arrays
    if cleaned.get("type") == "array" and "items" not in cleaned:
        cleaned["items"] = {"type": "integer"}
        
    return cleaned

def extract_brief(user_input: str) -> TravelBrief:
    """
    Sends the raw user input to Gemini 2.5 Flash and extracts a validated
    TravelBrief Pydantic schema using structured output (JSON schema).
    """
    system_instruction = (
        "You are an expert travel assistant. Your job is to parse unstructured, messy user "
        "travel queries and extract structured information into a strict JSON format matching "
        "the TravelBrief schema.\n\n"
        "Guidance for fields:\n"
        "- origin: Airport code or city (e.g. 'BOM', 'Mumbai') or null if not mentioned.\n"
        "- destination: Target city or country (e.g. 'CDG', 'London') or null if not mentioned.\n"
        "- travel_date: Specific travel date or date range/week reference (e.g. 'July 15th', 'next Friday') or null.\n"
        "- duration_days: Number of days of the trip, or null if not mentioned.\n"
        "- traveller_count: Number of travellers. If not specified, default to 1.\n"
        "- budget_range: Optional tuple of [min_budget, max_budget]. If only a max budget is given (e.g. 'under 150000'), "
        "use [0, max_budget]. If not mentioned, set to null.\n"
        "- accommodation_preferences: List of strings like ['hotel', 'quiet', 'close to transit'] if mentioned.\n"
        "- soft_constraints: List of strings containing preferences, likes, dislikes, or special instructions "
        "(e.g., 'hates early morning flights'). Ensure emotional tone and preferences are preserved.\n"
    )

    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        system_instruction=system_instruction
    )

    # Convert Pydantic v2 schema to a clean Gemini-compatible OpenAPI schema dictionary
    raw_schema = TravelBrief.model_json_schema()
    clean_schema = to_gemini_schema(raw_schema)

    # Use Gemini Structured Output mode
    generation_config = {
        "response_mime_type": "application/json",
        "response_schema": clean_schema,
    }

    prompt = f"User Input Query: \"{user_input}\""

    try:
        response = model.generate_content(
            prompt,
            generation_config=generation_config
        )
        return TravelBrief.model_validate_json(response.text)
    except Exception as e:
        # Fallback mechanism if schema extraction raises exceptions
        fallback_config = {
            "response_mime_type": "application/json"
        }
        try:
            fallback_prompt = (
                f"{prompt}\n\n"
                "Extract the travel brief parameters into valid JSON using this format:\n"
                "{\n"
                "  \"origin\": string or null,\n"
                "  \"destination\": string or null,\n"
                "  \"travel_date\": string or null,\n"
                "  \"duration_days\": integer or null,\n"
                "  \"traveller_count\": integer,\n"
                "  \"budget_range\": [integer, integer] or null,\n"
                "  \"accommodation_preferences\": [string],\n"
                "  \"soft_constraints\": [string]\n"
                "}"
            )
            response = model.generate_content(
                fallback_prompt,
                generation_config=fallback_config
            )
            return TravelBrief.model_validate_json(response.text)
        except Exception as inner_e:
            raise RuntimeError(f"Failed to extract and parse TravelBrief: {inner_e} (Original error: {e})")
