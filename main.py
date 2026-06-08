import sys
from schemas import TravelBrief
from extractor import extract_brief
from router import TravelRouter

def run_pipeline(query: str):
    print("\n" + "=" * 80)
    print(f" Processing Query: \"{query}\"")
    print("=" * 80)
    
    print("1. [AI TRANSLATION LAYER] Extracting travel brief parameters using Gemini...")
    try:
        brief = extract_brief(query)
        print("\nExtracted TravelBrief Model (JSON output):")
        print(brief.model_dump_json(indent=2))
        print(f"Completeness check (is_complete): {brief.is_complete}")
        
        print("\n2. [LOGIC LAYER] Deterministic Router executing Strategy Pattern...")
        strategy = TravelRouter.route(brief)
        strategy.execute(brief)
        
    except Exception as e:
        print(f"\n[ERROR] Pipeline failed: {e}")
        
    print("=" * 80 + "\n")

def run_test_cases():
    print("\nRunning default test cases...")
    test_case_a = "I want to go to Paris next week."
    test_case_b = (
        "I want to travel from Mumbai to London on July 15th for 6 days. "
        "Keep it under 150000 INR and I absolutely hate early morning flights."
    )
    run_pipeline(test_case_a)
    run_pipeline(test_case_b)

if __name__ == "__main__":
    print("Agentic Travel Planning System - Phase 1 CLI")
    
    # If command line arguments are provided, join and run them as a single query
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        run_pipeline(query)
    else:
        # Interactive mode
        print("Type your travel query below to test real-time extraction & routing.")
        print("Press Enter (empty line) to run the default test suite, or type 'exit'/'quit' to close.")
        while True:
            try:
                user_input = input("\nYour travel query: ").strip()
                if not user_input:
                    run_test_cases()
                    break
                if user_input.lower() in ("exit", "quit", "q"):
                    print("Exiting.")
                    break
                run_pipeline(user_input)
            except KeyboardInterrupt:
                print("\nExiting.")
                break
