"""
tools/backfill_extended_stats.py
---------------------------------
One-time backfill of all 476 PGA Tour stat IDs into player_stats_extended.

Fetches statDetails for every stat ID and every year in YEARS.
Inserts players into the players table if not already present.
Skips stat IDs that return null (not available for that year).
Rate limited to avoid getting blocked.

Run:
    python tools/backfill_extended_stats.py

Estimated time: ~30-45 minutes for 6 years x 476 stats with 0.3s delay.
Progress is printed to console and saved to tools/backfill_progress.json
so the script can be resumed if interrupted.

Resume after interruption:
    python tools/backfill_extended_stats.py --resume
"""

import argparse
import json
import logging
import os
import sys
import time

import psycopg2
import psycopg2.extras
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
PROGRESS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backfill_progress.json")

with open(CONFIG_PATH) as f:
    config = json.load(f)

DB_DSN = config["db_dsn"]

YEARS = [2021, 2022, 2023, 2024, 2025, 2026]

DELAY_SECONDS = 0.3  # delay between API calls to avoid rate limiting

ENDPOINT = "https://orchestrator.pgatour.com/graphql"
HEADERS = {
    "Content-Type": "application/json",
    "x-api-key": "da2-gsrx5bibzbb4njvhl7t37wqyl4",
    "origin": "https://www.pgatour.com",
    "referer": "https://www.pgatour.com/",
    "x-pgat-platform": "web",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/146.0.0.0 Safari/537.36"
    ),
}

# All 476 stat IDs extracted from statDetails.statCategories
STAT_IDS = {
    "01008": "Fairway Bunker Tendency",
    "014": "Career Earnings",
    "02325": "Average Approach Shot Distance",
    "02327": "Putting from 5-15'",
    "02328": "Putting from 15-25'",
    "02329": "Approaches from inside 100 yards",
    "02330": "GIR Percentage - < 100 yards",
    "02331": "Approaches from > 100 yards",
    "02332": "GIR Percentage - 100+ yards",
    "02333": "Birdie or Better Percentage - Fairway",
    "02334": "Birdie or Better Percentage - Left Rough",
    "02335": "Birdie or Better Percentage - Right Rough",
    "02336": "Birdie or Better Percentage - Rough",
    "02337": "Percentage of Available Purse Won",
    "02338": "Average Approach Distance - Birdie or Better",
    "02339": "Average Approach Distance - Par",
    "02340": "Average Approach Distance - Bogey or Worse",
    "02341": "Percentage of Yardage covered by Tee Shots",
    "02342": "Percentage of Yardage covered by Tee Shots - Par 4's",
    "02343": "Percentage of Yardage covered by Tee Shots - Par 5's",
    "02346": "Scoring Rating",
    "02347": "Last 5 Events - Power",
    "02348": "Last 5 Events - Accuracy",
    "02349": "Last 5 Events - Short Game",
    "02350": "Last 5 Events - Putting",
    "02351": "Last 5 Events - Scoring",
    "02352": "Last 15 Events - Power",
    "02353": "Last 15 Events - Accuracy",
    "02354": "Last 15 Events - Short Game",
    "02355": "Last 15 Events - Putting",
    "02356": "Last 15 Events - Scoring",
    "02357": "Going for the Green - Birdie or Better",
    "02358": "Approaches from 200-225 yards",
    "02359": "Approaches from 225-250 yards",
    "02360": "Approaches from 250-275 yards",
    "02361": "Approaches from > 275 yards",
    "02362": "Approaches from 50-75 yards (Rgh)",
    "02363": "Approaches from 75-100 yards (Rgh)",
    "02364": "Approaches from 100-125 yards (Rgh)",
    "02365": "Approaches from 50-125 yards (Rgh)",
    "02366": "Approaches from 125-150 yards (Rgh)",
    "02367": "Approaches from 150-175 yards (Rgh)",
    "02368": "Approaches from 175-200 yards (Rgh)",
    "02369": "Approaches from > 200 yards (Rgh)",
    "02370": "Approaches from inside 100 yards (Rgh)",
    "02371": "Approaches from > 100 yards (Rgh)",
    "02372": "Approaches from 200-225 yards (Rgh)",
    "02373": "Approaches from 225-250 yards (Rgh)",
    "02374": "Approaches from 250-275 yards (Rgh)",
    "02375": "Approaches from > 275 yards (Rgh)",
    "02376": "Approach 200-225 yards (RTP)",
    "02377": "Approach 225-250 yards (RTP)",
    "02378": "Approach 250-275 yards (RTP)",
    "02379": "Approach > 275 yards (RTP)",
    "02380": "Approaches 50-75 yards-Rgh (RTP)",
    "02381": "Approaches 75-100 yards-Rgh (RTP)",
    "02382": "Approaches 100-125 yards-Rgh (RTP)",
    "02383": "Approaches 50-125 yards-Rgh (RTP)",
    "02384": "Approaches 125-150 yards-Rgh (RTP)",
    "02385": "Approaches 150-175 yards-Rgh (RTP)",
    "02386": "Approaches 175-200 yards-Rgh (RTP)",
    "02387": "Approaches > 200 yards-Rgh (RTP)",
    "02388": "Approaches < 100 yards-Rgh (RTP)",
    "02389": "Approaches > 100 yards-Rgh (RTP)",
    "02390": "Approaches 200-225 yards-Rgh (RTP)",
    "02391": "Approaches 225-250 yards-Rgh (RTP)",
    "02392": "Approaches 250-275 yards-Rgh (RTP)",
    "02393": "Approaches > 275 yards-Rgh (RTP)",
    "02396": "FedExCup Bonus Money",
    "02398": "FedExCup Season Points for Non-Members",
    "02401": "Club Head Speed",
    "02402": "Ball Speed",
    "02403": "Smash Factor",
    "02404": "Launch Angle",
    "02405": "Spin Rate",
    "02406": "Distance to Apex",
    "02407": "Apex Height",
    "02408": "Hang Time",
    "02409": "Carry Distance",
    "02410": "Carry Efficiency",
    "02411": "Total Distance Efficiency",
    "02412": "Total Driving Efficiency",
    "02414": "Bogey Avoidance",
    "02415": "Birdie to Bogey Ratio",
    "02416": "Reverse Bounce Back",
    "02417": "Stroke Differential Field Average",
    "02419": "Bogey Average",
    "02420": "Distance from Edge of Fairway",
    "02421": "Distance from Center of Fairway",
    "02422": "Left Tendency",
    "02423": "Right Tendency",
    "02426": "Average Going for it Shot Distance (in Yards)",
    "02427": "Putting from 3-5'",
    "02428": "Total Putting",
    "02429": "Putting from - > 20'",
    "02430": "Average Distance to Hole After Tee Shot",
    "02431": "Average Distance after Going for it Shot",
    "02432": "Driving Pct. 300-320 (All Drives)",
    "02433": "Driving Pct. 320+ (All Drives)",
    "02434": "GIR Pct. - Fairway Bunker",
    "02435": "Rough Tendency",
    "02437": "Greens or Fringe in Regulation",
    "02438": "Good Drive Percentage",
    "02439": "Bonus Putting",
    "02440": "Average Distance of Birdie putts made",
    "02442": "Average Distance of Eagle putts made",
    "02444": "Money Leaders - Fall Series",
    "02447": "Percentage of potential money won",
    "02448": "% of Potential Pts won - FedExCup Regular Season",
    "02517": "Par 3 efficiency < 100 yards",
    "02518": "Par 3 efficiency 100-125 yards",
    "02519": "Par 3 efficiency 125-150 yards",
    "02520": "Par 3 efficiency 150-175 yards",
    "02521": "Par 3 efficiency 175-200 yards",
    "02522": "Par 3 efficiency 200-225 yards",
    "02523": "Par 3 efficiency 225-250 yards",
    "02524": "Par 3 efficiency >250 yards",
    "02525": "Par 4 efficiency < 250 Yards",
    "02526": "Par 4 efficiency 250-300 yards",
    "02527": "Par 4 Efficiency 300-350 yards",
    "02528": "Par 4 Efficiency 350-400 yards",
    "02529": "Par 4 Efficiency 400-450 yards",
    "02530": "Par 4 Efficiency 450-500 yards",
    "02531": "Par 4 Efficiency >500 yards",
    "02532": "Par 5 Efficiency <500 yards",
    "02533": "Par 5 Efficiency 500-550 Yards",
    "02534": "Par 5 Efficiency 550-600 Yards",
    "02535": "Par 5 Efficiency 600-650 Yards",
    "02536": "Par 5 Efficiency >650 Yards",
    "02562": "FedExCup Points per Event Leaders",
    "02564": "SG: Putting",
    "02567": "SG: Off-the-Tee",
    "02568": "SG: Approach the Green",
    "02569": "SG: Around-the-Green",
    "02667": "Non-WGC FedExCup Season Points for Non-Members",
    "02671": "FedExCup Standings",
    "02672": "Consecutive Birdies Streak",
    "02673": "Consecutive Birdies/Eagles streak",
    "02674": "SG: Tee-to-Green",
    "02675": "SG: Total",
    "02677": "Non-Member Off+WGC Earnings",
    "02685": "FedEx Air & Ground",
    "02689": "FedEx Ground Top Performer",
    "02698": "FedExCup Fall Points",
    "028": "Approach 100-125 yards (RTP Score)",
    "029": "Approach 75-100 yards (RTP Score)",
    "030": "Approach 50-75 yards (RTP Score)",
    "068": "3-Putt Avoidance - Inside 5'",
    "069": "3-Putt Avoidance - 5-10'",
    "070": "3-Putt Avoidance - 10-15'",
    "071": "GIR Putting Avg - 25-30'",
    "072": "GIR Putting Avg - 30-35'",
    "073": "GIR Putting Avg - > 35'",
    "074": "Approaches from 100-125 yards",
    "075": "Approaches from 75-100 yards",
    "076": "Approaches from 50-75 yards",
    "077": "GIR Percentage - 100-125 yards",
    "078": "GIR Percentage - 75-100 yards",
    "079": "GIR Percentage - < 75 yards",
    "080": "Right Rough Tendency (RTP Score)",
    "081": "Left Rough Tendency (RTP Score)",
    "085": "Power Rating",
    "086": "Accuracy Rating",
    "087": "Short Game Rating",
    "088": "Putting Rating",
    "101": "Driving Distance",
    "102": "Driving Accuracy Percentage",
    "103": "Greens in Regulation Percentage",
    "104": "Putting Average",
    "105": "Par Breakers",
    "106": "Total Eagles",
    "107": "Total Birdies",
    "108": "Scoring Average (Actual)",
    "109": "Official Money",
    "110": "Career Money Leaders",
    "111": "Sand Save Percentage",
    "112": "Par 3 Birdie or Better Leaders",
    "113": "Par 4 Birdie or Better Leaders",
    "114": "Par 5 Birdie or Better Leaders",
    "115": "Birdie or Better Conversion Percentage",
    "116": "Scoring Average Before Cut",
    "117": "Round 3 Scoring Average",
    "118": "Final Round Scoring Average",
    "119": "Putts Per Round",
    "120": "Scoring Average (Adjusted)",
    "122": "Consecutive Cuts",
    "127": "All-Around Ranking",
    "129": "Total Driving",
    "130": "Scrambling",
    "131": "Ryder Cup Points",
    "132": "PGA Championship Points",
    "135": "Putts made Distance",
    "137": "YTD Consecutive Cuts",
    "138": "Top 10 Finishes",
    "139": "Non-member Earnings",
    "140": "Presidents Cup Points (United States)",
    "142": "Par 3 Scoring Average",
    "143": "Par 4 Scoring Average",
    "144": "Par 5 Scoring Average",
    "145": "3-Putt Avoidance - 15-20'",
    "146": "3-Putt Avoidance - 20-25'",
    "147": "3-Putt Avoidance > 25'",
    "148": "Round 1 Scoring Average",
    "149": "Round 2 Scoring Average",
    "150": "Current Par or Better Streak",
    "152": "Rounds in the 60s",
    "153": "Sub-Par Rounds",
    "154": "Money per Event Leaders",
    "155": "Eagles (Holes per)",
    "156": "Birdie Average",
    "158": "Ball Striking",
    "159": "Longest Drives",
    "160": "Bounce Back",
    "171": "Par 3 Performance",
    "172": "Par 4 Performance",
    "173": "Par 5 Performance",
    "186": "Official World Golf Ranking",
    "187": "Presidents Cup Points (International)",
    "190": "GIR Percentage from Fairway",
    "194": "Total Money (Official and Unofficial)",
    "199": "GIR Percentage from Other than Fairway",
    "207": "Front 9 Scoring Average",
    "208": "Back 9 Scoring Average",
    "209": "First Tee Early Scoring Average",
    "210": "Tenth Tee Early Scoring Average",
    "211": "First Tee Late Scoring Average",
    "212": "Tenth Tee Late Scoring Average",
    "213": "Hit Fairway Percentage",
    "214": "Driving Pct. 300+ (All Drives)",
    "215": "Driving Pct. 280-300 (All Drives)",
    "216": "Driving Pct. 260-280 (All Drives)",
    "217": "Driving Pct. 240-260 (All Drives)",
    "218": "Driving Pct. <= 240 (All Drives)",
    "219": "Final Round Performance",
    "220": "Top 10 Final Round Performance",
    "221": "Front 9 Par 3 Scoring Average",
    "222": "Back 9 Par 3 Scoring Average",
    "223": "Early Par 3 Scoring Average",
    "224": "Late Par 3 Scoring Average",
    "225": "First Tee Early Par 3 Scoring Average",
    "226": "Tenth Tee Early Par 3 Scoring Average",
    "227": "First Tee Late Par 3 Scoring Average",
    "228": "Tenth Tee Late Par 3 Scoring Average",
    "229": "Front 9 Par 4 Scoring Average",
    "230": "Back 9 Par 4 Scoring Average",
    "231": "Early Par 4 Scoring Average",
    "232": "Late Par 4 Scoring Average",
    "233": "First Tee Early Par 4 Scoring Average",
    "234": "Tenth Tee Early Par 4 Scoring Average",
    "235": "First Tee Late Par 4 Scoring Average",
    "236": "Tenth Tee Late Par 4 Scoring Average",
    "237": "Front 9 Par 5 Scoring Average",
    "238": "Back 9 Par 5 Scoring Average",
    "239": "Early Par 5 Scoring Average",
    "240": "Late Par 5 Scoring Average",
    "241": "First Tee Early Par 5 Scoring Average",
    "242": "Tenth Tee Early Par 5 Scoring Average",
    "243": "First Tee Late Par 5 Scoring Average",
    "244": "Tenth Tee Late Par 5 Scoring Average",
    "245": "Front 9 Round 1 Scoring Average",
    "246": "Back 9 Round 1 Scoring Average",
    "247": "Early Round 1 Scoring Average",
    "248": "Late Round 1 Scoring Average",
    "249": "First Tee Early Round 1 Scoring Average",
    "250": "Tenth Tee Early Round 1 Scoring Average",
    "251": "First Tee Late Round 1 Scoring Average",
    "252": "Tenth Tee Late Round 1 Scoring Average",
    "253": "Front 9 Round 2 Scoring Average",
    "254": "Back 9 Round 2 Scoring Average",
    "255": "Early Round 2 Scoring Average",
    "256": "Late Round 2 Scoring Average",
    "257": "First Tee Early Round 2 Scoring Average",
    "258": "Tenth Tee Early Round 2 Scoring Average",
    "259": "First Tee Late Round 2 Scoring Average",
    "260": "Tenth Tee Late Round 2 Scoring Average",
    "261": "Front 9 Round 3 Scoring Average",
    "262": "Back 9 Round 3 Scoring Average",
    "263": "Early Round 3 Scoring Average",
    "264": "Late Round 3 Scoring Average",
    "265": "First Tee Early Round 3 Scoring Average",
    "266": "Tenth Tee Early Round 3 Scoring Average",
    "267": "First Tee Late Round 3 Scoring Average",
    "268": "Tenth Tee Late Round 3 Scoring Average",
    "269": "Front 9 Round 4 Scoring Average",
    "270": "Back 9 Round 4 Scoring Average",
    "271": "Early Round 4 Scoring Average",
    "272": "Late Round 4 Scoring Average",
    "273": "First Tee Early Round 4 Scoring Average",
    "274": "Tenth Tee Early Round 4 Scoring Average",
    "275": "First Tee Late Round 4 Scoring Average",
    "276": "Tenth Tee Late Round 4 Scoring Average",
    "277": "Front 9 Round 5 Scoring Average",
    "278": "Back 9 Round 5 Scoring Average",
    "279": "Early Round 5 Scoring Average",
    "280": "Late Round 5 Scoring Average",
    "281": "First Tee Early Round 5 Scoring Average",
    "282": "Tenth Tee Early Round 5 Scoring Average",
    "283": "First Tee Late Round 5 Scoring Average",
    "284": "Tenth Tee Late Round 5 Scoring Average",
    "285": "Round 4 Scoring Average",
    "286": "Round 5 Scoring Average",
    "292": "Early Scoring Average",
    "293": "Late Scoring Average",
    "294": "Best YTD Streak w/o a 3-Putt",
    "295": "Best YTD 1-Putt or Better Streak",
    "296": "Consecutive Sand Saves",
    "297": "Consecutive Fairways Hit",
    "298": "Consecutive GIR",
    "299": "Lowest Round",
    "300": "Victory Leaders",
    "301": "Front 9 Lowest Round",
    "302": "Back 9 Lowest Round",
    "303": "Early Lowest Round",
    "304": "Late Lowest Round",
    "305": "First Tee Early Lowest Round",
    "306": "Tenth Tee Early Lowest Round",
    "307": "First Tee Late Lowest Round",
    "308": "Tenth Tee Late Lowest Round",
    "309": "Top 5 Final Round Performance",
    "310": "11-25 Final Round Performance",
    "311": "25+ Final Round Performance",
    "317": "Driving Distance - All Drives",
    "326": "GIR Percentage - 200+ yards",
    "327": "GIR Percentage - 175-200 yards",
    "328": "GIR Percentage - 150-175 yards",
    "329": "GIR Percentage - 125-150 yards",
    "330": "GIR Percentage - < 125 yards",
    "331": "Proximity to Hole",
    "336": "Approaches from > 200 yards",
    "337": "Approaches from 175-200 yards",
    "338": "Approaches from 150-175 yards",
    "339": "Approaches from 125-150 yards",
    "340": "Approaches from 50-125 yards",
    "341": "Putting from 3'",
    "342": "Putting from 4'",
    "343": "Putting from 5'",
    "344": "Putting from 6'",
    "345": "Putting from 7'",
    "346": "Putting from 8'",
    "347": "Putting from 9'",
    "348": "Putting from 10'",
    "349": "Approach Putt Performance",
    "350": "Total Hole Outs",
    "351": "Longest Hole Outs (in yards)",
    "352": "Birdie or Better Percentage",
    "356": "Putting from - > 10'",
    "357": "Birdie or Better Percentage - 200+ yards",
    "358": "Birdie or Better Percentage - 175-200 yards",
    "359": "Birdie or Better Percentage - 150-175 yards",
    "360": "Birdie or Better Percentage - 125-150 yards",
    "361": "Birdie or Better Percentage - < 125 yards",
    "362": "Scrambling from the Sand",
    "363": "Scrambling from the Rough",
    "364": "Scrambling from the Fringe",
    "365": "Scrambling from Other Locations",
    "366": "Scrambling from > 30 yards",
    "367": "Scrambling from 20-30 yards",
    "368": "Scrambling from 10-20 yards",
    "369": "Scrambling from < 10 yards",
    "370": "Sand Saves from 30+ yards",
    "371": "Sand Saves from 20-30 yards",
    "372": "Sand Saves from 10-20 yards",
    "373": "Sand Saves from < 10 yards",
    "374": "Proximity to Hole (ARG)",
    "375": "Proximity to Hole from Sand",
    "376": "Proximity to Hole from Rough",
    "377": "Proximity to Hole from Fringe",
    "378": "Proximity to Hole from Other Locations",
    "379": "Proximity to Hole from 30+ yards",
    "380": "Proximity to Hole from 20-30 yards",
    "381": "Proximity to Hole from 10-20 yards",
    "382": "Proximity to Hole from < 10 yards",
    "383": "GIR Putting - Inside 5'",
    "384": "GIR Putting - 5-10'",
    "385": "GIR Putting - 10-15'",
    "386": "GIR Putting - 15-20'",
    "387": "GIR Putting - 20-25'",
    "388": "GIR Putting - > 25'",
    "389": "Average Putting Distance - GIR 1 Putts",
    "390": "Average Putting Distance - GIR 2 Putts",
    "391": "Average Putting Distance - GIR 3 Putts",
    "392": "Average Putting Distance - GIR 3+ Putts",
    "393": "Putts per Round - Round 1",
    "394": "Putts per Round - Round 2",
    "395": "Putts per Round - Round 3",
    "396": "Putts per Round - Round 4",
    "397": "Putts per Round - Round 5",
    "398": "1-Putts per Round",
    "399": "2-Putts per Round",
    "400": "3-Putts per Round",
    "401": "3+ Putts per Round",
    "402": "Overall Putting Average",
    "403": "Putting from Inside 5'",
    "404": "Putting from 5-10'",
    "405": "Putting from - 10-15'",
    "406": "Putting from - 15-20'",
    "407": "Putting from - 20-25'",
    "408": "Putting from - > 25'",
    "409": "Average Putting Distance - All 1 putts",
    "410": "Average Putting Distance - All 2 putts",
    "411": "Average Putting Distance - All 3 putts",
    "412": "Average Putting Distance - All 3+ putts",
    "413": "One-Putt Percentage",
    "414": "One-Putt Percentage - Round 1",
    "415": "One-Putt Percentage - Round 2",
    "416": "One-Putt Percentage - Round 3",
    "417": "One-Putt Percentage - Round 4",
    "418": "One-Putt Percentage - Round 5",
    "419": "Going for the Green",
    "420": "Total 1 Putts - Inside 5'",
    "421": "Total 1 Putts - 5-10'",
    "422": "Total 1 Putts - 10-15'",
    "423": "Total 1 Putts - 15-20'",
    "424": "Total 1 Putts - 20-25'",
    "425": "Total 1 Putts - > 25'",
    "426": "3-Putt Avoidance",
    "427": "3-Putt Avoidance - Round 1",
    "428": "3-Putt Avoidance - Round 2",
    "429": "3-Putt Avoidance - Round 3",
    "430": "3-Putt Avoidance - Round 4",
    "431": "Fairway Proximity",
    "432": "Left Rough Proximity",
    "433": "Right Rough Proximity",
    "434": "Putts Made Per Event Over 10'",
    "435": "Putts Made Per Event Over 20'",
    "436": "Par 5 Going for the Green",
    "437": "Rough Proximity",
    "438": "Average Distance of Putts made",
    "440": "3-Putt Avoidance - Round 5",
    "441": "Total 3 Putts - Inside 5'",
    "442": "Total 3 Putts - 5-10'",
    "443": "Total 3 Putts - 10-15'",
    "444": "Total 3 Putts - 15-20'",
    "445": "Total 3 Putts - 20-25'",
    "446": "Total 3 Putts - > 25'",
    "447": "Par 4 Eagle Leaders",
    "448": "Par 5 Eagle Leaders",
    "449": "Consecutive Par 3 Birdies",
    "450": "Consecutive Par 4 Birdies",
    "451": "Consecutive Par 5 Birdies",
    "452": "Consecutive Holes Below Par",
    "453": "6-10 Final Round Performance",
    "454": "Driving Pct. 300+ (Measured)",
    "455": "Driving Pct. 280-300 (Measured)",
    "456": "Driving Pct. 260-280 (Measured)",
    "457": "Driving Pct. 240-260 (Measured)",
    "458": "Driving Pct. <= 240 (Measured)",
    "459": "Left Rough Tendency",
    "460": "Right Rough Tendency",
    "461": "Missed Fairway Percent - Other",
    "464": "Scrambling Rough (RTP Score)",
    "465": "Scrambling Fringe (RTP Score)",
    "466": "Scrambling > 30 yds (RTP Score)",
    "467": "Scrambling 20-30 yds (RTP Score)",
    "468": "Scrambling 10-20 yds (RTP Score)",
    "469": "Approaches Left Rough (RTP Score)",
    "470": "Approaches Right Rough (RTP Score)",
    "471": "Fairway Approach (RTP Score)",
    "472": "Approach < 125 yards (RTP Score)",
    "473": "Approach 125-150 yards (RTP Score)",
    "474": "Best Rounds in 60's Streak",
    "475": "YTD Rounds in 60's Streak",
    "476": "Best Sub-Par Rounds Streak",
    "477": "YTD Sub-Par Rounds Streak",
    "478": "Approach 150-175 yards (RTP Score)",
    "479": "Approach 175-200 yards (RTP Score)",
    "480": "Approach > 200 yards (RTP Score)",
    "481": "Scrambling Average Distance to Hole",
    "482": "YTD Par or Better Streak",
    "483": "Current Streak without a 3-Putt",
    "484": "Putting - Inside 10'",
    "485": "Putting from 4-8'",
    "486": "Going for the Green - Hit Green Pct.",
    "495": "Driving Pct. 300-320 (Measured)",
    "496": "Driving Pct. 320+ (Measured)",
    "498": "Longest Putts",
}

STAT_DETAILS_QUERY = """
query StatDetails($tourCode: TourCode!, $statId: String!, $year: Int) {
  statDetails(tourCode: $tourCode, statId: $statId, year: $year, eventQuery: null) {
    tourCode
    year
    statId
    statTitle
    tourAvg
    rows {
      ... on StatDetailsPlayer {
        __typename
        playerId
        playerName
        country
        rank
        rankDiff
        rankChangeTendency
        stats { statName statValue }
      }
      ... on StatDetailTourAvg {
        __typename
      }
    }
  }
}
"""


# ---------------------------------------------------------------------------
# Progress tracking — allows resume after interruption
# ---------------------------------------------------------------------------

def load_progress():
    if os.path.exists(PROGRESS_PATH):
        with open(PROGRESS_PATH) as f:
            return json.load(f)
    return {"completed": []}


def save_progress(progress):
    with open(PROGRESS_PATH, "w") as f:
        json.dump(progress, f, indent=2)


def progress_key(year, stat_id):
    return f"{year}_{stat_id}"


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def fetch_stat(stat_id, year):
    body = {
        "operationName": "StatDetails",
        "variables": {"tourCode": "R", "statId": stat_id, "year": year},
        "query": STAT_DETAILS_QUERY,
    }
    resp = requests.post(ENDPOINT, json=body, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    parsed = resp.json()
    errors = parsed.get("errors")
    if errors:
        msgs = [e["message"] for e in errors]
        raise ValueError(msgs)
    return parsed.get("data", {}).get("statDetails")


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------

def upsert_players(conn, rows):
    if not rows:
        return
    sql = """
        INSERT INTO players (player_id, player_name, country)
        VALUES (%(player_id)s, %(player_name)s, %(country)s)
        ON CONFLICT (player_id) DO UPDATE SET
            player_name = EXCLUDED.player_name,
            country = EXCLUDED.country
    """
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, sql, rows, page_size=500)


def upsert_stats(conn, rows):
    if not rows:
        return
    sql = """
        INSERT INTO player_stats_extended
            (player_id, season_year, stat_id, stat_name, stat_value,
             stat_title, tour_avg, rank)
        VALUES
            (%(player_id)s, %(season_year)s, %(stat_id)s, %(stat_name)s,
             %(stat_value)s, %(stat_title)s, %(tour_avg)s, %(rank)s)
        ON CONFLICT (player_id, season_year, stat_id) DO UPDATE SET
            stat_name  = EXCLUDED.stat_name,
            stat_value = EXCLUDED.stat_value,
            stat_title = EXCLUDED.stat_title,
            tour_avg   = EXCLUDED.tour_avg,
            rank       = EXCLUDED.rank
    """
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, sql, rows, page_size=500)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(resume=False):
    conn = psycopg2.connect(DB_DSN)
    conn.autocommit = False

    progress = load_progress() if resume else {"completed": []}
    completed = set(progress["completed"])

    stat_ids = list(STAT_IDS.keys())
    total = len(YEARS) * len(stat_ids)
    done = len(completed)

    logger.info(
        "Starting backfill: %d years x %d stats = %d combinations",
        len(YEARS), len(stat_ids), total,
    )
    logger.info("Already completed: %d  Remaining: %d", done, total - done)

    errors = 0
    null_count = 0

    for year in YEARS:
        for stat_id in stat_ids:
            key = progress_key(year, stat_id)
            if key in completed:
                continue

            try:
                result = fetch_stat(stat_id, year)
                time.sleep(DELAY_SECONDS)

                if result is None:
                    null_count += 1
                    completed.add(key)
                    continue

                rows_data = result.get("rows") or []
                stat_title = result.get("statTitle", STAT_IDS.get(stat_id, ""))
                tour_avg = result.get("tourAvg")
                ret_year = result.get("year", year)

                player_rows = []
                stat_rows = []

                for row in rows_data:
                    if row.get("__typename") != "StatDetailsPlayer":
                        continue
                    pid = row.get("playerId")
                    if not pid:
                        continue

                    player_rows.append({
                        "player_id": pid,
                        "player_name": row.get("playerName"),
                        "country": row.get("country"),
                    })

                    stats = row.get("stats") or []
                    stat_value = stats[0].get("statValue") if stats else None
                    stat_col_title = stats[0].get("statName") if stats else None

                    rank_val = row.get("rank")
                    try:
                        rank_int = int(rank_val) if rank_val is not None else None
                    except (ValueError, TypeError):
                        rank_int = None

                    stat_rows.append({
                        "player_id": pid,
                        "season_year": int(ret_year),
                        "stat_id": stat_id,
                        "stat_name": stat_title,
                        "stat_value": stat_value,
                        "stat_title": stat_col_title,
                        "tour_avg": tour_avg,
                        "rank": rank_int,
                    })

                if player_rows:
                    upsert_players(conn, player_rows)
                if stat_rows:
                    upsert_stats(conn, stat_rows)
                conn.commit()

                completed.add(key)
                done += 1

                if done % 50 == 0:
                    pct = done / total * 100
                    logger.info(
                        "Progress: %d/%d (%.1f%%) | year=%d stat=%s players=%d",
                        done, total, pct, year, stat_id, len(stat_rows),
                    )
                    save_progress({"completed": list(completed)})

            except requests.exceptions.HTTPError as e:
                logger.warning("HTTP error year=%d stat=%s: %s", year, stat_id, e)
                errors += 1
                time.sleep(2)  # back off on HTTP errors
            except ValueError as e:
                logger.warning("GraphQL error year=%d stat=%s: %s", year, stat_id, e)
                completed.add(key)  # skip permanently — likely invalid stat/year combo
                errors += 1
            except Exception as e:
                logger.error("Unexpected error year=%d stat=%s: %s", year, stat_id, e)
                conn.rollback()
                errors += 1
                time.sleep(2)

    save_progress({"completed": list(completed)})
    conn.close()

    logger.info(
        "Done. Total=%d Completed=%d Null=%d Errors=%d",
        total, len(completed), null_count, errors,
    )
    logger.info(
        "Check results: SELECT season_year, COUNT(DISTINCT stat_id) "
        "FROM player_stats_extended GROUP BY season_year ORDER BY season_year;"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from last saved progress",
    )
    args = parser.parse_args()
    main(resume=args.resume)