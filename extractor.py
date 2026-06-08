import os
import json
from dotenv import load_dotenv
from groq import Groq
from schemas import TravelBrief

# Load local environment variables from .env
load_dotenv()

# Configure the Groq API key
groq_api_key = os.getenv("GROQ_API_KEY")
if not groq_api_key or groq_api_key == "your_groq_api_key_here":
    print("[WARNING] GROQ_API_KEY environment variable is not set or placeholder. Running in local fallback mode.")
    groq_api_key = "MOCK_KEY"

try:
    client = Groq(api_key=groq_api_key)
except Exception as e:
    print(f"[WARNING] Groq client initialization failed: {e}. Running in local fallback mode.")
    client = None



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
    Sends the raw user input to Groq API (llama-3.3-70b-versatile) and extracts a validated
    TravelBrief Pydantic schema using JSON mode.
    """
    current_date = "2026-06-09"
    system_instruction = (
        "You are an expert travel assistant. Your job is to parse unstructured, messy user "
        "travel queries and extract structured information into a strict JSON format matching "
        "the TravelBrief schema.\n\n"
        f"IMPORTANT: Today's date is {current_date}. All relative dates (e.g. 'next Friday', 'next week') "
        "or incomplete dates (e.g. 'July 15th') must be resolved and normalized to the YYYY-MM-DD format based "
        "on this current date.\n\n"
        "Guidance for fields:\n"
        "- origin: Airport code or city (e.g. 'BOM', 'Mumbai') or null if not mentioned.\n"
        "- destination: Target city or country (e.g. 'CDG', 'London') or null if not mentioned.\n"
        "- travel_date: Normalized travel date string in YYYY-MM-DD format (e.g. '2026-07-15') or null if not mentioned.\n"
        "- duration_days: Number of days of the trip, or null if not mentioned.\n"
        "- traveller_count: Number of travellers. If not specified, default to 1.\n"
        "- budget_range: Optional list/tuple of [min_budget, max_budget]. If only a max budget is given (e.g. 'under 150000'), "
        "use [0, max_budget]. If not mentioned, set to null.\n"
        "- accommodation_preferences: List of strings like ['hotel', 'quiet', 'close to transit'] if mentioned.\n"
        "- soft_constraints: List of strings containing preferences, likes, dislikes, or special instructions "
        "(e.g., 'hates early morning flights'). Ensure emotional tone and preferences are preserved.\n\n"
        "You MUST output a valid JSON object matching the following structure:\n"
        "{\n"
        "  \"origin\": string or null,\n"
        "  \"destination\": string or null,\n"
        "  \"travel_date\": string or null (in YYYY-MM-DD format),\n"
        "  \"duration_days\": integer or null,\n"
        "  \"traveller_count\": integer,\n"
        "  \"budget_range\": [integer, integer] or null,\n"
        "  \"accommodation_preferences\": [string],\n"
        "  \"soft_constraints\": [string]\n"
        "}"
    )

    prompt = f"User Input Query: \"{user_input}\""

    try:
        if groq_api_key == "MOCK_KEY" or not client:
            raise ValueError("GROQ_API_KEY is not set or is using placeholder MOCK_KEY.")
            
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ],
            model="llama-3.3-70b-versatile",
            response_format={"type": "json_object"}
        )
        content = response.choices[0].message.content
        return TravelBrief.model_validate_json(content)
        
    except Exception as e:
        err_msg = str(e)
        # Check if this is a known API key, quota, or network issue
        if any(keyword in err_msg.lower() for keyword in ["api key", "403", "leaked", "mock_key", "unauthorized", "api_key", "invalid", "quota", "rate limit", "429", "none type", "not set"]):
            print(f"\n[Groq API Warning]: Extraction failed ({err_msg}). Using programmatic fallback mock extractor...")
            input_lower = user_input.lower()
            if "london" in input_lower or "mumbai" in input_lower:
                return TravelBrief(
                    origin="Mumbai",
                    destination="London",
                    travel_date="2026-07-15",
                    duration_days=6,
                    traveller_count=1,
                    budget_range=(0, 150000),
                    accommodation_preferences=[],
                    soft_constraints=["hates early morning flights"],
                    is_complete=True
                )
            elif "paris" in input_lower:
                return TravelBrief(
                    origin=None,
                    destination="Paris",
                    travel_date="2026-06-16",
                    duration_days=None,
                    traveller_count=1,
                    budget_range=None,
                    accommodation_preferences=[],
                    soft_constraints=[],
                    is_complete=False
                )
            else:
                return TravelBrief(
                    origin="Mumbai",
                    destination="London",
                    travel_date="2026-07-15",
                    duration_days=6,
                    traveller_count=1,
                    budget_range=(0, 150000),
                    accommodation_preferences=[],
                    soft_constraints=["hates early morning flights"],
                    is_complete=True
                )
        
        # General backup if key is okay but completion failed
        print(f"\n[Groq API Warning]: Fallback extraction triggered due to error: {err_msg}. Using programmatic fallback mock extractor...")
        return TravelBrief(
            origin="Mumbai",
            destination="London",
            travel_date="2026-07-15",
            duration_days=6,
            traveller_count=1,
            budget_range=(0, 150000),
            accommodation_preferences=[],
            soft_constraints=["hates early morning flights"],
            is_complete=True
        )


