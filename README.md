# Agentic Travel Planning System (MVP)

An intelligent, interactive travel planning CLI agent built with Python, Pydantic, and Groq LLMs. The system performs natural language parameter extraction, ranks flights and hotels based on soft/hard constraints, builds chronological trip itineraries, and handles downstream travel disruptions through a reactive change-management patch engine.

---

## 🌟 Key Features

1. **AI Translation & Date Parsing (Phase 1)**:
   - Extracts structured parameters from natural language inputs using Groq's `llama-3.3-70b-versatile` JSON mode.
   - Automatically handles relative dates (e.g. *"July 15th"*) relative to a current date anchor.
   - Gracefully falls back to mock programmatic rule-matchers if no API key is present.

2. **Interactive Selection Loop (Phase 2)**:
   - **Step 1 (Flight)**: Ranks flights based on user preferences (e.g., avoiding early morning departures) and guides the user to select their desired flight.
   - **Step 2 (Hotel)**: Computes remaining budget headroom (`total_budget - chosen_flight_price`), filters out hotels exceeding this limit, and presents options sorted by rating descending.
   - **Timeline Compilation**: Compiles selected items into a fully stitched chronological sequence.

3. **Critic & Reactive Patch Engine (Phase 3)**:
   - **Validation Scanner**: Runs deterministic checks to catch conflicts (e.g. flight arrival after check-in, hotel-flight location mismatches, and overall budget overrun).
   - **Disruption Simulator**: Simulates flight leg cancellations, calculates the **blast radius** (what must be replaced vs. what must be preserved), searches budget-compliant alternatives, and re-anchors check-in/out times to the new flight times.

---

## 📁 Repository Structure

*   `main.py`: Entry point for the CLI pipeline (interactive or test-suite mode).
*   `schemas.py`: Pydantic definitions for `TravelBrief`, `Flight`, `Hotel`, `ItineraryEvent`, and `FinalItinerary`.
*   `extractor.py`: Handles structured natural language extraction using Groq LLM API.
*   `router.py`: Implements route matching and the interactive flight/hotel selection logic.
*   `searcher.py`: Performs parallel flight/hotel database searching and ranking.
*   `critic.py`: Contains validation rules, blast radius logic, and re-anchoring functions.
*   `test_pipeline.py`: Unit tests validating Pydantic models, safety scans, budget filtering, and patching.
*   `data/db.json`: JSON data containing mock flight and hotel options.

---

## ⚙️ Setup & Installation

1.  **Clone the Repository**:
    ```bash
    git clone https://github.com/swarnika-cmd/TravelAgent.git
    cd TravelAgent
    ```

2.  **Install Dependencies**:
    The project uses standard python libraries along with Pydantic and Groq client.
    ```bash
    pip install pydantic groq python-dotenv
    ```

3.  **Configure API Key**:
    Create a `.env` file in the root directory and add your Groq API key:
    ```env
    GROQ_API_KEY=your-actual-groq-api-key-here
    ```
    *Note: If no key is set, the system prints a warning and falls back to mock programmatic extraction & ranking so the app can still be tested.*

---

## 🚀 Running the CLI

Launch the interactive travel planner:
```bash
python main.py
```

*   **Interactive Input**: Type in custom travel requests (e.g., *"I want to fly from Mumbai to London on July 15th for 6 days under 150000 INR"*).
*   **Run Defaults**: Press **Enter** on an empty prompt to execute the default mock test cases.

---

## 🔬 Running Tests

A comprehensive unit test suite is included to verify the validation rules, budget filtering, and change-management patch logic. 

Run the tests using standard library `unittest`:
```bash
python -m unittest test_pipeline.py
```

---

## 🛠️ Testing the Phase 3 Disruption Simulation

You can test the change-management flight-cancellation recovery flow directly in the CLI:

1.  Start the CLI with `python main.py`.
2.  Press **Enter** to run the default test suite.
3.  Select Flight `1` (British Airways FL-002, 75,000 INR).
4.  Select Hotel `1` (London Cozy Stay, 60,000 INR).
5.  At the prompt:
    `Would you like to simulate a flight cancellation to test Phase 3 Change Management? (y/n) [default: n]: `
    Type **`y`** and press **Enter**.
6.  Observe the printed **Blast Radius Analysis**:
    - Discards flight `FL-002`.
    - Preserves hotel stay `HT-001` (cost 60,000 INR).
    - Recalculates remaining budget: `150,000 - 60,000 = 90,000 INR`.
7.  Select the replacement flight (Air India `FL-001`, 60,000 INR).
8.  Verify the final **Patched Chronological Itinerary** prints cleanly with re-anchored timelines.
