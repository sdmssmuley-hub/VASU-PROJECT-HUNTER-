"""
Static reference data + search-query generation.

build_daily_queries() implements the master brief's Section 13/15 search
strategy: it samples across equipment, region, industry, OEM, EPC, PSU and
signal-phrase pools each run, seeded by the current UTC hour so a
different combination is drawn on each hourly run. Across the 09:00-18:00
IST operating window this cycles through most of the search space instead
of repeating a handful of fixed queries.
"""

import datetime
import random

# ---- Geography (Section 5) ----
TIER1_REGIONS = [
    "Pune", "Chakan", "Talegaon", "Ranjangaon", "Baramati", "Pimpri-Chinchwad",
    "Mumbai", "Navi Mumbai", "Thane", "Panvel", "Taloja", "Raigad", "Nagothane",
    "Dolvi", "Roha", "Khalapur", "Khopoli", "Chhatrapati Sambhajinagar", "Waluj",
    "Bidkin", "AURIC", "Nagpur", "Butibori",
]
TIER2_REGIONS = [
    "Ahmedabad", "Vadodara", "Bharuch", "Dahej", "Vagra", "Hazira", "Surat",
    "Sanand", "Jamnagar", "Mundra", "Kandla",
]
TIER3_REGIONS = [
    "Rajasthan", "Haryana", "Punjab", "Uttar Pradesh", "Uttarakhand",
    "Madhya Pradesh", "Chhattisgarh", "Odisha", "Jharkhand", "Karnataka",
    "Tamil Nadu", "Telangana", "Andhra Pradesh", "Kerala", "West Bengal",
    "Bihar", "Goa", "Himachal Pradesh",
]
PRIORITY_REGIONS = TIER1_REGIONS  # used by scoring's geography bonus

STATE_CODES = {
    "maharashtra": "MH", "gujarat": "GJ", "rajasthan": "RJ", "haryana": "HR",
    "punjab": "PB", "uttar pradesh": "UP", "uttarakhand": "UK",
    "madhya pradesh": "MP", "chhattisgarh": "CG", "odisha": "OD",
    "jharkhand": "JH", "karnataka": "KA", "tamil nadu": "TN",
    "telangana": "TG", "andhra pradesh": "AP", "kerala": "KL",
    "west bengal": "WB", "bihar": "BR", "goa": "GA",
    "himachal pradesh": "HP", "jammu and kashmir": "JK",
}

# ---- Target project types / industries (Sections 4/15 in the earlier
#      brief, Section 4 here) ----
TARGET_INDUSTRIES = [
    "power plant", "thermal power plant", "hydro project", "nuclear project",
    "transformer manufacturing", "electrical substation", "transmission project",
    "steel plant", "rolling mill", "forging plant", "automotive plant",
    "EV factory", "battery plant", "stamping plant", "press shop",
    "heavy engineering plant", "chemical plant", "petrochemical plant",
    "refinery project", "fertilizer plant", "cement plant", "hydrogen plant",
    "green hydrogen project", "solar manufacturing", "gigafactory",
    "data centre", "semiconductor fab", "aerospace plant", "defence plant",
    "port project", "plant relocation project", "shutdown turnaround project",
]

# ---- Priority equipment (Section 3) ----
PRIORITY_EQUIPMENT = [
    "power transformer", "generator transformer", "auto-transformer",
    "ICT transformer", "400kV transformer", "765kV transformer",
    "shunt reactor", "steam turbine", "gas turbine", "hydro turbine",
    "generator stator", "turbine rotor", "condenser", "large industrial motor",
    "large compressor",
    "forging press", "hydraulic press", "mechanical press", "transfer press",
    "stamping press", "servo press", "drop hammer", "screw press",
    "ring rolling machine", "press manipulator",
    "rolling mill stand", "reheating furnace", "coiler", "uncoiler",
    "mill gearbox",
    "pressure vessel", "reactor vessel", "distillation column", "process tower",
    "heat exchanger", "industrial dryer", "storage tank", "silo",
    "vertical roller mill", "ball mill", "cement kiln", "industrial crusher",
    "battery manufacturing equipment", "data-centre generator",
    "electrolyser equipment", "large chiller",
]

# ---- Section source targets ----
PSU_TARGETS = [
    "POWERGRID", "NTPC", "NHPC", "NLC India", "SJVN", "THDC", "DVC",
    "MAHAGENCO", "MSETCL", "GETCO", "PGCIL", "BHEL", "SECI", "IOCL", "BPCL",
    "HPCL", "GAIL", "ONGC", "SAIL", "RINL", "NMDC", "Coal India",
]
OEM_TARGETS = [
    "GE Vernova", "Siemens Energy", "Hitachi Energy", "BHEL", "Mitsubishi Power",
    "Toshiba", "Hyundai Electric", "TBEA", "CG Power", "Schneider Electric",
    "ABB", "John Cockerill", "SMS group", "Primetals Technologies", "Danieli",
    "Fives Group", "Schuler", "Peddinghaus", "HMT", "Komatsu",
]
EPC_TARGETS = [
    "L&T", "Tata Projects", "Afcons", "Megha Engineering", "Shapoorji Pallonji",
    "Kalpataru Projects", "Technip Energies", "Worley", "Fluor", "Bechtel",
    "Jacobs", "thyssenkrupp", "Tata Consulting Engineers", "MECON", "ISGEC",
    "Thermax", "Praj Industries", "Tecnimont", "Engineers India Limited",
]

SIGNAL_PHRASES = [
    "equipment delivery", "equipment dispatch", "equipment shipment",
    "machine installation", "equipment erection", "mechanical erection",
    "transformer delivery", "transformer erection", "transformer commissioning",
    "press installation", "rolling mill equipment delivery", "turbine delivery",
    "generator delivery", "pressure vessel delivery", "reactor delivery",
    "heavy lift", "skidding", "hydraulic jacking", "ODC transport",
    "erection contractor appointed", "civil work underway",
    "foundation work underway", "equipment purchase order awarded",
    "FAT completed", "dispatch expected", "commissioning expected",
    "heavy haulage tender", "SPMT transport",
]

# ---- Run-cost controls (Section 82) ----
MAX_QUERIES_PER_RUN = 24
SEARCH_RESULTS_PER_QUERY = 6
MAX_CANDIDATES_PER_RUN = 40
MAX_TELEGRAM_ALERTS_PER_RUN = 4
MAX_GEMINI_TOKENS = 1400

# ---- Minimum bar (Section 38) ----
MIN_WEIGHT_TONNES_FOR_SINGLE_MACHINE = 80
MIN_QUANTITY_FOR_MULTI_PACKAGE = 5
MIN_SCORE_TO_STORE = 30       # below this -> rejected_candidates, not stored
MIN_SCORE_TO_ALERT = 55       # WATCH tier and below never gets a Telegram alert


def build_daily_queries(seed=None):
    now = datetime.datetime.utcnow()
    rnd = random.Random(seed if seed is not None else now.strftime("%Y%m%d%H"))
    year = now.year
    queries = []

    for equip in rnd.sample(PRIORITY_EQUIPMENT, k=min(5, len(PRIORITY_EQUIPMENT))):
        queries.append(f"{equip} delivery India {year}")

    for region in rnd.sample(TIER1_REGIONS, k=min(3, len(TIER1_REGIONS))):
        industry = rnd.choice(TARGET_INDUSTRIES)
        queries.append(f"{industry} construction underway {region} {year}")

    for region in rnd.sample(TIER2_REGIONS, k=min(2, len(TIER2_REGIONS))):
        industry = rnd.choice(TARGET_INDUSTRIES)
        queries.append(f"{industry} construction underway {region} {year}")

    for oem in rnd.sample(OEM_TARGETS, k=min(4, len(OEM_TARGETS))):
        equip = rnd.choice(PRIORITY_EQUIPMENT)
        queries.append(f"{oem} {equip} order India {year}")

    for epc in rnd.sample(EPC_TARGETS, k=min(4, len(EPC_TARGETS))):
        queries.append(f"{epc} EPC mechanical erection heavy equipment India {year}")

    for psu in rnd.sample(PSU_TARGETS, k=min(3, len(PSU_TARGETS))):
        signal = rnd.choice(SIGNAL_PHRASES)
        queries.append(f"{psu} {signal} tender {year}")

    for signal in rnd.sample(SIGNAL_PHRASES, k=min(3, len(SIGNAL_PHRASES))):
        queries.append(f"{signal} India {year}")

    seen = set()
    deduped = []
    for q in queries:
        if q not in seen:
            seen.add(q)
            deduped.append(q)
    return deduped[:MAX_QUERIES_PER_RUN]
