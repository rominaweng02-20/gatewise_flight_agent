
import asyncio
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
from agents import Agent, Runner, ModelSettings, set_tracing_disabled
from agents.extensions.models.litellm_model import LitellmModel

# Load the same environment variables used by GateWise
load_dotenv()

# Disable OpenAI tracing (GateWise uses Gemini through Vertex AI)
set_tracing_disabled(True)

# Use the exact same primary model as GateWise
MODEL = LitellmModel(
    model="vertex_ai/gemini-3.5-flash",
    api_key="unused"
)

SETTINGS = ModelSettings(
    extra_args={
        "vertex_location": "global",
        "timeout": 90,
        "num_retries": 2
    }
)

# The exact same queries submitted to GateWise
QUERIES = {
    "Sample Query 1: JFK Departure Arrival Planning": (
        "I have a flight departing from Terminal 4 JFK on July 15, 2026 at 8:00 AM."
    ),

    "Sample Query 2.1: Comparing NYC-Area Airports": (
        "I'm deciding between JFK, LaGuardia, and Newark for a 9 am departure. "
        "Which airport has historically offered the most predictable departure "
        "experience, considering security wait times, flight delays, and cancellations?"
    ),
    "Sample Query 2.2: Terminal Recommendations": (
            "What terminal in EWR do you recommend?"
        ),

    "Sample Query 3: Best Times of Day for JFK Departures": (
        "For flights departing from JFK, which times of day have historically "
        "had the most reliable departures and shortest security waits? Are there "
        "particular periods I should avoid if I want a smoother airport experience?"
    )
}


async def main():

    # No custom system instructions and no tools
    baseline_agent = Agent(
        name="Baseline",
        instructions=None,
        tools=[],
        model=MODEL,
        model_settings=SETTINGS
    )

    # Initialize the output file
    output_path = Path("baseline_outputs.md")
    run_date = datetime.now().isoformat(timespec="seconds")

    output = f"""# Baseline Model Answers

**Model:** Gemini 3.5 Flash (Vertex AI)

**Tools:** None

**Custom system prompt:** None

**Run date:** {run_date}

**Method:** Each query was submitted independently to the same model without tools or custom system instructions.

---

"""

    output_path.write_text(output, encoding="utf-8")

    # Run each query independently
    for title, query in QUERIES.items():

        print("\n" + "=" * 70)
        print(title)
        print("=" * 70)
        print(f"\nQuery: {query}\n")

        try:
            print("Running baseline model...")

            result = await Runner.run(
                baseline_agent,
                query
            )

            answer = str(result.final_output)

            print("\nBASELINE MODEL ANSWER")
            print("-" * 70)
            print(answer)

            # Append the actual response to the Markdown file
            section = f"""
## {title}

**Query:**

> {query}

### Actual baseline response

{answer}

---

"""

            with output_path.open("a", encoding="utf-8") as file:
                file.write(section)

        except Exception as e:
            error_message = f"Baseline run failed: {str(e)}"

            print(f"\nERROR: {error_message}")

            with output_path.open("a", encoding="utf-8") as file:
                file.write(f"""
## {title}

**Query:**

> {query}

**Status:** {error_message}

---

""")

    print("\n" + "=" * 70)
    print("ALL BASELINE TESTS COMPLETED")
    print("=" * 70)
    print(f"Results saved to: {output_path.resolve()}")


if __name__ == "__main__":
    asyncio.run(main())
