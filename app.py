import asyncio
import json
import uuid
import re
import threading
import uvicorn

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal
from agents import Agent, ModelSettings, RunContextWrapper, Runner, function_tool, set_tracing_disabled, AgentHooks
from agents.extensions.models.litellm_model import LitellmModel
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from src.analytics.temporal_filters import (
    normalize_day_filters,
    validate_hour_filters
)

from src.analytics import (
    security_patterns,
    security_arrival_profile,
    flight_reliability,
    weather_conditions,
    weather_risk_profile,
    airport_operations,
    flight_risk_profile,
)

from contextvars import ContextVar
from functools import wraps
import inspect
from context_panel import AgentContexts, PanelHooks, add_context_panel


# Traces upload to OpenAI by default, which needs an OpenAI key. We're on Gemini.
set_tracing_disabled(True)

# LiteLLM routes the call to Gemini. api_key is unused: Vertex AI uses your gcloud credentials.
MODEL = LitellmModel(model="vertex_ai/gemini-3.5-flash", api_key="unused")
# Researchers only read and take notes: the cheaper model is enough.
RESEARCHER_MODEL = LitellmModel(model="vertex_ai/gemini-3.5-flash-lite", api_key="unused")
# A stalled model call would hang the page: give up after 90 s, and retry twice.
SETTINGS = ModelSettings(extra_args={"vertex_location": "global", "timeout": 90, "num_retries": 2})
LEAD_SETTINGS = ModelSettings(
    extra_args={"vertex_location": "global", "timeout": 90, "num_retries": 2},
    parallel_tool_calls=True,
)
# The Lead gets this many researchers in all. Prompts ask for restraint; code enforces it.
# --- Limits enforced in code (prompts ask for restraint; code guarantees it) ---
MAX_RESEARCHERS = 6        # researchers the Lead may start in one run
MAX_RESEARCHER_TURNS = 6   # model turns per researcher
MAX_ROWS = 400             # rows a tool may return before it is truncated
 
# --- What the data covers. Tools reject anything outside this. ---
AIRPORTS = {"JFK", "LGA", "EWR"}
DATA_START, DATA_END = "2026-04-01", "2026-08-31"
 
# --- Advice-card assumptions (shown on the card, not from the data) ---
SECURITY_LEAD_HOURS = 2     # passengers clear security 1-2 hours before departure
OTHER_OVERHEAD_MIN = 45     # check-in, bag drop, walk to gate
MIN_OBSERVED_HOURS = 20     # fewer observed hours than this = thin evidence

# --- Selected tool-call recorder ---

CURRENT_AGENT = ContextVar("current_agent", default="Lead")
MAX_TOOL_RESULT_CHARS = 2500


def preview_result(value: Any) -> str:
    """Convert a tool result to a readable, size-limited string."""
    if isinstance(value, str):
        result = value
    else:
        result = json.dumps(value, default=str)

    if len(result) > MAX_TOOL_RESULT_CHARS:
        result = result[:MAX_TOOL_RESULT_CHARS] + "... [truncated]"

    return result


def record_tool_call(fn):
    """Record a selected tool's arguments, agent, and result."""

    signature = inspect.signature(fn)

    def make_entry(args, kwargs):
        bound = signature.bind_partial(*args, **kwargs)

        # All selected tools use ctx as their first parameter.
        ctx = bound.arguments["ctx"]
        state = ctx.context

        tool_args = {
            key: value
            for key, value in bound.arguments.items()
            if key != "ctx"
        }

        entry = {
            "agent": CURRENT_AGENT.get(),
            "name": fn.__name__,
            "args": json.loads(json.dumps(tool_args, default=str)),
            "result": None,
        }

        with state.lock:
            state.tool_calls.append(entry)

        return entry

    if inspect.iscoroutinefunction(fn):

        @wraps(fn)
        async def async_wrapper(*args, **kwargs):
            entry = make_entry(args, kwargs)

            try:
                result = await fn(*args, **kwargs)
                entry["result"] = preview_result(result)
                return result

            except Exception as exc:
                entry["result"] = preview_result(
                    f"ERROR: {type(exc).__name__}: {exc}"
                )
                raise

        return async_wrapper

    @wraps(fn)
    def sync_wrapper(*args, **kwargs):
        entry = make_entry(args, kwargs)

        try:
            result = fn(*args, **kwargs)
            entry["result"] = preview_result(result)
            return result

        except Exception as exc:
            entry["result"] = preview_result(
                f"ERROR: {type(exc).__name__}: {exc}"
            )
            raise

    return sync_wrapper
@dataclass
class Research:
    """One run's state, shared by every agent and tool in it."""

    hooks: PanelHooks
    researchers: int = 0
    findings: list[str] = field(default_factory=list)
    lock: object = field(default_factory=threading.Lock)
    evidence: list[dict] = field(default_factory=list)
    research_tasks: set[tuple] = field(default_factory=set)
    tool_calls: list[dict] = field(default_factory=list)      # new: the /chat tool_calls    
    # --- Tools ---

def check_scope(airports: list[str], start_date: str, end_date: str, grain: str = "daily") -> str | None:
    """Return a message the model can act on if the request is outside the data, else None."""
    bad = [a for a in airports if a not in AIRPORTS]
    if bad or not airports:
        return f"Unsupported airports {bad or airports}. The data covers only JFK, LGA, and EWR."
    if grain not in ("daily", "hourly"):
        return f"Unsupported grain '{grain}'. Use 'daily' or 'hourly'."
    try:
        start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
    except ValueError:
        return "Dates must be YYYY-MM-DD."
    if not (date.fromisoformat(DATA_START) <= start <= end <= date.fromisoformat(DATA_END)):
        return (f"The data covers only {DATA_START} to {DATA_END}. "
                f"Requested {start_date} to {end_date} is outside it, or start is after end.")
    return None

def cite(
    ctx: RunContextWrapper[Research],
    tool: str,
    source: str,
    params: dict,
    results,
) -> str:
    """Register one tool result and return its unique evidence ID."""

    note = (
        "Some raw rows were truncated to the first MAX_ROWS records. "
        "The returned row arrays do not represent the complete range. "
        "Use summary statistics for full-range conclusions, or narrow "
        "the filters/use daily grain for more detailed analysis."
    )

    # Case 1: Results are a list.
    if isinstance(results, list) and len(results) > MAX_ROWS:
        results = {
            "rows_total": len(results),
            "rows_returned": MAX_ROWS,
            "truncated": True,
            "note": note,
            "rows": results[:MAX_ROWS],
        }

    # Case 2: Results are a dictionary containing row arrays.
    elif isinstance(results, dict):
        results = dict(results)
        cut = {}

        for key in ("rows", "daily_rows"):
            rows = results.get(key)

            if isinstance(rows, list) and len(rows) > MAX_ROWS:
                cut[key] = {
                    "rows_total": len(rows),
                    "rows_returned": MAX_ROWS,
                }
                results[key] = rows[:MAX_ROWS]

        if cut:
            results["truncated"] = cut
            results["note"] = note

    # Extract shared research state and summary.
    state = ctx.context
    summary = results.get("summary") if isinstance(results, dict) else None

    # Assign a unique evidence ID atomically.
    with state.lock:
        evidence_id = f"E{len(state.evidence) + 1}"

        state.evidence.append({
            "id": evidence_id,
            "tool": tool,
            "source": source,
            "params": params,
            "summary": summary,

            # Keep terminal-level hourly rows for deterministic arrival calculations.
            "rows": (
                results.get("rows")
                if tool == "analyze_security_patterns"
                and isinstance(results, dict)
                else None
            ),

            # Do not calculate from incomplete row sets.
            "truncated": (
                bool(results.get("truncated"))
                if isinstance(results, dict)
                else False
            ),
        })

    # Return evidence ID and actual results to the researcher.
    return json.dumps(
        {
            "evidence_id": evidence_id,
            "source": source,
            "params": params,
            "results": results,
        },
        default=str,
    )
 
# Every researcher ends its reply in this format, so the Lead and Writer can read them alike.
FINDINGS_FORMAT = """
Return your findings in exactly this format and nothing else:

FINDINGS
- <one factual statement, with its numbers> [E1]
- <another factual statement> [E2]

CAVEATS
- <limitations of the data that apply to these findings>

Rules:
- The bracketed citation must contain the exact evidence_id returned by your tool.
- For example, if the tool returns evidence_id "E3", cite it as [E3].
- Never write [E#], [E#3], or any other placeholder format.
- Every factual statement containing numbers must cite the relevant evidence ID.
- Never invent an evidence ID.
- Never state a number that did not come from a tool result.
- If a tool returns an error or no rows, say so under CAVEATS. Do not guess.
- You know only your assigned task. Use the airports, dates, and grain it names.
- Call your tool once per distinct question. Do not repeat identical calls.
- The data covers only JFK, LGA, and EWR, April 1 to August 31, 2026.
"""

#TSA_SECURITY RESEARCHER

@function_tool
@record_tool_call
def analyze_security_patterns(
    ctx: RunContextWrapper[Research],
    airports: list[str],
    start_date: str,
    end_date: str,
    grain: str = "daily",
    terminal: str | None = None,
    queue_type: Literal["standard", "precheck"] | None = None,
) -> str:
    """Analyze TSA posted security wait times by airport, terminal, and queue.

    Args:
        airports: Any of 'JFK', 'LGA', 'EWR'.
        start_date: First day, YYYY-MM-DD, no earlier than 2026-04-01.
        end_date: Last day, YYYY-MM-DD, no later than 2026-08-31.
        grain: 'daily' or 'hourly'. Prefer daily for long ranges.
        terminal: Optional terminal filter, e.g. '4' for JFK or 'A' for EWR.
        queue_type: Optional 'standard' or 'precheck' filter.
    """
    airports = [a.upper().strip() for a in airports]

    if terminal is not None:
        terminal = re.sub(
            r"^\s*terminal\s*",
            "",
            terminal,
            flags=re.IGNORECASE,
        ).strip() or None
    if queue_type is not None:
        queue_type = queue_type.strip().lower()
        if queue_type not in {"standard", "precheck"}:
            return json.dumps({
                "error": "queue_type must be 'standard' or 'precheck'."
            })

    if error := check_scope(airports, start_date, end_date, grain):
        return json.dumps({"error": error})

    try:
        results = security_patterns(
            airports=airports,
            start_date=start_date,
            end_date=end_date,
            grain=grain,
            terminal=terminal,
            queue_type=queue_type,
        )
    except Exception as e:
        return json.dumps({
            "error": (
                f"Could not analyze security waits: "
                f"{type(e).__name__}: {e}"
            )
        })

    return cite(
        ctx,
        "analyze_security_patterns",
        "TSA posted wait times (Hugging Face: digitalhen/us-airport-wait-times)",
        {
            "airports": airports,
            "start_date": start_date,
            "end_date": end_date,
            "grain": grain,
            "terminal": terminal,
            "queue_type": queue_type,
        },
        results,
    )

@function_tool
@record_tool_call
def analyze_security_arrival_profile(
    ctx: RunContextWrapper[Research],
    airports: list[str],
    start_date: str,
    end_date: str,
    start_hour: int | None = None,
    end_hour: int | None = None,
    day_type: Literal["all", "weekday", "weekend"] = "all",
    days_of_week: list[str] | None = None,
    queue_type: Literal["overall", "standard", "precheck"] = "standard",
) -> str:
    """Summarize hourly airport-level security wait percentiles.

    Args:
        airports: Any of 'JFK', 'LGA', 'EWR'.
        start_date: First day, YYYY-MM-DD.
        end_date: Last day, YYYY-MM-DD.
        start_hour: Eastern hour the window starts, 0-23, inclusive. Give with end_hour.
        end_hour: Eastern hour the window ends, 1-24, EXCLUSIVE (16 to 18 covers 16:00-17:59)
        day_type: 'all', 'weekday', or 'weekend'.
        queue_type: 'overall', 'standard', or 'precheck'.
        days_of_week: Optional list of weekdays to include, e.g. ["Monday", "Friday"]. Narrows the day_type selection.
    """
    airports = [a.upper().strip() for a in airports]

    if error := check_scope(airports, start_date, end_date, "hourly"):
        return json.dumps({"error": error})
    try:
        day_type, days_of_week = normalize_day_filters(
            day_type,
            list(days_of_week or [])
        )
        validate_hour_filters(start_hour, end_hour)
    except ValueError as e:
        return json.dumps({"error": str(e)})
    
    try:
        results = security_arrival_profile(
            airports=airports,
            start_date=start_date,
            end_date=end_date,
            start_hour=start_hour,
            end_hour=end_hour,
            day_type=day_type,
            days_of_week=days_of_week,
            queue_type=queue_type,
        )
    except Exception as e:
        return json.dumps({
            "error": (
                "Could not analyze security arrival profile: "
                f"{type(e).__name__}: {e}"
            )
        })

    return cite(
        ctx,
        "analyze_security_arrival_profile",
        "TSA posted hourly airport-level security wait estimates",
        {
            "airports": airports,
            "start_date": start_date,
            "end_date": end_date,
            "day_type": day_type,
            "days_of_week": days_of_week,
            "start_hour": start_hour,
            "end_hour": end_hour,
            "queue_type": queue_type,
        },
        results,
    )
security_researcher = Agent(
    name="Security Researcher",
    instructions="""
    You investigate airport security wait patterns from TSA posted wait times.

    Use the available analytics tools to examine:
    - Average security wait times and P50/P90 percentiles.
    - Differences between airports.
    - Standard versus PreCheck queues.
    - Terminal-level variation where supported.
    - Missing observations and coverage limitations.
    - Hour-of-day and day-of-week patterns.

    Tool selection:
    - For any advice question with a specified terminal, use
    analyze_security_patterns with grain="hourly".
    - Pass the exact terminal and queue_type from the assignment.
    - Use the requested airport and date range.
    - Do not use analyze_security_arrival_profile for terminal-specific advice.
    - When no terminal is specified, use analyze_security_arrival_profile
    for airport-wide percentile-based arrival advice.
    - Never substitute airport-wide evidence for missing terminal-specific data.

    FILTER REQUIREMENTS:
    - If the assigned task specifies a terminal, pass that exact terminal value
    to the analytics tool.
    - If the assigned task specifies standard or PreCheck, pass the matching
    queue_type to the analytics tool.
    - If both filters are specified, apply both.
    - If a filter is not specified, leave it as None.
    - Do not invent terminal labels. Use the terminal values supplied in the
    task or supported by the data.
    - For terminal-specific analysis, prefer hourly grain when examining
    time-of-day patterns.

    Percentiles from the arrival profile describe hourly airport-level
    weighted estimates, not individual passenger wait times.

    Never interpret missing observations as zero-minute wait times.
    These are posted wait estimates, not measured waits.
    Do not claim anything about flight delays.
    """ + FINDINGS_FORMAT,
    tools=[analyze_security_patterns, analyze_security_arrival_profile,],
    model=RESEARCHER_MODEL,
    model_settings=SETTINGS,
)

#FLIGHT RESEARCHER

@function_tool
@record_tool_call
def analyze_flight_reliability(
    ctx: RunContextWrapper[Research],
    airports: list[str],
    start_date: str,
    end_date: str,
    grain: str = "daily",
    day_type: Literal["all", "weekday", "weekend"] = "all",
    start_hour: int | None = None,
    end_hour: int | None = None,
    days_of_week: list[str] | None = None,
) -> str:
    """Analyze flight departure reliability: delays, cancellations, and the share of flights
    departing at least 15 minutes late.
 
    Args:
        airports: Any of 'JFK', 'LGA', 'EWR'.
        start_date: First day, YYYY-MM-DD, no earlier than 2026-04-01.
        end_date: Last day, YYYY-MM-DD, no later than 2026-08-31.
        grain: 'daily' or 'hourly'. Prefer daily for long ranges.
        day_type: 'all', 'weekday', or 'weekend'.
        days_of_week: 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'
        start_hour: Eastern hour the window starts, 0-23, inclusive. Give with end_hour.
        end_hour: Eastern hour the window ends, 1-24, EXCLUSIVE (16 to 18 covers 16:00-17:59)
    """
    airports = [a.upper().strip() for a in airports]
    if error := check_scope(airports, start_date, end_date, grain):
        return json.dumps({"error": error})
    
    if grain == "hourly" and (start_hour is not None or end_hour is not None):
        return json.dumps({"error": "For a specific day or hour window, use "
                    "analyze_flight_risk_profile, which returns pooled rates."})
    try:
        day_type, days_of_week = normalize_day_filters(
            day_type, days_of_week
        )
        validate_hour_filters(start_hour, end_hour)
    except ValueError as e:
        return json.dumps({"error": str(e)})
    try:
        results = flight_reliability(
            airports=airports,
            start_date=start_date,
            end_date=end_date,
            grain=grain,
            start_hour=start_hour,
            end_hour=end_hour,
            day_type=day_type,
            days_of_week=days_of_week,
        )
    except Exception as e:
        return json.dumps({"error": f"Could not analyze flight reliability: {type(e).__name__}: {e}"})
    return cite(ctx, "analyze_flight_reliability", "BTS on-time performance",
                {
                    "airports": airports,
                    "start_date": start_date,
                    "end_date": end_date,
                    "day_type": day_type,
                    "days_of_week": days_of_week,
                    "start_hour": start_hour,
                    "end_hour": end_hour,
                },
                results)

@function_tool
@record_tool_call
def analyze_flight_risk_profile(
    ctx: RunContextWrapper[Research],
    airports: list[str],
    start_date: str,
    end_date: str,
    start_hour: int | None = None,
    end_hour: int | None = None,
    day_type: Literal["all", "weekday", "weekend"] = "all",
    days_of_week: list[str] | None = None,
) -> str:
    """Summarize pooled departure risk (share of flights 15+ minutes late, cancellation rate,
    mean delay, sample size) for a day and scheduled-departure-hour window. Use this for
    questions about specific days or times.

    Args:
        airports: Any of 'JFK', 'LGA', 'EWR'.
        start_date: First day, YYYY-MM-DD.
        end_date: Last day, YYYY-MM-DD.
        start_hour: Eastern hour the window starts, 0-23, inclusive. Give with end_hour.
        end_hour: Eastern hour the window ends, 1-24, EXCLUSIVE (18 to 19 covers 18:00-18:59).
            Give with start_hour, or omit both.
        day_type: 'all', 'weekday', or 'weekend'.
        days_of_week: Optional specific days, e.g. ['Friday']. Must fit day_type.
    """
    airports = [a.upper().strip() for a in airports]
    if error := check_scope(airports, start_date, end_date, "hourly"):
        return json.dumps({"error": error})
    try:
        day_type, days_of_week = normalize_day_filters(day_type, days_of_week)
        validate_hour_filters(start_hour, end_hour)
    except ValueError as e:
        return json.dumps({"error": str(e)})
    try:
        results = flight_risk_profile(
            airports=airports, start_date=start_date, end_date=end_date,
            start_hour=start_hour, end_hour=end_hour,
            day_type=day_type, days_of_week=days_of_week,
        )
    except Exception as e:
        return json.dumps({"error": f"Could not analyze flight risk profile: {type(e).__name__}: {e}"})
    return cite(ctx, "analyze_flight_risk_profile", "BTS on-time performance (pooled hourly)",
                {"airports": airports, "start_date": start_date, "end_date": end_date,
                 "day_type": day_type, "days_of_week": days_of_week,
                 "start_hour": start_hour, "end_hour": end_hour},
                results)

flight_researcher = Agent(
    name="Flight Researcher",
    instructions="""
    You are a specialized airport flight reliability researcher.

    Your responsibility is to investigate flight departure
    performance across JFK, EWR, and LGA.

    Use the available analytics tool to investigate:
    1. Departure delay patterns and average delay duration.
    2. The percentage of flights departing at least 15 minutes late.
    3. Flight cancellation rates.
    4. Differences in reliability across airports.
    5. Daily versus hourly departure patterns.
    6. Potential periods of increased flight disruption.

    Compare airports using rates and distributions rather than
    relying only on raw flight counts.
    
    Tool selection:
    - Use analyze_flight_risk_profile for a specific day or time window (pooled rates).
    - Use analyze_flight_reliability for trends or daily/hourly detail.

    Important methodological requirements:
    - Do not interpret missing observations as zero delays.
    - Distinguish cancellations from departure delays.
    - Keep cancellations separate from departure delays.
    - Do not claim that security wait times cause flight delays.
    - Clearly identify the date range and aggregation grain.
    - Support findings with numerical evidence from the tool.
    - The available dataset supports the percentage of classified
    departed flights delayed by more than 15 minutes. It does not
    support a 30-minute delay rate.
    - Never estimate or infer a 30-minute delay rate from the
    15-minute delay rate or mean departure delay. If the user asks
    about delays exceeding 30 minutes, explicitly state that this
    metric is unavailable in the current dataset.

    Return structured findings that the Lead Researcher can use
    in its final analysis.
    """ + FINDINGS_FORMAT,
    tools=[analyze_flight_reliability, analyze_flight_risk_profile],
    model=RESEARCHER_MODEL,
    model_settings=SETTINGS,
)

#WEATHER RESEARCHER

@function_tool
@record_tool_call
def analyze_weather_conditions(
    ctx: RunContextWrapper[Research],
    airports: list[str],
    start_date: str,
    end_date: str,
    grain: str = "daily",
) -> str:
    """Analyze weather at the airports: temperature, precipitation, visibility, and wind.
 
    Args:
        airports: Any of 'JFK', 'LGA', 'EWR'.
        start_date: First day, YYYY-MM-DD, no earlier than 2026-04-01.
        end_date: Last day, YYYY-MM-DD, no later than 2026-08-31.
        grain: 'daily' or 'hourly'. Prefer daily for long ranges.
    """
    airports = [a.upper().strip() for a in airports]
    if error := check_scope(airports, start_date, end_date, grain):
        return json.dumps({"error": error})
    try:
        results = weather_conditions(airports=airports, start_date=start_date, end_date=end_date, grain=grain)
    except Exception as e:
        return json.dumps({"error": f"Could not analyze weather: {type(e).__name__}: {e}"})
    return cite(ctx, "analyze_weather_conditions", "NOAA NCEI hourly observations",
                {"airports": airports, "start_date": start_date, "end_date": end_date, "grain": grain},
                results)
 
@function_tool
@record_tool_call
def analyze_weather_risk_profile(
    ctx: RunContextWrapper[Research],
    airports: list[str],
    start_date: str,
    end_date: str,
    visibility_threshold_km: float = 5.0,
    precipitation_threshold_mm: float = 1.0,
    wind_threshold_m_s: float = 10.0,
    day_type: Literal["all", "weekday", "weekend"] = "all",
    start_hour: int | None = None,
    end_hour: int | None = None,
    days_of_week: list[str] | None = None,
) -> str:
    """Summarize the frequency of selected adverse hourly weather conditions.

    Args:
        airports: Any of 'JFK', 'LGA', 'EWR'.
        start_date: First day, YYYY-MM-DD.
        end_date: Last day, YYYY-MM-DD.
        visibility_threshold_km: Low-visibility threshold in kilometers.
        precipitation_threshold_mm: Significant precipitation threshold in mm.
        wind_threshold_m_s: High-wind threshold in meters per second.
        day_type: 'all', 'weekday', or 'weekend'.
        days_of_week: 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'
        start_hour: Eastern hour the window starts, 0-23, inclusive. Give with end_hour.
        end_hour: Eastern hour the window ends, 1-24, EXCLUSIVE (16 to 18 covers 16:00-17:59)
    """
    airports = [a.upper().strip() for a in airports]

    if error := check_scope(airports, start_date, end_date, "hourly"):
        return json.dumps({"error": error})
    try:
        day_type, days_of_week = normalize_day_filters(
            day_type, days_of_week
        )
        validate_hour_filters(start_hour, end_hour)
    except ValueError as e:
        return json.dumps({"error": str(e)})
    try:
        results = weather_risk_profile(
            airports=airports,
            start_date=start_date,
            end_date=end_date,
            visibility_threshold_km=visibility_threshold_km,
            precipitation_threshold_mm=precipitation_threshold_mm,
            wind_threshold_m_s=wind_threshold_m_s,
            day_type=day_type,
            days_of_week=days_of_week,
            start_hour=start_hour,
            end_hour=end_hour,
        )
    except Exception as e:
        return json.dumps({
            "error": (
                "Could not analyze weather risk profile: "
                f"{type(e).__name__}: {e}"
            )
        })

    return cite(
        ctx,
        "analyze_weather_risk_profile",
        "NOAA NCEI hourly weather risk indicators",
        {
            "airports": airports,
            "start_date": start_date,
            "end_date": end_date,
            "visibility_threshold_km": visibility_threshold_km,
            "precipitation_threshold_mm": precipitation_threshold_mm,
            "wind_threshold_m_s": wind_threshold_m_s,
            "day_type": day_type,
            "start_hour": start_hour,
            "end_hour": end_hour,
            "days_of_week": days_of_week,
        },
        results,
    )

weather_researcher = Agent(
    name="Weather Researcher",
    instructions="""
    You are a specialized airport weather researcher.

    Your responsibility is to investigate weather conditions
    across JFK, EWR, and LGA and examine how they coincide
    with periods of airport disruption.

    Use the available analytics tool to investigate:

    1. Temperature patterns.
    2. Precipitation and precipitation trace observations.
    3. Visibility conditions.
    4. Wind speeds and wind gusts.
    5. Differences in weather conditions across airports.
    6. Periods when adverse weather coincides with increased
       flight delays or cancellations.

    Tool selection:
    - Use analyze_weather_conditions for general weather observations.
    - Use analyze_weather_risk_profile for the frequency and percentage
      of selected adverse weather conditions.
    
    When using the risk-profile tool, report the configured thresholds and 
    valid-observation denominators. Make clear that these thresholds are 
    analytical parameters, not official aviation safety standards.

    Important methodological requirements:
    - Distinguish missing observations from zero values; do not interpret missing data as favorable weather.
    - Treat precipitation traces as distinct from zero precipitation.
    - Preserve the units and temporal grain of all weather variables; 
    do not conflate daily and hourly findings.
    - Identify gaps in observation coverage and explain how they affect interpretation.
    - Compare weather conditions across airports and examine their temporal 
    relationship with flight delays and cancellations.
    - Describe observed associations without claiming that weather caused a 
    disruption unless the evidence supports that conclusion.

    Return structured findings that the Lead Researcher can use
    in its final analysis.
    """ + FINDINGS_FORMAT,
    tools=[analyze_weather_conditions, analyze_weather_risk_profile,],
    model=RESEARCHER_MODEL,
    model_settings=SETTINGS,
)

#OPERATIONS RESEARCHER

@function_tool
@record_tool_call
def analyze_airport_operations(
    ctx: RunContextWrapper[Research],
    airports: list[str],
    start_date: str,
    end_date: str,
) -> str:
    """Analyze FAA OPSNET daily operations and operational delays, including delay causes.
 
    Args:
        airports: Any of 'JFK', 'LGA', 'EWR'.
        start_date: First day, YYYY-MM-DD, no earlier than 2026-04-01.
        end_date: Last day, YYYY-MM-DD, no later than 2026-08-31.
    """
    airports = [a.upper().strip() for a in airports]
    if error := check_scope(airports, start_date, end_date):
        return json.dumps({"error": error})
    try:
        results = airport_operations(airports=airports, start_date=start_date, end_date=end_date)
    except Exception as e:
        return json.dumps({"error": f"Could not analyze operations: {type(e).__name__}: {e}"})
    return cite(ctx, "analyze_airport_operations", "FAA OPSNET (daily)",
                {"airports": airports, "start_date": start_date, "end_date": end_date}, results)

 
operations_researcher = Agent(
    name="Operations Researcher",
    instructions="""
    You are a specialized airport operations researcher.

    Your responsibility is to investigate FAA-reported airport
    operational delays across JFK, EWR, and LGA.

    Use the available analytics tool to investigate:

    1. Total airport operations.
    2. Total operational delays.
    3. Delays per 100 airport operations.
    4. Delay causes, including weather, volume, equipment,
       runway, and other reported causes.
    5. Differences in operational performance across airports.
    6. Daily and monthly operational disruption patterns.

    Important methodological requirements:
    - Compare delay rates rather than relying only on total delays.
    - Distinguish FAA operational delays from BTS flight departure
      delays.
    - Do not assume that FAA delay categories are interchangeable
      with airline-reported departure delay categories.
    - Identify the daily aggregation grain.
    - Do not duplicate airport-day observations when interpreting
      the results.
    - Avoid unsupported causal claims.
    
    FAA OPSNET METHODOLOGY
    - FAA OPSNET observations are daily.
    - Report total operations and delays across the requested date range.
    - Do not describe results as weekday-only unless weekday filtering
    was explicitly implemented.
    - Do not infer hourly congestion from daily totals.
    - Keep FAA operational delay counts separate from BTS flight
    departure-delay statistics.
   
    Return structured findings that the Lead Researcher can use
    in its final analysis.
    """ + FINDINGS_FORMAT,
    tools=[analyze_airport_operations],
    model=RESEARCHER_MODEL,
    model_settings=SETTINGS,
)

SPECIALISTS = {
    "security": security_researcher,
    "flights": flight_researcher,
    "weather": weather_researcher,
    "operations": operations_researcher,
}


@function_tool
@record_tool_call
async def research(
    ctx: RunContextWrapper[Research],
    specialist: Literal["security", "flights", "weather", "operations"],
    airports: list[str],
    task: str,
    metrics: list[str],
    start_date: str,
    end_date: str,
    grain: Literal["daily", "hourly"],
    focus: Literal[
        "airport_comparison",
        "temporal_trends",
        "weather_association",
        "data_quality",
        "operational_breakdown",
        "other",
    ],
    day_type: Literal["all", "weekday", "weekend"] = "all",
    days_of_week: list[str] | None = None,
    start_hour: int | None = None,
    end_hour: int | None = None,
    queue_type: Literal["standard", "precheck"] | None = None,
    terminal: str | None = None,
) -> str:
    """Run a specialist research task only when its scope adds new coverage."""

    state = ctx.context
    try:
        day_type, days_of_week = normalize_day_filters(
            day_type, days_of_week
        )
        validate_hour_filters(start_hour, end_hour)
    
    except ValueError as e:
        return f"Invalid research filters: {e}"
    
    airports = sorted({a.upper().strip() for a in airports})
    if not airports or any(a not in AIRPORTS for a in airports):
        return f"Unsupported airports {airports}. Use JFK, LGA, and EWR only."


    # Normalize the scope so wording differences do not affect duplicate checks.
    normalized_metrics = tuple(sorted({
        " ".join(metric.lower().split())
        for metric in metrics
    }))

    if not normalized_metrics:
        return "No metrics were specified. Define the metrics before assigning research."

    if start_date > end_date:
        return "Invalid date range: start_date must be before or equal to end_date."

    # Scope dimensions are independent of the natural-language task description.
    scope_prefix = (
        specialist,
        start_date,
        end_date,
        grain,
        focus,
        day_type,
        tuple(days_of_week),
        start_hour,
        end_hour,
        queue_type,
        terminal,
    )
    n = len(scope_prefix)

    with state.lock:
        # Reject overlapping metric coverage within the same scope.
        for existing_scope in state.research_tasks:
            existing_prefix = existing_scope[:n]
            existing_metrics = set(existing_scope[n])

            if (
                existing_prefix == scope_prefix
                and existing_metrics.intersection(normalized_metrics)
            ):
                overlapping = sorted(
                    existing_metrics.intersection(normalized_metrics)
                )
                return (
                    "This assignment overlaps research already assigned for "
                    f"{specialist}. Already-covered metrics: {overlapping}. "
                    "Do not repeat this work. Identify a genuinely uncovered "
                    "metric, period, grain, or analytical focus instead."
                )

        if state.researchers >= MAX_RESEARCHERS:
            return "No researchers left. Synthesize the available findings."

        task_key = scope_prefix + (normalized_metrics,)
        state.research_tasks.add(task_key)

        state.researchers += 1
        researcher_number = state.researchers

    base = SPECIALISTS[specialist]
    agent = base.clone(name=f"{base.name} {researcher_number}")
    token = CURRENT_AGENT.set(agent.name)
    try:
        try:
            result = await Runner.run(
                agent,
                (
                    f"Task: {task}\n"
                    f"Research scope:\n"
                    f"- Specialist: {specialist}\n"
                    f"- Airports: {', '.join(airports)}\n"
                    f"- Metrics: {', '.join(normalized_metrics)}\n"
                    f"- Dates: {start_date} through {end_date}\n"
                    f"- Grain: {grain}\n"
                    f"- Focus: {focus}\n\n"
                    f"- Day classification: {day_type}\n"
                    f"- Specific days: {days_of_week or 'all days in classification'}\n"
                    f"- Start hour: {start_hour}\n"
                    f"- End hour: {end_hour}\n"
                    f"- Queue type: {queue_type or 'not specified'}\n"
                    f"- Terminal: {terminal or 'not specified'}\n\n"
                    "Stay within this scope. Report which metrics and comparisons "
                    "you successfully analyzed, and identify any unanswered parts."
                ),
                context=state,
                hooks=state.hooks,
                max_turns=MAX_RESEARCHER_TURNS,
            )

            output = str(result.final_output)

        except Exception as e:
            output = (
                f"RESEARCHER FAILED ({type(e).__name__}: {str(e)[:200]}). "
                "Treat this part of the question as unanswered."
            )
    
    finally:
        CURRENT_AGENT.reset(token)

    with state.lock:
        state.findings.append(
            f"[{specialist}] {task}\n"
            f"Scope: {normalized_metrics}, {start_date} to {end_date}, "
            f"{grain}, {focus}\n\n{output}"
        )

    return output

 
# --- The clarifier: turns the question into a brief, or asks the user one thing ---
 
class Brief(BaseModel):
    status: Literal["ready", "ask", "out_of_scope"]
    message_to_user: str
    intent: Literal["advice", "analysis"]
    restated_question: str
    airports: list[str]
    start_date: str
    end_date: str
    departure_time: str | None   # "HH:MM", 24-hour Eastern, advice questions only

    day_type: Literal["all", "weekday", "weekend"]
    days_of_week: list[str]

    start_hour: int | None
    end_hour: int | None

    queue_type: Literal["standard", "precheck"] | None
    terminal: str | None
    assumptions: list[str]
 
 
clarifier = Agent(
    name="Clarifier",
    instructions=f"""You are the first checkpoint of an airport departure research tool. Turn the conversation
into a research brief, or ask the user ONE short question.
 
What the data covers (and nothing else):
- Airports: JFK, LaGuardia (LGA), Newark (EWR) only.
- Dates: {DATA_START} to {DATA_END} only (spring and summer 2026). No winter data.
- Sources: TSA posted security wait times (by terminal, standard and PreCheck), BTS flight
  departure reliability, NOAA weather, FAA operational delays (daily).
- It cannot tell: live conditions today, specific airlines' lines, check-in or bag-drop
  times, other airports, or dates outside the window.
 
Set intent:
- "advice": the user is planning a trip ("how early should I arrive...").
- "analysis": the user wants comparisons or explanations about the airports.
 

Set status:
- "out_of_scope": the question needs data the tool doesn't have (other airports, dates outside the
  window, live conditions, airline-specific). In message_to_user, say plainly what it can't answer
  and suggest one related question it can answer. If part of the question is answerable, use "ready"
  for that part instead and list the limit in assumptions.

- "ask": intent is "advice" and the airport or the day and time of travel is missing.
  Ask ONE short question that covers what's missing. Never ask about PreCheck or terminals.

- "ready": otherwise. For "analysis" questions, default to all three airports and the full
  window and list those defaults in assumptions.

Terminal and queue handling (apply to every brief, regardless of status):
- If the user explicitly specifies a terminal, preserve its exact label in terminal.
  Otherwise, set terminal to null.
- If the user explicitly specifies "standard" or "PreCheck", preserve the corresponding
  value in queue_type ("standard" or "precheck").
- If the user explicitly asks to compare or analyze both queues, set queue_type to null.
- If the user does not specify a queue type, default queue_type to "standard".
- Record defaults and assumptions in assumptions.

 
If the user already answered a clarifying question, never ask again; proceed with sensible
defaults and record them in assumptions. If status is "ready", message_to_user must be "".
Fill unused optional fields with null. Dates are YYYY-MM-DD.

ADVICE QUESTIONS
- For "advice", set departure_time to the flight's scheduled departure as HH:MM in 24-hour
  Eastern time. Set days_of_week to the traveler's weekday and day_type to match. Leave
  start_hour and end_hour null; code derives the hour windows from departure_time.
- "ask" if the airport, the weekday, or the departure time is missing.
- Season: use the full data window unless the user names a month or season. A single month
  gives few observations, so say so in assumptions.

TIME DEFAULTS FOR ANALYSIS QUESTIONS
- Hours are Eastern, start-inclusive and end-exclusive: start_hour=5, end_hour=11 covers
  05:00-10:59. Always give both or neither.
- "Morning" means start_hour=5, end_hour=11 unless the user says otherwise; record it in assumptions.

FILTER APPLICATION REQUIREMENTS

For every hourly research assignment:
- Security: pass day_type, days_of_week, start_hour,
  end_hour, and queue_type.
- Flights: pass day_type, days_of_week, start_hour,
  and end_hour.
- Weather: pass day_type, days_of_week, start_hour,
  and end_hour.
- Operations: use the requested date range only.
  FAA OPSNET is daily data.

Specific days must narrow the broad day classification.
For example:
- Monday and Friday: day_type="weekday",
  days_of_week=["Monday", "Friday"].
- Saturday only: day_type="weekend",
  days_of_week=["Saturday"].
- All weekdays: day_type="weekday",
  days_of_week=[].

Never claim that a filter was applied unless the underlying
analytics query actually implements it.

Do not claim a filter was applied unless the corresponding
analytics tool accepts and implements it.
If a requested filter is unsupported, explicitly disclose this.

""",
    model=MODEL,
    model_settings=SETTINGS,
    output_type=Brief,
)


# --- The lead: plans, fans out to researchers, and checks for gaps ---

lead = Agent(
    name="Lead",
    instructions=f"""\
You lead a research team that answers questions about departures from JFK, LGA, and EWR.
You receive a brief. Your researchers can only use these sources, and only for {DATA_START}
to {DATA_END}:
 
- security: TSA posted wait times: standard and PreCheck, by terminal, daily or hourly.
- flights: BTS flight departures: delays, the share 15+ minutes late, cancellations.
- weather: NOAA hourly observations: visibility, wind, gusts, precipitation, temperature.
- operations: FAA OPSNET: daily operations, delays, and delay causes (weather, volume, equipment,
  runway, other).
1. **Initial research planning and assignment**
   Break the brief into the smallest set of independent research questions needed to answer it.
   Assign each question to the appropriate specialist. Include the following in every research assignment:
   - Specialist
   - Airports
   - Date range
   - Metrics
   - Grain
   - Analytical focus
   - Relevant filters

   Call research once per distinct research scope. Submit independent tasks in the same turn to preserve parallel execution.
   Before assigning a task, review existing findings and compare the research scope:
   - Specialist
   - Airports
   - Date range
   - Metrics
   - Grain
   - Analytical focus
   - Filters
    
    When assigning security research:
    - Pass the brief's terminal value through the terminal argument of research().
    - Pass the brief's queue_type value through the queue_type argument of research().
    - Preserve the exact terminal label supplied by the brief.
    - If the brief specifies a terminal but not a queue type, use the brief's
    queue_type default.
    - Do not pass terminal or queue_type filters to flight, weather, or
    operations researchers.
    - If comparing multiple terminals, create separate security assignments
    with the appropriate terminal filter for each.
   
   Do not assign a task that substantially overlaps with research already completed or assigned.
   Different wording does not make an existing research question new.
   A second researcher is justified only when it investigates a genuinely uncovered question, such as:
   - A metric not previously analyzed.
   - A distinct date range or time period.
   - A different analytical grain.
   - A different analytical focus or comparison.
   - A specific unanswered question resulting from an earlier failed or incomplete query.
   
   Advice questions usually need security and flights. Questions about why disruptions happen may also need weather and operations.
    -For advice questions, make one round of assignments in the same turn: security, flights,
   and weather (add operations only if the question asks why). Use grain="hourly". If the
   prompt contains an "Hour windows" block, use those exact windows: security assignments
   take the security window; flights and weather assignments take the flight window. Pass
   days_of_week, day_type, and queue_type from the brief, and name the airports in every
   assignment.

2. **Follow-up research and gap identification**
   After receiving the initial findings, identify only genuinely unanswered parts of the original brief.
   Before calling research again:
   - State internally what question remains unanswered.
   - Identify which part of the existing research failed to address it.
   - Specify how the new assignment differs from existing research.
   - Assign only the missing metrics or analysis, not the entire original task again.
  
    You may call research again for genuinely missing coverage, at most once after the initial research round.
   Never repeat an identical or substantially overlapping specialist assignment merely because the first result was inconvenient, incomplete, or unsuccessful.
   If a researcher reports a failed query, treat that part of the brief as unanswered. A retry is permitted only when it addresses the failure or investigates a distinct missing scope.
   If the available evidence is insufficient, report the limitation instead of repeatedly querying the same data.

3. **Evidence interpretation and comparison**
   Only compare sources when the findings support it.
   These airports share weather and airspace, so do not treat them as independent.
   Correlation is not causation. Do not claim that weather, security waits, or operational congestion caused flight delays unless the evidence supports that conclusion.
   Preserve the original grain of each dataset. Do not treat airport-day observations as independent hourly observations or imply individual passenger-to-flight relationships.

4. **Completion and handoff**
   When the original brief is adequately covered, reply "DONE", followed by one short paragraph explaining anything the writer must disclose about:
   - Missing data or incomplete coverage.
   - Failed researcher queries.
   - Important methodological limitations.
   - Questions the available data cannot answer.
   Never answer from your own knowledge. All factual claims and numerical findings must come from researcher findings and their registered evidence.
   Do not launch additional researchers once the brief is covered.
 
Never answer from your own knowledge. Numbers come only from researcher findings.""",
    model=MODEL,
    model_settings=LEAD_SETTINGS,
    tools=[research],
)

# --- The writer: one call, after the research ends ---


writer = Agent(
    name="Writer",
    instructions="""\
You write the final answer for a traveler or analyst, using ONLY the findings you're given.

If intent is "advice", write a card under 300 words with exactly these four labeled sections,
in this order, and nothing else:

**Arrive**
- Use the "Computed arrival times" block exactly: the typical arrive-by time and the
  conservative arrive-by time, citing the row's evidence ID.
- For airport-wide estimates, report the typical (P50) and conservative (P90) arrive-by
  times and the posted-wait P50 and P90 behind them.
- For terminal-specific estimates, report the typical arrive-by time and the
  conservative arrive-by time. The typical wait is the mean of the hourly P50 estimates;
  the conservative wait is the maximum hourly P95 in the security window. Label them
  accurately. Do not call either a pooled percentile.
- State observed_hours. If thin_sample is true, say the evidence is thin.
- When terminal-specific evidence contains only a small number of observed
  hours, explicitly describe the arrival times as illustrative historical
  estimates, not validated safe arrival recommendations.
- State the assumptions (security window, other overhead) as assumptions, not data.
- If the block says arrival times are not available, say so. Do not estimate them.
- If terminal-specific hourly evidence is unavailable, say the terminal-specific
  arrival estimate could not be calculated. Never substitute airport-wide or
  daily-average values.
- Label the conservative percentile according to the evidence:
  airport-wide estimates use P90; terminal-specific estimates use the
  maximum hourly P95. Never call these equivalent.

**Disruption risk**
- Share of flights departing 15+ minutes late and the cancellation rate for this airport,
  weekday, and hour, with the number of flights. The data has no 30-minute metric; say
  "15+ minutes".

**What's driving it**
- Only drivers the findings support (weather conditions in this slot, security waits at
  that hour). FAA data is daily, so never describe it as specific to the hour or weekday.
  Say "coincides with" or "is associated with", never "causes".
- Weather evidence must cover comparable dates and hours to the flight-risk
  evidence before you discuss weather as a potential explanation for that
  flight-risk pattern.
- General monthly or daily weather observations cannot be described as
  conditions in a specific weekday/hour slot.
- If weather evidence does not match the flight-risk filters, omit conclusions
  about whether weather explains the disruptions. State that comparable
  weather evidence is unavailable.
- Do not describe weather as "stable" or "favorable" unless the findings
  support that characterization.
- Clearly distinguish historical pattern estimates from observations
  on the user's specific travel date. If research uses matching
  weekdays across a date range, say so.

- Do not describe two metrics as coinciding unless their date and
  time windows overlap. Security arrival windows may provide
  planning context, but do not imply they explain flight disruptions.

- When reporting weather thresholds, distinguish valid observations
  from missing observations. Never generalize a threshold result
  across hours with missing measurements.

**What the data can't tell you**
- Live conditions, airline-specific effects, checkpoint or terminal-level lines beyond
  posted estimates, check-in/bag-drop/gate time, dates outside April-August 2026, and
  any thin-sample or missing-evidence limit.

If intent is "analysis":
- One short paragraph that answers the question directly.
- Then "What's behind it" (weather and operations), only if findings support it.
- Always end with "What the data can't tell you".

Rules for both:
- P50 and P90 are percentiles of hourly airport-level weighted security wait estimates,
  not individual passenger wait-time percentiles. Security waits are posted estimates, not
  independently measured queue times.
- Every factual sentence containing numbers must include the exact evidence ID from the
  authoritative evidence registry, formatted [E1], [E2]. Cite each ID in its own brackets,
  like [E1][E4]. Never group IDs in one bracket. Never use placeholders such as [E#].
- Never cite an ID that is not in the registry. Never invent a number or an ID. If you
  cannot support a claim with a valid ID, leave it out or say the evidence is insufficient.
- If a researcher failed or the findings don't answer part of the question, say so.
- Don't promise outcomes, and don't give advice the findings don't support.
- Plain, specific sentences. No hype words. Analysis answers stay under about 350 words.
- Report flight risk only as the pooled rate for the slot. Never present a single day's or
  hour's extreme (the worst day) as typical risk. If only per-day rows exist, say the pooled
  rate is unavailable.
- In "What's driving it", state an association only when findings compare conditions.
  Never infer "stable performance" from the absence of bad-weather observations. If weather
  indicators were rarely or never triggered in the slot, say so and say they do not explain
  the disruptions seen.
- Never describe a number as associated with itself.
""",
    model=MODEL,
    model_settings=SETTINGS,
)

def format_evidence_registry(state: Research) -> str:
    """Create the authoritative list of evidence IDs available to the Writer."""

    with state.lock:
        records = list(state.evidence)

    if not records:
        return "(No evidence was collected.)"

    lines = []

    for record in records:
        params = json.dumps(record["params"], default=str)

        lines.append(
            f"[{record['id']}] "
            f"Source: {record['source']} | "
            f"Tool: {record['tool']} | "
            f"Parameters: {params}"
        )

    return "\n".join(lines)

CITATION_GROUP = re.compile(r"\[(E[^\]]*)\]")
VALID_ID = re.compile(r"E\d+")


def normalize_citations(report: str) -> str:
    """Rewrite grouped citations: [E1, E4, E5] -> [E1][E4][E5]. Leaves bad ones alone."""
    def split(m: re.Match) -> str:
        parts = [p.strip() for p in re.split(r"[,;]", m.group(1))]
        if all(VALID_ID.fullmatch(p) for p in parts):
            return "".join(f"[{p}]" for p in parts)
        return m.group(0)
    return CITATION_GROUP.sub(split, report)


def citation_problems(report: str, state: Research) -> list[str]:
    """Return a list of citation problems (empty if the report is clean)."""
    with state.lock:
        valid_ids = {record["id"] for record in state.evidence}
    problems = []
    for reference in CITATION_GROUP.findall(report):
        if not VALID_ID.fullmatch(reference):
            problems.append(f"Malformed citation: [{reference}]")
        elif reference not in valid_ids:
            problems.append(f"Unknown evidence ID: [{reference}]")
    return problems


def strip_bad_citations(report: str, state: Research) -> str:
    """Last resort: drop any bracketed citation that is not a valid evidence ID."""
    with state.lock:
        valid_ids = {record["id"] for record in state.evidence}
    return CITATION_GROUP.sub(
        lambda m: m.group(0) if m.group(1) in valid_ids else "", report
    )

def evidence_appendix(report: str, state: Research) -> str:
    """Deterministic list of the evidence the report cites. Catches invented ids."""
    cited = sorted(set(re.findall(r"\bE\d+\b", report)), key=lambda e: int(e[1:]))
    by_id = {e["id"]: e for e in state.evidence}
    lines = []
    for eid in cited:
        e = by_id.get(eid)
        if e is None:
            lines.append(f"- **[{eid}]** not found in this run's tool results; disregard this citation.")
        else:
            args = ", ".join(f"{k}={v}" for k, v in e["params"].items())
            lines.append(f"- **[{eid}]** {e['source']}: `{e['tool']}({args})`")
    return "\n\n---\n**Evidence**\n\n" + "\n".join(lines) if lines else ""

def advice_windows(brief) -> dict | None:
    """Hour windows (Eastern, start-inclusive, end-exclusive) derived from departure_time."""
    if brief.intent != "advice" or not brief.departure_time:
        return None
    try:
        hour = int(brief.departure_time.split(":")[0])
    except ValueError:
        return None
    if not 0 <= hour <= 23:
        return None
    return {
        "security": (max(hour - SECURITY_LEAD_HOURS, 0), max(hour, 1)),
        "flight": (hour, hour + 1),
    }

def arrival_windows(brief, state: Research) -> list[dict]:
    """Compute arrival times from matching airport-wide or terminal-level evidence."""
    windows = advice_windows(brief)
    if not windows:
        return []

    hh, mm = brief.departure_time.split(":")
    departure = int(hh) * 60 + int(mm)
    sec_start, sec_end = windows["security"]
    queue = brief.queue_type or "standard"

    try:
        day_type, brief_days = normalize_day_filters(
            brief.day_type, brief.days_of_week
        )
        requested_start = date.fromisoformat(brief.start_date)
        requested_end = date.fromisoformat(brief.end_date)
    except ValueError:
        return []

    def hhmm(minutes: int) -> str:
        label = f"{minutes % 1440 // 60:02d}:{minutes % 1440 % 60:02d}"
        return label + " (previous day)" if minutes < 0 else label

    # ---------------------------------------------------------
    # PATH 1: Terminal-specific hourly evidence
    # ---------------------------------------------------------
    if brief.terminal:
        def normalize_terminal(value):
            return (
                str(value or "")
                .strip()
                .lower()
                .removeprefix("terminal")
                .strip()
            )

        requested_terminal = normalize_terminal(brief.terminal)

        with state.lock:
            records = [
                e for e in state.evidence
                if e["tool"] == "analyze_security_patterns"
                and e.get("rows")
                and not e.get("truncated", False)
                and normalize_terminal(
                    e["params"].get("terminal")
                ) == requested_terminal
                and e["params"].get("queue_type") == queue
            ]

        # Prefer the most narrowly scoped complete evidence record.
        records = [
            e for e in records
            if e["params"].get("start_date")
            and e["params"].get("end_date")
        ]

        if not records:
            return []

        def date_span(record):
            start = date.fromisoformat(record["params"]["start_date"])
            end = date.fromisoformat(record["params"]["end_date"])
            return (end - start).days

        records.sort(key=date_span)
        rec = records[0]

        # Do not use a record outside the requested date range.
        rec_start = date.fromisoformat(rec["params"]["start_date"])
        rec_end = date.fromisoformat(rec["params"]["end_date"])

        if rec_start > requested_end or rec_end < requested_start:
            return []

        rows_by_airport = {}

        for row in rec["rows"]:
            if row.get("airport") not in brief.airports:
                continue

            if normalize_terminal(row.get("terminal")) != requested_terminal:
                continue

            if row.get("queue_type") != queue:
                continue

            timestamp = str(row.get("hour_et", ""))
            try:
                row_date = date.fromisoformat(timestamp[:10])
                row_hour = int(timestamp[11:13])
            except (ValueError, IndexError):
                continue

            if not requested_start <= row_date <= requested_end:
                continue

            if not sec_start <= row_hour < sec_end:
                continue

            if day_type == "weekday" and row_date.weekday() >= 5:
                continue

            if day_type == "weekend" and row_date.weekday() < 5:
                continue

            if brief_days and row_date.strftime("%A") not in brief_days:
                continue

            p50 = row.get("p50_wait")
            p95 = row.get("p95_wait")

            if p50 is None or p95 is None:
                continue

            rows_by_airport.setdefault(row["airport"], []).append({
                "date": row_date,
                "p50": float(p50),
                "p95": float(p95),
            })

        out = []

        for airport, rows in sorted(rows_by_airport.items()):
            if not rows:
                continue

            # Terminal-specific calculations:
            # Typical = mean of hourly P50 estimates.
            # Conservative = maximum hourly P95 in the security window.
            typical_wait = sum(r["p50"] for r in rows) / len(rows)
            conservative_wait = max(r["p95"] for r in rows)

            typical = departure - round(typical_wait) - OTHER_OVERHEAD_MIN
            conservative = (
                departure - round(conservative_wait) - OTHER_OVERHEAD_MIN
            )

            out.append({
                "airport": airport,
                "terminal": brief.terminal,
                "queue_type": queue,
                "evidence_id": rec["id"],
                "departure_time": brief.departure_time,
                "typical_arrive_by": hhmm(typical),
                "conservative_arrive_by": hhmm(conservative),
                "typical_wait_min": round(typical_wait, 1),
                "conservative_wait_min": round(conservative_wait, 1),
                "typical_wait_method": "mean of hourly P50 estimates",
                "conservative_wait_method": "maximum hourly P95",
                "observed_hours": len(rows),
                "observed_days": len({r["date"] for r in rows}),
                "thin_sample": len(rows) < MIN_OBSERVED_HOURS,
                "security_window": f"{sec_start:02d}:00-{sec_end:02d}:00",
                "other_overhead_min_assumed": OTHER_OVERHEAD_MIN,
            })

        return out

    # ---------------------------------------------------------
    # PATH 2: Airport-wide arrival profile (existing behavior)
    # ---------------------------------------------------------
    with state.lock:
        records = [
            e for e in state.evidence
            if e["tool"] == "analyze_security_arrival_profile"
            and e.get("summary")
            and e["params"].get("start_hour") == sec_start
            and e["params"].get("end_hour") == sec_end
            and e["params"].get("queue_type") == queue
            and e["params"].get("days_of_week") == brief_days
        ]

    best = {}

    for rec in records:
        for row in rec["summary"]:
            if (
                row["airport"] in brief.airports
                and row.get("p50_wait_min") is not None
                and row.get("p90_wait_min") is not None
            ):
                best[row["airport"]] = (rec, row)

    out = []

    for airport, (rec, row) in sorted(best.items()):
        typical = departure - round(row["p50_wait_min"]) - OTHER_OVERHEAD_MIN
        conservative = departure - round(row["p90_wait_min"]) - OTHER_OVERHEAD_MIN

        out.append({
            "airport": airport,
            "evidence_id": rec["id"],
            "departure_time": brief.departure_time,
            "typical_arrive_by": hhmm(typical),
            "conservative_p90_arrive_by": hhmm(conservative),
            "p50_wait_min": round(row["p50_wait_min"], 1),
            "p90_wait_min": round(row["p90_wait_min"], 1),
            "observed_hours": row["observed_hours"],
            "observed_days": row["observed_days"],
            "thin_sample": row["observed_hours"] < MIN_OBSERVED_HOURS,
            "other_overhead_min_assumed": OTHER_OVERHEAD_MIN,
        })

    return out
async def deep_research(conversation: list[str], state: Research) -> dict:
    """Run the whole pipeline. Returns {"type": "clarify" | "done" | "partial", "text": markdown}."""
    brief = (await Runner.run(clarifier, "\n".join(conversation),
                              context=state, hooks=state.hooks)).final_output
    if brief.status == "ask":
        return {"type": "clarify", "text": brief.message_to_user}
    if brief.status == "out_of_scope":
        return {"type": "done", "text": brief.message_to_user}
    brief.airports = [a.upper() for a in brief.airports] or sorted(AIRPORTS)

    # Derive hour windows for advice questions, and record the assumptions the card must show.
    windows = advice_windows(brief)
    if windows:
        s0, s1 = windows["security"]
        brief.assumptions.append(
            f"Security waits are sampled over the {SECURITY_LEAD_HOURS} hours before "
            f"departure ({s0:02d}:00-{s1:02d}:00 Eastern), plus {OTHER_OVERHEAD_MIN} minutes "
            "for check-in, bag drop, and walking to the gate. The window and the overhead "
            "are modeling assumptions, not data."
        )
        if int(brief.departure_time.split(":")[0]) < SECURITY_LEAD_HOURS:
            brief.assumptions.append("Early departure: the security window is clipped at midnight.")

    # 1. Research: plan, fan out, check for gaps
    prompt = f"Question: {brief.restated_question}\n\nBrief:\n{brief.model_dump_json(indent=2)}"
    if windows:
        (s0, s1), (f0, f1) = windows["security"], windows["flight"]
        prompt += (
            "\n\nHour windows (Eastern, start-inclusive, end-exclusive):\n"
            f"- security: start_hour={s0}, end_hour={s1}\n"
            f"- flights and weather: start_hour={f0}, end_hour={f1}"
        )
    try:
        lead_run = await Runner.run(lead, prompt, context=state, hooks=state.hooks, max_turns=12)
        lead_notes = str(lead_run.final_output)
    except Exception as e:
        lead_notes = (f"The Lead stopped early ({type(e).__name__}). "
                      "Treat any uncovered part of the brief as unanswered.")

    # 2. Write
    findings = "\n\n---\n\n".join(state.findings) or "(no findings)"
    evidence_registry = format_evidence_registry(state)

    arrival_block = ""
    if brief.intent == "advice":
        arrival = arrival_windows(brief, state)
        arrival_block = (
            "Computed arrival times (use exactly; cite each row's evidence_id):\n"
            + json.dumps(arrival, indent=2) + "\n\n"
            if arrival else
            "Computed arrival times: NOT AVAILABLE (no matching security evidence). "
            "Say the arrival window could not be computed. Do not estimate one.\n\n"
        )

    writer_prompt = (
        f"Question: {brief.restated_question}\n"
        f"Intent: {brief.intent}\n"
        f"Assumptions: {'; '.join(brief.assumptions) or 'none'}\n\n"
        f"Lead's notes on limits:\n{lead_notes}\n\n"
        f"{arrival_block}"
        f"Research findings:\n\n{findings}\n\n"
        f"AUTHORITATIVE EVIDENCE REGISTRY:\n{evidence_registry}\n\n"
        "Citation requirements:\n"
        "- You may ONLY cite IDs listed in the authoritative evidence registry.\n"
        "- Copy each ID exactly, including its E prefix.\n"
        "- Cite each ID in its own brackets, like [E1][E4]. Never group IDs in one bracket.\n"
        "- Do not invent, modify, or guess evidence IDs.\n"
        "- Every factual statement containing numbers must cite its evidence ID.\n"
        "- If a finding cannot be supported by a valid evidence ID, leave it out "
        "or explicitly state that the evidence is insufficient."
    )

    try:
        report = await Runner.run(writer, writer_prompt, context=state, hooks=state.hooks)
        text = normalize_citations(str(report.final_output))
        problems = citation_problems(text, state)

        if problems:
            retry = await Runner.run(
                writer,
                writer_prompt + "\n\nYour previous draft had citation problems:\n- "
                + "\n- ".join(problems)
                + "\nRewrite it. Cite each ID in its own brackets, like [E1][E4], "
                "using only IDs from the authoritative evidence registry.",
                context=state, hooks=state.hooks,
            )
            text = normalize_citations(str(retry.final_output))
            problems = citation_problems(text, state)

        if problems:
            text = strip_bad_citations(text, state)
            text += "\n\n_Note: some citations could not be verified and were removed._"

        return {"type": "done", "text": text + evidence_appendix(text, state)}

    except Exception as e:
        return {
            "type": "partial",
            "text": (
                "## Research completed; final report unavailable\n\n"
                "The specialist researchers completed their work, but the Writer could not "
                f"generate the final recommendation. Reason: {type(e).__name__}: {str(e)[:250]}\n\n"
                f"### Research findings\n\n{findings}\n\n"
                f"### Lead's limitations and caveats\n\n{lead_notes}"
            ),
        }


# --- FastAPI App ---

HERE = Path(__file__).parent

# run_id -> every agent's context, in order. In-memory, single process. The context panel reads it.
sessions: dict[str, AgentContexts] = {}

# session_id -> conversation history across clarification requests.
conversation_sessions: dict[str, list[str]] = {}

app = FastAPI()
add_context_panel(app, sessions)


@app.get("/")
def index():
    # no-cache: browsers otherwise keep serving an old page after a redeploy
    return FileResponse(HERE / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/run")
async def run(question: str, session_id: str | None = None):
    """Research a question while preserving clarification history."""

    # Create a new conversation session if this is the first request.
    if not session_id or session_id not in conversation_sessions:
        session_id = str(uuid.uuid4())
        conversation_sessions[session_id] = []

    # Add the user's latest message to the conversation.
    conversation_sessions[session_id].append(question)

    # Copy the conversation so this run has a stable history.
    conversation = conversation_sessions[session_id].copy()

    # Each research run gets its own ID and agent context.
    run_id = str(uuid.uuid4())
    sessions[run_id] = AgentContexts()

    queue: asyncio.Queue = asyncio.Queue()
    hooks = PanelHooks(sessions[run_id], queue.put_nowait)

    # Create fresh research state for this run.
    state = Research(hooks=hooks)

    async def work():
        try:
            result = await deep_research(conversation, state)

            if result["type"] == "clarify":
                # Keep the history, including the question, for the user's next reply.
                conversation_sessions[session_id].append(f"Assistant asked: {result['text']}")
            else:
                # done, partial, or out of scope: the conversation is over.
                conversation_sessions.pop(session_id, None)

            queue.put_nowait({
                "type": "done",
                "markdown": result["text"],
                "result_type": result["type"],
                "tool_calls": state.tool_calls,
            })

        except Exception as e:
            conversation_sessions.pop(session_id, None)
            queue.put_nowait({
                "type": "error",
                "message": f"{type(e).__name__}: {str(e)[:500]}",
            })

    task = asyncio.create_task(work())

    async def events():
        try:
            yield f"data: {json.dumps({
                'type': 'start',
                'run_id': run_id,
                'session_id': session_id
            })}\n\n"

            while True:
                event = await queue.get()
                yield f"data: {json.dumps(event, default=str)}\n\n"

                if event["type"] in ("done", "error"):
                    break

        finally:
            task.cancel()

    return StreamingResponse(events(), media_type="text/event-stream")

class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    response: str
    session_id: str
    tool_calls: list[dict]


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    session_id = request.session_id or str(uuid.uuid4())
    history = conversation_sessions.setdefault(session_id, [])
    history.append(request.message)

    run_id = str(uuid.uuid4())
    sessions[run_id] = AgentContexts()
    hooks = PanelHooks(sessions[run_id], lambda event: None)   # unchanged from your /run
    state = Research(hooks=hooks)

    try:
        result = await deep_research(history.copy(), state)
        response = result["text"]
        if result["type"] == "clarify":
            history.append(f"Assistant asked: {response}")   # keep going on the next turn
        else:
            conversation_sessions.pop(session_id, None)
    except Exception as e:
        conversation_sessions.pop(session_id, None)
        response = f"Research failed: {type(e).__name__}: {str(e)[:300]}"

    return ChatResponse(response=response, session_id=session_id, tool_calls=state.tool_calls)

@app.post("/clear")
def clear(session_id: str | None = None):
    conversation_sessions.pop(session_id, None)
    return {"status": "ok"}
if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
