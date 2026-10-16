#!/usr/bin/env python3
"""Build 50 extraction prompts from public Wikipedia page summaries (REST API, CC BY-SA 4.0).
5 domains x 10 pages; each domain has one strict JSON Schema. Writes data/schemas/*.json, data/prompts.jsonl."""
import json, os, time, urllib.parse, urllib.request
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = lambda t: {"type": [t, "null"]}
SCHEMAS = {
 "person": {"type": "object", "additionalProperties": False,
   "required": ["name", "birth_year", "death_year", "nationality", "occupations", "known_for"],
   "properties": {"name": {"type": "string"}, "birth_year": S("integer"), "death_year": S("integer"),
     "nationality": S("string"), "occupations": {"type": "array", "items": {"type": "string"}},
     "known_for": {"type": "array", "items": {"type": "string"}}}},
 "city": {"type": "object", "additionalProperties": False,
   "required": ["name", "country", "is_capital", "population", "population_year", "rivers"],
   "properties": {"name": {"type": "string"}, "country": {"type": "string"}, "is_capital": {"type": "boolean"},
     "population": S("integer"), "population_year": S("integer"), "rivers": {"type": "array", "items": {"type": "string"}}}},
 "element": {"type": "object", "additionalProperties": False,
   "required": ["name", "symbol", "atomic_number", "category", "state_at_room_temperature", "discovered_by"],
   "properties": {"name": {"type": "string"}, "symbol": {"type": "string"}, "atomic_number": {"type": "integer"},
     "category": {"type": "string", "enum": ["alkali metal", "alkaline earth metal", "transition metal", "post-transition metal",
        "metalloid", "nonmetal", "halogen", "noble gas", "lanthanide", "actinide", "unknown"]},
     "state_at_room_temperature": {"type": "string", "enum": ["solid", "liquid", "gas", "unknown"]},
     "discovered_by": {"type": "array", "items": {"type": "string"}}}},
 "company": {"type": "object", "additionalProperties": False,
   "required": ["name", "founded_year", "founders", "headquarters", "industries", "is_public"],
   "properties": {"name": {"type": "string"}, "founded_year": S("integer"), "founders": {"type": "array", "items": {"type": "string"}},
     "headquarters": {"type": "object", "additionalProperties": False, "required": ["city", "country"],
        "properties": {"city": S("string"), "country": S("string")}},
     "industries": {"type": "array", "items": {"type": "string"}}, "is_public": S("boolean")}},
 "event": {"type": "object", "additionalProperties": False,
   "required": ["name", "start_year", "end_year", "locations", "participants", "kind"],
   "properties": {"name": {"type": "string"}, "start_year": S("integer"), "end_year": S("integer"),
     "locations": {"type": "array", "items": {"type": "string"}}, "participants": {"type": "array", "items": {"type": "string"}},
     "kind": {"type": "string", "enum": ["war", "battle", "treaty", "disaster", "expedition", "sporting event", "other"]}}},
}
PAGES = {
 "person": ["Marie_Curie", "Alan_Turing", "Ada_Lovelace", "Srinivasa_Ramanujan", "Frida_Kahlo", "Nikola_Tesla", "Rabindranath_Tagore", "Isaac_Newton", "Rosalind_Franklin", "Leonardo_da_Vinci"],
 "city": ["Hyderabad", "Lisbon", "Nairobi", "Kyoto", "Buenos_Aires", "Vienna", "Melbourne", "Cairo", "Montreal", "Kraków"],
 "element": ["Helium", "Sodium", "Mercury_(element)", "Bromine", "Uranium", "Silicon", "Neodymium", "Calcium", "Argon", "Tungsten"],
 "company": ["Toyota", "Infosys", "Nokia", "Unilever", "Samsung", "Spotify", "Tata_Steel", "Nintendo", "IKEA", "Airbus"],
 "event": ["Battle_of_Hastings", "Treaty_of_Versailles", "1906_San_Francisco_earthquake", "Apollo_11", "Battle_of_Plassey", "Peace_of_Westphalia", "1883_eruption_of_Krakatoa", "Lewis_and_Clark_Expedition", "1983_Cricket_World_Cup", "Crimean_War"],
}
os.makedirs(os.path.join(HERE, "data", "schemas"), exist_ok=True)
for k, v in SCHEMAS.items():
    json.dump(v, open(os.path.join(HERE, "data", "schemas", f"{k}.json"), "w"), indent=1)
def fetch(titles):
    q = urllib.parse.urlencode({"action": "query", "format": "json", "prop": "extracts|info", "inprop": "url", "exintro": 1,
                                "explaintext": 1, "exlimit": "max", "redirects": 1, "titles": "|".join(titles)})
    for attempt in range(6):
        try:
            req = urllib.request.Request("https://en.wikipedia.org/w/api.php?" + q,
                                         headers={"User-Agent": "TIG-experiments/0.1 (public research)"})
            return json.load(urllib.request.urlopen(req, timeout=30))
        except Exception as e:
            time.sleep(5 * (attempt + 1))
    raise SystemExit("fetch failed")

out = open(os.path.join(HERE, "data", "prompts.jsonl"), "w")
i = 0
for dom, titles in PAGES.items():
    d = fetch([t.replace("_", " ") for t in titles])
    norm = {}
    for m in (d["query"].get("normalized") or []) + (d["query"].get("redirects") or []):
        norm[m["from"]] = m["to"]
    pages = {p["title"]: p for p in d["query"]["pages"].values()}
    for t in titles:
        tt = t.replace("_", " "); tt = norm.get(tt, tt); tt = norm.get(tt, tt)
        pg = pages[tt]
        text = pg["extract"].strip()
        text = text[:2500].rsplit(". ", 1)[0] + "." if len(text) > 2500 else text  # cap at ~2.5K chars, cut at a sentence
        i += 1
        out.write(json.dumps({"id": f"P{i:02d}", "domain": dom, "title": pg["title"], "source_url": pg["fullurl"],
                              "lastrevid": pg.get("lastrevid"), "license": "CC BY-SA 4.0 (Wikipedia)", "text": text}) + "\n")
    time.sleep(2)
print("wrote", i)
