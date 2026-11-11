# GateWise - NYC Airport Research Agent

---

## 1. Project Overview

**GateWise** is an airport research assistant that investigates security wait times, flight reliability, weather, and airport operations to help travelers plan ahead for a seamless departure experience. GateWise helps travelers plan when to arrive at the airport and assess potential disruption risks through a multi-agent research system that investigates data sources in parallel, synthesizes findings, and delivers concise, evidence-backed answers with citations. 

### Primary Target User:

Any air traveler planning to travel from any of the airports in NYC (JFK, LGA, and EWR)

### Scope:

GateWise currently analyzes only the following:

- Airports: John F. Kennedy International (JFK), LaGuardia (LGA), and Newark Liberty International (EWR).
- Date coverage: April 1, 2026 – August 31, 2026.
- Data frequency: Daily and hourly, depending on the source and analysis.

GateWise is a historical research tool, not a live airport monitoring service. It cannot provide current security-line conditions, airline-specific wait times, check-in or bag-drop estimates, or recommendations for airports outside its supported coverage.

Link: https://gatewise-flight-agent-git-708411086094.europe-west1.run.app 

---

## 2. Data Sources:

GateWise combines four independent data sources to investigate airport departure conditions

| Data source | Information used | Analytical purpose | Analytics function |
|---|---|---|---|
| TSA posted security wait times (Hugging Face) | Standard and PreCheck wait estimates by airport and terminal | Compare security wait distributions and identify time-based patterns | `security_patterns()` |
| Bureau of Transportation Statistics (BTS) | Flight departure delays, cancellations, and percentage of flights departing 15+ minutes late | Measure historical flight departure reliability | `flight_reliability()` |
| NOAA National Centers for Environmental Information (NCEI) | Hourly weather observations, including visibility, wind, gusts, precipitation, and temperature | Examine weather conditions associated with airport disruptions | `weather_conditions()` |
| FAA OPSNET | Daily airport operations, operational delays, and reported delay causes | Compare airport operational activity and disruption patterns | `airport_operations()` |

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

GateWise uses specialized research agents to investigate different aspects of an airport departure question.

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
- **Flight reliability:** For Wednesday 8:00–9:00 AM departures in July 2026, 10.0% of scheduled flights were canceled (13/130), while 20.51% of classified departed flights were at least 15 minutes late (24/117).
- **Weather:** Historical Wednesday 8:00 AM observations in July showed that 100% of visibility observations met the 5 km safety threshold, with wind speeds below 10 m/s. However, no valid precipitation observations were available, indicating insufficient evidence to assess precipitation-related risk.

**Illustrative arrival calculation:**

Using the largest observed P95 security estimate (28 minutes) and an assumed 45 minutes for check-in, baggage, and walking:

8:00 AM − 28 minutes − 45 minutes = **6:47 AM arrival**

This is an illustrative planning estimate, not a validated safe-arrival recommendation. The 45-minute overhead is an assumption, and posted security estimates do not guarantee individual wait times.

**Limitations:**

- July 15 security observations are distinct from flight statistics aggregated across Wednesdays in July.
- Historical flight rates provide context, not predictions for an individual flight.
- Security waits should not be presented as causing flight delays.
- Missing weather observations do not mean zero weather risk.
- The data does not provide live conditions, actual individual queue times, or measured check-in and walking times.


**Underlying Data and Analytical Tools:**

| Evidence | Research area | Source / table | Tool call |
|---|---|---|---|
| E1 | Security wait times | TSA, `security_airport_hourly` | `analyze_security_arrival_profile(airports=['JFK'], terminal=4, start_date=2026-07-15, end_date=2026-07-15, start_hour=<6>, end_hour=<7>, queue_type=standard)` |
| E2 | Flight reliability | BTS On-Time Performance, `flight_hourly` | `analyze_flight_risk_profile(airports=['JFK'], start_date=2026-07-01, end_date=2026-07-31, days_of_week=['Wednesday'], start_hour=8, end_hour=9)` |
| E3 | Weather conditions | NOAA NCEI, `weather_hourly_local` | `analyze_weather_risk_profile(airports=['JFK'], <dates>, <hours>, <thresholds>)` |


**Model Outputs:**

<details>
<summary><strong>GateWise Response</strong></summary>

**GateWise**

**Arrive** For an 8:00 AM departure at Terminal 4 on Wednesday, July 15, 2026, the typical arrive-by time is 06:56 [E5] and the conservative arrive-by time is 06:47 [E5]. Under these estimates, the typical security wait is 19.0 minutes (the mean of the hourly P50 estimates) [E5], and the conservative wait is 28.0 minutes (the maximum hourly P95) [E5]. This terminal-specific evidence is thin, covering only 2 observed hours [E5] on 1 observed day [E5], making these arrival times illustrative historical estimates rather than validated safe arrival recommendations. These calculations treat the security window and other overhead as assumptions, not empirical data.

**Disruption risk** For JFK departures on Wednesdays in July 2026 between 8:00 AM and 9:00 AM, 20.51% of departures (24 flights) were delayed by 15+ minutes [E3], and the cancellation rate was 10.0% (13 out of 130 scheduled flights) [E3].

**What's driving it** Historical patterns for July Wednesdays at 8:00 AM show 100% of visibility observations met safety thresholds [E2] and wind speed was under 10 m/s [E2]. Wind and visibility risk indicators were not triggered and do not explain the disruptions seen [E2]. Comparable precipitation weather evidence is unavailable as there are 0 valid observations [E2]. These historical pattern estimates for July Wednesdays [E2][E3] are distinguished from your specific travel date. Security arrival windows provide planning context but do not overlap with or explain flight disruptions.

**What the data can't tell you** Live conditions, airline-specific effects, physical queue lines beyond posted estimates, actual check-in/bag-drop/gate transit times, dates outside April-August 2026, or precipitation patterns due to missing observations [E2].

---

**Evidence**

- **[E2]** NOAA NCEI hourly weather risk indicators: `analyze_weather_risk_profile(airports=['JFK'], start_date=2026-07-01, end_date=2026-07-31, visibility_threshold_km=5.0, precipitation_threshold_mm=1.0, wind_threshold_m_s=10.0, day_type=weekday, start_hour=8, end_hour=9, days_of_week=['Wednesday'])`
- **[E3]** BTS on-time performance (pooled hourly): `analyze_flight_risk_profile(airports=['JFK'], start_date=2026-07-01, end_date=2026-07-31, day_type=weekday, days_of_week=['Wednesday'], start_hour=8, end_hour=9)`
- **[E5]** TSA posted wait times (Hugging Face: digitalhen/us-airport-wait-times): `analyze_security_patterns(airports=['JFK'], start_date=2026-07-15, end_date=2026-07-15, grain=hourly, terminal=4, queue_type=standard)`

</details>

<details>
<summary><strong>Base Model Response</strong></summary>

That sounds like you are planning well ahead! A Wednesday morning departure from JFK's busy Terminal 4 requires a bit of strategy.

Here is a recommended timeline and some key tips to keep in mind for your departure on **July 15, 2026**:

### **Recommended Timeline**

- **For International Flights:** Plan to arrive at Terminal 4 by **5:00 AM** (3 hours prior).
- **For Domestic Flights:** Plan to arrive at Terminal 4 by **6:00 AM** (2 hours prior).

*Note: Terminal 4 is one of the largest terminals at JFK (major hub for Delta, as well as many international airlines like Emirates, Singapore, and Virgin Atlantic). The walk to the furthest gates (especially the B gates) can take 15 to 20 minutes even after you pass security.*

### **How to prepare as the date approaches:**

1. **TSA PreCheck / CLEAR:** If you have these, they are highly recommended for T4, as morning rush hours (6:00 AM to 8:00 AM) can have very long standard security lines.
2. **Transportation:**
   - If taking a rideshare (Uber/Lyft) or taxi from NYC, aim to leave by 4:15 AM – 5:15 AM (depending on your starting point) to avoid any early morning construction or highway bottlenecks.
   - If taking the **LIRR or Subway to Jamaica Station**, the AirTrain runs 24/7 and takes about 15 minutes from Jamaica to Terminal 4.
3. **Lounge Access:** Terminal 4 has some of the best lounges at JFK, including the Delta Sky Club, American Express Centurion Lounge, and Chase Sapphire Lounge. If you have access, arriving early to grab breakfast is highly recommended.

</details>

---

### Sample Query 2: 

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
- Does not cover live conditions, airline-specific differences, terminal-level queues, or check-in, bag-drop, and gate-walk time.

**Underlying Data and Analytical Tools:**

| Evidence | Research area | Source / table | Tool call |
|---|---|---|---|
| E1 | Security wait times | TSA, `security_airport_hourly` | `analyze_security_arrival_profile(airports=['EWR','JFK','LGA'], start_date=2026-04-01, end_date=2026-08-31, start_hour=8, end_hour=10, queue_type=standard)` |
| E3 | Weather conditions | NOAA NCEI, `weather_hourly_local` | `analyze_weather_risk_profile(airports=['EWR','JFK','LGA'], start_date=2026-04-01, end_date=2026-08-31, start_hour=8, end_hour=10, visibility_threshold_km=5.0, precipitation_threshold_mm=1.0, wind_threshold_m_s=10.0)` |
| E4 | Flight delays and cancellations | BTS On-Time Performance, `flight_hourly` | `analyze_flight_risk_profile(airports=['EWR','JFK','LGA'], start_date=2026-04-01, end_date=2026-08-31, start_hour=8, end_hour=10)` |

**Model Outputs:**

<details>
<summary><strong>GateWise Response</strong></summary>

**GateWise**

No single airport is most predictable across all categories. LaGuardia (LGA) is the most predictable for security, with a mean standard wait of 4.97 minutes and a 90th percentile (P90) of 8.65 minutes across 287 observed hours [E1]. Newark (EWR) is the most predictable for flight operations, recording a mean departure delay of 4.72 minutes, a 15-minute late departure rate of 11.68%, and a cancellation rate of 1.52% [E3]. John F. Kennedy (JFK) is the least predictable overall, suffering from the highest mean security wait of 13.37 minutes [E1] and the highest flight cancellation rate of 2.74% [E3].

**What's behind it** While security and operational patterns are documented, the data cannot establish a causal link between weather risks and flight disruptions [E2]. For contextual weather conditions, EWR recorded low visibility in 1.31% of observations and high winds in 3.28% [E2]. JFK recorded low visibility in 1.31% of observations and high winds in 3.93% [E2]. LGA recorded low visibility in 2.30% of 304 valid observations and high winds in 0.33% [E2]. Because weather indicators were rarely triggered and the analysis does not compare matched conditions, they do not explain the disruptions seen [E2].

**What the data can't tell you** This analysis cannot provide live conditions, airline-specific effects, checkpoint-level lines beyond posted estimates, check-in/bag-drop/gate times, or dates outside April-August 2026. Data limits include missing precipitation observations (only 24 valid for EWR, 40 for JFK, and 111 for LGA out of 305 total hourly rows) and one missing visibility observation at LGA [E2]. Security statistics represent hourly, airport-wide weighted estimates of posted wait times rather than individual passenger transit times [E1]. Flight metrics are pooled for the 8:00 AM to 10:00 AM window, and the dataset does not support 30-minute delay rates [E3].

---

**Evidence**

- **[E1]** TSA posted hourly airport-level security wait estimates: `analyze_security_arrival_profile(airports=['EWR', 'JFK', 'LGA'], start_date=2026-04-01, end_date=2026-08-31, day_type=all, days_of_week=[], start_hour=8, end_hour=10, queue_type=standard)`
- **[E2]** NOAA NCEI hourly weather risk indicators: `analyze_weather_risk_profile(airports=['EWR', 'JFK', 'LGA'], start_date=2026-04-01, end_date=2026-08-31, visibility_threshold_km=5.0, precipitation_threshold_mm=1.0, wind_threshold_m_s=10.0, day_type=all, start_hour=8, end_hour=10, days_of_week=[])`
- **[E3]** BTS on-time performance (pooled hourly): `analyze_flight_risk_profile(airports=['EWR', 'JFK', 'LGA'], start_date=2026-04-01, end_date=2026-08-31, day_type=all, days_of_week=[], start_hour=8, end_hour=10)`

</details>

<details>
<summary><strong>Base Model Response</strong></summary>

For a 9:00 AM departure—meaning you need to arrive at the airport between 7:00 AM and 7:30 AM—**LaGuardia (LGA)** has historically and recently offered the most predictable departure experience.

While LGA used to be a punchline for airport delays, its massive multi-billion-dollar redevelopment (completed in 2022) has transformed it into the most efficient and predictable of the three NYC-area airports, especially for morning flights.

Here is how the three airports rank for a 9:00 AM departure across key metrics.

### 1. Flight Delays & Cancellations (Airspace and Runway Factors)

- **Winner: LGA**
- **Loser: EWR**

- **LaGuardia (LGA):** Because LGA has no international flights (except for Canada and select Caribbean destinations), it operates on a highly structured domestic schedule. At 9:00 AM, LGA is wrapping up its first major bank of business-travel departures. While LGA's short, intersecting runways are vulnerable to severe weather, on a standard day, its departure queue moves much faster than JFK or EWR.
- **JFK:** JFK is a massive international hub. While morning is relatively quiet for international departures (which peak in the afternoon/evening), JFK’s sheer size means taxi times can be incredibly long. It is not uncommon to spend 30 to 45 minutes idling on the tarmac before takeoff.
- **Newark (EWR):** Historically, EWR has the worst on-time departure record of the three. It suffers from severe airspace congestion (sharing airspace with LGA and JFK, plus Philadelphia). By 9:00 AM, any cascading delays from the early morning rush are already starting to compound.

### 2. Security Wait Times & Terminal Experience

- **Winner: LGA (Terminals B and C)**
- **Runner-Up: EWR (Terminal A only)**
- **Loser: JFK**

- **LGA:** Terminals B and C are brand new and feature state-of-the-art security screening technology (meaning you don't have to take electronics out of your bag in most lanes). TSA PreCheck and CLEAR are highly optimized here. Even general security lines at Terminal B rarely exceed 15 minutes.
- **EWR:** If you are flying out of the brand-new **Terminal A**, the experience is excellent. However, if you are flying United out of **Terminal C** or an international carrier out of **Terminal B**, security lines are notoriously unpredictable and can easily exceed 30–40 minutes during the morning rush.
- **JFK:** JFK is currently undergoing a massive, multi-year **$19 billion redevelopment project**. Terminal construction has caused erratic TSA line surges, confusing pedestrian detours, and sudden terminal closures. Furthermore, Terminal 4 (Delta/International) is massive; even after clearing security, the walk to your gate can take 15–20 minutes.

### Summary Verdict

For a **9:00 AM departure**, book your flight out of **LaGuardia (LGA)**, ideally flying Delta (Terminal C) or United/American/Southwest (Terminal B).

- **Why:** You will experience the fastest security lines, the most modern terminals, the shortest tarmac taxi times, and a quick car ride to the airport.

</details>


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


**Model Outputs:**

<details>
<summary><strong>GateWise Response</strong></summary>

**GateWise**

Terminal A is recommended because it consistently has the shortest security wait times, with hourly averages ranging from 0.03 to 20.80 minutes [E2] and daily averages between 1.40 and 6.82 minutes [E6]. By comparison, hourly average wait times reach up to 37.24 minutes in Terminal B [E4] and up to 36.62 minutes in Terminal C [E1]. Flight departure reliability cannot be evaluated by terminal because flight performance data is only available at the airport level [E3].

**What's behind it** The shorter wait times in Terminal A, where hourly averages peak at 20.80 minutes [E2], contrast with peak average waits of 37.24 minutes in Terminal B [E4] and 36.62 minutes in Terminal C [E1]. For airport-wide departures, flight disruptions coincide with adverse weather conditions. For example, on the historically disrupted date of April 14, 2026, peak wind gusts of 18 m/s [E5] coincided with an hourly mean departure delay of 82.9 minutes and a 38.9% 15+ minute late rate [E3]. Other recorded weather conditions over the period included temperatures from -1.1°C to 32.2°C and visibility dropping to 0.8 km [E5]. The overall pooled flight departure reliability rate for the entire period is unavailable in this dataset [E3].

**What the data can't tell you** This dataset cannot provide live conditions, airline-specific delays, or terminal-level flight reliability. It cannot measure check-in, bag-drop, or gate-transfer times, nor does it cover dates outside the spring and summer period analyzed [E3]. Security times represent posted estimates rather than independently measured passenger queue times [E1][E2][E4]. Hourly security [E1][E2][E4], flights [E3], and weather [E5] datasets were truncated to 400 rows. Daily security averages could not be completed for Terminals B and C, and missing values in weather [E5] or security records [E6] cannot be assumed to represent zero wait times or favorable conditions.

---

**Evidence**

- **[E1]** TSA posted wait times (Hugging Face: digitalhen/us-airport-wait-times): `analyze_security_patterns(airports=['EWR'], start_date=2026-04-01, end_date=2026-08-31, grain=hourly, terminal=C, queue_type=standard)`
- **[E2]** TSA posted wait times (Hugging Face: digitalhen/us-airport-wait-times): `analyze_security_patterns(airports=['EWR'], start_date=2026-04-01, end_date=2026-08-31, grain=hourly, terminal=A, queue_type=standard)`
- **[E3]** BTS on-time performance: `analyze_flight_reliability(airports=['EWR'], start_date=2026-04-01, end_date=2026-08-31, day_type=all, days_of_week=[], start_hour=None, end_hour=None)`
- **[E4]** TSA posted wait times (Hugging Face: digitalhen/us-airport-wait-times): `analyze_security_patterns(airports=['EWR'], start_date=2026-04-01, end_date=2026-08-31, grain=hourly, terminal=B, queue_type=standard)`
- **[E5]** NOAA NCEI hourly observations: `analyze_weather_conditions(airports=['EWR'], start_date=2026-04-01, end_date=2026-08-31, grain=hourly)`
- **[E6]** TSA posted wait times (Hugging Face: digitalhen/us-airport-wait-times): `analyze_security_patterns(airports=['EWR'], start_date=2026-04-01, end_date=2026-08-31, grain=daily, terminal=A, queue_type=standard)`

</details>

<details>
<summary><strong>Base Model Response</strong></summary>

Hands down, the best terminal at Newark Liberty International Airport (EWR) is **Terminal A**.

In fact, it is currently considered one of the best airport terminals in the entire United States, having won the Skytrax award for "World’s Best New Airport Terminal" in 2024.

However, since your terminal is determined by your airline, here is a breakdown of why **Terminal A** is the best, how **Terminal C** compares, and why you should try to avoid **Terminal B**.

---

### 1. The Winner: Terminal A (The Brand New Masterpiece)

Opened in early 2023 after a $2.7 billion overhaul, Terminal A is modern, spacious, filled with natural light, and features local New Jersey-centric art and design.

* **Airlines:** Air Canada, American Airlines, Delta Air Lines, JetBlue, and some United Airlines domestic flights.
* **Why it’s the best:**
  * **Efficiency:** The TSA security checkpoints are state-of-the-art and move incredibly fast.
  * **Vibe:** It is massive, airy, and doesn't feel cramped. There are excellent play areas for kids and sensory rooms.
  * **Food:** Incredible options showcasing local NJ/NY favorites, including *Jersey Mike's*, *Town Providence* (fine dining), *Bang cookies*, and *Marcus Samuelsson’s Marcus Bar & Grill*.
  * **Lounges:** Features brand-new, stunning lounges, including the Delta Sky Club, United Club, and American Admirals Club. (An American Express Centurion Lounge is also under construction).

### 2. The Runner-Up: Terminal C (The United Airlines Megahub)

If you are flying United Airlines, you will likely end up here. While it is older than Terminal A, it has been heavily modernized and is a very solid terminal.

* **Airlines:** United Airlines (domestic and international).
* **Why it’s good:**
  * **The Food Scene:** It is famous for its iPad-ordering system at almost every seat and restaurant. It has great dining options like *Saison* (French bistro) and *Abruzzo Italian Steakhouse*.
  * **Lounges:** If you are flying international business class, Terminal C houses the **United Polaris Lounge**, which is one of the best business-class lounges in the world (featuring a sit-down, à la carte restaurant).
* **The Downside:** It can get incredibly crowded, and the gate areas can feel very cramped during peak bank hours.

### 3. The One to Avoid: Terminal B

Terminal B is the oldest, most outdated terminal at EWR.

* **Airlines:** Most foreign international carriers (e.g., Lufthansa, British Airways, Singapore Airlines, Emirates) and Spirit.
* **Why it’s tough:**
  * It is split into three separate satellite concourses. If you go through security for one concourse, you cannot access the food or amenities in the others.
  * The food and shopping options are highly mediocre and limited.
  * The security lines can be agonizingly long and chaotic during evening international departure rushes.

### Summary Recommendation:

* **If you have a choice of airline:** Book **Delta, American, or JetBlue** so you can use **Terminal A**.
* **If you are flying United Business/First Class:** You will love **Terminal C** for the United Polaris Lounge.
* **If you are flying international on a foreign carrier:** Prepare for **Terminal B** by arriving early, and consider eating before you get to the airport.

</details>

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


**Model Outputs:**

<details>
<summary><strong>GateWise Response</strong></summary>

**GateWise**

Late-night and early-morning hours (01:00 to 06:00) feature the shortest security wait times, dropping to a 1.00-minute average in Terminal 1 [E1], 2.39 to 3.26 minutes in Terminal 4 [E4], and 0.00 minutes in Terminal 5 [E5]. Midday departures (12:00) are the most reliable, with a 0.27 delay share of 15+ minutes [E3]. Conversely, travelers should avoid the afternoon and evening (13:00 to 18:00), when standard security waits average 30 to 40 minutes [E4], peaking at 41.00 to 61.28 minutes [E1][E4], and flight delay shares reach 0.57 at 18:00 [E3]. In July 2026, JFK departures experienced a 33.33% delay rate of 15+ minutes and a 10.87% cancellation rate [E6].

**What's behind it** While operational congestion compounds queues later in the day, weather events also coincide with disruption risks. JFK experienced wind gusts reaching 19.0 m/s on April 4, fog reducing visibility to 0.2 km on April 5, and hourly precipitation up to 2.0 mm [E2]. However, because the weather data was not directly analyzed alongside hourly flight departures, weather cannot be definitively said to explain the hourly delay patterns.

**What the data can't tell you** The data cannot provide live conditions, airline-specific outcomes, check-in or bag-drop times, or dates outside the April–August 2026 window [E1][E2][E3][E4][E5]. Standard security wait times reflect posted estimates rather than actual passenger queue experiences [E4][E5]. Additionally, the hourly datasets were capped at a 400-row truncation limit, meaning these statistics represent illustrative historical patterns rather than a complete mathematical average of all 17,195 seasonal observations [E1][E2][E3][E4][E5]. Hourly flight reliability for July 2026 is also unavailable due to tool constraints [E6].

---

**Evidence**

- **[E1]** TSA posted wait times (Hugging Face: digitalhen/us-airport-wait-times): `analyze_security_patterns(airports=['JFK'], start_date=2026-04-01, end_date=2026-08-31, grain=hourly, terminal=None, queue_type=standard)`
- **[E2]** NOAA NCEI hourly observations: `analyze_weather_conditions(airports=['JFK'], start_date=2026-04-01, end_date=2026-08-31, grain=hourly)`
- **[E3]** BTS on-time performance: `analyze_flight_reliability(airports=['JFK'], start_date=2026-04-01, end_date=2026-08-31, day_type=all, days_of_week=[], start_hour=None, end_hour=None)`
- **[E4]** TSA posted wait times (Hugging Face: digitalhen/us-airport-wait-times): `analyze_security_patterns(airports=['JFK'], start_date=2026-04-01, end_date=2026-08-31, grain=hourly, terminal=4, queue_type=standard)`
- **[E5]** TSA posted wait times (Hugging Face: digitalhen/us-airport-wait-times): `analyze_security_patterns(airports=['JFK'], start_date=2026-04-01, end_date=2026-08-31, grain=hourly, terminal=5, queue_type=standard)`
- **[E6]** BTS on-time performance (pooled hourly): `analyze_flight_risk_profile(airports=['JFK'], start_date=2026-07-01, end_date=2026-07-31, day_type=all, days_of_week=[], start_hour=None, end_hour=None)`

</details>

<details>
<summary><strong>Base Model Response</strong></summary>

To get the smoothest experience at John F. Kennedy International Airport (JFK)—which is notorious for airspace congestion and terminal crowding—you have to balance two different factors: **air traffic reliability** (on-time departures) and **terminal foot traffic** (security wait times).

Historically, these two factors don't always align, but there are clear windows of time that offer the best experience, as well as specific periods you should avoid at all costs.

### 1. The Best Time for Reliable Departures: Early Morning

If your priority is departing on time, **the earlier the flight, the better.**

- **The Golden Window:** **6:00 AM – 9:00 AM**
- **Why it works:** Flights scheduled in the early morning have the highest on-time departure rates (historically above 85-90%). The aircraft flying these routes usually arrived the night before and are already parked at the gate. Furthermore, the air traffic control (ATC) system in the congested Northeast corridor hasn't had time to back up yet.
- **The Trade-off:** To catch a 6:30 AM flight, you have to brave the morning security rush (which peaks between 5:00 AM and 7:00 AM).

### 2. The Best Time for Short Security Waits: Mid-Day

If you want to breeze through the terminal and security with minimal lines, aim for the mid-day lull.

- **The Golden Window:** **10:00 AM – 2:00 PM**
- **Why it works:** The early morning business and domestic rush has cleared out, and the massive wave of international travelers (bound for Europe and Asia) has not yet arrived. Security lines at major terminals (like Terminal 4 and Terminal 8) are historically at their shortest during these hours.
- **The Trade-off:** Because delays in the U.S. airspace begin to cascade by early afternoon, a 1:00 PM departure has a slightly higher risk of a delay than a 7:00 AM departure, though it is still highly manageable.

### 3. Periods to Avoid (The "Danger Zones")

If you want a smooth experience, avoid JFK during its peak international push and during peak commuter travel times.

#### **The Daily Blackout Window: 4:00 PM – 8:00 PM**

This is the absolute worst time to depart from JFK.

- **The Congestion Peak:** JFK is a massive international gateway. Dozens of heavy aircraft bound for Europe, Africa, and South America depart in the late afternoon and evening.
- **The Delay Cascade:** By 4:00 PM, any delays at other major hubs (like Chicago, Atlanta, or Boston) have rippled into New York. The airspace becomes incredibly crowded, often leading to "ground stops" or tarmac delays.
- **The Security Nightmare:** Terminal 1 and Terminal 4 (and to a lesser extent, Terminal 7 and 8) experience massive surges in passenger volume starting around 3:00 PM, leading to the longest security lines of the day.

#### **Weekly Patterns to Avoid:**

- **Thursday and Friday Afternoons:** The combination of business travelers heading home and weekend leisure travelers creates a massive bottleneck starting around 2:00 PM.
- **Sunday Evenings:** Heavy leisure travel return flows.

#### **Seasonal Warning:**

- **Summer Afternoons (June – August):** The Northeast is highly prone to afternoon thunderstorms. Because JFK operates at near-capacity, a single thunderstorm at 3:00 PM can cause delays that last until midnight. If traveling in the summer, *always* book a morning flight.

### 4. JFK Terminal-Specific Nuances

Because JFK is divided into separate, unconnected terminals, your experience will depend heavily on which airline you fly:

- **Terminal 1 (Air France, Lufthansa, Korean Air, etc.):** This terminal handles mostly international flights. Avoid departures between **4:00 PM and 9:00 PM**, when the terminal becomes incredibly cramped and security lines spill into the check-in area.
- **Terminal 4 (Delta, Emirates, Virgin Atlantic):** The largest and busiest terminal. It is busy almost around the clock, but security lines are longest from **5:00 AM – 8:00 AM** (domestic rush) and **4:00 PM – 8:00 PM** (international rush).
- **Terminal 5 (JetBlue):** Has a massive morning rush. Avoid security here between **5:00 AM and 7:30 AM**, as well as Sunday afternoons.
- **Terminal 8 (American, British Airways):** Generally the most efficient terminal at JFK, but still experiences a significant bottleneck during the transatlantic rush between **5:00 PM and 8:00 PM**.

### Summary: The Ultimate Strategy

For the absolute smoothest JFK experience, book a flight departing between **8:00 AM and 9:30 AM**.

- Your flight is highly likely to depart on time.
- If you arrive at the airport around 6:30 AM, you will hit the tail-end of the morning security rush, but with TSA PreCheck or CLEAR, you will breeze through.

</details>
