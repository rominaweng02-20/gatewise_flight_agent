# GateWise - NYC Airport Research Agent

---

## 1. Project Overview

**GateWise** is an AI-powered airport departure research assistant that investigates airport security wait times, flight reliability, weather, and airport operations to help travelers plan ahead for a seamless departure experience. Gatewise can help assist in planning how early to arrive and how much disruption risk to plan for.

GateWsie addresses this problem through a multi-agent research system that investigates data sources in parallel, combines their findings, and produces a concise, evidence-backed response with citations.

### Primary Target User:

Any air traveler planning to travel from any of the airports in NYC (JFK, LGA, and EWR)

### Scope:

GateWise currently analyzes only the following:

- Airports: John F. Kennedy International (JFK), LaGuardia (LGA), and Newark Liberty International (EWR).
- Date coverage: April 1, 2026 – August 31, 2026.
- Data frequency: Daily and hourly, depending on the source and analysis.

GateWise is a historical research tool, not a live airport monitoring service. It cannot provide current security-line conditions, airline-specific wait times, check-in or bag-drop estimates, or recommendations for airports outside its supported coverage.

---

## 2. Data Sources:

GateWise combines four independent data sources to investigate airport departure conditions

| Data source | Information used | Analytical purpose |
|---|---|---|
| TSA posted security wait times | Standard and PreCheck wait estimates by airport and terminal | Compare security wait distributions and identify time-based patterns |
| Bureau of Transportation Statistics (BTS) | Flight departure delays, cancellations, and percentage of flights departing 15+ minutes late | Measure historical flight departure reliability |
| NOAA National Centers for Environmental Information (NCEI) | Hourly weather observations, including visibility, wind, gusts, precipitation, and temperature | Examine weather conditions associated with airport disruptions |
| FAA OPSNET | Daily airport operations, operational delays, and reported delay causes | Compare airport operational activity and disruption patterns |

### Data Provenance and Loading

**TSA Security Wait Times**

- Source: Hugging Face dataset `digitalhen/us-airport-wait-times`.
- Used fields include posted standard and PreCheck wait estimates, airport, terminal, and timestamps.
- Analytics function: `security_patterns()`.

**BTS Flight Reliability**

- Source: Bureau of Transportation Statistics, TranStats On-Time Performance data.
- Used to analyze departure delays, cancellations, and the share of classified departed flights that departed at least 15 minutes late.
- Analytics function: `flight_reliability()`.

**NOAA Weather**

- Source: NOAA National Centers for Environmental Information hourly observations.
- Used fields include temperature, precipitation, visibility, wind speed, and wind gusts.
- Analytics function: `weather_conditions()`.

**FAA Airport Operations**

- Source: Federal Aviation Administration OPSNET.
- Used to analyze daily airport operations, operational delays, and reported delay categories, including weather, volume, equipment, runway, and other causes.
- Analytics function: `airport_operations()`.

### Loading and Reproducing the Analysis

The source datasets are processed by the project's analytics module and exposed to the research agents through Python tools.

The main application imports the following analytical functions from `src.analytics`:

- `security_patterns()`
- `flight_reliability()`
- `weather_conditions()`
- `airport_operations()`
- `airport_overview()`
- `hourly_airport_patterns()`

To reproduce the application: First, obtain the source datasets from the providers listed above and then prepare the datasets in the format expected by the project's `src.analytics` module.

---

## 3. Multi-Agent Research Architecture

GateReady uses a Deep Research architecture in which specialized agents investigate different aspects of an airport departure question.

| Agent | Responsibility |
|---|---|
| Clarifier | Determines the user's intent, identifies missing information, and establishes the research scope |
| Lead Researcher | Breaks the question into independent research tasks, assigns specialists, identifies evidence gaps, and coordinates follow-up research |
| Security Researcher | Investigates TSA posted security wait estimates |
| Flight Researcher | Analyzes BTS departure delays and cancellations |
| Weather Researcher | Examines NOAA weather observations and their association with disruptions |
| Operations Researcher | Investigates FAA airport operations and operational delay causes |
| Writer | Synthesizes findings into a concise response with evidence citations |

The Lead Researcher can assign multiple independent research tasks in the same turn, allowing specialist agents to work in parallel. Each researcher has a distinct responsibility and returns structured findings to the Lead.

After the initial research round, the Lead identifies unanswered parts of the question and can conduct one additional round of targeted research. The Writer then combines the findings into a final response.

### Evidence and Citation Handling

Each successful analytical tool call registers an evidence record with:

- A unique evidence ID.
- The source dataset.
- The analytical tool used.
- The parameters used, including airport and date range.

The Writer uses this evidence registry to cite numerical findings in the final answer. A deterministic validation step checks that cited evidence IDs exist in the current research run.

This allows users to trace claims back to the underlying data and analytical calls.

---

## 4. Sample Queries and Expected Results

### Sample Query 1:

**Query:**

> How early should I arrive at JFK?
> I have a flight departing from Terminal 4 on July 15, 2026 at 8:00 AM.

**Expected Answer:**

GateWise combines terminal-specific security estimates with historical flight reliability and weather data to support arrival planning.

- **Security:** For JFK Terminal 4 on July 15, 2026, standard-security estimates were:
  - 6:00 AM: P50 = 24 minutes; P95 = 28 minutes.
  - 7:00 AM: P50 = 14 minutes; P95 = 26 minutes.
- **Flight reliability:** For Wednesday 8:00–9:00 AM departures in July, 10.0% of scheduled flights were canceled (13/130), while 20.5% of classified departed flights were at least 15 minutes late (24/117).
- **Weather:** No valid observations were available to assess high winds or precipitation. This indicates insufficient evidence, not an absence of weather risk.

**Illustrative arrival calculation:**

Using the largest observed P95 security estimate (28 minutes) and an assumed 45 minutes for check-in, baggage, and walking:

8:00 AM − 28 minutes − 45 minutes = **6:47 AM arrival**

This is an illustrative planning estimate, not a validated safe-arrival recommendation. The 45-minute overhead is an assumption, and posted security estimates do not guarantee individual wait times.

**Limitations:**

- July 15 security observations are distinct from flight statistics aggregated across Wednesdays in July.
- Historical flight rates are context, not predictions for an individual flight.
- Security waits should not be presented as causing flight delays.
- Missing weather observations do not mean zero weather risk.
- The data does not provide live conditions, actual individual queue times, or measured check-in and walking times.

**Underlying Data and Analytical Tools:**

| Evidence | Research area | Source / table | Tool call |
|---|---|---|---|
| E1 | Security wait times | TSA, `security_airport_hourly` | `analyze_security_arrival_profile(airports=['JFK'], terminal=4, start_date=2026-07-15, end_date=2026-07-15, start_hour=<6>, end_hour=<7>, queue_type=standard)` |
| E2 | Flight reliability | BTS On-Time Performance, `flight_hourly` | `analyze_flight_risk_profile(airports=['JFK'], start_date=2026-07-01, end_date=2026-07-31, days_of_week=['Wednesday'], start_hour=8, end_hour=9)` |
| E3 | Weather conditions | NOAA NCEI, `weather_hourly_local` | `analyze_weather_risk_profile(airports=['JFK'], <dates>, <hours>, <thresholds>)` |

**Baseline: Same Model, No Tools and No System Prompt**

> That sounds like you are planning well ahead! A Wednesday morning departure from JFK's busy Terminal 4 requires a bit of strategy.
>
> Here is a recommended timeline and some key tips to keep in mind for your departure on **July 15, 2026**:
>
> ### **Recommended Timeline**
>
> - **For International Flights:** Plan to arrive at Terminal 4 by **5:00 AM** (3 hours prior).
> - **For Domestic Flights:** Plan to arrive at Terminal 4 by **6:00 AM** (2 hours prior).
>
> *Note: Terminal 4 is one of the largest terminals at JFK (major hub for Delta, as well as many international airlines like Emirates, Singapore, and Virgin Atlantic). The walk to the furthest gates (especially the B gates) can take 15 to 20 minutes even after you pass security.*
>
> ### **How to prepare as the date approaches:**
>
> 1. **TSA PreCheck / CLEAR:** If you have these, they are highly recommended for T4, as morning rush hours (6:00 AM to 8:00 AM) can have very long standard security lines.
> 2. **Transportation:**
>    - If taking a rideshare (Uber/Lyft) or taxi from NYC, aim to leave by 4:15 AM – 5:15 AM (depending on your starting point) to avoid any early morning construction or highway bottlenecks.
>    - If taking the **LIRR or Subway to Jamaica Station**, the AirTrain runs 24/7 and takes about 15 minutes from Jamaica to Terminal 4.
> 3. **Lounge Access:** Terminal 4 has some of the best lounges at JFK, including the Delta Sky Club, American Express Centurion Lounge, and Chase Sapphire Lounge. If you have access, arriving early to grab breakfast is highly recommended.

---

### Sample Query 2: Which NYC-area airport offers the most predictable 9 AM departure?

**Query:**

> I'm deciding between JFK, LaGuardia, and Newark for a 9 am departure. Which airport has historically offered the most predictable departure experience, considering security wait times, flight delays, and cancellations?

**Expected answer:**

GateWise should compare JFK, LaGuardia (LGA), and Newark (EWR) using historical data from April 1 through August 31, 2026, focusing on departures around 9 AM.

LGA is the most predictable for security and EWR is the most reliable for flights. JFK is the weakest on both.

- **Security (standard queue, 8–10 AM, Apr 1–Aug 31, 2026):**
  - LGA: mean wait 4.97 min; P90 8.65 min (287 observed hours). The most predictable security experience.
  - JFK: mean wait 13.37 min. The longest of the three.
- **Flight reliability (8–10 AM scheduled departures):**
  - EWR: mean departure delay 4.72 min; 11.68% of departed flights 15+ min late; 1.52% cancellation rate (6,370 scheduled flights). The most reliable flight operations.
  - JFK: mean departure delay 8.67 min; 2.74% cancellation rate (6,303 scheduled flights). The least reliable.
- **Weather (does not explain the disruptions):** High winds (≥10 m/s) occurred in under 3.93% of observations and low visibility (<5 km) in under 2.30%. Precipitation ≥1 mm was recorded in 20.83% of 24 valid records at EWR, 30.00% of 40 at JFK, and 10.81% of 111 at LGA. The observation counts differ widely, which points to missing data rather than a true weather pattern.
- **Conclusion:** JFK is the least predictable option. The choice between LGA and EWR depends on whether security-line predictability or flight reliability matters more.

**Limitations:**

- Historical only (Apr 1–Aug 31, 2026), standard queues only, with the 8–10 AM hourly window used as a proxy for a 9 AM departure.
- Security figures are hourly airport-level weighted posted estimates, not individual passenger waits.
- Late-departure shares and average delays cover departed flights only. Cancellation rates use all scheduled flights.
- Delays over 30 minutes are not available in this dataset.
- Does not cover live conditions, airline-specific differences, terminal-level queues, or check-in, bag-drop, and gate-walk time.

**Underlying Data and Analytical Tools:**

| Evidence | Research area | Source / table | Tool call |
|---|---|---|---|
| E1 | Security wait times | TSA, `security_airport_hourly` | `analyze_security_arrival_profile(airports=['EWR','JFK','LGA'], start_date=2026-04-01, end_date=2026-08-31, start_hour=8, end_hour=10, queue_type=standard)` |
| E3 | Weather conditions | NOAA NCEI, `weather_hourly_local` | `analyze_weather_risk_profile(airports=['EWR','JFK','LGA'], start_date=2026-04-01, end_date=2026-08-31, start_hour=8, end_hour=10, visibility_threshold_km=5.0, precipitation_threshold_mm=1.0, wind_threshold_m_s=10.0)` |
| E4 | Flight delays and cancellations | BTS On-Time Performance, `flight_hourly` | `analyze_flight_risk_profile(airports=['EWR','JFK','LGA'], start_date=2026-04-01, end_date=2026-08-31, start_hour=8, end_hour=10)` |

**Follow-Up:**

> What terminal in EWR do you recommend?

**Expected answer:**

GateWise should compare EWR Terminals A, B, and C using historical TSA data from April 1–August 31, 2026.

- **Terminal A:** Daily weighted average standard wait ranged from 1.40 to 6.82 minutes across Apr 1–Aug 31, 2026 (E6). Its peak hourly average in the sampled early-April data was 20.80 minutes, on April 12 (E2).
- **Terminal B:** Hourly standard waits peaked at 37.24 minutes on April 5, 2026 (E5).
- **Terminal C:** Hourly standard waits peaked at 36.62 minutes on April 18, 2026 (E4).
- **Time of day:** Terminals B and C show higher averages in the afternoon, with peaks around 15:00 (E4, E5).
- **Flight reliability (airport-wide, not by terminal):** Reliability varies by departure hour rather than by terminal. On April 1, 2026, the 05:00 ET hour had 0% cancellations and 0% of flights 15+ min late. The 16:00 ET hour had 14.81% of flights 15+ min late, and the 22:00 ET hour had a 33.33% cancellation rate (E1).
- **Weather:** Hourly observations ranged from -1.1 °C to 32.2 °C with precipitation up to 3.0 mm (E3). They are not linked to flight reliability because the data does not compare overlapping conditions.

**Limitations:**

- BTS data is airport-level, so it cannot show delay or cancellation differences between terminals.
- Hourly security, flight, and weather results were truncated to 400 rows, so the hourly figures are early-season samples, mostly from April 2026.
- Terminal A's figures are daily averages from the full period, while the B and C figures are hourly peaks from the April sample. They are not a like-for-like comparison.
- TSA figures are posted estimates, not measured individual passenger waits.
- No live conditions, terminal-level queues, or check-in, bag-drop, and gate-transit times.

**Underlying Data and Analytical Tools:**

| Evidence | Research area | Source | Tool call |
|---|---|---|---|
| E1 | Flight reliability | BTS On-Time Performance | `analyze_flight_reliability(airports=['EWR'], start_date=2026-04-01, end_date=2026-08-31)` |
| E2 | Security, Terminal A (hourly) | TSA (Hugging Face: `digitalhen/us-airport-wait-times`) | `analyze_security_patterns(airports=['EWR'], grain=hourly, terminal=A, queue_type=standard)` |
| E3 | Weather | NOAA NCEI hourly observations | `analyze_weather_conditions(airports=['EWR'], grain=hourly)` |
| E4 | Security, Terminal C (hourly) | TSA (Hugging Face) | `analyze_security_patterns(airports=['EWR'], grain=hourly, terminal=C, queue_type=standard)` |
| E5 | Security, Terminal B (hourly) | TSA (Hugging Face) | `analyze_security_patterns(airports=['EWR'], grain=hourly, terminal=B, queue_type=standard)` |
| E6 | Security, Terminal A (daily) | TSA (Hugging Face) | `analyze_security_patterns(airports=['EWR'], grain=daily, terminal=A, queue_type=standard)` |

All calls use `start_date=2026-04-01, end_date=2026-08-31`.

**Baseline: Same Model, No Tools and No System Prompt**

> For a 9:00 AM departure—meaning you need to arrive at the airport between 7:00 AM and 7:30 AM—**LaGuardia (LGA)** has historically and recently offered the most predictable departure experience.
>
> While LGA used to be a punchline for airport delays, its massive multi-billion-dollar redevelopment (completed in 2022) has transformed it into the most efficient and predictable of the three NYC-area airports, especially for morning flights.
>
> Here is how the three airports rank for a 9:00 AM departure across key metrics.
>
> ### 1. Flight Delays & Cancellations (Airspace and Runway Factors)
>
> - **Winner: LGA**
> - **Loser: EWR**
>
> - **LaGuardia (LGA):** Because LGA has no international flights (except for Canada and select Caribbean destinations), it operates on a highly structured domestic schedule. At 9:00 AM, LGA is wrapping up its first major bank of business-travel departures. While LGA's short, intersecting runways are vulnerable to severe weather, on a standard day, its departure queue moves much faster than JFK or EWR.
> - **JFK:** JFK is a massive international hub. While morning is relatively quiet for international departures (which peak in the afternoon/evening), JFK’s sheer size means taxi times can be incredibly long. It is not uncommon to spend 30 to 45 minutes idling on the tarmac before takeoff.
> - **Newark (EWR):** Historically, EWR has the worst on-time departure record of the three. It suffers from severe airspace congestion (sharing airspace with LGA and JFK, plus Philadelphia). By 9:00 AM, any cascading delays from the early morning rush are already starting to compound.
>
> ### 2. Security Wait Times & Terminal Experience
>
> - **Winner: LGA (Terminals B and C)**
> - **Runner-Up: EWR (Terminal A only)**
> - **Loser: JFK**
>
> - **LGA:** Terminals B and C are brand new and feature state-of-the-art security screening technology (meaning you don't have to take electronics out of your bag in most lanes). TSA PreCheck and CLEAR are highly optimized here. Even general security lines at Terminal B rarely exceed 15 minutes.
> - **EWR:** If you are flying out of the brand-new **Terminal A**, the experience is excellent. However, if you are flying United out of **Terminal C** or an international carrier out of **Terminal B**, security lines are notoriously unpredictable and can easily exceed 30–40 minutes during the morning rush.
> - **JFK:** JFK is currently undergoing a massive, multi-year **$19 billion redevelopment project**. Terminal construction has caused erratic TSA line surges, confusing pedestrian detours, and sudden terminal closures. Furthermore, Terminal 4 (Delta/International) is massive; even after clearing security, the walk to your gate can take 15–20 minutes.
>
> ### Summary Verdict
>
> For a **9:00 AM departure**, book your flight out of **LaGuardia (LGA)**, ideally flying Delta (Terminal C) or United/American/Southwest (Terminal B).
>
> - **Why:** You will experience the fastest security lines, the most modern terminals, the shortest tarmac taxi times, and a quick car ride to the airport.

---

### Sample Query 3:

**Query:**

> For flights departing from JFK, which times of day have historically had the most reliable departures and shortest security waits? Are there particular periods I should avoid if I want a smoother airport experience?

**Expected Answer:**

At JFK, security waits are shortest overnight and in the early morning. Midday has the most reliable departures, and the afternoon and evening are the periods to avoid.

- **Shortest security waits (01:00–06:00):** Standard-queue averages were 1.00 min in Terminal 1 (E1), 2.39–3.26 min in Terminal 4 (E4), and 0.00 min in Terminal 5 (E5).
- **Most reliable departures (12:00):** The share of departed flights 15+ min late was 0.27 (E3), the lowest of any hour.
- **Periods to avoid (13:00–18:00):**
  - Terminal 4 standard waits average 30–40 min, with hourly peaks of 41.00–61.28 min (E1, E4).
  - The share of flights 15+ min late reaches 0.57 at 18:00 (E3).
- **July 2026 JFK departures:** 33.33% delayed 15+ min and a 10.87% cancellation rate (E6).
- **Weather:** Gusts reached 19.0 m/s on April 4, fog cut visibility to 0.2 km on April 5, and hourly precipitation reached 2.0 mm (E2). Weather was not analyzed alongside hourly departures, so it cannot be said to explain the delay pattern.
- **Trade-off:** The security-optimal hours (overnight) and the flight-reliability-optimal hour (midday) do not coincide. The answer should say so rather than give a single ranking.

**Limitations:**

- Hourly datasets were capped at 400 rows, so these are illustrative early-season patterns (mostly April) rather than averages over all 17,195 seasonal observations.
- Posted security estimates, not measured passenger waits.
- Hourly flight reliability for July is unavailable due to tool constraints (E6).
- No live conditions, airline-specific outcomes, check-in or bag-drop times, or dates outside Apr 1–Aug 31, 2026.

**Evidence and Underlying Data:**

| Evidence | Research area | Source | Tool call |
|---|---|---|---|
| E1 | Security, all JFK (hourly) | TSA (Hugging Face: `digitalhen/us-airport-wait-times`) | `analyze_security_patterns(airports=['JFK'], grain=hourly, terminal=None, queue_type=standard)` |
| E2 | Weather | NOAA NCEI hourly observations | `analyze_weather_conditions(airports=['JFK'], grain=hourly)` |
| E3 | Flight reliability by hour | BTS On-Time Performance | `analyze_flight_reliability(airports=['JFK'])` |
| E4 | Security, Terminal 4 (hourly) | TSA (Hugging Face) | `analyze_security_patterns(airports=['JFK'], grain=hourly, terminal=4, queue_type=standard)` |
| E5 | Security, Terminal 5 (hourly) | TSA (Hugging Face) | `analyze_security_patterns(airports=['JFK'], grain=hourly, terminal=5, queue_type=standard)` |
| E6 | July flight risk | BTS On-Time Performance (pooled hourly) | `analyze_flight_risk_profile(airports=['JFK'], start_date=2026-07-01, end_date=2026-07-31)` |

All calls except E6 use `start_date=2026-04-01, end_date=2026-08-31`.

**Baseline: Same Model, No Tools and No System Prompt**

> To get the smoothest experience at John F. Kennedy International Airport (JFK)—which is notorious for airspace congestion and terminal crowding—you have to balance two different factors: **air traffic reliability** (on-time departures) and **terminal foot traffic** (security wait times).
>
> Historically, these two factors don't always align, but there are clear windows of time that offer the best experience, as well as specific periods you should avoid at all costs.
>
> ### 1. The Best Time for Reliable Departures: Early Morning
>
> If your priority is departing on time, **the earlier the flight, the better.**
>
> - **The Golden Window:** **6:00 AM – 9:00 AM**
> - **Why it works:** Flights scheduled in the early morning have the highest on-time departure rates (historically above 85-90%). The aircraft flying these routes usually arrived the night before and are already parked at the gate. Furthermore, the air traffic control (ATC) system in the congested Northeast corridor hasn't had time to back up yet.
> - **The Trade-off:** To catch a 6:30 AM flight, you have to brave the morning security rush (which peaks between 5:00 AM and 7:00 AM).
>
> ### 2. The Best Time for Short Security Waits: Mid-Day
>
> If you want to breeze through the terminal and security with minimal lines, aim for the mid-day lull.
>
> - **The Golden Window:** **10:00 AM – 2:00 PM**
> - **Why it works:** The early morning business and domestic rush has cleared out, and the massive wave of international travelers (bound for Europe and Asia) has not yet arrived. Security lines at major terminals (like Terminal 4 and Terminal 8) are historically at their shortest during these hours.
> - **The Trade-off:** Because delays in the U.S. airspace begin to cascade by early afternoon, a 1:00 PM departure has a slightly higher risk of a delay than a 7:00 AM departure, though it is still highly manageable.
>
> ### 3. Periods to Avoid (The "Danger Zones")
>
> If you want a smooth experience, avoid JFK during its peak international push and during peak commuter travel times.
>
> #### **The Daily Blackout Window: 4:00 PM – 8:00 PM**
>
> This is the absolute worst time to depart from JFK.
>
> - **The Congestion Peak:** JFK is a massive international gateway. Dozens of heavy aircraft bound for Europe, Africa, and South America depart in the late afternoon and evening.
> - **The Delay Cascade:** By 4:00 PM, any delays at other major hubs (like Chicago, Atlanta, or Boston) have rippled into New York. The airspace becomes incredibly crowded, often leading to "ground stops" or tarmac delays.
> - **The Security Nightmare:** Terminal 1 and Terminal 4 (and to a lesser extent, Terminal 7 and 8) experience massive surges in passenger volume starting around 3:00 PM, leading to the longest security lines of the day.
>
> #### **Weekly Patterns to Avoid:**
>
> - **Thursday and Friday Afternoons:** The combination of business travelers heading home and weekend leisure travelers creates a massive bottleneck starting around 2:00 PM.
> - **Sunday Evenings:** Heavy leisure travel return flows.
>
> #### **Seasonal Warning:**
>
> - **Summer Afternoons (June – August):** The Northeast is highly prone to afternoon thunderstorms. Because JFK operates at near-capacity, a single thunderstorm at 3:00 PM can cause delays that last until midnight. If traveling in the summer, *always* book a morning flight.
>
> ### 4. JFK Terminal-Specific Nuances
>
> Because JFK is divided into separate, unconnected terminals, your experience will depend heavily on which airline you fly:
>
> - **Terminal 1 (Air France, Lufthansa, Korean Air, etc.):** This terminal handles mostly international flights. Avoid departures between **4:00 PM and 9:00 PM**, when the terminal becomes incredibly cramped and security lines spill into the check-in area.
> - **Terminal 4 (Delta, Emirates, Virgin Atlantic):** The largest and busiest terminal. It is busy almost around the clock, but security lines are longest from **5:00 AM – 8:00 AM** (domestic rush) and **4:00 PM – 8:00 PM** (international rush).
> - **Terminal 5 (JetBlue):** Has a massive morning rush. Avoid security here between **5:00 AM and 7:30 AM**, as well as Sunday afternoons.
> - **Terminal 8 (American, British Airways):** Generally the most efficient terminal at JFK, but still experiences a significant bottleneck during the transatlantic rush between **5:00 PM and 8:00 PM**.
>
> ### Summary: The Ultimate Strategy
>
> For the absolute smoothest JFK experience, book a flight departing between **8:00 AM and 9:30 AM**.
>
> - Your flight is highly likely to depart on time.
> - If you arrive at the airport around 6:30 AM, you will hit the tail-end of the morning security rush, but with TSA PreCheck or CLEAR, you will breeze through.
